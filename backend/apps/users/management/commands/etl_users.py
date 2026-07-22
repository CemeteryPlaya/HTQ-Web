"""ETL фазы 10 — домен **users** (перенос платформенных пользователей).

⚠️ КРИТИЧНО для боевого переезда (P0.0). ВСЕ домены ссылаются на пользователя
голым целым ``user_id`` (= ``users_user.id``, без cross-domain FK — инвариант
изоляции). Поэтому users надо перенести **ПЕРВЫМ и с СОХРАНЕНИЕМ исходного id** —
иначе ``hr_employee.user_id`` / ``task.reporter_id`` / … начнут указывать на
ДРУГОГО человека (тихая порча идентичности: FK-ошибки нет, ссылки голые).

Старая FastAPI-таблица user-сервиса — ``users`` в схеме ``auth`` (search_path;
у остальных сервисов был public+префикс, user — исключение). Колонки почти 1:1 с
Django-моделью ``apps.users.models.User`` (``password_hash`` → поле ``password``;
bcrypt-хэши переносятся как есть — ``User.check_password`` их принимает и лениво
апгрейдит до PBKDF2). id и sequence сохраняются.

Интерфейс: ``etl_users [--source-dsn DSN] [--source-schema auth] [--source-table users]
[--dry-run] [--verify] [--limit N]``. Форма отчёта — общая (apps.core.etl.Report).
"""
from __future__ import annotations

from datetime import datetime as _dt, timezone as _tz

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.core.etl import (
    DEFAULT_SOURCE_DSN,
    Report,
    TableResult,
    legacy_cursor,
    row_hash,
)
from apps.users.models import User

# Колонки источника (auth.users) → одноимённые поля User, КРОМЕ password_hash→password.
# Порядок совпадает с SELECT ниже. last_login — обычный DateTime (не auto).
_SOURCE_COLUMNS = (
    "id", "username", "email", "password_hash",
    "first_name", "last_name", "patronymic", "display_name",
    "bio", "phone", "avatar_url", "settings",
    "status", "is_staff", "is_superuser", "must_change_password",
    "date_joined", "last_login", "created_at", "updated_at",
)
# auto_now / auto_now_add поля модели: Model.save() (внутри update_or_create)
# затирает переданное значение → доставляем follow-up QuerySet.update() (в обход save()).
_AUTONOW_FIELDS = ("date_joined", "created_at", "updated_at")


def _to_user_fields(row: dict) -> dict:
    """legacy-строка (dict по _SOURCE_COLUMNS) → kwargs модели User (без id)."""
    return {
        "username": row["username"],
        "email": row["email"],
        "password": row["password_hash"],   # db_column='password_hash'
        "first_name": row.get("first_name") or "",
        "last_name": row.get("last_name") or "",
        "patronymic": row.get("patronymic") or "",
        "display_name": row.get("display_name") or "",
        "bio": row.get("bio") or "",
        "phone": row.get("phone") or "",
        "avatar_url": row.get("avatar_url"),
        "settings": row.get("settings") if row.get("settings") is not None else {},
        "status": row["status"],
        "is_staff": row["is_staff"],
        "is_superuser": row["is_superuser"],
        "must_change_password": row.get("must_change_password", False),
        "date_joined": _utc(row.get("date_joined")),
        "last_login": _utc(row.get("last_login")),
        "created_at": _utc(row.get("created_at")),
        "updated_at": _utc(row.get("updated_at")),
    }


def _utc(v):
    if isinstance(v, _dt):
        return v.replace(tzinfo=_tz.utc) if v.tzinfo is None else v.astimezone(_tz.utc)
    return v


def _obj_fields(obj: User) -> dict:
    """Django-объект → тот же набор ключей, что _to_user_fields, для сверки hash."""
    return {
        "username": obj.username,
        "email": obj.email,
        "password": obj.password,
        "first_name": obj.first_name,
        "last_name": obj.last_name,
        "patronymic": obj.patronymic,
        "display_name": obj.display_name,
        "bio": obj.bio,
        "phone": obj.phone,
        "avatar_url": obj.avatar_url,
        "settings": obj.settings,
        "status": obj.status,
        "is_staff": obj.is_staff,
        "is_superuser": obj.is_superuser,
        "must_change_password": obj.must_change_password,
        "date_joined": _utc(obj.date_joined),
        "last_login": _utc(obj.last_login),
        "created_at": _utc(obj.created_at),
        "updated_at": _utc(obj.updated_at),
    }


def _reset_sequence() -> None:
    """setval users_user-sequence на MAX(id): id переносятся ЯВНО, иначе первый же
    живой User.objects.create() (регистрация/сид) столкнётся с занятым id. setval
    НЕ транзакционен → зовётся ПОСЛЕ коммита (не в --dry-run)."""
    table = connection.ops.quote_name(User._meta.db_table)
    pk = connection.ops.quote_name(User._meta.pk.column)
    with connection.cursor() as c:
        c.execute(
            "SELECT setval("
            "  pg_get_serial_sequence(%s, %s),"
            f"  COALESCE((SELECT MAX({pk}) FROM {table}), 1),"
            f"  (SELECT MAX({pk}) IS NOT NULL FROM {table})"
            ")",
            [User._meta.db_table, User._meta.pk.column],
        )


class _DryRunRollback(Exception):
    pass


class Command(BaseCommand):
    help = ("ETL фазы 10: перенос старых FastAPI-пользователей (auth.users) в "
            "apps.users.User с СОХРАНЕНИЕМ id (P0.0 — целостность user_id всех доменов).")

    def add_arguments(self, parser):
        parser.add_argument("--source-dsn", default=DEFAULT_SOURCE_DSN)
        parser.add_argument("--source-schema", default="auth",
                            help="Схема legacy user-сервиса (дефолт auth)")
        parser.add_argument("--source-table", default="users",
                            help="Legacy-таблица пользователей (дефолт users)")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--verify", action="store_true")
        parser.add_argument("--limit", type=int, default=None)

    def handle(self, *args, **o):
        self.schema, self.table = o["source_schema"], o["source_table"]
        if o["verify"]:
            self._verify(o["source_dsn"], o["limit"])
        else:
            self._load(o["source_dsn"], dry_run=o["dry_run"], limit=o["limit"])

    def _select(self, limit: int | None) -> str:
        cols = ", ".join(_SOURCE_COLUMNS)
        sql = f'SELECT {cols} FROM "{self.schema}"."{self.table}" ORDER BY id'
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return sql

    def _load(self, dsn: str, *, dry_run: bool, limit: int | None):
        created = updated = 0
        try:
            with transaction.atomic():
                with legacy_cursor(dsn) as cur:
                    cur.execute(self._select(limit))
                    for row in cur.fetchall():
                        defaults = _to_user_fields(row)
                        _obj, was_created = User.objects.update_or_create(
                            id=row["id"], defaults=defaults,
                        )
                        # auto_now(_add) затёрло date_joined/created_at/updated_at →
                        # доставляем legacy-значения в обход save().
                        User.objects.filter(id=row["id"]).update(
                            **{f: defaults[f] for f in _AUTONOW_FIELDS}
                        )
                        created += was_created
                        updated += not was_created
                if dry_run:
                    raise _DryRunRollback()
        except _DryRunRollback:
            pass

        if not dry_run:
            _reset_sequence()

        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(
            f"{prefix}{self.schema}.{self.table} -> users_user: "
            f"создано={created} обновлено={updated}"
            + ("  (sequence сдвинут на MAX(id))" if not dry_run else "  (rollback)")
        )

    def _verify(self, dsn: str, limit: int | None):
        sample_limit = 50 if limit is None else limit
        report = Report(domain="users")
        with legacy_cursor(dsn) as cur:
            cur.execute(f'SELECT count(*) AS n FROM "{self.schema}"."{self.table}"')
            src = int(cur.fetchone()["n"])
            tgt = User.objects.count()
            cur.execute(self._select(min(sample_limit, src) if src else 0))
            match = 0
            sample = cur.fetchall()
            for row in sample:
                try:
                    obj = User.objects.get(id=row["id"])
                except User.DoesNotExist:
                    continue
                if row_hash(_to_user_fields(row)) == row_hash(_obj_fields(obj)):
                    match += 1
            report.add(TableResult(
                name=f"{self.schema}.{self.table} -> users_user",
                src=src, tgt=tgt, sample=len(sample), hash_match=match,
            ))
        self.stdout.write(report.render())
        # доп. кросс-проверка целостности id-пространства (все домены зависят от неё)
        self.stdout.write(self._cross_check_hint())
        if not report.ok:
            raise CommandError("etl_users --verify: расхождения (см. отчёт выше).")

    def _cross_check_hint(self) -> str:
        """Подсказка: после ПОЛНОГО ETL проверить, что доменные user_id резолвятся.
        Здесь считаем только hr (самый показательный) — если >0, id-пространства разошлись."""
        try:
            with connection.cursor() as c:
                c.execute(
                    "SELECT count(*) FROM hr_employee e "
                    "WHERE e.user_id IS NOT NULL AND NOT EXISTS "
                    "(SELECT 1 FROM users_user u WHERE u.id = e.user_id)"
                )
                orphans = c.fetchone()[0]
            status = "OK" if orphans == 0 else "РАСХОЖДЕНИЕ"
            return f"[cross-check] hr_employee.user_id без users_user: {orphans} ({status})"
        except Exception as exc:  # hr не мигрирован в этой БД и т.п. — не фейлим verify
            return f"[cross-check] пропущен ({exc})"

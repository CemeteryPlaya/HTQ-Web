"""ETL фазы 10 — домен task (Django-аппка ``tasks``).

Перелив legacy FastAPI-данных (public-таблицы ``task_*`` + производственный
календарь ``calendar_*``) в Django-модели ``apps.tasks``. Источник — read-only
копия в htqweb1-db-1 (см. ``apps.core.etl``). Цель — Django ORM.

Обобщённый маппинг: для каждой пары (legacy-таблица → модель) переносятся
колонки, ПЕРЕСЕКАЮЩИЕСЯ по имени с полями модели (имена совпадают 1:1). Особые
случаи:
- ``calendar_event_participants`` — в источнике НЕТ суррогатного ``id`` (ключ —
  пара ``event_id``+``user_id``); у Django-модели ``id`` автогенерится.
- ``task_users`` — user-реплика (username/email/avatar): в Django её НЕТ (Р2 —
  данные о пользователях через ``users.interface``), поэтому ПРОПУСК.
- ``created_at``/``updated_at`` с ``auto_now(_add)`` затираются внутри
  ``Model.save()`` (его зовёт ``update_or_create``) → точные legacy-значения
  доставляются follow-up ``QuerySet.update()`` в обход ``save()``.

Интерфейс: ``etl_task [--source-dsn DSN] [--dry-run] [--verify] [--limit N]``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime as _dt, timezone as _tz

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.core.etl import (
    DEFAULT_SOURCE_DSN,
    Report,
    TableResult,
    legacy_count,
    legacy_cursor,
    row_hash,
)
from apps.tasks import models as m


@dataclass
class _Spec:
    table: str                       # legacy-таблица (схема public)
    model: type | None               # Django-модель (None → пропуск)
    key: tuple[str, ...] = ("id",)   # натуральный ключ (колонки И в источнике, И в модели)
    skip: bool = False
    note: str = ""


# Порядок — с учётом внутридоменных зависимостей (родители раньше детей).
SPECS: list[_Spec] = [
    _Spec("task_types", m.TaskType),
    _Spec("projects", m.Project),
    _Spec("tasks", m.Task),                    # родитель assignees/assignments/activities
    _Spec("task_sequence", m.TaskSequence),
    _Spec("task_assignees", m.TaskAssignee),
    _Spec("task_assignments", m.TaskAssignment),
    _Spec("task_activities", m.TaskActivity),
    _Spec("calendar_events", m.CalendarEvent),
    _Spec("calendar_event_participants", m.CalendarEventParticipant, key=("event_id", "user_id")),
    _Spec("event_exceptions", m.EventException),
    _Spec("task_users", None, key=(), skip=True,
          note="user replica (Р2), нет Django-цели"),
]

_SCHEMA = "public"


class _DryRunRollback(Exception):
    """Служебное исключение — откат транзакции при --dry-run."""


def _utc(v):
    """Нормализация datetime → UTC-aware (naive считаем UTC; aware приводим к UTC).

    Источник смешивает ``timestamptz`` (aware, разные смещения) и ``timestamp``
    (naive, напр. calendar_event_participants.created_at) — без нормализации
    hash источника не сойдётся с hash Django-объекта (Django отдаёт UTC-aware).
    """
    if isinstance(v, _dt):
        return v.replace(tzinfo=_tz.utc) if v.tzinfo is None else v.astimezone(_tz.utc)
    return v


def _model_cols(model: type) -> list[str]:
    """Колонки (db column names) конкретных полей модели, в порядке объявления."""
    return [f.column for f in model._meta.concrete_fields]


def _ts_cols(model: type) -> list[str]:
    """Колонки с auto_now / auto_now_add — их save() затирает 'сейчас'."""
    return [
        f.column for f in model._meta.concrete_fields
        if getattr(f, "auto_now", False) or getattr(f, "auto_now_add", False)
    ]


def _source_cols(cur, table: str) -> set[str]:
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name=%s",
        (_SCHEMA, table),
    )
    return {r["column_name"] for r in cur.fetchall()}


def _table_exists(cur, table: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema=%s AND table_name=%s",
        (_SCHEMA, table),
    )
    return cur.fetchone() is not None


def _fetch(cur, table: str, limit: int | None = None) -> list[dict]:
    sql = f'SELECT * FROM "{_SCHEMA}"."{table}" ORDER BY 1'
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    cur.execute(sql)
    return cur.fetchall()


def _reset_sequence(model: type) -> None:
    """Сдвинуть identity-последовательность PK на MAX(id) (мы сохраняем legacy-id).

    setval НЕ транзакционен — звать только на реальной загрузке (не --dry-run).
    """
    table = connection.ops.quote_name(model._meta.db_table)
    pk = connection.ops.quote_name(model._meta.pk.column)
    with connection.cursor() as c:
        c.execute(
            "SELECT setval("
            "  pg_get_serial_sequence(%s, %s),"
            f"  COALESCE((SELECT MAX({pk}) FROM {table}), 1),"
            f"  (SELECT MAX({pk}) IS NOT NULL FROM {table})"
            ")",
            [model._meta.db_table, model._meta.pk.column],
        )


class Command(BaseCommand):
    help = "ETL фазы 10: перелив legacy task_*/calendar_* → Django-модели apps.tasks."

    def add_arguments(self, parser):
        parser.add_argument("--source-dsn", dest="source_dsn", default=DEFAULT_SOURCE_DSN)
        parser.add_argument("--dry-run", action="store_true",
                            help="Прочитать+смаппить, ничего не записывать (rollback).")
        parser.add_argument("--verify", action="store_true",
                            help="Сверка count+hash; код выхода 1 при расхождениях.")
        parser.add_argument("--limit", type=int, default=None,
                            help="Загрузка: макс. строк/таблицу. --verify: размер hash-выборки (дефолт 50).")

    def handle(self, *args, **options):
        dsn = options["source_dsn"]
        if options["verify"]:
            self._verify(dsn, options["limit"])
        else:
            self._load(dsn, dry_run=options["dry_run"], limit=options["limit"])

    # ── load ─────────────────────────────────────────────────────────────
    def _load(self, dsn: str, *, dry_run: bool, limit: int | None):
        results: list[tuple[_Spec, int, int, int, str]] = []
        loaded_specs: list[_Spec] = []
        try:
            with transaction.atomic():
                with legacy_cursor(dsn) as cur:
                    for spec in SPECS:
                        if spec.skip:
                            src = legacy_count(cur, spec.table) if _table_exists(cur, spec.table) else 0
                            results.append((spec, src, 0, 0, f"ПРОПУСК: {spec.note}"))
                            continue
                        if not _table_exists(cur, spec.table):
                            results.append((spec, 0, 0, 0, "legacy-таблицы нет в этой копии — пропущено"))
                            continue
                        srccols = _source_cols(cur, spec.table)
                        shared = [c for c in _model_cols(spec.model) if c in srccols]
                        tscols = [c for c in _ts_cols(spec.model) if c in srccols]
                        rows = _fetch(cur, spec.table, limit=limit)
                        created = updated = 0
                        for row in rows:
                            lookup = {k: row[k] for k in spec.key}
                            defaults = {c: _utc(row[c]) for c in shared if c not in spec.key}
                            obj, was_created = spec.model.objects.update_or_create(
                                defaults=defaults, **lookup,
                            )
                            ts_fix = {c: _utc(row[c]) for c in tscols}
                            if ts_fix:
                                spec.model.objects.filter(pk=obj.pk).update(**ts_fix)
                            created += was_created
                            updated += not was_created
                        results.append((spec, len(rows), created, updated, ""))
                        loaded_specs.append(spec)
                if dry_run:
                    raise _DryRunRollback()
        except _DryRunRollback:
            pass

        if not dry_run:
            for spec in loaded_specs:
                if "id" in spec.key:
                    _reset_sequence(spec.model)

        prefix = "[dry-run] " if dry_run else ""
        for spec, n, created, updated, note in results:
            suffix = f"  ({note})" if note else ""
            self.stdout.write(
                f"{prefix}{spec.table:<28} прочитано={n:<5} создано={created:<5} "
                f"обновлено={updated:<5}{suffix}"
            )
        if dry_run:
            self.stdout.write(self.style.WARNING("--dry-run: транзакция откачена."))

    # ── verify ───────────────────────────────────────────────────────────
    def _verify(self, dsn: str, limit: int | None):
        sample_limit = 50 if limit is None else limit
        report = Report(domain="task")
        with legacy_cursor(dsn) as cur:
            for spec in SPECS:
                if spec.skip:
                    src = legacy_count(cur, spec.table) if _table_exists(cur, spec.table) else 0
                    self.stdout.write(f"[SKIP] {spec.table} (src={src}) — {spec.note}")
                    continue
                tgt = spec.model.objects.count()
                if not _table_exists(cur, spec.table):
                    report.add(TableResult(name=f"{spec.table} -> {spec.model._meta.db_table}",
                                           src=0, tgt=tgt, note="legacy-таблицы нет в копии"))
                    continue
                src = legacy_count(cur, spec.table)
                srccols = _source_cols(cur, spec.table)
                shared = [c for c in _model_cols(spec.model) if c in srccols]
                sample = _fetch(cur, spec.table, limit=min(sample_limit, src) if src else 0)
                match = 0
                for row in sample:
                    lookup = {k: row[k] for k in spec.key}
                    try:
                        obj = spec.model.objects.get(**lookup)
                    except spec.model.DoesNotExist:
                        continue
                    src_fields = {c: _utc(row[c]) for c in shared}
                    obj_fields = {c: _utc(getattr(obj, c)) for c in shared}
                    if row_hash(src_fields) == row_hash(obj_fields):
                        match += 1
                report.add(TableResult(
                    name=f"{spec.table} -> {spec.model._meta.db_table}",
                    src=src, tgt=tgt, sample=len(sample), hash_match=match,
                    note="" if src else "src пуст (0 строк в legacy)",
                ))
        self.stdout.write(report.render())
        if not report.ok:
            raise CommandError("etl_task --verify: обнаружены расхождения (см. отчёт выше).")

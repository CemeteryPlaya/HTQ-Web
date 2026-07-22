"""``manage.py etl_requests`` — Фаза 10 (ETL): перелив legacy FastAPI-БД
(requests-service, public-префикс ``request_*``) в Django ``apps.approvals``.

Источник (read-only, копия — не боевая БД): 12 непустых/учтённых таблиц схемы
``public`` — см. ``services/requests/app/models/*.py`` для точных
``__tablename__``/колонок. Маппинг — везде 1:1 (Django-порт в
``apps/approvals/models.py`` не переименовал НИ ОДНОЙ колонки этого домена, в
т.ч. FK-колонки: Django-поля ``template``/``project``/``request``/``source``
названы так, что их attname (``template_id``/``project_id``/``request_id``/
``source_id``) буквально совпадает с legacy-колонкой) — поэтому маппинг ниже
чисто метаданны (``TableSpec.columns``/``.key``), без per-таблицы функций:

  * ``request_projects``               (2) → ``RequestProject``
  * ``request_project_members``        (1) → ``RequestProjectMember``       (натур. ключ project+user, суррогатный id)
  * ``request_form_templates``        (10) → ``RequestFormTemplate``
  * ``request_form_template_versions`` (5) → ``RequestFormTemplateVersion``
  * ``request_instances``              (3) → ``RequestInstance``
  * ``request_approval_actions``       (1) → ``ApprovalAction``
  * ``request_activity``               (5) → ``RequestActivity``
  * ``request_watchers``               (0) → ``RequestWatcher``             (натур. ключ request+user, суррогатный id)
  * ``request_notifications_log``      (2) → ``NotificationsLog``
  * ``request_reference_sources``      (5) → ``RequestReferenceSource``
  * ``request_reference_rows``         (2) → ``RequestReferenceRow``
  * ``request_stats_daily``            (0) → ``RequestStatsDaily``          (натур. ключ date+project+template, суррогатный id)

Порядок ``TABLE_SPECS`` уважает FK-зависимости ВНУТРИ домена (родители раньше
детей): Project → ProjectMember/FormTemplate/Instance; FormTemplate →
FormTemplateVersion/Instance; Instance → ApprovalAction/Activity/Watcher/
NotificationsLog; ReferenceSource → ReferenceRow; StatsDaily — независима,
последняя. Кросс-доменные ссылки (``owner_id``/``department_id``/
``initiator_id``/``approver_id``/``actor_id``/``recipient_id``/``created_by``/
``published_by``/``granted_by``) копируются как обычные int — они НЕ FK на
другие Django-аппки (инвариант межаппной изоляции,
``apps/core/tests/test_app_isolation.py``); резолвятся через
``apps.users.interface``/``apps.hr.interface``.

Два P2-решения (см. ``apps/approvals/models.py`` module docstring — те же
самые, задокументированы там независимо):

  * ``request_users`` (3 строки) и ``request_departments`` (0 строк) —
    user-/department-реплики, синканные по Redis pub/sub из user-/hr-service.
    У НИХ НЕТ Django-цели (``RequestUser``/``RequestDepartment`` в
    ``apps/approvals/models.py`` сознательно отсутствуют). ЭТИ ДВЕ ТАБЛИЦЫ
    НЕ участвуют в ``Report``/``report.render()`` (структурно нечего
    сравнивать: 0 Django-строк при 3 legacy для request_users дал бы
    механическое "DIFF", хотя это ожидаемый, намеренный пропуск, а не
    расхождение) — они печатаются отдельной [SKIP]-строкой с реальным
    legacy-count, вне count/hash-отчёта и вне кода возврата ``--verify``.
  * ``AuditLog`` — Django-модель ЕСТЬ, но у неё НЕТ legacy-источника: в
    исходной ``services/requests/app/models/audit_log.py`` таблица называлась
    ``audit_log`` (без префикса ``request_``) и в скопированной legacy-БД её
    попросту не существует (``information_schema`` подтверждает: только
    ``cms``/``media``/``messenger`` имеют её в СВОИХ схемах). В отличие от
    request_users/request_departments здесь src=0 и tgt=0 ОБА честны (нечего
    переносить с обеих сторон) — поэтому AuditLog ОСТАЁТСЯ в ``Report`` как
    обычная (тривиально зелёная) строка с note, а не выносится в [SKIP].

⚠️ auto_now/auto_now_add (главная ловушка этого домена): ``created_at``
(``auto_now_add``), ``updated_at``/``granted_at`` не в счёт — весь домен
объявляет временные поля как ``auto_now_add=True``/``auto_now=True`` ПОВЕРХ
``db_default=Now()`` (см. ``apps/approvals/models.py``). ``Field.pre_save()``
(``django/db/models/fields/__init__.py``) для ЛЮБОГО поля с ``auto_now=True``
ИЛИ (``auto_now_add=True`` и это INSERT) БЕЗУСЛОВНО перезаписывает значение на
``timezone.now()`` через ``setattr`` — независимо от того, что реально
передано в ``defaults=``/конструктор. Наивный
``Model.objects.update_or_create(pk=.., defaults={"created_at": row[...], ...})``
поэтому молча потерял бы легаси-таймстемпы. ``_upsert`` ниже обходит это:
апдейт существующей строки идёт через queryset ``.update(**fields)``
(``QuerySet.update()`` НИКОГДА не вызывает ``Field.pre_save()`` — SQL
собирается напрямую из переданных значений), а для новой строки —
``.create()`` (тут ``pre_save()`` один раз перетирает auto-поля на INSERT)
сразу же исправляется точечным ``.filter(**lookup).update(**auto_fields)``,
который эту перезапись отменяет обратно на легаси-значение.

Автоинкремент-PK (все таблицы, где ``TableSpec.key == ("id",)``): переносим
legacy ``id`` явно (натуральный ключ переноса = сам legacy id), поэтому после
загрузки нужно подтянуть Postgres-sequence до ``MAX(id)`` — иначе следующий
обычный ``INSERT`` через приложение получит номер, уже занятый перенесённой
строкой. См. ``_reset_sequences`` (``django.db.connection.ops.sequence_reset_sql``
— официальный механизм, тот же, что использует ``loaddata``). Три таблицы с
суррогатным id и натуральным ключом (``RequestProjectMember``/
``RequestWatcher``/``RequestStatsDaily``) сюда не входят — их id никогда не
задаётся руками, Postgres продолжает авто-инкрементировать сам.

⚠️ tzinfo-представление: легаси-курсор (голый psycopg) и Django ORM
(``USE_TZ=True``) МОГУТ вернуть один и тот же момент времени с разным
``tzinfo`` (напр. ``+00:00`` вместо иного offset'а) — ``timestamptz`` в
Postgres абсолютен, но ``row_hash``/``_norm`` в ``apps/core/etl.py`` хеширует
``.isoformat()``, а он ЧУВСТВИТЕЛЕН к представлению offset'а. ``_utc()`` ниже
приводит обе стороны к UTC ДО записи и ДО хеширования (тот же момент времени,
просто другое "лицо" tzinfo — безопасно); применяется универсально ко всем
значениям (non-datetime проходят через неё no-op).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connection

from apps.core.etl import (
    DEFAULT_SOURCE_DSN,
    Report,
    TableResult,
    legacy_count,
    legacy_cursor,
    row_hash,
)
from apps.approvals.models import (
    ApprovalAction,
    AuditLog,
    NotificationsLog,
    RequestActivity,
    RequestFormTemplate,
    RequestFormTemplateVersion,
    RequestInstance,
    RequestProject,
    RequestProjectMember,
    RequestReferenceRow,
    RequestReferenceSource,
    RequestStatsDaily,
    RequestWatcher,
)

_SCHEMA = "public"

# Реплики без Django-цели (Р2) — НЕ участвуют в TABLE_SPECS/Report, см. module
# docstring. Печатаются отдельно с реальным legacy-count, для прозрачности.
_SKIPPED_REPLICAS = (
    ("request_users", "user-реплика (Р2) — апруверы/инициаторы адресуются как "
                       "plain int id через apps.users.interface"),
    ("request_departments", "department-реплика (Р2) — department_id остаётся "
                             "plain int, резолвится через apps.hr.interface"),
)


def _utc(value: Any) -> Any:
    """UTC-нормализация tz-aware ``datetime`` (см. module docstring)."""
    if isinstance(value, dt.datetime) and value.tzinfo is not None:
        return value.astimezone(dt.timezone.utc)
    return value


@dataclass(frozen=True)
class TableSpec:
    """Метаданные одной legacy-таблицы → Django-модели.

    ``columns`` — ВСЕ колонки legacy-таблицы; они же (без переименований,
    см. module docstring) — валидные kwargs/attname'ы Django-модели.
    ``key`` — подмножество ``columns``, идентифицирующее строку для
    идемпотентного upsert: ``("id",)`` для таблиц с перенесённым PK,
    натуральный ключ (несколько колонок) для суррогатно-id таблиц.
    ``auto_now`` — подмножество ``columns`` вне ``key``, которое на модели
    объявлено ``auto_now``/``auto_now_add`` (нужно для обхода ловушки,
    см. module docstring и ``_upsert``).
    """

    table: str
    model: type
    columns: tuple[str, ...]
    key: tuple[str, ...]
    auto_now: tuple[str, ...] = ()


TABLE_SPECS: tuple[TableSpec, ...] = (
    TableSpec(
        table="request_projects", model=RequestProject,
        columns=("id", "name", "description", "status", "color", "budget_limit",
                 "currency", "start_date", "end_date", "owner_id", "department_id",
                 "created_at", "updated_at"),
        key=("id",), auto_now=("created_at", "updated_at"),
    ),
    TableSpec(
        table="request_project_members", model=RequestProjectMember,
        columns=("project_id", "user_id", "role", "granted_by", "granted_at"),
        key=("project_id", "user_id"), auto_now=("granted_at",),
    ),
    TableSpec(
        table="request_form_templates", model=RequestFormTemplate,
        columns=("id", "project_id", "name", "slug", "description", "icon", "color",
                 "config_json", "is_active", "status", "created_by",
                 "current_version_id", "created_at", "updated_at"),
        key=("id",), auto_now=("created_at", "updated_at"),
    ),
    TableSpec(
        table="request_form_template_versions", model=RequestFormTemplateVersion,
        columns=("id", "template_id", "version", "schema_json", "workflow_json",
                 "published_at", "published_by"),
        key=("id",), auto_now=("published_at",),
    ),
    TableSpec(
        table="request_instances", model=RequestInstance,
        columns=("id", "code", "template_id", "template_version_id", "project_id",
                 "initiator_id", "title", "status", "current_node_id",
                 "form_values_json", "total_amount", "currency", "submitted_at",
                 "finalized_at", "due_at", "requires_admin_attention",
                 "created_at", "updated_at"),
        key=("id",), auto_now=("created_at", "updated_at"),
    ),
    TableSpec(
        table="request_approval_actions", model=ApprovalAction,
        columns=("id", "request_id", "node_id", "step_index", "approver_id",
                 "assigned_at", "action", "comment", "acted_at", "due_at",
                 "reminded_at", "reminders_sent"),
        key=("id",), auto_now=("assigned_at",),
    ),
    TableSpec(
        table="request_activity", model=RequestActivity,
        columns=("id", "request_id", "actor_id", "event_type", "payload",
                 "created_at"),
        key=("id",), auto_now=("created_at",),
    ),
    TableSpec(
        table="request_watchers", model=RequestWatcher,
        columns=("request_id", "user_id"),
        key=("request_id", "user_id"), auto_now=(),
    ),
    TableSpec(
        table="request_notifications_log", model=NotificationsLog,
        columns=("id", "request_id", "recipient_id", "kind", "channel",
                 "dedup_key", "created_at"),
        key=("id",), auto_now=("created_at",),
    ),
    TableSpec(
        table="request_reference_sources", model=RequestReferenceSource,
        columns=("id", "slug", "name", "columns_json", "created_by", "template_id",
                 "access_ids", "created_at", "updated_at"),
        key=("id",), auto_now=("created_at", "updated_at"),
    ),
    TableSpec(
        table="request_reference_rows", model=RequestReferenceRow,
        columns=("id", "source_id", "data_json", "instance_id"),
        key=("id",), auto_now=(),
    ),
    TableSpec(
        table="request_stats_daily", model=RequestStatsDaily,
        columns=("date", "project_id", "template_id", "created", "approved",
                 "rejected", "cancelled", "sum_approved_amount",
                 "time_to_decision_seconds_sum"),
        key=("date", "project_id", "template_id"), auto_now=(),
    ),
)

# Модели, где legacy `id` переносится явно (см. module docstring) — их
# sequence нужно подтянуть после реальной загрузки.
_ID_KEYED_MODELS: tuple[type, ...] = tuple(
    spec.model for spec in TABLE_SPECS if spec.key == ("id",)
)


def _row_lookup(spec: TableSpec, row: dict) -> dict:
    return {k: row[k] for k in spec.key}


def _row_fields(spec: TableSpec, row: dict) -> dict:
    return {k: _utc(row[k]) for k in spec.columns if k not in spec.key}


def _row_hash_dict(spec: TableSpec, row: dict) -> dict:
    return {k: _utc(row[k]) for k in spec.columns}


def _obj_hash_dict(spec: TableSpec, obj: Any) -> dict:
    return {k: _utc(getattr(obj, k)) for k in spec.columns}


def _fetch_rows(cur, spec: TableSpec, *, limit: int | None = None) -> list[dict]:
    """Все колонки (``SELECT *``) legacy-таблицы, упорядоченные по ``key`` —
    детерминированно для идемпотентной загрузки и для сэмплинга в --verify."""
    order = ", ".join(f'"{c}"' for c in spec.key)
    sql = f'SELECT * FROM "{_SCHEMA}"."{spec.table}" ORDER BY {order}'
    if limit is not None:
        cur.execute(sql + " LIMIT %s", [limit])
    else:
        cur.execute(sql)
    return cur.fetchall()


def _upsert(model: type, lookup: dict, fields: dict, auto_now: tuple[str, ...],
            write: bool) -> str:
    """Идемпотентный create/update по ``lookup`` (pk или натуральный ключ).

    Возвращает ``"create"``/``"update"``. При ``write=False`` в БД ничего не
    пишется — только читается, существует ли строка. См. module docstring про
    то, почему апдейт идёт через queryset ``.update()`` (не триггерит
    auto_now/auto_now_add), а после ``.create()`` требуется точечный
    fix-up тех же auto-полей.
    """
    qs = model.objects.filter(**lookup)
    if not write:
        return "update" if qs.exists() else "create"

    n = qs.update(**fields) if fields else (1 if qs.exists() else 0)
    if n:
        return "update"

    model.objects.create(**lookup, **fields)
    if auto_now:
        model.objects.filter(**lookup).update(
            **{k: fields[k] for k in auto_now if k in fields}
        )
    return "create"


def _reset_sequences() -> None:
    """Подтягивает Postgres-sequence автополя PK до ``MAX(id)`` после
    upsert'а с явно переданным id (Django не продвигает sequence сам, когда
    PK указан руками). Официальный механизм — тот же, что использует
    ``loaddata``; no-op, если список моделей пуст."""
    sql_statements = connection.ops.sequence_reset_sql(no_style(), list(_ID_KEYED_MODELS))
    if not sql_statements:
        return
    with connection.cursor() as cursor:
        for stmt in sql_statements:
            cursor.execute(stmt)


class Command(BaseCommand):
    help = (
        "ETL requests (Фаза 10): перелив legacy FastAPI-БД (requests-service, "
        "public.request_*) в Django apps.approvals. Без флагов — идемпотентный "
        "upsert + count-сводка. --dry-run — прочитать/смаппить, ничего не "
        "писать. --verify — сверка count+hash (код выхода 1 при расхождении)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--source-dsn", default=DEFAULT_SOURCE_DSN,
            help="DSN legacy-БД (по умолчанию — apps.core.etl.DEFAULT_SOURCE_DSN).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Прочитать+смаппить, ничего не записывать в БД.",
        )
        parser.add_argument(
            "--verify", action="store_true",
            help="Сверка count+hash вместо загрузки; код выхода 1, если есть расхождения.",
        )
        parser.add_argument(
            "--limit", type=int, default=50,
            help="--verify: размер per-row hash-выборки на таблицу (дефолт 50, "
                 "или все строки — если их меньше). Не влияет на обычную "
                 "загрузку/--dry-run — те переносят ВСЕ строки домена.",
        )

    def handle(self, *args, **options) -> None:
        dsn: str = options["source_dsn"]
        if options["verify"]:
            self._run_verify(dsn, options["limit"])
        else:
            self._run_load(dsn, dry_run=options["dry_run"])

    # ── load (без флагов / --dry-run) ───────────────────────────────────

    def _run_load(self, dsn: str, *, dry_run: bool) -> None:
        write = not dry_run
        verb = "DRY-RUN" if dry_run else "ETL"
        self.stdout.write(f"=== {verb} requests: legacy public.request_* -> apps.approvals ===")

        results: list[tuple[TableSpec, int, int, int]] = []
        with legacy_cursor(dsn) as cur:
            for spec in TABLE_SPECS:
                rows = _fetch_rows(cur, spec)
                created = updated = 0
                for row in rows:
                    lookup = _row_lookup(spec, row)
                    fields = _row_fields(spec, row)
                    outcome = _upsert(spec.model, lookup, fields, spec.auto_now, write)
                    if outcome == "create":
                        created += 1
                    else:
                        updated += 1
                results.append((spec, len(rows), created, updated))

            skip_counts = [(table, legacy_count(cur, table), note)
                           for table, note in _SKIPPED_REPLICAS]

        total_created = total_updated = 0
        for spec, n, created, updated in results:
            total_created += created
            total_updated += updated
            verb_created = "создал(и) бы" if dry_run else "создано"
            verb_updated = "обновил(и) бы" if dry_run else "обновлено"
            self.stdout.write(
                f"  {spec.table:<32} legacy={n:<5} {verb_created}={created:<5} "
                f"{verb_updated}={updated:<5}"
            )

        for table, n, note in skip_counts:
            self.stdout.write(self.style.WARNING(f"  [SKIP] {table} (src={n}): {note}"))

        if write:
            _reset_sequences()
            self.stdout.write(self.style.SUCCESS(
                f"ИТОГ: создано={total_created} обновлено={total_updated} "
                "(идемпотентно; sequences подтянуты до MAX(id))"
            ))
        else:
            self.stdout.write(self.style.WARNING(
                "--dry-run: в БД ничего не записано."
            ))
            self.stdout.write(self.style.SUCCESS(
                f"ИТОГ (dry-run): создал(и) бы={total_created} "
                f"обновил(и) бы={total_updated}"
            ))

    # ── verify (--verify) ────────────────────────────────────────────────

    def _run_verify(self, dsn: str, limit: int) -> None:
        self.stdout.write(f"=== ETL requests --verify (limit={limit}) ===")
        report = Report(domain="requests")

        with legacy_cursor(dsn) as cur:
            for spec in TABLE_SPECS:
                src = legacy_count(cur, spec.table, schema=_SCHEMA)
                tgt = spec.model.objects.count()

                take = min(limit, src) if src else 0
                sample_rows = _fetch_rows(cur, spec, limit=take) if take else []
                hash_match = 0
                for row in sample_rows:
                    lookup = _row_lookup(spec, row)
                    obj = spec.model.objects.filter(**lookup).first()
                    if obj is None:
                        continue
                    if row_hash(_row_hash_dict(spec, row)) == row_hash(_obj_hash_dict(spec, obj)):
                        hash_match += 1

                note = "src пуст (0 строк в legacy)" if src == 0 else ""
                report.add(TableResult(
                    name=spec.table, src=src, tgt=tgt,
                    sample=len(sample_rows), hash_match=hash_match, note=note,
                ))

            # AuditLog: НЕТ legacy-источника вообще (см. module docstring) —
            # src=0/tgt=0 оба честны (мигрировать нечего с обеих сторон),
            # поэтому остаётся обычной (тривиально зелёной) строкой отчёта,
            # а не уходит в [SKIP] как request_users/request_departments.
            report.add(TableResult(
                name="audit_log", src=0, tgt=AuditLog.objects.count(),
                sample=0, hash_match=0,
                note="нет legacy-источника (audit_log не создавался в "
                     "requests-service) — мигрировать нечего",
            ))

            skip_counts = [(table, legacy_count(cur, table), note)
                           for table, note in _SKIPPED_REPLICAS]

        self.stdout.write(report.render())
        for table, n, note in skip_counts:
            self.stdout.write(self.style.WARNING(
                f"[SKIP] {table} (src={n}, вне count/hash-отчёта выше): {note}"
            ))

        if not report.ok:
            raise CommandError("etl_requests --verify: обнаружены расхождения (см. отчёт выше).")

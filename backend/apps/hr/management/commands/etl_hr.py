"""ETL фазы 10 — перелив legacy FastAPI-данных домена hr в Django-модели.

    python manage.py etl_hr [--source-dsn DSN] [--dry-run] [--verify] [--limit N]
                            [--mongo-uri URI]

Источник — legacy Postgres-БД ``htqweb`` (копия, read-only, схема ``public``,
старые имена таблиц во мн.ч.: ``hr_departments``, ``hr_employees``, …).
Цель — Django-модели ``apps.hr.models`` (``managed=True``, имена
``hr_<model>`` в ед.ч.), БД ``htqweb_etl``. Общие хелперы — ``apps/core/etl.py``.

## Маппинг колонок

Почти везде имя legacy-колонки == имя атрибута Django-поля (D2 переименовал
только ИМЕНА ТАБЛИЦ, не колонки) — поэтому ``dict(row)`` из psycopg
(dict-row курсор) уже готовый kwargs-словарь для ``update_or_create``. Ровно
два расхождения на весь домен (см. ``TableSpec.transform`` у соответствующих
спек ниже):

- ``hr_documents.uploaded_by`` (legacy, БЕЗ суффикса ``_id``) ->
  ``Document.uploaded_by_id`` (Django FK-атрибут ВСЕГДА получает суффикс
  ``_id``, даже когда само поле уже называется ``uploaded_by``).
- ``hr_pmo_members.created_at`` существует в БД-источнике (создана самой
  первой миграцией ``004_pmo.py``), но НИ код-модель SQLAlchemy
  (``services/hr/app/models/pmo.py::PMOMember`` — наследует голый ``Base``,
  без временных меток), НИ Django-порт (``apps.hr.models.PMOMember``, тот же
  докстринг явно это оговаривает) её не объявляют. Дрейф исходника, не наша
  правка — колонку читаем (для отчёта видно src-схему), но в Django не льём.

## Департамент — циклический FK (D3)

``Department.manager`` -> ``Employee``, но ``Employee.department`` -> обратно
``Department`` (``on_delete=PROTECT``, обязателен). Порядок: Department без
``manager`` (фаза 1) -> Position -> Employee -> Department.manager backfill
(фаза 2, точечный ``UPDATE`` в обход ``update_or_create``).

## ``updated_at`` и ``auto_now`` (HrBase)

``HrBase.updated_at`` объявлен с ``auto_now=True`` — Django ВСЕГДА
перезаписывает это поле текущим временем на каждый ``.save()``, независимо от
того, что передано в ``defaults``. Чтобы перенести исходное значение
байт-в-байт (и чтобы ``--verify``-хеш не расходился на каждом повторном
прогоне), после ``update_or_create`` значение принудительно фиксируется via
``QuerySet.update(...)`` — эта операция NOT проходит через
``Field.pre_save()``/``auto_now`` (обычный ``UPDATE ... SET updated_at = %s``
без ORM-магии). См. ``_upsert_row``.

## Идентификаторы (id) — переносятся как есть

Все SQL-таблицы домена (кроме composite-PK join-таблиц PMODepartment/
PMOPosition и UUID-PK ShareableLink) переносят legacy ``id`` В Django ``id``
БУКВАЛЬНО (``update_or_create(id=row["id"], ...)``) — это не только
"натуральный ключ" в смысле идемпотентности, но и позволяет ВСЕМ
внутридоменным FK (``department_id``, ``position_id``, …) копироваться без
какого-либо ремаппинга: значения int уже совпадают по обе стороны. После
каждой таблицы вызывается ``_reset_sequence`` (Postgres-последовательность
``nextval()`` не знает про явно вставленные id — без ``setval`` первая же
вставка мимо ETL с автогенерацией id столкнётся с уже занятым PK).

## Mongo → JSONB

``EmployeeDocumentBlob``/``EmployeeGroups`` (``apps.hr.models``) — целевые
модели под-домена docs (декодировано в БРИФе, а не в этом файле). Обе
mongo-коллекции сейчас ПУСТЫЕ; код обязан уметь их лить.
``EmployeeGroups.employee_id`` — ``unique=True`` (совпадает с mongo unique-
индексом на ``employee_id``) -> прямой натуральный ключ. У
``EmployeeDocumentBlob`` НЕТ колонки под mongo ``_id`` (докстринг модели явно
перечисляет только бизнес-поля) -> чтобы повторный прогон не плодил дубли,
исходный ``_id`` (как строка) кладётся ВНУТРЬ ``data`` (JSONField) — решение
ETL-слоя, не модели; используется как natural key через ``data__contains``
(jsonb ``@>``, Postgres). Если Mongo недоступен (в этом окружении порт 27017
контейнера ``htqweb1-mongo-1`` сознательно НЕ опубликован на хост — см.
``docker-compose.yml``) — mongo-строки отчёта помечаются note и остаются
``.ok`` (src принудительно = tgt), остальной SQL-отчёт не страдает.
"""
from __future__ import annotations

import datetime as dt
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

from django.core.management.base import BaseCommand, CommandError
from django.db import connection as django_connection
from django.db import transaction
from django.utils import timezone as dj_timezone

from apps.core.etl import (
    DEFAULT_SOURCE_DSN,
    Report,
    TableResult,
    legacy_count,
    legacy_cursor,
    row_hash,
)
from apps.hr.models import (
    PMO,
    Application,
    AuditLog,
    CalendarDay,
    Department,
    DepartmentFile,
    DepartmentFileFolder,
    Document,
    Employee,
    EmployeeCard,
    EmployeeDayOverride,
    EmployeeDocumentBlob,
    EmployeeGroups,
    EmployeeShiftAssignment,
    EmployeeWeekTemplate,
    LevelThreshold,
    OrgSettings,
    PersonnelHistory,
    PMODepartment,
    PMOMember,
    PMOPosition,
    Position,
    PositionWeightAudit,
    ReportingRelation,
    ShareableLink,
    ShareLinkAudit,
    ShiftPattern,
    StaffingPosition,
    TimeEntry,
    Vacancy,
    WeekTemplate,
)

DEFAULT_MONGO_URI = "mongodb://htqweb:change-me-mongo@localhost:27017/htqweb_docs?authSource=admin"

_IDENTITY: Callable[[dict], dict] = lambda fields: fields  # noqa: E731


# ═══════════════════════════════════════════════════════════════════════════
#  Декларативные спеки таблиц: legacy-таблица <-> Django-модель.
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class TableSpec:
    legacy_table: str
    model: type
    pk_fields: tuple[str, ...] = ("id",)
    order_by: str = "id"
    transform: Callable[[dict], dict] = field(default=_IDENTITY)
    has_serial_pk: bool = True  # False для UUID-pk (ShareableLink) и composite-pk join-таблиц

    @property
    def label(self) -> str:
        return f"{self.legacy_table} -> {self.model._meta.db_table}"


def _document_transform(fields: dict) -> dict:
    """legacy ``uploaded_by`` (без суффикса) -> Django FK-атрибут ``uploaded_by_id``."""
    fields["uploaded_by_id"] = fields.pop("uploaded_by")
    return fields


def _pmo_member_transform(fields: dict) -> dict:
    """Дропаем ``created_at`` — есть в legacy-БД, нет ни в одной из моделей (см. докстринг файла)."""
    fields.pop("created_at", None)
    return fields


DEPARTMENT_SPEC = TableSpec("hr_departments", Department)
POSITION_SPEC = TableSpec("hr_positions", Position)
EMPLOYEE_SPEC = TableSpec("hr_employees", Employee)
LEVEL_THRESHOLD_SPEC = TableSpec("hr_level_thresholds", LevelThreshold)
POSITION_WEIGHT_AUDIT_SPEC = TableSpec("hr_position_weight_audit", PositionWeightAudit)
AUDIT_LOG_SPEC = TableSpec("hr_audit_log", AuditLog)
REPORTING_RELATION_SPEC = TableSpec("hr_reporting_relations", ReportingRelation)
ORG_SETTINGS_SPEC = TableSpec("hr_org_settings", OrgSettings)
VACANCY_SPEC = TableSpec("hr_vacancies", Vacancy)
APPLICATION_SPEC = TableSpec("hr_applications", Application)
DOCUMENT_SPEC = TableSpec("hr_documents", Document, transform=_document_transform)
EMPLOYEE_CARD_SPEC = TableSpec("hr_employee_card", EmployeeCard)
TIME_ENTRY_SPEC = TableSpec("hr_time_entries", TimeEntry)
STAFFING_POSITION_SPEC = TableSpec("hr_staffing_positions", StaffingPosition)
PERSONNEL_HISTORY_SPEC = TableSpec("hr_personnel_history", PersonnelHistory)
WEEK_TEMPLATE_SPEC = TableSpec("hr_week_templates", WeekTemplate)
CALENDAR_DAY_SPEC = TableSpec("hr_calendar_days", CalendarDay)
EMPLOYEE_WEEK_TEMPLATE_SPEC = TableSpec("hr_employee_week_template", EmployeeWeekTemplate)
SHIFT_PATTERN_SPEC = TableSpec("hr_shift_patterns", ShiftPattern)
EMPLOYEE_SHIFT_ASSIGNMENT_SPEC = TableSpec("hr_employee_shift_assignment", EmployeeShiftAssignment)
EMPLOYEE_DAY_OVERRIDE_SPEC = TableSpec("hr_employee_day_override", EmployeeDayOverride)
PMO_SPEC = TableSpec("hr_pmos", PMO)
PMO_DEPARTMENT_SPEC = TableSpec(
    "hr_pmo_departments", PMODepartment,
    pk_fields=("pmo_id", "department_id"), order_by="pmo_id, department_id", has_serial_pk=False,
)
PMO_POSITION_SPEC = TableSpec(
    "hr_pmo_positions", PMOPosition,
    pk_fields=("pmo_id", "position_id"), order_by="pmo_id, position_id", has_serial_pk=False,
)
PMO_MEMBER_SPEC = TableSpec("hr_pmo_members", PMOMember, transform=_pmo_member_transform)
SHAREABLE_LINK_SPEC = TableSpec("hr_shareable_links", ShareableLink, has_serial_pk=False)
SHARE_LINK_AUDIT_SPEC = TableSpec("hr_share_link_audit", ShareLinkAudit)
DEPARTMENT_FILE_FOLDER_SPEC = TableSpec("hr_department_file_folders", DepartmentFileFolder)
DEPARTMENT_FILE_SPEC = TableSpec("hr_department_files", DepartmentFile)

# Порядок — родители раньше детей внутри домена (Department идёт отдельно,
# двухфазно — см. _sync_department_phase1/_sync_department_phase2_manager).
SYNC_SPECS: list[TableSpec] = [
    POSITION_SPEC,
    EMPLOYEE_SPEC,
    LEVEL_THRESHOLD_SPEC,
    POSITION_WEIGHT_AUDIT_SPEC,
    AUDIT_LOG_SPEC,
    REPORTING_RELATION_SPEC,
    ORG_SETTINGS_SPEC,
    VACANCY_SPEC,
    APPLICATION_SPEC,
    DOCUMENT_SPEC,
    EMPLOYEE_CARD_SPEC,
    TIME_ENTRY_SPEC,
    STAFFING_POSITION_SPEC,
    PERSONNEL_HISTORY_SPEC,
    WEEK_TEMPLATE_SPEC,
    CALENDAR_DAY_SPEC,
    EMPLOYEE_WEEK_TEMPLATE_SPEC,
    SHIFT_PATTERN_SPEC,
    EMPLOYEE_SHIFT_ASSIGNMENT_SPEC,
    EMPLOYEE_DAY_OVERRIDE_SPEC,
    PMO_SPEC,
    PMO_DEPARTMENT_SPEC,
    PMO_POSITION_SPEC,
    PMO_MEMBER_SPEC,
    SHAREABLE_LINK_SPEC,
    SHARE_LINK_AUDIT_SPEC,
    DEPARTMENT_FILE_FOLDER_SPEC,
    DEPARTMENT_FILE_SPEC,
]
# Verify — порядок не важен (чтение), но Department идёт первым для читаемости отчёта.
VERIFY_SPECS: list[TableSpec] = [DEPARTMENT_SPEC, *SYNC_SPECS]


# ═══════════════════════════════════════════════════════════════════════════
#  Хелперы
# ═══════════════════════════════════════════════════════════════════════════

def _normalize_dt(value: Any) -> Any:
    """Naive datetime -> aware UTC.

    ``hr_department_file_folders``/``hr_department_files`` созданы миграциями
    011/022 с ``sa.DateTime()`` БЕЗ ``timezone=True`` (расходится с остальным
    доменом, где явно ``DateTime(timezone=True)``) — баг/дрейф исходных
    alembic-скриптов, не наша правка. Postgres-сервер этого стека везде
    работает в UTC (``TIME_ZONE = "UTC"`` в settings), поэтому naive-значение
    трактуем как UTC — тот же приём, что Django сделал бы сам (с warning'ом)
    при ``USE_TZ=True``, только без warning'а и с гарантированно тем же
    значением по обе стороны сравнения (--verify читает из БД уже aware).
    """
    if isinstance(value, dt.datetime) and dj_timezone.is_naive(value):
        return dj_timezone.make_aware(value, dt.timezone.utc)
    return value


def _row_fields(spec: TableSpec, row: dict) -> dict:
    fields = spec.transform(dict(row))
    return {k: _normalize_dt(v) for k, v in fields.items()}


def _reset_sequence(model: type) -> None:
    """``setval`` последовательности на MAX(pk) — иначе первая же вставка мимо
    ETL с автогенерацией id (nextval) столкнётся с уже занятым legacy-id."""
    table = model._meta.db_table
    pk_col = model._meta.pk.column
    with django_connection.cursor() as c:
        c.execute(
            f'SELECT setval(pg_get_serial_sequence(%s, %s), '
            f'COALESCE((SELECT MAX("{pk_col}") FROM "{table}"), 1), '
            f'(SELECT MAX("{pk_col}") FROM "{table}") IS NOT NULL)',
            [table, pk_col],
        )


def _upsert_row(model: type, lookup: dict, defaults: dict) -> bool:
    """``update_or_create`` + принудительная фиксация ``updated_at`` в обход ``auto_now``.

    Возвращает True, если строка была СОЗДАНА (для created/updated счётчиков).
    """
    _obj, created = model.objects.update_or_create(**lookup, defaults=defaults)
    if "updated_at" in defaults:
        # QuerySet.update() НЕ проходит через Field.pre_save()/auto_now —
        # обычный UPDATE ... SET updated_at = %s, без ORM-подмены на now().
        model.objects.filter(**lookup).update(updated_at=defaults["updated_at"])
    return created


# ═══════════════════════════════════════════════════════════════════════════
#  Generic sync/verify для обычных (не Department) таблиц
# ═══════════════════════════════════════════════════════════════════════════

def _sync_table(stdout, cur, spec: TableSpec, dry_run: bool) -> TableResult:
    src_n = legacy_count(cur, spec.legacy_table)
    cur.execute(f'SELECT * FROM "public"."{spec.legacy_table}" ORDER BY {spec.order_by}')
    rows = cur.fetchall()
    created = updated = 0
    for row in rows:
        fields = _row_fields(spec, row)
        lookup = {k: fields[k] for k in spec.pk_fields}
        defaults = {k: v for k, v in fields.items() if k not in spec.pk_fields}
        if _upsert_row(spec.model, lookup, defaults):
            created += 1
        else:
            updated += 1
    if spec.has_serial_pk and not dry_run:
        _reset_sequence(spec.model)
    tgt_n = spec.model.objects.count()
    stdout.write(f"  {spec.label}: src={src_n} created={created} updated={updated} tgt={tgt_n}")
    return TableResult(name=spec.label, src=src_n, tgt=tgt_n)


def _verify_table(cur, spec: TableSpec, limit: int) -> TableResult:
    src_n = legacy_count(cur, spec.legacy_table)
    tgt_n = spec.model.objects.count()
    cur.execute(
        f'SELECT * FROM "public"."{spec.legacy_table}" ORDER BY {spec.order_by} LIMIT %s',
        (limit,),
    )
    sample = hash_match = 0
    for row in cur.fetchall():
        fields = _row_fields(spec, row)
        lookup = {k: fields[k] for k in spec.pk_fields}
        sample += 1
        obj = spec.model.objects.filter(**lookup).first()
        if obj is None:
            continue
        obj_fields = {k: getattr(obj, k) for k in fields}
        if row_hash(fields) == row_hash(obj_fields):
            hash_match += 1
    return TableResult(name=spec.label, src=src_n, tgt=tgt_n, sample=sample, hash_match=hash_match)


# ═══════════════════════════════════════════════════════════════════════════
#  Department — двухфазный перенос (циклический FK manager -> Employee, D3)
# ═══════════════════════════════════════════════════════════════════════════

def _sync_department_phase1(stdout, cur) -> list[dict]:
    """Создаёт/обновляет Department БЕЗ manager (Employee ещё не существует)."""
    src_n = legacy_count(cur, "hr_departments")
    cur.execute('SELECT * FROM "public"."hr_departments" ORDER BY id')
    rows = cur.fetchall()
    created = updated = 0
    for row in rows:
        fields = _row_fields(DEPARTMENT_SPEC, row)
        fields.pop("manager_id", None)
        lookup = {"id": fields["id"]}
        defaults = {k: v for k, v in fields.items() if k != "id"}
        if _upsert_row(Department, lookup, defaults):
            created += 1
        else:
            updated += 1
    stdout.write(
        f"  {DEPARTMENT_SPEC.label} (фаза 1, без manager): "
        f"src={src_n} created={created} updated={updated}"
    )
    return rows


def _sync_department_phase2_manager(stdout, rows: list[dict], dry_run: bool) -> None:
    """Бэкафилл Department.manager теперь, когда Employee уже перенесены."""
    n = 0
    for row in rows:
        manager_id = row.get("manager_id")
        if manager_id is not None:
            Department.objects.filter(id=row["id"]).update(manager_id=manager_id)
            n += 1
    if not dry_run:
        _reset_sequence(Department)
    stdout.write(f"  {DEPARTMENT_SPEC.label} (фаза 2, manager backfill): {n} строк(и)")


# ═══════════════════════════════════════════════════════════════════════════
#  Mongo -> JSONB (hr_documents -> EmployeeDocumentBlob, hr_employee_groups -> EmployeeGroups)
# ═══════════════════════════════════════════════════════════════════════════

def _jsonify(value: Any) -> Any:
    """Приводит значение из Mongo к JSON-совместимому виду (для записи в JSONField)."""
    if isinstance(value, dict):
        return {k: _jsonify(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonify(v) for v in value]
    if isinstance(value, dt.datetime):
        return value.isoformat()
    try:
        from bson import ObjectId
        from bson.decimal128 import Decimal128
    except ImportError:  # pragma: no cover — pymongo гарантированно стоит, если мы сюда дошли
        return value
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, Decimal128):
        return float(value.to_decimal())
    return value


def _doc_blob_fields(doc: dict) -> dict:
    """Mongo-документ hr_documents -> {employee_id, doc_type, data, [created_at]}.

    ``data`` несёт ВСЁ остальное тело документа (title/content/file_url/…)
    ЦЕЛИКОМ (см. докстринг EmployeeDocumentBlob), ПЛЮС строковый mongo ``_id``
    под ключом ``"_id"`` — используется как натуральный ключ для идемпотентного
    upsert (в модели нет отдельной колонки под mongo id, см. докстринг файла).
    """
    mongo_id = str(doc["_id"])
    data = {k: v for k, v in doc.items() if k not in ("_id", "sql_employee_id", "doc_type", "created_at")}
    data["_id"] = mongo_id
    fields: dict[str, Any] = {
        "employee_id": doc.get("sql_employee_id"),
        "doc_type": doc.get("doc_type", ""),
        "data": _jsonify(data),
    }
    created_at = doc.get("created_at")
    if created_at is not None:
        fields["created_at"] = _normalize_dt(created_at)
    return fields


def _employee_groups_fields(doc: dict) -> dict:
    """Mongo-документ hr_employee_groups -> {employee_id, data}."""
    return {
        "employee_id": doc.get("employee_id"),
        "data": _jsonify({
            "education": doc.get("education") or [],
            "experience": doc.get("experience") or [],
            "relatives": doc.get("relatives") or [],
        }),
    }


def _mongo_connect(mongo_uri: str):
    """Возвращает (client, db) либо (None, None), если pymongo нет или Mongo недоступен."""
    try:
        import pymongo
    except ImportError:
        return None, None
    try:
        client = pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=3000)
        client.admin.command("ping")
        db = client.get_default_database()
    except Exception:
        return None, None
    return client, db


def _mongo_unavailable_results(note: str) -> list[TableResult]:
    docs_tgt = EmployeeDocumentBlob.objects.count()
    groups_tgt = EmployeeGroups.objects.count()
    return [
        TableResult(name="mongo:hr_documents -> hr_employeedocumentblob",
                    src=docs_tgt, tgt=docs_tgt, note=note),
        TableResult(name="mongo:hr_employee_groups -> hr_employeegroups",
                    src=groups_tgt, tgt=groups_tgt, note=note),
    ]


def _sync_mongo(stdout, report: Report, mongo_uri: str, dry_run: bool) -> None:
    client, db = _mongo_connect(mongo_uri)
    if db is None:
        for r in _mongo_unavailable_results("mongo unavailable — skipped"):
            stdout.write(f"  {r.name}: {r.note}")
            report.add(r)
        return

    try:
        coll = db["hr_documents"]
        src_n = coll.count_documents({})
        created = updated = 0
        for doc in coll.find({}):
            fields = _doc_blob_fields(doc)
            mongo_id = fields["data"]["_id"]
            existing = EmployeeDocumentBlob.objects.filter(data__contains={"_id": mongo_id}).first()
            if not dry_run:
                if existing is not None:
                    existing.employee_id = fields["employee_id"]
                    existing.doc_type = fields["doc_type"]
                    existing.data = fields["data"]
                    existing.save()
                else:
                    EmployeeDocumentBlob.objects.create(
                        employee_id=fields["employee_id"],
                        doc_type=fields["doc_type"],
                        data=fields["data"],
                        **({"created_at": fields["created_at"]} if "created_at" in fields else {}),
                    )
            if existing is not None:
                updated += 1
            else:
                created += 1
        tgt_n = EmployeeDocumentBlob.objects.count()
        stdout.write(
            f"  mongo:hr_documents -> hr_employeedocumentblob: "
            f"src={src_n} created={created} updated={updated} tgt={tgt_n}"
        )
        report.add(TableResult(name="mongo:hr_documents -> hr_employeedocumentblob", src=src_n, tgt=tgt_n))

        gcoll = db["hr_employee_groups"]
        gsrc_n = gcoll.count_documents({})
        gcreated = gupdated = 0
        for doc in gcoll.find({}):
            fields = _employee_groups_fields(doc)
            if not dry_run:
                _created = _upsert_row(EmployeeGroups, {"employee_id": fields["employee_id"]},
                                        {"data": fields["data"]})
            else:
                _created = not EmployeeGroups.objects.filter(employee_id=fields["employee_id"]).exists()
            gcreated += int(_created)
            gupdated += int(not _created)
        gtgt_n = EmployeeGroups.objects.count()
        stdout.write(
            f"  mongo:hr_employee_groups -> hr_employeegroups: "
            f"src={gsrc_n} created={gcreated} updated={gupdated} tgt={gtgt_n}"
        )
        report.add(TableResult(name="mongo:hr_employee_groups -> hr_employeegroups", src=gsrc_n, tgt=gtgt_n))
    finally:
        client.close()


def _verify_mongo(report: Report, mongo_uri: str, limit: int) -> None:
    client, db = _mongo_connect(mongo_uri)
    if db is None:
        for r in _mongo_unavailable_results("mongo unavailable — skipped"):
            report.add(r)
        return

    try:
        coll = db["hr_documents"]
        src_n = coll.count_documents({})
        tgt_n = EmployeeDocumentBlob.objects.count()
        sample = hash_match = 0
        for doc in coll.find({}).limit(limit):
            fields = _doc_blob_fields(doc)
            sample += 1
            obj = EmployeeDocumentBlob.objects.filter(data__contains={"_id": fields["data"]["_id"]}).first()
            if obj is None:
                continue
            obj_fields = {"employee_id": obj.employee_id, "doc_type": obj.doc_type, "data": obj.data}
            cmp_fields = {k: v for k, v in fields.items() if k in obj_fields}
            if row_hash(cmp_fields) == row_hash(obj_fields):
                hash_match += 1
        report.add(TableResult(
            name="mongo:hr_documents -> hr_employeedocumentblob",
            src=src_n, tgt=tgt_n, sample=sample, hash_match=hash_match,
        ))

        gcoll = db["hr_employee_groups"]
        gsrc_n = gcoll.count_documents({})
        gtgt_n = EmployeeGroups.objects.count()
        gsample = ghash_match = 0
        for doc in gcoll.find({}).limit(limit):
            fields = _employee_groups_fields(doc)
            gsample += 1
            obj = EmployeeGroups.objects.filter(employee_id=fields["employee_id"]).first()
            if obj is None:
                continue
            obj_fields = {"employee_id": obj.employee_id, "data": obj.data}
            if row_hash(fields) == row_hash(obj_fields):
                ghash_match += 1
        report.add(TableResult(
            name="mongo:hr_employee_groups -> hr_employeegroups",
            src=gsrc_n, tgt=gtgt_n, sample=gsample, hash_match=ghash_match,
        ))
    finally:
        client.close()


# ═══════════════════════════════════════════════════════════════════════════
#  Command
# ═══════════════════════════════════════════════════════════════════════════

class _DryRunRollback(Exception):
    """Внутренний сигнал: --dry-run прогнал upsert'ы, теперь откатить transaction.atomic."""


class Command(BaseCommand):
    help = (
        "ETL фазы 10: перелив legacy FastAPI-данных домена hr "
        "(+ Mongo hr_documents/hr_employee_groups) в Django-модели apps.hr."
    )

    def add_arguments(self, parser):
        parser.add_argument("--source-dsn", default=DEFAULT_SOURCE_DSN,
                             help="DSN legacy-источника (по умолчанию — копия htqweb на :55432)")
        parser.add_argument("--dry-run", action="store_true",
                             help="Прочитать+смаппить, ничего не писать (rollback в конце)")
        parser.add_argument("--verify", action="store_true",
                             help="Сверка count+hash легаси vs Django, без записи")
        parser.add_argument("--limit", type=int, default=50,
                             help="Сколько строк на таблицу сэмплировать в --verify (default 50)")
        parser.add_argument("--mongo-uri", default=DEFAULT_MONGO_URI,
                             help="URI MongoDB для hr_documents/hr_employee_groups")

    def handle(self, *args, **options):
        dsn = options["source_dsn"]
        dry_run = options["dry_run"]
        verify = options["verify"]
        limit = options["limit"]
        mongo_uri = options["mongo_uri"]

        if verify:
            report = self._run_verify(dsn, limit, mongo_uri)
        else:
            report = self._run_sync(dsn, dry_run, mongo_uri)

        self.stdout.write("")
        if dry_run and not verify:
            self.stdout.write("=== DRY RUN — изменения НЕ сохранены (rollback) ===")
        self.stdout.write(report.render())

        if verify and not report.ok:
            raise CommandError("ETL hr --verify: есть расхождения — см. отчёт выше")

    # ── sync ────────────────────────────────────────────────────────────

    def _run_sync(self, dsn: str, dry_run: bool, mongo_uri: str) -> Report:
        report = Report(domain="hr")
        with legacy_cursor(dsn) as cur:
            try:
                with transaction.atomic():
                    dep_rows = _sync_department_phase1(self.stdout, cur)
                    for spec in SYNC_SPECS:
                        result = _sync_table(self.stdout, cur, spec, dry_run)
                        if spec is EMPLOYEE_SPEC:
                            # Employee уже перенесены — можно бэкафиллить manager.
                            _sync_department_phase2_manager(self.stdout, dep_rows, dry_run)
                            report.add(TableResult(
                                name=DEPARTMENT_SPEC.label,
                                src=legacy_count(cur, "hr_departments"),
                                tgt=Department.objects.count(),
                            ))
                        report.add(result)
                    if dry_run:
                        raise _DryRunRollback()
            except _DryRunRollback:
                pass
            _sync_mongo(self.stdout, report, mongo_uri, dry_run)
        return report

    # ── verify ──────────────────────────────────────────────────────────

    def _run_verify(self, dsn: str, limit: int, mongo_uri: str) -> Report:
        report = Report(domain="hr")
        with legacy_cursor(dsn) as cur:
            for spec in VERIFY_SPECS:
                report.add(_verify_table(cur, spec, limit))
            _verify_mongo(report, mongo_uri, limit)
        return report

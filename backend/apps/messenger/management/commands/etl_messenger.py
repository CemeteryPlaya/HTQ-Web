"""``manage.py etl_messenger`` — фаза 10 ETL: legacy FastAPI (схема Postgres
``messenger``, read-only копия) -> Django-модели ``apps.messenger`` (см.
общий контракт ``etl-contract.md`` и доменный бриф ``etl-messenger-brief.md``,
переданные постановщиком фазы; сам файл-бриф в репозиторий не входит).

Источник — 6 непустых/учитываемых таблиц (все счётчики сверены на копии
``htqweb`` через ``information_schema``/``count(*)`` перед реализацией):
``rooms``(8), ``room_participants``(16), ``messages``(25),
``chat_attachments``(10), ``audit_log``(19), ``user_keys``(0, пустая, но
таблица включена в перенос/отчёт). ``chat_user_replicas``(13) —
ПРОПУСКАЕТСЯ: денормализованная user-реплика легаси, для которой в Django
нет и не будет модели (Р2 — пользователи домена messenger обслуживаются
через ``apps.users.interface``, см. докстринг ``apps/messenger/models.py``).
Пропуск отражён в каждом печатаемом отчёте отдельной ``[SKIP]``-строкой
(``_render_report`` ниже), но НЕ участвует в ``Report.ok``/коде выхода — это
явное решение брифа ("не считай это расхождением"), см. ``SKIP_NOTE``.

Порядок переноса — родители раньше детей (см. FK ``apps/messenger/models.py``):
Room -> RoomParticipant -> Message -> ChatAttachment -> AuditLog -> UserKey
(``_SPECS`` ниже в этом самом порядке; ``AuditLog``/``UserKey`` не имеют
внутридоменных FK друг на друга и могут идти в любом относительном порядке
между собой — оставлены в порядке брифа).

Все FK-подобные "кросс-доменные" колонки (``user_id``/``sender_id``/
``uploaded_by``) в Django-моделях этого домена — голые ``IntegerField`` БЕЗ
настоящего ``ForeignKey`` (см. models.py докстринг, Р2/межаппная изоляция) —
переносятся как простое int-значение, без резолва/валидации.

Маппинг колонок 1:1 по имени для ВСЕХ полей ВСЕХ 6 таблиц (проверено по
``information_schema.columns`` схемы ``messenger`` источника и по атрибутам
целевых моделей) — единственное исключение: ``rooms.department_path``
(Postgres ``ltree``) читается с явным ``::text``-кастом (``_TableSpec.
column_overrides``), т.к. Django-поле — обычный ``CharField`` (см. ``Room.
department_path`` докстринг: расширение ltree в порту не подключено). На
момент реализации это поле всюду ``NULL`` в источнике (0 непустых строк и в
``rooms``, и в пропускаемой ``chat_user_replicas``) — каст добавлен как
защита на будущее/другие копии данных, а не потому что он востребован
текущими строками.

## auto_now("updated_at") — единственная нетривиальная часть переноса

Все 6 моделей (кроме ``AuditLog``, у которой только ``created_at``) несут
``updated_at = DateTimeField(db_default=Now(), auto_now=True)``. Django
навязывает ``auto_now`` ИСКЛЮЧИТЕЛЬНО внутри ``Model.save()`` (через
``Field.pre_save()``, см. ``django/db/models/fields/__init__.py``) —
следовательно ЛЮБОЕ значение ``updated_at``, переданное в ``defaults=``
``update_or_create()`` (который внутри вызывает ``.save()``), было бы молча
заменено на ``timezone.now()`` при каждом прогоне: и hash-сверка не сошлась
бы (легаси-таймстамп невоспроизводим), и повторный (идемпотентный) прогон
двигал бы ``updated_at`` вперёд на каждый вызов. ``QuerySet.update()`` НЕ
проходит через ``Field.pre_save()`` (см. ``django/db/models/query.py::
QuerySet.update`` — работает напрямую с переданными kwargs, официально
задокументированное поведение Django: "auto_now недоступен для перезаписи
через save(), но доступен через QuerySet.update()"). Поэтому ``_upsert_row``
ниже делает ДВА шага на строку: ``update_or_create(defaults=<всё кроме
updated_at>)``, затем отдельный ``Model.objects.filter(<lookup>).update(
updated_at=<легаси-значение>)``, который расставляет точное легаси-значение
уже ПОСЛЕ того, как ``auto_now`` его перезаписал.

## Идемпотентность

``update_or_create`` по PK (``Room``/``Message``/``ChatAttachment``/
``AuditLog`` СОХРАНЯЮТ исходный легаси ``id`` явно — критично для ``Room``:
``RoomParticipant.room_id``/``Message.room_id``/``ChatAttachment.room_id``
хранят голое int-значение легаси ``room_id``, поэтому Django ``Room.id``
обязан совпадать с легаси ``rooms.id`` дословно, иначе перекрёстные ссылки
разъедутся) или по составному натуральному ключу (``RoomParticipant`` —
``room_id``+``user_id``; ``UserKey`` — ``user_id``+``device_id``, оба поля и
так были ``primary_key=True`` у легаси-модели, здесь — Django 5.2
``CompositePrimaryKey``, см. ``apps/messenger/models.py``). Второй прогон не
плодит дублей и не падает — то же самое ``update_or_create`` находит
существующую строку по тому же ключу.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.etl import (
    DEFAULT_SOURCE_DSN,
    Report,
    TableResult,
    legacy_count,
    legacy_cursor,
    row_hash,
)
from apps.messenger.models import (
    AuditLog,
    ChatAttachment,
    Message,
    Room,
    RoomParticipant,
    UserKey,
)

SCHEMA = "messenger"

# Р2 (см. модульный докстринг выше и apps/messenger/models.py): реплика
# пользователей легаси, у которой в Django нет и не будет модели.
SKIP_TABLE = "chat_user_replicas"
SKIP_NOTE = "skip: user replica (Р2), нет Django-цели"


@dataclass(frozen=True)
class _TableSpec:
    """Одна строка ETL-карты: легаси-таблица схемы messenger -> Django-модель.

    ``fields`` — ИМЕНА одновременно и legacy-колонок (SQL-алиасов, см.
    ``_select_sql``), и Django-атрибутов модели (``getattr(obj, f)``) — весь
    маппинг этого домена 1:1 по имени, поэтому один и тот же кортеж строк
    обслуживает и чтение из legacy, и чтение из Django-объекта при верификации
    (см. ``Command._table_result``), без риска, что два списка полей
    разъедутся друг с другом.
    ``lookup`` — подмножество ``fields``, однозначно определяющее строку
    (PK или составной натуральный ключ) — используется и как kwargs
    ``update_or_create()``, и как SQL ``ORDER BY``.
    ``column_overrides`` — SQL-выражение вместо голого имени колонки
    (сейчас только ``rooms.department_path::text``, см. модульный докстринг).
    """

    legacy_table: str
    model: type
    fields: tuple[str, ...]
    lookup: tuple[str, ...]
    column_overrides: dict[str, str] | None = None


# Порядок — родители раньше детей (FK ВНУТРИ домена, см. models.py).
_SPECS: tuple[_TableSpec, ...] = (
    _TableSpec(
        legacy_table="rooms",
        model=Room,
        fields=(
            "id", "name", "storage_key", "room_type", "department_path",
            "is_e2ee", "avatar_url", "created_at", "updated_at",
        ),
        lookup=("id",),
        column_overrides={"department_path": "department_path::text"},
    ),
    _TableSpec(
        legacy_table="room_participants",
        model=RoomParticipant,
        fields=(
            "room_id", "user_id", "role", "last_read_message_id",
            "created_at", "updated_at",
        ),
        lookup=("room_id", "user_id"),
    ),
    _TableSpec(
        legacy_table="messages",
        model=Message,
        fields=(
            "id", "room_id", "sender_id", "content", "is_encrypted",
            "metadata_json", "is_edited", "created_at", "updated_at",
        ),
        lookup=("id",),
    ),
    _TableSpec(
        legacy_table="chat_attachments",
        model=ChatAttachment,
        fields=(
            "id", "message_id", "room_id", "file_metadata_id", "filename",
            "size", "content_type", "data_type", "storage_path",
            "public_url", "thumbnail_path", "width", "height", "uploaded_by",
            "created_at", "updated_at",
        ),
        lookup=("id",),
    ),
    _TableSpec(
        legacy_table="audit_log",
        model=AuditLog,
        fields=(
            "id", "user_id", "action", "resource_type", "resource_id",
            "changes", "ip_address", "user_agent", "correlation_id",
            "created_at",
        ),
        lookup=("id",),
    ),
    _TableSpec(
        legacy_table="user_keys",
        model=UserKey,
        fields=(
            "user_id", "device_id", "public_identity_key", "signed_pre_key",
            "signature", "created_at", "updated_at",
        ),
        lookup=("user_id", "device_id"),
    ),
)


def _select_sql(spec: _TableSpec) -> str:
    overrides = spec.column_overrides or {}
    cols = [f"{overrides[f]} AS {f}" if f in overrides else f for f in spec.fields]
    order_by = ", ".join(spec.lookup)
    return (
        f'SELECT {", ".join(cols)} FROM "{SCHEMA}"."{spec.legacy_table}" '
        f"ORDER BY {order_by}"
    )


def _fetch_rows(cur, spec: _TableSpec) -> list[dict]:
    cur.execute(_select_sql(spec))
    return cur.fetchall()


def _upsert_row(spec: _TableSpec, fields: dict) -> bool:
    """Идемпотентный upsert одной строки. Возвращает True, если СОЗДАНА.

    Двухшаговая запись ``updated_at`` — см. модульный докстринг ("auto_now").
    """
    lookup_kwargs = {k: fields[k] for k in spec.lookup}
    defaults = {k: v for k, v in fields.items()
                if k not in spec.lookup and k != "updated_at"}

    _, created = spec.model.objects.update_or_create(**lookup_kwargs, defaults=defaults)
    if "updated_at" in fields:
        spec.model.objects.filter(**lookup_kwargs).update(updated_at=fields["updated_at"])
    return created


def _would_create(spec: _TableSpec, fields: dict) -> bool:
    lookup_kwargs = {k: fields[k] for k in spec.lookup}
    return not spec.model.objects.filter(**lookup_kwargs).exists()


def _render_report(report: Report, skip_src: int) -> str:
    """``report.render()`` + информационная ``[SKIP]``-строка про
    ``chat_user_replicas`` ПЕРЕД строкой ``ИТОГ:``.

    Строка НЕ добавляется в ``report.results`` (т.е. НЕ участвует в
    ``Report.ok``/коде выхода ``--verify``) — по брифу пропуск user-реплики
    "не считается расхождением", хотя ``src=13, tgt=0`` формально не совпали
    бы. Формат строки скопирован из ``TableResult``-цикла ``Report.render()``
    (``apps/core/etl.py``, общий для всех доменов файл — трогать нельзя),
    статус ``SKIP`` вместо ``OK``/``DIFF`` явно отличает её от реальной
    сверки.
    """
    lines = report.render().splitlines()
    total_line = lines.pop()  # "ИТОГ: ..."
    lines.append(
        f"[SKIP] {'messenger.' + SKIP_TABLE:<34} src={skip_src:<7} tgt={0:<7} "
        f"hash -  {SKIP_NOTE}"
    )
    lines.append(total_line)
    return "\n".join(lines)


class Command(BaseCommand):
    help = (
        "ETL фазы 10: перенос messenger.* (legacy FastAPI, схема messenger, "
        "read-only копия) в Django-модели apps.messenger. "
        "messenger.chat_user_replicas ПРОПУСКАЕТСЯ (Р2, нет Django-цели, см. "
        "докстринг файла)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-dsn", default=DEFAULT_SOURCE_DSN,
            help="DSN legacy-источника (дефолт — копия FastAPI-данных на :55432)",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Прочитать+смаппить легаси-строки, НИЧЕГО не писать в Django",
        )
        parser.add_argument(
            "--verify", action="store_true",
            help="Сверка count+hash (legacy vs Django) вместо переноса",
        )
        parser.add_argument(
            "--limit", type=int, default=50,
            help="Сколько строк на таблицу сверять по hash в --verify (дефолт 50)",
        )

    def handle(self, *args, **options):
        dsn = options["source_dsn"]
        with legacy_cursor(dsn) as cur:
            if options["dry_run"]:
                self._run_dry(cur)
                return
            if options["verify"]:
                self._run_verify(cur, options["limit"])
                return
            self._run_migrate(cur)

    # ------------------------------------------------------------------
    # без флагов — идемпотентный upsert + count-сводка
    # ------------------------------------------------------------------
    def _run_migrate(self, cur) -> None:
        with transaction.atomic():
            for spec in _SPECS:
                rows = _fetch_rows(cur, spec)
                created = updated = 0
                for row in rows:
                    fields = {f: row[f] for f in spec.fields}
                    if _upsert_row(spec, fields):
                        created += 1
                    else:
                        updated += 1
                self.stdout.write(
                    f"messenger.{spec.legacy_table} -> {spec.model.__name__}: "
                    f"{len(rows)} legacy строк (создано {created}, "
                    f"обновлено {updated})"
                )

        skip_src = legacy_count(cur, SKIP_TABLE, schema=SCHEMA)
        self.stdout.write(self.style.WARNING(
            f"messenger.{SKIP_TABLE}: {skip_src} legacy строк — {SKIP_NOTE}"
        ))

        report = self._build_report(cur, sample_limit=0)
        self.stdout.write(_render_report(report, skip_src))

    # ------------------------------------------------------------------
    # --verify — сверка count+hash, ничего не пишет
    # ------------------------------------------------------------------
    def _run_verify(self, cur, limit: int) -> None:
        report = self._build_report(cur, sample_limit=limit)
        skip_src = legacy_count(cur, SKIP_TABLE, schema=SCHEMA)
        self.stdout.write(_render_report(report, skip_src))
        if not report.ok:
            sys.exit(1)

    # ------------------------------------------------------------------
    # --dry-run — читает+маппит, ничего не пишет и не сверяет
    # ------------------------------------------------------------------
    def _run_dry(self, cur) -> None:
        for spec in _SPECS:
            rows = _fetch_rows(cur, spec)
            would_create = would_update = 0
            for row in rows:
                fields = {f: row[f] for f in spec.fields}
                if _would_create(spec, fields):
                    would_create += 1
                else:
                    would_update += 1
            self.stdout.write(
                f"[DRY] messenger.{spec.legacy_table} -> {spec.model.__name__}: "
                f"{len(rows)} legacy строк (создал бы {would_create}, "
                f"обновил бы {would_update}) — ничего не записано"
            )
        skip_src = legacy_count(cur, SKIP_TABLE, schema=SCHEMA)
        self.stdout.write(self.style.WARNING(
            f"[DRY] messenger.{SKIP_TABLE}: {skip_src} legacy строк — {SKIP_NOTE}"
        ))

    # ------------------------------------------------------------------
    def _build_report(self, cur, sample_limit: int) -> Report:
        report = Report(domain="messenger")
        for spec in _SPECS:
            report.add(self._table_result(cur, spec, sample_limit))
        return report

    def _table_result(self, cur, spec: _TableSpec, sample_limit: int) -> TableResult:
        src = legacy_count(cur, spec.legacy_table, schema=SCHEMA)
        tgt = spec.model.objects.count()
        sample = 0
        hash_match = 0
        if sample_limit > 0:
            rows = _fetch_rows(cur, spec)[:sample_limit]
            sample = len(rows)
            for row in rows:
                legacy_fields = {f: row[f] for f in spec.fields}
                lookup_kwargs = {k: row[k] for k in spec.lookup}
                obj = spec.model.objects.filter(**lookup_kwargs).first()
                if obj is None:
                    continue
                django_fields = {f: getattr(obj, f) for f in spec.fields}
                if row_hash(legacy_fields) == row_hash(django_fields):
                    hash_match += 1
        return TableResult(
            name=f"messenger.{spec.legacy_table}", src=src, tgt=tgt,
            sample=sample, hash_match=hash_match,
        )

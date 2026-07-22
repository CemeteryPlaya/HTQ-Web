"""ETL фазы 10 — перелив ``media.*`` (legacy FastAPI, схема ``media``) в
``apps.media_files`` (Django ORM).

    python manage.py etl_media [--source-dsn DSN] [--dry-run] [--verify] [--limit N]

Домен ``media`` — ТОЛЬКО метаданные (``services/media/app/models/*.py``):
сами файлы лежат в S3/MinIO и не переносятся, здесь копируются лишь строки
(``path``, ``sha256``, ``mime``, ``size``/``width``/``height`` и т.д.).
Ничего не скачивается и не проверяется на стороне object storage.

Три непустые legacy-таблицы, порядок переноса уважает внутридоменный FK
(``file_variants.file_id -> file_metadata.id``):

    media.file_metadata (51) -> FileMetadata
    media.file_variants  (7) -> FileVariant
    media.audit_log      (52) -> AuditLog

Колонки всех трёх таблиц сопоставлены 1:1 с полями Django-моделей (см.
``apps/media_files/models.py``) — переименований нет, сверено построчно
против ``\\d media.<table>`` источника и старых SQLAlchemy-моделей. Кросс-
доменные ссылки (``owner_id``/``user_id``) остаются простыми int (не FK) —
инвариант межаппной изоляции.

Общая инфраструктура (курсор на legacy, count/hash-хелперы, единый формат
отчёта) — ``apps.core.etl``, см. её докстринг.
"""
from __future__ import annotations

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
from apps.media_files.models import AuditLog, FileMetadata, FileVariant

SCHEMA = "media"

# Колонка-в-колонку: имя legacy-колонки == имя поля/attname Django-модели
# для ВСЕХ трёх таблиц (сверено против services/media/app/models/*.py и
# \d вживую на обеих БД — переименований нет). Один и тот же список ключей
# используется и для сборки словаря на hash-сверку (с обеих сторон), и как
# набор колонок для update_or_create(defaults=...) (минус "id").
#
# FileVariant.file — ForeignKey(FileMetadata); Django-attname у FK — ровно
# "file_id", то же имя, что и у legacy-колонки, поэтому getattr(obj, "file_id")
# работает единообразно, без спецкейса под FK.
FILE_METADATA_KEYS: tuple[str, ...] = (
    "id", "path", "original_filename", "owner_id", "size", "mime",
    "storage_backend", "is_public", "sha256", "kind", "scope",
    "width", "height", "deleted_at", "created_at", "updated_at",
)
FILE_VARIANT_KEYS: tuple[str, ...] = (
    "id", "file_id", "variant", "path", "size", "mime", "width", "height", "created_at",
)
AUDIT_LOG_KEYS: tuple[str, ...] = (
    "id", "user_id", "action", "resource_type", "resource_id", "changes",
    "ip_address", "user_agent", "correlation_id", "created_at",
)

# (legacy table name in schema `media`, Django model, column keys, отчётный note).
# Порядок ВАЖЕН: file_metadata раньше file_variants (FK-родитель раньше ребёнка).
TABLE_SPECS: tuple[tuple[str, type, tuple[str, ...], str], ...] = (
    ("file_metadata", FileMetadata, FILE_METADATA_KEYS,
     "только метаданные — сам объект в S3/MinIO не переносится"),
    ("file_variants", FileVariant, FILE_VARIANT_KEYS, ""),
    ("audit_log", AuditLog, AUDIT_LOG_KEYS, ""),
)

# Все три модели держат created_at (FileMetadata + updated_at тоже) как
# auto_now_add=/auto_now=True — Django ЖЁСТКО перезаписывает эти поля
# текущим временем на каждый Model.save(), включая save() внутри
# update_or_create(), игнорируя любое явно переданное значение (это не
# дефолт, а безусловный override — см. докстринг Field.pre_save()). Чтобы
# сохранить ПОДЛИННЫЕ legacy-таймстемпы, после upsert'а форсируем их через
# QuerySet.update() — тот НЕ ходит через Model.save(), auto_now(_add) не
# применяется, пишется ровно то, что передали.
AUTO_TIMESTAMP_KEYS: dict[type, tuple[str, ...]] = {
    FileMetadata: ("created_at", "updated_at"),
    FileVariant: ("created_at",),
    AuditLog: ("created_at",),
}


def _row_fields(row: dict, keys: tuple[str, ...]) -> dict:
    """Словарь для hash-сверки из legacy dict-row (psycopg dict_row)."""
    return {k: row[k] for k in keys}


def _obj_fields(obj, keys: tuple[str, ...]) -> dict:
    """Тот же словарь, собранный с Django-объекта (по тем же ключам)."""
    return {k: getattr(obj, k) for k in keys}


class _DryRunRollback(Exception):
    """Внутренний сигнал: --dry-run должен откатить внешний atomic()."""


class Command(BaseCommand):
    help = (
        "ETL фазы 10: перелив media.* (legacy FastAPI, схема `media`) в "
        "apps.media_files (Django ORM). Только метаданные, S3/MinIO не трогаем."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-dsn", default=DEFAULT_SOURCE_DSN,
            help="DSN legacy-источника (дефолт — копия FastAPI-БД, :55432/htqweb).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Прочитать + смаппить, ничего не писать (транзакция откатывается).",
        )
        parser.add_argument(
            "--verify", action="store_true",
            help="Только сверка count+hash по каждой таблице (без записи), печатает отчёт.",
        )
        parser.add_argument(
            "--limit", type=int, default=50,
            help="Сколько строк на таблицу сверять по hash в --verify (дефолт 50).",
        )

    def handle(self, *args, **options):
        dsn = options["source_dsn"]

        if options["verify"]:
            self._verify(dsn, options["limit"])
            return

        self._sync(dsn, dry_run=options["dry_run"])

    # ------------------------------------------------------------------
    # upsert (без флагов / --dry-run)
    # ------------------------------------------------------------------

    def _sync(self, dsn: str, dry_run: bool) -> None:
        counts = {table: {"created": 0, "updated": 0} for table, *_ in TABLE_SPECS}

        try:
            with transaction.atomic():
                with legacy_cursor(dsn) as cur:
                    for table, model, keys, _note in TABLE_SPECS:
                        n = self._load_table(cur, table, model, keys, counts[table])
                        self.stdout.write(f"{table}: прочитано {n} строк из legacy")

                if not dry_run:
                    self._resync_auditlog_pk_sequence()

                if dry_run:
                    # Откатываем ВСЮ транзакцию (включая уже сделанные
                    # update_or_create внутри неё) — --dry-run обязан не
                    # писать ничего в БД.
                    raise _DryRunRollback
        except _DryRunRollback:
            pass

        if dry_run:
            self.stdout.write(self.style.WARNING(
                "--dry-run: транзакция откачена, в БД ничего не записано"
            ))
            for table, c in counts.items():
                self.stdout.write(
                    f"  {table}: создал бы {c['created']}, обновил бы {c['updated']}"
                )
            return

        for table, c in counts.items():
            self.stdout.write(
                self.style.SUCCESS(
                    f"{table}: создано {c['created']}, обновлено {c['updated']}"
                )
            )

        # count-сводка (без per-row hash — это работа --verify)
        with legacy_cursor(dsn) as cur:
            report = self._build_report(cur, sample_limit=0)
        self.stdout.write(report.render())

    def _load_table(self, cur, table: str, model, keys: tuple[str, ...], counter: dict) -> int:
        cur.execute(f'SELECT * FROM "{SCHEMA}"."{table}" ORDER BY id')
        rows = cur.fetchall()
        ts_keys = AUTO_TIMESTAMP_KEYS.get(model, ())
        for row in rows:
            defaults = {k: row[k] for k in keys if k != "id"}
            _obj, created = model.objects.update_or_create(id=row["id"], defaults=defaults)
            if ts_keys:
                # Форсируем подлинные legacy-таймстемпы поверх auto_now(_add)
                # — см. AUTO_TIMESTAMP_KEYS выше.
                model.objects.filter(pk=row["id"]).update(**{k: row[k] for k in ts_keys})
            counter["created" if created else "updated"] += 1
        return len(rows)

    def _resync_auditlog_pk_sequence(self) -> None:
        """``AuditLog.id`` — обычный Django AutoField (identity-колонка), а
        мы пишем в него явно (сохраняем legacy id) через
        ``update_or_create(id=..., ...)``. Postgres САМ не продвигает
        identity-последовательность при явной вставке id — без этого шага
        первая же запись, которую позже создаст живое Django-приложение без
        явного id (``nextval()``), может попытаться взять id, уже занятый
        перенесённой строкой. Идемпотентно: просто выставляет счётчик на
        MAX(id) текущей таблицы (no-op, если таблица пуста).
        Только для не-dry-run веток — при --dry-run транзакция откатывается,
        но setval() в Postgres НЕ транзакционен, поэтому не должен вызываться
        внутри отменяемого прогона.
        """
        table_name = AuditLog._meta.db_table
        with connection.cursor() as cur:
            cur.execute(
                "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                f'COALESCE((SELECT MAX(id) FROM "{table_name}"), 1), '
                f'(SELECT MAX(id) FROM "{table_name}") IS NOT NULL)',
                [table_name],
            )

    # ------------------------------------------------------------------
    # --verify
    # ------------------------------------------------------------------

    def _verify(self, dsn: str, limit: int) -> None:
        with legacy_cursor(dsn) as cur:
            report = self._build_report(cur, sample_limit=limit)
        self.stdout.write(report.render())
        if not report.ok:
            raise CommandError("ETL media: сверка нашла расхождения (см. отчёт выше)")

    def _build_report(self, cur, sample_limit: int) -> Report:
        report = Report(domain="media")
        for table, model, keys, note in TABLE_SPECS:
            src = legacy_count(cur, table, schema=SCHEMA)
            tgt = model.objects.count()
            sample = 0
            hash_match = 0

            if sample_limit:
                n = min(sample_limit, src)
                cur.execute(
                    f'SELECT * FROM "{SCHEMA}"."{table}" ORDER BY id LIMIT %s', [n]
                )
                sample_rows = cur.fetchall()
                sample = len(sample_rows)
                for row in sample_rows:
                    obj = model.objects.filter(pk=row["id"]).first()
                    if obj is None:
                        continue
                    if row_hash(_row_fields(row, keys)) == row_hash(_obj_fields(obj, keys)):
                        hash_match += 1

            report.add(TableResult(
                name=f"media.{table}", src=src, tgt=tgt,
                sample=sample, hash_match=hash_match, note=note,
            ))
        return report

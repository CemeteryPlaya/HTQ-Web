"""``manage.py etl_mail`` — Фаза 10 (ETL): перелив legacy FastAPI-БД (email-
service, схема Postgres ``email``, НЕ ``public``!) в Django ``apps.mail``.

Источник (read-only, копия — не боевая БД): 7 непустых/учтённых таблиц схемы
``email`` — см. ``services/email/app/models/{account,email,mailbox,
audit_log}.py`` для точных ``__tablename__``/колонок:

  * ``email.provisioned_mailboxes``  → ``ProvisionedMailbox``
  * ``email.oauth_tokens``           → ``OAuthToken``
  * ``email.email_accounts``         → ``EmailAccount``
  * ``email.email_messages``         → ``EmailMessage``
  * ``email.email_attachments``      → ``EmailAttachment`` (пустая в проде,
    маппинг/verify всё равно есть — паритет схемы)
  * ``email.recipient_statuses``     → ``RecipientStatus``
  * ``email.audit_log``              → ``AuditLog`` — ⚠️ ОТСУТСТВУЕТ в этой
    копии БД (``relation "email.audit_log" does not exist`` — проверено
    напрямую; ``psql \\d email.*``/``information_schema.tables`` подтверждают: схема
    ``email`` физически несёт только 6 таблиц выше). Источник —
    ``services/email/app/models/audit_log.py::AuditLog`` не объявляет
    ``__table_args__ = {"schema": "email"}`` (в отличие от ``account.py``/
    ``email.py``/``mailbox.py`` в этом же пакете, где схема указана явно) —
    похоже, эта таблица никогда не была смигрирована для email-service (в
    отличие от cms/media/messenger, у которых ``<их схема>.audit_log`` реально
    существует). Обрабатывается не как хардкод-исключение, а универсально —
    см. ``_table_exists``: КАЖДАЯ таблица спецификации сначала проверяется на
    физическое существование в legacy-БД; отсутствующая — src=0 (а не
    падение команды), с ``note`` в отчёте, по тем же count/hash правилам, что
    и остальные (если Django-цель почему-то не пуста — расхождение так же
    честно всплывёт как DIFF, тут не "всегда OK").

Порядок вставки (``SPECS`` ниже) уважает FK-зависимости ВНУТРИ домена
(родители раньше детей), как того требует общий контракт
(``etl-contract.md``): ``ProvisionedMailbox``/``OAuthToken`` — родители
``EmailAccount`` (её ``mailbox_id``/``oauth_token_id`` на них ссылаются), не
наоборот — поэтому здесь они идут ДО ``EmailAccount``, а не после, как можно
прочитать в буквальной формулировке доменного брифа ("EmailAccount →
OAuthToken/ProvisionedMailbox → ..."); дальше ``EmailMessage`` (ссылается на
``EmailAccount``), затем её дети ``EmailAttachment``/``RecipientStatus``.
``AuditLog`` (mail-домена) внутри-доменных FK не несёт — место в списке не
важно, оставлена последней.

Маппинг колонок — везде 1:1 (те же имена что у SQLAlchemy-моделей; Django-порт
в ``apps/mail/models.py`` не переименовывал ни одной колонки этих 7 таблиц).
Кросс-доменные ссылки (``user_id``, ``account_id``/``message_id`` пере-нося
как обычные int/uuid) копируются как есть — они НЕ FK на другие Django-аппки
(инвариант межаппной изоляции, ``apps/core/tests/test_app_isolation.py``).

⚠️ Шифртексты/токены: ``OAuthToken.encrypted_access_token``/
``encrypted_refresh_token`` и ``ProvisionedMailbox.encrypted_smtp_app_password``
— AES-256-GCM ciphertext (``apps/mail/services/crypto.py``) — копируются
байт-в-байт, никогда не расшифровываются/не перешифровываются здесь. Ключ
шифрования (``settings.ENCRYPTION_KEY``) должен быть один и тот же в обеих
средах, иначе расшифровка после переноса не сработает — это ответственность
конфигурации окружения, не этой команды.

Автоинкремент-PK (``ProvisionedMailbox``/``OAuthToken``/``EmailAccount``/
``RecipientStatus``/``AuditLog``): переносим legacy ``id`` явно (натуральный
ключ переноса — используем его как lookup для идемпотентного
``update_or_create``), поэтому после загрузки нужно подтянуть Postgres-
sequence до ``MAX(id)`` — иначе следующий обычный ``INSERT`` через приложение
получит номер, уже занятый перенесённой строкой. См. ``_reset_sequence``
(``django.db.connection.ops.sequence_reset_sql`` — официальный механизм,
тот же, что использует ``loaddata``). UUID-модели (``EmailMessage``/
``EmailAttachment``) сюда же передаются безопасно: ``sequence_reset_sql``
для non-autoincrement PK просто возвращает пустой список.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Callable

from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connection, transaction

from apps.core.etl import (
    DEFAULT_SOURCE_DSN,
    Report,
    TableResult,
    legacy_count,
    legacy_cursor,
    row_hash,
)
from apps.mail.models import (
    AuditLog,
    EmailAccount,
    EmailAttachment,
    EmailMessage,
    OAuthToken,
    ProvisionedMailbox,
    RecipientStatus,
)

_SCHEMA = "email"


def _utc(value: Any) -> Any:
    """Нормализует tz-aware ``datetime`` к UTC-представлению offset'а.

    Легаси-курсор (голый psycopg, без Django) и Django ORM (``USE_TZ=True``,
    ``TIME_ZONE='UTC'``) МОГУТ вернуть один и тот же момент времени с разным
    ``tzinfo`` (например ``+00:00`` вместо ``+03:00``) — ``timestamptz`` в
    Postgres абсолютен, но ``row_hash``/``_norm`` в ``apps/core/etl.py``
    хеширует ``.isoformat()``, а он ЧУВСТВИТЕЛЕН к представлению offset'а.
    Приводим обе стороны к UTC ДО хеширования (и до записи — тот же момент
    времени, просто другое "лицо" tzinfo, безопасно) — без этого хеш мог бы
    разойтись из-за окружения, а не из-за реальных данных.
    """
    if isinstance(value, dt.datetime) and value.tzinfo is not None:
        return value.astimezone(dt.timezone.utc)
    return value


def _fetch_rows(cur, table: str, *, limit: int | None = None, order_col: str = "id") -> list[dict]:
    """Все колонки (``SELECT *``) legacy-таблицы схемы ``email``, упорядоченные
    по ``order_col`` — детерминированно для сэмплинга в ``--verify``."""
    sql = f'SELECT * FROM "{_SCHEMA}"."{table}" ORDER BY "{order_col}"'
    if limit is not None:
        cur.execute(sql + " LIMIT %s", [limit])
    else:
        cur.execute(sql)
    return cur.fetchall()


def _table_exists(cur, table: str, schema: str = _SCHEMA) -> bool:
    """Проверка физического существования legacy-таблицы ПЕРЕД чтением.

    Не хардкод-исключение под ``audit_log`` конкретно — универсальная защита:
    эта копия БД, как выяснилось при реальном прогоне, не несёт
    ``email.audit_log`` вовсе (``UndefinedTable`` при прямом ``SELECT``, см.
    module docstring). ``legacy_cursor`` работает в ``autocommit=True``
    (``apps/core/etl.py``), поэтому проверка через ``information_schema`` —
    без риска "отравить" транзакцию для последующих таблиц спецификации.
    """
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = %s AND table_name = %s) AS present",
        [schema, table],
    )
    return bool(cur.fetchone()["present"])


def _reset_sequence(model: type) -> None:
    """Подтягивает Postgres-sequence автополя PK до ``MAX(id)`` после
    upsert'а с явно переданным ``id`` (Django НЕ продвигает sequence сам,
    когда PK указан руками). Официальный механизм (``loaddata`` использует
    тот же ``connection.ops.sequence_reset_sql``); no-op для UUID-PK моделей."""
    with connection.cursor() as cursor:
        for sql in connection.ops.sequence_reset_sql(no_style(), [model]):
            cursor.execute(sql)


class _DryRunRollback(Exception):
    """Внутренний сигнал для отката транзакции --dry-run (см. Command._run_load)."""


# ─────────────────────────────────────────────────────────────────────────
# Маппинг полей: ОДНА и та же форма словаря используется и как `defaults=`
# для update_or_create, и как вход в row_hash() с обеих сторон (legacy-строка
# / Django-объект) — см. apps/core/etl.py::row_hash. `<fk>_id=...` ключи
# (mailbox_id, oauth_token_id, account_id, message_id) — обычные Django-
# attname'ы FK-полей, валидны и в defaults=, и как getattr(obj, "...").
# ─────────────────────────────────────────────────────────────────────────


def _pm_row(row: dict) -> dict:
    return {
        "user_id": row["user_id"],
        "local_part": row["local_part"],
        "domain": row["domain"],
        "address": row["address"],
        "status": row["status"],
        "quota_mb": row["quota_mb"],
        "display_name": row["display_name"],
        "last_error": row["last_error"],
        "encrypted_smtp_app_password": row["encrypted_smtp_app_password"],
        "created_at": _utc(row["created_at"]),
        "updated_at": _utc(row["updated_at"]),
        "archived_at": _utc(row["archived_at"]),
        "deleted_at": _utc(row["deleted_at"]),
    }


def _pm_obj(obj: ProvisionedMailbox) -> dict:
    return {
        "user_id": obj.user_id,
        "local_part": obj.local_part,
        "domain": obj.domain,
        "address": obj.address,
        "status": obj.status,
        "quota_mb": obj.quota_mb,
        "display_name": obj.display_name,
        "last_error": obj.last_error,
        "encrypted_smtp_app_password": obj.encrypted_smtp_app_password,
        "created_at": _utc(obj.created_at),
        "updated_at": _utc(obj.updated_at),
        "archived_at": _utc(obj.archived_at),
        "deleted_at": _utc(obj.deleted_at),
    }


def _oauth_row(row: dict) -> dict:
    return {
        "user_id": row["user_id"],
        "provider": row["provider"],
        "provider_account_id": row["provider_account_id"],
        "encrypted_access_token": row["encrypted_access_token"],
        "encrypted_refresh_token": row["encrypted_refresh_token"],
        "expires_at": _utc(row["expires_at"]),
        "is_active": row["is_active"],
        "created_at": _utc(row["created_at"]),
        "updated_at": _utc(row["updated_at"]),
    }


def _oauth_obj(obj: OAuthToken) -> dict:
    return {
        "user_id": obj.user_id,
        "provider": obj.provider,
        "provider_account_id": obj.provider_account_id,
        "encrypted_access_token": obj.encrypted_access_token,
        "encrypted_refresh_token": obj.encrypted_refresh_token,
        "expires_at": _utc(obj.expires_at),
        "is_active": obj.is_active,
        "created_at": _utc(obj.created_at),
        "updated_at": _utc(obj.updated_at),
    }


def _acct_row(row: dict) -> dict:
    return {
        "user_id": row["user_id"],
        "type": row["type"],
        "provider": row["provider"],
        "address": row["address"],
        "display_name": row["display_name"],
        "is_default": row["is_default"],
        "is_active": row["is_active"],
        "mailbox_id": row["mailbox_id"],
        "oauth_token_id": row["oauth_token_id"],
        "sync_state": row["sync_state"],
        "last_sync_at": _utc(row["last_sync_at"]),
        "last_sync_error": row["last_sync_error"],
        "watch_expires_at": _utc(row["watch_expires_at"]),
        "connected_at": _utc(row["connected_at"]),
        "created_at": _utc(row["created_at"]),
        "updated_at": _utc(row["updated_at"]),
    }


def _acct_obj(obj: EmailAccount) -> dict:
    return {
        "user_id": obj.user_id,
        "type": obj.type,
        "provider": obj.provider,
        "address": obj.address,
        "display_name": obj.display_name,
        "is_default": obj.is_default,
        "is_active": obj.is_active,
        "mailbox_id": obj.mailbox_id,
        "oauth_token_id": obj.oauth_token_id,
        "sync_state": obj.sync_state,
        "last_sync_at": _utc(obj.last_sync_at),
        "last_sync_error": obj.last_sync_error,
        "watch_expires_at": _utc(obj.watch_expires_at),
        "connected_at": _utc(obj.connected_at),
        "created_at": _utc(obj.created_at),
        "updated_at": _utc(obj.updated_at),
    }


def _msg_row(row: dict) -> dict:
    return {
        "user_id": row["user_id"],
        "account_id": row["account_id"],
        "message_id": row["message_id"],
        "thread_id": row["thread_id"],
        "folder": row["folder"],
        "provider_folder": row["provider_folder"],
        "subject": row["subject"],
        "snippet": row["snippet"],
        "body_html": row["body_html"],
        "body_text": row["body_text"],
        "sender_email": row["sender_email"],
        "sender_name": row["sender_name"],
        "to_recipients": row["to_recipients"],
        "cc_recipients": row["cc_recipients"],
        "bcc_recipients": row["bcc_recipients"],
        "is_read": row["is_read"],
        "is_flagged": row["is_flagged"],
        "has_attachments": row["has_attachments"],
        "date": _utc(row["date"]),
        "dlp_flagged": row["dlp_flagged"],
        "created_at": _utc(row["created_at"]),
        "updated_at": _utc(row["updated_at"]),
    }


def _msg_obj(obj: EmailMessage) -> dict:
    return {
        "user_id": obj.user_id,
        "account_id": obj.account_id,
        "message_id": obj.message_id,
        "thread_id": obj.thread_id,
        "folder": obj.folder,
        "provider_folder": obj.provider_folder,
        "subject": obj.subject,
        "snippet": obj.snippet,
        "body_html": obj.body_html,
        "body_text": obj.body_text,
        "sender_email": obj.sender_email,
        "sender_name": obj.sender_name,
        "to_recipients": obj.to_recipients,
        "cc_recipients": obj.cc_recipients,
        "bcc_recipients": obj.bcc_recipients,
        "is_read": obj.is_read,
        "is_flagged": obj.is_flagged,
        "has_attachments": obj.has_attachments,
        "date": _utc(obj.date),
        "dlp_flagged": obj.dlp_flagged,
        "created_at": _utc(obj.created_at),
        "updated_at": _utc(obj.updated_at),
    }


def _att_row(row: dict) -> dict:
    return {
        "message_id": row["message_id"],
        "file_metadata_id": row["file_metadata_id"],
        "filename": row["filename"],
        "mime_type": row["mime_type"],
        "size": row["size"],
        "content_id": row["content_id"],
        "created_at": _utc(row["created_at"]),
        "updated_at": _utc(row["updated_at"]),
    }


def _att_obj(obj: EmailAttachment) -> dict:
    return {
        "message_id": obj.message_id,
        "file_metadata_id": obj.file_metadata_id,
        "filename": obj.filename,
        "mime_type": obj.mime_type,
        "size": obj.size,
        "content_id": obj.content_id,
        "created_at": _utc(obj.created_at),
        "updated_at": _utc(obj.updated_at),
    }


def _rs_row(row: dict) -> dict:
    return {
        "message_id": row["message_id"],
        "recipient_email": row["recipient_email"],
        "status": row["status"],
        "error_message": row["error_message"],
        "created_at": _utc(row["created_at"]),
        "updated_at": _utc(row["updated_at"]),
    }


def _rs_obj(obj: RecipientStatus) -> dict:
    return {
        "message_id": obj.message_id,
        "recipient_email": obj.recipient_email,
        "status": obj.status,
        "error_message": obj.error_message,
        "created_at": _utc(obj.created_at),
        "updated_at": _utc(obj.updated_at),
    }


def _audit_row(row: dict) -> dict:
    return {
        "user_id": row["user_id"],
        "action": row["action"],
        "resource_type": row["resource_type"],
        "resource_id": row["resource_id"],
        "changes": row["changes"],
        "ip_address": row["ip_address"],
        "user_agent": row["user_agent"],
        "correlation_id": row["correlation_id"],
        "created_at": _utc(row["created_at"]),
    }


def _audit_obj(obj: AuditLog) -> dict:
    return {
        "user_id": obj.user_id,
        "action": obj.action,
        "resource_type": obj.resource_type,
        "resource_id": obj.resource_id,
        "changes": obj.changes,
        "ip_address": obj.ip_address,
        "user_agent": obj.user_agent,
        "correlation_id": obj.correlation_id,
        "created_at": _utc(obj.created_at),
    }


@dataclass(frozen=True)
class _Spec:
    table: str                              # legacy: schema email, __tablename__
    model: type
    row_fields: Callable[[dict], dict]
    obj_fields: Callable[[Any], dict]


# Порядок = зависимости FK внутри домена, родители раньше детей (см. module
# docstring — отличается от буквальной формулировки доменного брифа).
SPECS: tuple[_Spec, ...] = (
    _Spec("provisioned_mailboxes", ProvisionedMailbox, _pm_row, _pm_obj),
    _Spec("oauth_tokens", OAuthToken, _oauth_row, _oauth_obj),
    _Spec("email_accounts", EmailAccount, _acct_row, _acct_obj),
    _Spec("email_messages", EmailMessage, _msg_row, _msg_obj),
    _Spec("email_attachments", EmailAttachment, _att_row, _att_obj),
    _Spec("recipient_statuses", RecipientStatus, _rs_row, _rs_obj),
    _Spec("audit_log", AuditLog, _audit_row, _audit_obj),
)


class Command(BaseCommand):
    help = (
        "ETL mail (Фаза 10): перелив legacy FastAPI-БД (email-service, схема "
        "Postgres `email`) в Django apps.mail. Без флагов — идемпотентный "
        "upsert + count-сводка. --dry-run — прочитать/смаппить, ничего не "
        "писать (транзакция откатывается). --verify — сверка count+hash "
        "(код выхода 1 при расхождении)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--source-dsn", default=DEFAULT_SOURCE_DSN,
            help="DSN legacy-БД (по умолчанию — копия из apps.core.etl.DEFAULT_SOURCE_DSN).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Прочитать+смаппить, ничего не записывать (rollback транзакции).",
        )
        parser.add_argument(
            "--verify", action="store_true",
            help="Сверка count+hash вместо загрузки; код выхода 1, если есть расхождения.",
        )
        parser.add_argument(
            "--limit", type=int, default=None,
            help="Загрузка: макс. строк на таблицу. --verify: размер per-row "
                 "hash-выборки (дефолт 50, или все — если строк меньше).",
        )

    def handle(self, *args, **options) -> None:
        dsn: str = options["source_dsn"]
        if options["verify"]:
            self._run_verify(dsn, options["limit"])
        else:
            self._run_load(dsn, dry_run=options["dry_run"], limit=options["limit"])

    # ── load (без флагов / --dry-run) ───────────────────────────────────

    def _run_load(self, dsn: str, *, dry_run: bool, limit: int | None) -> None:
        results: list[tuple[_Spec, int, int, int, str]] = []
        try:
            with transaction.atomic():
                with legacy_cursor(dsn) as cur:
                    for spec in SPECS:
                        if not _table_exists(cur, spec.table):
                            results.append((
                                spec, 0, 0, 0,
                                f"legacy-таблица email.{spec.table} отсутствует в этой "
                                "копии БД (не мигрирована исходным сервисом) — пропущено",
                            ))
                            continue
                        rows = _fetch_rows(cur, spec.table, limit=limit)
                        created = updated = 0
                        for row in rows:
                            defaults = spec.row_fields(row)
                            _obj, was_created = spec.model.objects.update_or_create(
                                id=row["id"], defaults=defaults,
                            )
                            # updated_at = auto_now=True → Model.save() (внутри
                            # update_or_create) молча перезаписывает переданное
                            # legacy-значение на "сейчас". QuerySet.update() ставит
                            # точное legacy-значение в обход save() (auto_now там не
                            # срабатывает). created_at — db_default без auto_now_add,
                            # переданное значение сохраняется, править не нужно.
                            if "updated_at" in defaults:
                                spec.model.objects.filter(id=row["id"]).update(
                                    updated_at=defaults["updated_at"],
                                )
                            if was_created:
                                created += 1
                            else:
                                updated += 1
                        results.append((spec, len(rows), created, updated, ""))

                if not dry_run:
                    for spec, *_rest in results:
                        _reset_sequence(spec.model)
                else:
                    raise _DryRunRollback()
        except _DryRunRollback:
            pass

        prefix = "[dry-run] " if dry_run else ""
        for spec, n, created, updated, note in results:
            suffix = f"  ({note})" if note else ""
            self.stdout.write(
                f"{prefix}email.{spec.table:<22} -> mail_{spec.model.__name__.lower():<18} "
                f"прочитано={n:<5} создано={created:<5} обновлено={updated:<5}{suffix}"
            )
        if dry_run:
            self.stdout.write(self.style.WARNING(
                "--dry-run: транзакция откачена, в БД ничего не записано."
            ))

    # ── verify (--verify) ────────────────────────────────────────────────

    def _run_verify(self, dsn: str, limit: int | None) -> None:
        sample_limit = limit if limit is not None else 50
        report = Report(domain="mail")
        with legacy_cursor(dsn) as cur:
            for spec in SPECS:
                tgt = spec.model.objects.count()

                if not _table_exists(cur, spec.table):
                    report.add(TableResult(
                        name=f"email.{spec.table} -> mail_{spec.model.__name__.lower()}",
                        src=0, tgt=tgt, sample=0, hash_match=0,
                        note=(
                            f"legacy-таблица email.{spec.table} отсутствует в этой копии "
                            "БД (не мигрирована исходным сервисом)"
                        ),
                    ))
                    continue

                src = legacy_count(cur, spec.table, schema=_SCHEMA)
                take = min(sample_limit, src)
                sample_rows = _fetch_rows(cur, spec.table, limit=take)
                hash_match = 0
                for row in sample_rows:
                    try:
                        obj = spec.model.objects.get(pk=row["id"])
                    except spec.model.DoesNotExist:
                        continue
                    if row_hash(spec.row_fields(row)) == row_hash(spec.obj_fields(obj)):
                        hash_match += 1

                note = "src пуст (0 строк в legacy)" if src == 0 else ""
                report.add(TableResult(
                    name=f"email.{spec.table} -> mail_{spec.model.__name__.lower()}",
                    src=src, tgt=tgt, sample=len(sample_rows), hash_match=hash_match,
                    note=note,
                ))
        self.stdout.write(report.render())
        if not report.ok:
            raise CommandError("etl_mail --verify: обнаружены расхождения (см. отчёт выше).")

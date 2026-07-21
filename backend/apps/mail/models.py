"""Модели домена mail — mail-core: порт services/email/app/models/
{account,email,audit_log}.py.

Имена таблиц — дефолтные Django (решение D2, как и в apps.hr): mail_
emailaccount, mail_oauthtoken, mail_auditlog. Старые имена (email_accounts,
oauth_tokens, audit_log) живут только в карте ETL будущей фазы. Схема — ТОЛЬКО
public (PgBouncer transaction-mode роняет search_path, см. CLAUDE.md); в
исходнике таблицы жили в схеме ``email``, здесь это не переносится.

Область mail-core (бриф prep): EmailAccount + OAuthToken + AuditLog(mail) +
crypto. ``EmailAccount.mailbox_id`` остаётся голым уникальным int без FK
(решение 4 брифа mail-core) — ``ProvisionedMailbox`` создаётся под-задачей
mailboxes, ещё не перенесена (вне зоны mail-messages); растяжка
``tests/test_stretch.py::test_mailbox_id_fk_todo_is_tracked`` следит за этим.

Под-задача mail-messages (бриф ``mail-messages-brief.md``) добавляет
EmailMessage/EmailAttachment/RecipientStatus — порт
``services/email/app/models/email.py``. Их ``unread_count``-растяжка снята:
``apps/mail/services/account_service.py::list_accounts`` теперь считает
реальный коррелированный COUNT (folder=inbox, is_read=false), как исходник
(accounts.py::list_accounts) — см. тот сервис.
"""
from __future__ import annotations

import uuid

from django.db import models
from django.db.models.functions import Now


class AccountType(models.TextChoices):
    """Порт account.py: ``type IN ('corporate','personal')``."""

    CORPORATE = "corporate", "Корпоративный (Mailcow)"
    PERSONAL = "personal", "Личный (OAuth)"


class AccountProvider(models.TextChoices):
    """Порт account.py: ``provider IN ('mailcow','google','microsoft')``."""

    MAILCOW = "mailcow", "Mailcow"
    GOOGLE = "google", "Google"
    MICROSOFT = "microsoft", "Microsoft"


class OAuthProvider(models.TextChoices):
    """Провайдеры, для которых вообще существует OAuthToken — подмножество
    AccountProvider без ``mailcow`` (у Mailcow-ящиков токенов нет: это
    IMAP/SMTP-креды, не OAuth). Источник: oauth.py — ``Literal["google",
    "microsoft"]`` на ``POST /oauth/connect/{provider}``. Исходная модель
    email.py::OAuthToken саму колонку CHECK-констрейнтом не ограничивала
    (просто ``String(50)``) — тут только выбор choices для Django-админки,
    без CheckConstraint, буквально как в исходнике."""

    GOOGLE = "google", "Google"
    MICROSOFT = "microsoft", "Microsoft"


class OAuthToken(models.Model):
    """Порт services/email/app/models/email.py::OAuthToken
    (Base, IntIdMixin, TimestampMixin).

    Токены хранятся ТОЛЬКО в зашифрованном виде (AES-256-GCM,
    apps/mail/services/crypto.py) — расшифровка лениво, при использовании
    (revoke на disconnect и т.п.), никогда в состоянии покоя.
    """

    user_id = models.IntegerField(db_index=True)
    provider = models.CharField(max_length=50, choices=OAuthProvider.choices)
    provider_account_id = models.CharField(max_length=255)

    encrypted_access_token = models.TextField()
    encrypted_refresh_token = models.TextField(null=True, blank=True)

    expires_at = models.DateTimeField()
    # D-mail-1: исходник — ``default=True`` БЕЗ server_default (в отличие от
    # EmailAccount.is_active ниже, где server_default=text("true") явный).
    # Различие буквальное — не унифицируем ради красоты.
    is_active = models.BooleanField(default=True)

    # TimestampMixin исходника: created_at ИНДЕКСИРОВАН, updated_at — нет
    # (в отличие от EmailAccount.created_at ниже, который индекса не несёт).
    created_at = models.DateTimeField(db_default=Now(), db_index=True)
    updated_at = models.DateTimeField(db_default=Now(), auto_now=True)

    def __str__(self) -> str:
        return f"<OAuthToken(id={self.id}, provider={self.provider})>"


class EmailAccount(models.Model):
    """Порт services/email/app/models/account.py::EmailAccount.

    Одна строка — один почтовый ящик, связанный с платформенным
    пользователем: либо Mailcow ``ProvisionedMailbox`` (corporate), либо
    ``OAuthToken`` внешнего провайдера (personal). Ровно одно из
    ``mailbox_id``/``oauth_token_id`` заполнено — типовая согласованность
    проверяется CheckConstraint ``ck_email_accounts_type_consistency``.

    D-mail-2 (решение 4 брифа mail-core): ``mailbox_id`` — БЕЗ FK. Исходник
    ссылается на ``email.provisioned_mailboxes.id``
    (``ProvisionedMailbox``), модель которой создаётся под-задачей
    mailboxes (ещё не перенесена — вне зоны этой под-задачи). Поле заведено
    как голый уникальный int; растяжка
    ``tests/test_stretch.py::test_mailbox_id_fk_todo_is_tracked`` падает в
    момент появления ``apps.mail.models.ProvisionedMailbox``, требуя
    заменить на настоящий FK.
    """

    user_id = models.IntegerField(db_index=True)

    type = models.CharField(max_length=16, choices=AccountType.choices)
    provider = models.CharField(max_length=16, choices=AccountProvider.choices)

    address = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255, null=True, blank=True)

    # Compose-дефолт — ровно один на пользователя (обеспечивается сервисом,
    # НЕ БД-констрейнтом: исходник тоже не имел partial unique index на
    # is_default, только атомарный reset+set в set_default_account).
    is_default = models.BooleanField(default=False, db_default=False)
    # False = синхронизация на паузе (пользователь деактивирован, отвязан и т.д.).
    is_active = models.BooleanField(default=True, db_default=True)

    # TODO(mailboxes-под-задача): заменить на FK на ProvisionedMailbox, когда
    # модель появится (решение 4 брифа) — см. растяжку в tests/test_stretch.py.
    mailbox_id = models.IntegerField(null=True, blank=True, unique=True)
    # FK-имя атрибута ``oauth_token`` даёт Django-колонку ``oauth_token_id``
    # (совпадает с именем атрибута исходника ``oauth_token_id`` в
    # SQLAlchemy-модели) — доступна и как ``account.oauth_token_id`` без
    # похода в БД (Django FK attname), и как ``account.oauth_token``
    # (объект) при необходимости.
    oauth_token = models.ForeignKey(
        OAuthToken, null=True, blank=True, unique=True,
        on_delete=models.SET_NULL, related_name="email_account",
    )

    # Per-provider непрозрачный курсор синхронизации (google: history_id,
    # microsoft: delta_link, mailcow: uidvalidity/uidnext, ...) — под-задача
    # sync ещё не пишет сюда, поле заведено для паритета схемы.
    sync_state = models.JSONField(default=dict, db_default={})
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_error = models.TextField(null=True, blank=True)
    # Push-подписка (Gmail watch / Graph subscription) — планировщик под-задачи
    # workers продлевает её до этого момента.
    watch_expires_at = models.DateTimeField(null=True, blank=True)

    connected_at = models.DateTimeField(db_default=Now())
    created_at = models.DateTimeField(db_default=Now())
    updated_at = models.DateTimeField(db_default=Now(), auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "address"], name="uq_email_accounts_user_address",
            ),
            models.CheckConstraint(
                condition=models.Q(type__in=list(AccountType.values)),
                name="ck_email_accounts_type",
            ),
            models.CheckConstraint(
                condition=models.Q(provider__in=list(AccountProvider.values)),
                name="ck_email_accounts_provider",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        type=AccountType.CORPORATE,
                        mailbox_id__isnull=False,
                        oauth_token_id__isnull=True,
                    )
                    | models.Q(
                        type=AccountType.PERSONAL,
                        oauth_token_id__isnull=False,
                        mailbox_id__isnull=True,
                    )
                ),
                name="ck_email_accounts_type_consistency",
            ),
        ]

    def __str__(self) -> str:
        return f"<EmailAccount(id={self.id}, address={self.address})>"


class AuditLog(models.Model):
    """Порт services/email/app/models/audit_log.py::AuditLog — аудит-таблица
    ДОМЕНА mail (своя, отдельная от hr_auditlog и т.п.).

    Ничем не пишется в mail-core (роутеры accounts.py/oauth.py исходника
    аудит-лог не трогают вовсе) — модель заведена здесь для паритета схемы
    (DoD п.2 брифа); запись появится вместе с под-задачей, которая её
    реально использует (services/email/app/services/audit.py,
    workers/scheduler.py::audit_log_compaction).
    """

    user_id = models.IntegerField(null=True, blank=True, db_index=True)
    action = models.CharField(max_length=100, db_index=True)
    resource_type = models.CharField(max_length=100)
    resource_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    changes = models.JSONField(null=True, blank=True)
    ip_address = models.CharField(max_length=45, null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    correlation_id = models.CharField(max_length=36, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(db_default=Now(), db_index=True)

    def __str__(self) -> str:
        return f"<AuditLog(id={self.id}, action={self.action})>"


# ── mail-messages (бриф mail-messages-brief.md) ────────────────────────────
#
# Порт services/email/app/models/email.py::{EmailMessage, EmailAttachment,
# RecipientStatus}. Таблицы — дефолтные Django-имена (решение D2, как и
# mail-core): mail_emailmessage, mail_emailattachment, mail_recipientstatus.
#
# TimestampMixin исходника (см. models/base.py): created_at ИНДЕКСИРОВАН,
# server_default=now(); updated_at — БЕЗ индекса, тоже server_default=now() +
# onupdate — тот же паттерн, что уже применён к OAuthToken/EmailAccount выше
# (db_default=Now(), db_index только на created_at).


class Folder(models.TextChoices):
    """Канонические папки — порт ``VALID_FOLDERS`` из
    ``services/email/app/api/v1/emails.py`` (используется вьюхой
    ``list_emails`` для 400 на неизвестную папку в пути). Источник НЕ несёт
    CheckConstraint на колонку ``folder`` (обычный ``String(50)``) — choices
    здесь чисто для админки/документации, без ограничения на уровне БД
    (тот же принцип, что и ``OAuthProvider`` выше)."""

    INBOX = "inbox", "Входящие"
    SENT = "sent", "Отправленные"
    DRAFTS = "drafts", "Черновики"
    TRASH = "trash", "Корзина"
    ARCHIVE = "archive", "Архив"
    SPAM = "spam", "Спам"
    OUTBOX = "outbox", "Исходящие"


class EmailMessage(models.Model):
    """Порт services/email/app/models/email.py::EmailMessage (Base,
    TimestampMixin).

    ``account`` — ``ForeignKey`` на ``EmailAccount`` с ``on_delete=SET_NULL``
    (порт ``ondelete="SET_NULL"`` исходника, ``nullable=True``); Django-имя
    атрибута ``account`` даёт колонку ``account_id`` (совпадает с исходным
    именем колонки SQLAlchemy). FK Django индексирует сам — отдельный
    ``db_index`` не нужен, композитный индекс ниже (порт
    ``ix_email_messages_user_account_folder_date`` из миграции 005
    ``services/email/alembic/versions/005_email_accounts.py``) покрывает
    ``account_id`` в составе.

    ``message_id``/``thread_id`` — внешний message-id провайдера (String,
    индексирован, как в исходнике); НЕ путать с полем ``message`` FK на
    ``EmailAttachment``/``RecipientStatus`` ниже — это другая модель.

    Частичный уникальный индекс ``ux_email_messages_account_message`` — порт
    ``CREATE UNIQUE INDEX ... ON email.email_messages (account_id,
    message_id) WHERE message_id IS NOT NULL`` (миграция 005) — тот самый
    индекс, на который опирается ``ON CONFLICT (account_id, message_id)`` в
    ``services/email/app/services/sync/mapper.py::upsert_message``
    (см. apps/mail/services/sync/mapper.py — Django-порт через
    ``update_or_create``).

    ``folder``/``provider_folder``/``subject``/``snippet``/``to_recipients``/
    ``cc_recipients``/``bcc_recipients``/``is_read``/``is_flagged``/
    ``has_attachments``/``dlp_flagged`` — в исходнике ``default=`` БЕЗ
    ``server_default`` (клиентский Python-дефолт SQLAlchemy) — переносится
    как ``default=`` БЕЗ ``db_default`` (тот же принцип, что
    ``OAuthToken.is_active`` в mail-core, см. D-mail-1 выше). Единственное
    исключение — ``provider_folder``: исходная модель объявляет его так же
    клиентским ``default=""``, но миграция 005
    (``op.add_column(..., server_default="")``) добавила РЕАЛЬНЫЙ
    DB-server_default при бэкфилле существующих строк — поэтому здесь ОБА:
    ``default=""`` И ``db_default=""`` (буквальное отражение фактической
    схемы, не только модели).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.IntegerField(db_index=True)
    account = models.ForeignKey(
        EmailAccount, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="messages",
    )

    message_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    thread_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)

    folder = models.CharField(max_length=50, choices=Folder.choices, default=Folder.INBOX)
    # Оригинальная метка провайдера — для round-trip (напр. '[Gmail]/Sent Mail').
    provider_folder = models.CharField(max_length=255, default="", blank=True, db_default="")

    subject = models.CharField(max_length=512, default="", blank=True)
    snippet = models.CharField(max_length=255, default="", blank=True)
    body_html = models.TextField(null=True, blank=True)
    body_text = models.TextField(null=True, blank=True)

    sender_email = models.CharField(max_length=255)
    sender_name = models.CharField(max_length=255, null=True, blank=True)

    # [{"email": "...", "name": "..."}] — как в исходнике (JSONB, default=list).
    to_recipients = models.JSONField(default=list)
    cc_recipients = models.JSONField(default=list)
    bcc_recipients = models.JSONField(default=list)

    is_read = models.BooleanField(default=False)
    is_flagged = models.BooleanField(default=False)
    has_attachments = models.BooleanField(default=False)
    date = models.DateTimeField()

    dlp_flagged = models.BooleanField(default=False)

    created_at = models.DateTimeField(db_default=Now(), db_index=True)
    updated_at = models.DateTimeField(db_default=Now(), auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user_id", "account", "folder", "-date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["account", "message_id"],
                condition=models.Q(message_id__isnull=False),
                name="ux_email_messages_account_message",
            ),
        ]

    def __str__(self) -> str:
        return f"<EmailMessage(id={self.id}, subject={self.subject!r})>"


class EmailAttachment(models.Model):
    """Порт services/email/app/models/email.py::EmailAttachment (Base,
    TimestampMixin).

    ``file_metadata_id`` — ГОЛЫЙ UUID (НЕ ForeignKey) буквально как в
    исходнике (``mapped_column(UUID(as_uuid=True), nullable=True)`` —
    отдельный media-микросервис, кросс-схемной FK не было). В Django-порту
    это тоже осталось голым полем: прямой FK на
    ``apps.media_files.models.FileMetadata`` запрещён
    (apps/core/tests/test_app_isolation.py — сосед доступен только через
    ``apps.media_files.interface``); значение сюда пишет
    ``services/attachment_service.py`` после ``media_interface.store_file``.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(
        EmailMessage, on_delete=models.CASCADE, related_name="attachments",
    )

    file_metadata_id = models.UUIDField(null=True, blank=True)

    filename = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=255)
    size = models.IntegerField()
    content_id = models.CharField(max_length=255, null=True, blank=True)  # inline images

    created_at = models.DateTimeField(db_default=Now(), db_index=True)
    updated_at = models.DateTimeField(db_default=Now(), auto_now=True)

    def __str__(self) -> str:
        return f"<EmailAttachment(id={self.id}, filename={self.filename!r})>"


class RecipientStatus(models.Model):
    """Порт services/email/app/models/email.py::RecipientStatus (Base,
    TimestampMixin). ``status`` — обычный ``CharField`` без choices/
    CheckConstraint: исходник хранит туда ``pending``/``sent``/``bounced``
    (workers/actors.py::_do_deliver), НЕ только ``pending, delivered,
    bounced`` из докстринга модели (докстринг исходника расходится с
    реальным множеством значений — перенесено как есть, без искусственного
    ограничения choices)."""

    message = models.ForeignKey(
        EmailMessage, on_delete=models.CASCADE, related_name="recipient_statuses",
    )
    recipient_email = models.CharField(max_length=255)
    status = models.CharField(max_length=50, default="pending")
    error_message = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(db_default=Now(), db_index=True)
    updated_at = models.DateTimeField(db_default=Now(), auto_now=True)

    def __str__(self) -> str:
        return f"<RecipientStatus(id={self.id}, recipient_email={self.recipient_email!r}, status={self.status!r})>"

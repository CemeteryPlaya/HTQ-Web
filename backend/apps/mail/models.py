"""Модели домена mail — mail-core: порт services/email/app/models/
{account,email,audit_log}.py.

Имена таблиц — дефолтные Django (решение D2, как и в apps.hr): mail_
emailaccount, mail_oauthtoken, mail_auditlog. Старые имена (email_accounts,
oauth_tokens, audit_log) живут только в карте ETL будущей фазы. Схема — ТОЛЬКО
public (PgBouncer transaction-mode роняет search_path, см. CLAUDE.md); в
исходнике таблицы жили в схеме ``email``, здесь это не переносится.

Область этой под-задачи (mail-core, бриф): EmailAccount + OAuthToken +
AuditLog(mail) + crypto (apps/mail/services/crypto.py). Другие модели домена
(EmailMessage/EmailAttachment/RecipientStatus/ProvisionedMailbox) — под-задачи
messages/mailboxes, ещё НЕ перенесены. Два места здесь намеренно неполные до
их прихода (см. TODO-комментарии + tests/test_stretch.py):
  * ``EmailAccount.mailbox_id`` — голый уникальный int без FK (решение 4);
  * ``unread_count`` в ответе ``GET /accounts/`` (apps/mail/services/
    account_service.py) — всегда 0, в исходнике коррелированный подзапрос к
    EmailMessage.
"""
from __future__ import annotations

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

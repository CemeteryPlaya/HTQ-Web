"""Роуты домена mail под ``/api/email/v1/`` (монтируется автодискавери по
``MailConfig.API_PREFIX``, см. htqweb/urls.py).

``APPEND_SLASH=False`` — каждое написание пути регистрируется явно (как в
apps/hr/urls.py и apps/cms/urls.py).

Реальные вызовы фронта (frontend/src/api/email.ts,
frontend/src/services/emailService.ts — легаси, ещё не выпилен):
``accounts/`` (GET), ``accounts/{id}/set-default/`` и ``accounts/{id}/sync/``
(POST) — СО слешем; ``accounts/{id}/`` (DELETE) — тоже со слешем.
``oauth/status``, ``oauth/connect/{provider}``, ``oauth/callback``,
``oauth/disconnect`` — ВСЕ БЕЗ слеша (см. legacy emailService.ts) — ровно как
в роутере исходника (``router = APIRouter(tags=["oauth"])`` без trailing
slash на путях). ``oauth/accounts`` (список сырых OAuthToken — легаси
account-picker) фронтом сейчас не используется — регистрируется защитно, по
конвенции остальных аппок.

Источник: services/email/app/main.py — ``accounts_router`` смонтирован под
prefix="/api/email/v1/accounts", ``oauth_router`` — под
prefix="/api/email/v1/oauth".
"""
from django.urls import path

from . import views

urlpatterns = [
    # ── accounts (4 эндпойнта, services/email/app/api/v1/accounts.py) ──────
    path("accounts/", views.accounts_collection),
    path("accounts", views.accounts_collection),

    path("accounts/<int:account_id>/set-default/", views.account_set_default),
    path("accounts/<int:account_id>/set-default", views.account_set_default),

    path("accounts/<int:account_id>/sync/", views.account_sync),
    path("accounts/<int:account_id>/sync", views.account_sync),

    path("accounts/<int:account_id>/", views.account_detail),
    path("accounts/<int:account_id>", views.account_detail),

    # ── oauth (5 эндпойнтов, services/email/app/api/v1/oauth.py) ───────────
    path("oauth/status", views.oauth_status),
    path("oauth/status/", views.oauth_status),

    path("oauth/accounts", views.oauth_accounts),
    path("oauth/accounts/", views.oauth_accounts),

    path("oauth/connect/<str:provider>", views.oauth_connect),
    path("oauth/connect/<str:provider>/", views.oauth_connect),

    path("oauth/callback", views.oauth_callback),
    path("oauth/callback/", views.oauth_callback),

    path("oauth/disconnect", views.oauth_disconnect),
    path("oauth/disconnect/", views.oauth_disconnect),

    # ── messages (mail-messages-brief.md, 6 эндпойнтов
    # services/email/app/api/v1/emails.py) ──────────────────────────────────
    # Реальные вызовы фронта (frontend/src/api/email.ts::emailApi,
    # frontend/src/services/emailService.ts — легаси): ``folder/{folder}``
    # (GET, БЕЗ слеша), ``{messageId}`` (GET, БЕЗ слеша),
    # ``{messageId}/read`` (POST, БЕЗ слеша), ``unread-counts/`` (GET, СО
    # слешем), ``send``/``draft`` (POST, БЕЗ слеша) — оба написания
    # регистрируются защитно, как и везде в этом файле.
    path("folder/<str:folder>", views.list_emails),
    path("folder/<str:folder>/", views.list_emails),

    path("unread-counts/", views.unread_counts),
    path("unread-counts", views.unread_counts),

    path("send", views.send_email),
    path("send/", views.send_email),

    path("draft", views.save_draft),
    path("draft/", views.save_draft),

    # <uuid:message_id> — намеренно ПОСЛЕ более специфичных путей выше (как
    # и в apps/media_files/urls.py::<uuid:file_id>): валидный UUID-сегмент
    # никогда не совпадёт с "folder", "send", "draft", "unread-counts", так
    # что порядок здесь не критичен, но соблюдается конвенция "самое общее —
    # в конце".
    path("<uuid:message_id>/read", views.mark_as_read),
    path("<uuid:message_id>/read/", views.mark_as_read),

    path("<uuid:message_id>", views.get_email),
    path("<uuid:message_id>/", views.get_email),

    # ── mailboxes (mailboxes-под-задача, mail-mailboxes-brief.md, 12
    # эндпойнтов services/email/app/api/v1/mailboxes.py) ────────────────────
    # Реальные вызовы фронта (frontend/src/pages/AdminMailboxes.tsx): все
    # мажоритарно СО слешем — ``mailboxes/?include_deleted=true`` (GET),
    # ``mailboxes/{id}/archive/``/``restore/``/``reset-password/`` (POST),
    # ``mailboxes/{id}/`` (DELETE), ``mailboxes/aliases/`` (GET/POST),
    # ``mailboxes/aliases/{id}/`` (DELETE). ``forwarding/`` фронтом сейчас не
    # вызывается — регистрируется защитно, по конвенции остальных аппок.
    # Литеральный ``mailboxes/aliases/`` — ДО ``mailboxes/<int:mailbox_id>/``
    # (конвенция репозитория; <int:...> и так не матчит "aliases", но порядок
    # соблюдён явно).
    path("mailboxes/aliases/", views.aliases_collection),
    path("mailboxes/aliases", views.aliases_collection),

    path("mailboxes/aliases/<int:alias_id>/", views.delete_alias),
    path("mailboxes/aliases/<int:alias_id>", views.delete_alias),

    path("mailboxes/", views.mailboxes_collection),
    path("mailboxes", views.mailboxes_collection),

    path("mailboxes/<int:mailbox_id>/reset-password/", views.reset_mailbox_password),
    path("mailboxes/<int:mailbox_id>/reset-password", views.reset_mailbox_password),

    path("mailboxes/<int:mailbox_id>/archive/", views.archive_mailbox),
    path("mailboxes/<int:mailbox_id>/archive", views.archive_mailbox),

    path("mailboxes/<int:mailbox_id>/restore/", views.restore_mailbox),
    path("mailboxes/<int:mailbox_id>/restore", views.restore_mailbox),

    path("mailboxes/<int:mailbox_id>/forwarding/", views.set_forwarding),
    path("mailboxes/<int:mailbox_id>/forwarding", views.set_forwarding),

    path("mailboxes/<int:mailbox_id>/", views.mailbox_detail),
    path("mailboxes/<int:mailbox_id>", views.mailbox_detail),
]

"""HTTP-вьюхи домена mail — ``/api/email/v1/{accounts,oauth,mailboxes}/*``.

Порт services/email/app/api/v1/{accounts,oauth}.py. Вьюхи тонкие:
аутентификация, парсинг, коды ответа. Логика — в apps/mail/services/
{account,oauth}_service.py.

Авторизация (решение 3 брифа mail-core): все accounts/oauth эндпойнты, КРОМЕ
callback — обычный залогиненный пользователь (``get_current_user``
исходника) → ``api_view(auth="jwt")``. Аккаунт/токен привязан к ``user_id``
из JWT — пользователь видит и правит ТОЛЬКО свои строки (фильтрация — в
apps/mail/services/*, не ослаблена относительно исходника).

Единственное исключение — ``GET /oauth/callback``: это редирект ПРОВАЙДЕРА
(без заголовка Authorization), в исходнике роут объявлен БЕЗ
``get_current_user`` — идентичность пользователя приходит из state-нонса
(см. oauth_service.connect/callback), а не из JWT → ``api_view(auth=None)``.

Каждый из 9 эндпойнтов accounts/oauth обслуживает РОВНО один HTTP-метод —
дублирующий диспетчер (как в apps/hr/views.py для departments/positions/...)
здесь не нужен, ни один путь не переиспользуется под другим методом.

Mailboxes (mailboxes-под-задача, mail-mailboxes-brief.md — порт
``services/email/app/api/v1/mailboxes.py``, 12 эндпойнтов) — авторизация
``require_mailbox_admin`` исходника принимает ЛИБО user-JWT с
``is_staff``/``is_superuser``/``is_admin``, ЛИБО S2S service-JWT
(``service=True``, для user-service hook на создание пользователя). PLAN.md
Р3 ("без S2S", строка 142/322 — снос S2S-механики монолитом) убирает вторую
ветку: у нас один Django-процесс, S2S-вызов между "сервисами" не существует
как класс задач. Остаётся первая ветка — тот же ``is_elevated`` предикат,
что и ``require_hr_write`` в apps/hr (positions/org и т.п.) →
``api_view(auth="jwt", admin=True)``, единый платформенный admin-гейт (R1,
htqweb/http.py). 3 пути ("/mailboxes/", "/mailboxes/{id}/",
"/mailboxes/aliases/") обслуживают больше одного HTTP-метода — те же
диспетчеры, что в apps/hr/views.py (staffing_lines_collection и т.п.).
"""
from __future__ import annotations

from django.http import HttpResponse

from htqweb.http import api_view, json_error

from . import schemas
from .services import account_service as acct_svc
from .services import email_service as mail_svc
from .services import mailbox_service as mbx_svc
from .services import oauth_service as oauth_svc
from .services.mailcow_client import MailcowClient

_VALID_PROVIDERS = ("google", "microsoft")


class _QueryValidationError(Exception):
    """422 — некорректный query-параметр (порт неявной FastAPI
    ``Query(..., ge=..., le=...)`` валидации из emails.py::list_emails)."""


def _int_query(request, name: str, *, default: int, ge: int | None = None,
               le: int | None = None) -> int:
    raw = request.GET.get(name)
    if raw is None or raw == "":
        value = default
    else:
        try:
            value = int(raw)
        except ValueError:
            raise _QueryValidationError(name) from None
    if (ge is not None and value < ge) or (le is not None and value > le):
        raise _QueryValidationError(name)
    return value


_TRUE_TOKENS = {"1", "true", "yes", "on"}
_FALSE_TOKENS = {"0", "false", "no", "off"}


def _bool_query(request, name: str, *, default: bool) -> bool:
    """Порт неявной FastAPI ``bool``-query-параметр валидации
    (``mailboxes.py::list_mailboxes(include_deleted: bool = False)``) —
    pydantic/FastAPI принимает те же token-варианты (case-insensitive)."""
    raw = request.GET.get(name)
    if raw is None or raw == "":
        return default
    lowered = raw.strip().lower()
    if lowered in _TRUE_TOKENS:
        return True
    if lowered in _FALSE_TOKENS:
        return False
    raise _QueryValidationError(name)


# ── /accounts/ ────────────────────────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def accounts_collection(request):
    return acct_svc.list_accounts(request.token.user_id)


@api_view(methods=("POST",), auth="jwt")
def account_set_default(request, account_id: int):
    try:
        return acct_svc.set_default_account(request.token.user_id, account_id)
    except acct_svc.AccountNotFound:
        return json_error("Account not found", 404)


@api_view(methods=("POST",), auth="jwt", status=202)
def account_sync(request, account_id: int):
    try:
        return acct_svc.trigger_sync(request.token.user_id, account_id)
    except acct_svc.AccountNotFound:
        return json_error("Account not found", 404)
    except acct_svc.AccountInactive:
        return json_error("Account is inactive", 409)


@api_view(methods=("DELETE",), auth="jwt")
def account_detail(request, account_id: int):
    try:
        acct_svc.disconnect_account(request.token.user_id, account_id)
    except acct_svc.AccountNotFound:
        return json_error("Account not found", 404)
    except acct_svc.CorporateAccountProtected:
        return json_error(
            "Corporate mailboxes are removed via /mailboxes/{id}/archive/", 400,
        )
    return HttpResponse(status=204)


# ── /oauth/* ──────────────────────────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt")
def oauth_status(request):
    return oauth_svc.status(request.token.user_id)


@api_view(methods=("GET",), auth="jwt")
def oauth_accounts(request):
    return oauth_svc.list_tokens(request.token.user_id)


@api_view(methods=("POST",), auth="jwt")
def oauth_connect(request, provider: str):
    if provider not in _VALID_PROVIDERS:
        return json_error(f"Unsupported OAuth provider: {provider!r}", 422)
    try:
        return oauth_svc.connect(request.token.user_id, provider)
    except oauth_svc.ProviderNotConfigured as exc:
        return json_error(str(exc), 503)


@api_view(methods=("GET",), auth=None)
def oauth_callback(request):
    code = request.GET.get("code")
    state = request.GET.get("state")
    error = request.GET.get("error")
    if error:
        return json_error(f"Provider error: {error}", 400)
    if not code or not state:
        return json_error("Missing required query parameter: code/state", 422)
    try:
        return oauth_svc.callback(code=code, state=state)
    except oauth_svc.InvalidOAuthState:
        return json_error("Invalid or expired state", 400)
    except oauth_svc.ProviderEmailMissing:
        return json_error("Provider did not return an email address", 502)


@api_view(methods=("DELETE",), auth="jwt")
def oauth_disconnect(request):
    return oauth_svc.disconnect_all(request.token.user_id)


# ── /folder/{folder}, /unread-counts/, /{message_id}, /send, /draft ───────
# (mail-messages-brief.md — порт services/email/app/api/v1/emails.py, 6
# эндпойнтов). Авторизация — обычный JWT-пользователь, СТРОГИЙ user-scoping:
# каждый запрос фильтрует EmailMessage по request.token.user_id; чужое —
# 404 "Email not found" (не 403 — та же конвенция, что и accounts/*).


@api_view(methods=("GET",), auth="jwt")
def list_emails(request, folder: str):
    try:
        account_id = _int_query(request, "account_id", default=None)
        limit = _int_query(request, "limit", default=50, ge=1, le=100)
        offset = _int_query(request, "offset", default=0, ge=0)
    except _QueryValidationError as exc:
        return json_error(f"Invalid query parameter: {exc}", 422)

    try:
        return mail_svc.list_emails(
            request.token.user_id, folder=folder, account_id=account_id,
            limit=limit, offset=offset,
        )
    except mail_svc.InvalidFolder:
        return json_error("Invalid folder", 400)


@api_view(methods=("GET",), auth="jwt")
def unread_counts(request):
    return mail_svc.unread_counts(request.token.user_id)


@api_view(methods=("GET",), auth="jwt")
def get_email(request, message_id):
    try:
        return mail_svc.get_email(request.token.user_id, message_id)
    except mail_svc.EmailNotFound:
        return json_error("Email not found", 404)


@api_view(methods=("POST",), auth="jwt", body=schemas.EmailSendRequest, status=202)
def send_email(request, data: schemas.EmailSendRequest):
    try:
        return mail_svc.send_email(
            request.token.user_id,
            account_id=data.account_id,
            to_recipients=data.to_recipients,
            cc_recipients=data.cc_recipients,
            bcc_recipients=data.bcc_recipients,
            subject=data.subject,
            body_html=data.body_html,
            body_text=data.body_text,
        )
    except mail_svc.AccountNotFound:
        return json_error("Account not found", 404)
    except mail_svc.AccountInactive:
        return json_error("Account is inactive", 409)
    except mail_svc.DLPViolation:
        return json_error("DLP Policy Violation: Sensitive data detected.", 403)


@api_view(methods=("POST",), auth="jwt")
def mark_as_read(request, message_id):
    mail_svc.mark_as_read(request.token.user_id, message_id)
    return HttpResponse(status=204)


@api_view(methods=("POST",), auth="jwt", body=schemas.DraftIn, status=201)
def save_draft(request, data: schemas.DraftIn):
    return mail_svc.save_draft(request.token.user_id, subject=data.subject, body=data.body)


# ── /mailboxes/* (mailboxes-под-задача, порт api/v1/mailboxes.py) ─────────
#
# Все 12 — ``api_view(auth="jwt", admin=True)`` (require_mailbox_admin, см.
# докстринг модуля выше). "/mailboxes/" и "/mailboxes/{id}/" обслуживают
# больше одного HTTP-метода — диспетчер (как staffing_lines_collection в
# apps/hr/views.py) вызывает приватную ``api_view``-обёрнутую функцию per
# метод, чтобы у GET/POST/PATCH/DELETE были свои коды/тела ответов.


# ── /mailboxes/ ─────────────────────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt", admin=True)
def _list_mailboxes(request):
    try:
        include_deleted = _bool_query(request, "include_deleted", default=False)
    except _QueryValidationError as exc:
        return json_error(f"Invalid query parameter: {exc}", 422)
    return [mbx_svc.serialize(mb) for mb in mbx_svc.list_mailboxes(include_deleted=include_deleted)]


@api_view(methods=("POST",), auth="jwt", admin=True, body=schemas.MailboxCreateRequest, status=201)
def _create_mailbox(request, data: schemas.MailboxCreateRequest):
    try:
        mb, generated_password = mbx_svc.create(data)
    except mbx_svc.MailboxDomainNotConfigured:
        return json_error("MAILCOW_DOMAIN not configured", 500)
    except mbx_svc.MailboxUserConflict as exc:
        return json_error(exc.detail, 409)
    except mbx_svc.InvalidLocalPart:
        return json_error("Invalid local_part", 400)
    return {**mbx_svc.serialize(mb), "generated_password": generated_password}


def mailboxes_collection(request):
    if request.method == "GET":
        return _list_mailboxes(request)
    if request.method == "POST":
        return _create_mailbox(request)
    return json_error("Method Not Allowed", 405)


# ── /mailboxes/{mailbox_id}/ ────────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt", admin=True)
def _get_mailbox(request, mailbox_id: int):
    try:
        return mbx_svc.serialize(mbx_svc.get_by_id(mailbox_id))
    except mbx_svc.MailboxNotFound:
        return json_error("Mailbox not found", 404)


@api_view(methods=("PATCH",), auth="jwt", admin=True, body=schemas.MailboxUpdateRequest)
def _update_mailbox(request, mailbox_id: int, data: schemas.MailboxUpdateRequest):
    try:
        mb = mbx_svc.update(mailbox_id, data)
    except mbx_svc.MailboxNotFound:
        return json_error("Mailbox not found", 404)
    except mbx_svc.MailboxAlreadyDeleted:
        return json_error("Mailbox already deleted", 409)
    return mbx_svc.serialize(mb)


@api_view(methods=("DELETE",), auth="jwt", admin=True)
def _delete_mailbox(request, mailbox_id: int):
    """Stage 2 — only allowed if mailbox is currently in `archived` state."""
    try:
        mbx_svc.delete(mailbox_id)
    except mbx_svc.MailboxNotFound:
        return json_error("Mailbox not found", 404)
    except mbx_svc.CannotDelete:
        return json_error("Mailbox must be archived before permanent deletion", 409)
    return HttpResponse(status=204)


def mailbox_detail(request, mailbox_id: int):
    if request.method == "GET":
        return _get_mailbox(request, mailbox_id=mailbox_id)
    if request.method == "PATCH":
        return _update_mailbox(request, mailbox_id=mailbox_id)
    if request.method == "DELETE":
        return _delete_mailbox(request, mailbox_id=mailbox_id)
    return json_error("Method Not Allowed", 405)


# ── /mailboxes/{mailbox_id}/reset-password|archive|restore/ ────────────────

@api_view(methods=("POST",), auth="jwt", admin=True, body=schemas.MailboxResetPasswordRequest)
def reset_mailbox_password(request, mailbox_id: int, data: schemas.MailboxResetPasswordRequest):
    try:
        mb, generated_password = mbx_svc.reset_password(mailbox_id, data)
    except mbx_svc.MailboxNotFound:
        return json_error("Mailbox not found", 404)
    except mbx_svc.MailboxNotActive:
        return json_error("Mailbox is not active", 409)
    return {**mbx_svc.serialize(mb), "generated_password": generated_password}


@api_view(methods=("POST",), auth="jwt", admin=True)
def archive_mailbox(request, mailbox_id: int):
    try:
        mb = mbx_svc.archive(mailbox_id)
    except mbx_svc.MailboxNotFound:
        return json_error("Mailbox not found", 404)
    except mbx_svc.CannotArchive as exc:
        return json_error(exc.detail, 409)
    return mbx_svc.serialize(mb)


@api_view(methods=("POST",), auth="jwt", admin=True)
def restore_mailbox(request, mailbox_id: int):
    try:
        mb = mbx_svc.restore(mailbox_id)
    except mbx_svc.MailboxNotFound:
        return json_error("Mailbox not found", 404)
    except mbx_svc.CannotRestore:
        return json_error("Only archived mailboxes can be restored", 409)
    return mbx_svc.serialize(mb)


# ── /mailboxes/aliases/* (проксируется живьём в Mailcow, локально не
# зеркалируется) ────────────────────────────────────────────────────────

@api_view(methods=("GET",), auth="jwt", admin=True)
def _list_aliases(request):
    try:
        return MailcowClient().list_aliases()
    except Exception as exc:  # noqa: BLE001 — буквальный порт исходника
        return json_error(f"Mailcow error: {exc}", 502)


@api_view(methods=("POST",), auth="jwt", admin=True, body=schemas.AliasCreateRequest, status=201)
def _create_alias(request, data: schemas.AliasCreateRequest):
    try:
        return MailcowClient().add_alias(
            address=str(data.address), goto=data.goto, active=data.active,
        )
    except Exception as exc:  # noqa: BLE001 — буквальный порт исходника
        return json_error(f"Mailcow error: {exc}", 502)


def aliases_collection(request):
    if request.method == "GET":
        return _list_aliases(request)
    if request.method == "POST":
        return _create_alias(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("DELETE",), auth="jwt", admin=True)
def delete_alias(request, alias_id: int):
    try:
        MailcowClient().delete_alias(alias_id)
    except Exception as exc:  # noqa: BLE001 — буквальный порт исходника
        return json_error(f"Mailcow error: {exc}", 502)
    return HttpResponse(status=204)


# ── /mailboxes/{mailbox_id}/forwarding/ ────────────────────────────────────

@api_view(methods=("POST",), auth="jwt", admin=True, body=schemas.ForwardingSetRequest, status=201)
def set_forwarding(request, mailbox_id: int, data: schemas.ForwardingSetRequest):
    try:
        mb = mbx_svc.get_by_id(mailbox_id)
    except mbx_svc.MailboxNotFound:
        return json_error("Mailbox not found", 404)
    try:
        return MailcowClient().set_forwarding(
            mb.address, str(data.forward_to), keep_local_copy=data.keep_local_copy,
        )
    except Exception as exc:  # noqa: BLE001 — буквальный порт исходника
        return json_error(f"Mailcow error: {exc}", 502)

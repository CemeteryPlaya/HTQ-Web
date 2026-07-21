"""HTTP-вьюхи домена mail — ``/api/email/v1/{accounts,oauth}/*``.

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

Каждый из 9 эндпойнтов этой под-задачи обслуживает РОВНО один HTTP-метод —
дублирующий диспетчер (как в apps/hr/views.py для departments/positions/...)
здесь не нужен, ни один путь не переиспользуется под другим методом.
"""
from __future__ import annotations

from django.http import HttpResponse

from htqweb.http import api_view, json_error

from . import schemas
from .services import account_service as acct_svc
from .services import email_service as mail_svc
from .services import oauth_service as oauth_svc

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

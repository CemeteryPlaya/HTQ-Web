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

from django.http import HttpResponse, JsonResponse

from htqweb.fallback import fallback
from htqweb.http import api_view, json_error

from . import schemas
from .services import account_service as acct_svc
from .services import email_service as mail_svc
from .services import mailbox_service as mbx_svc
from .services import oauth_service as oauth_svc
from .services import (connection_check, imap_account_service, lookup_service,
                       provisioning, reconcile_service, self_service,
                       settings_service)
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


@api_view(methods=("PATCH",), auth="jwt", body=schemas.AccountSignatureRequest)
def account_signature(request, account_id: int, data: schemas.AccountSignatureRequest):
    """Подпись, которой подписываются письма с этого адреса."""
    try:
        return acct_svc.update_signature(
            request.token.user_id, account_id, data.signature,
        )
    except acct_svc.AccountNotFound:
        return json_error("Account not found", 404)


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


# ── /accounts/connect-corporate/ — сотрудник подключает свой ящик сам ─────
#
# Единственная точка домена, где НЕпривилегированный пользователь заводит
# ProvisionedMailbox. Все ограничения — в services/self_service.py (режим
# включается админом, домен обязан совпасть, чужой ящик не увести).


@api_view(methods=("GET",), auth="jwt")
def corporate_connect_info(request):
    """Что показать сотруднику: можно ли подключать ящик и в каком домене.

    Отдаётся обычному пользователю, поэтому наружу идёт только необходимое —
    без адресов серверов и прочих деталей инфраструктуры.
    """
    info = provisioning.describe()
    user_id = request.token.user_id
    mailbox = _current_mailbox(user_id)
    awaiting = bool(mailbox and mailbox.get("awaiting_password"))
    own_address = _own_corporate_address(user_id, info["domain"])
    return {
        # Карточка показывается сотруднику, если админ разрешил подключать
        # ящики самим, ЛИБО если ящик ему уже назначен и ждёт пароль, ЛИБО
        # если его собственный рабочий адрес лежит в корпоративном домене.
        # Последние два случая подделкой не грозят: адрес закреплён за ним
        # админом, а пароль всё равно проверяется живым входом.
        "allowed": bool(info["allow_self_service"] or awaiting or own_address),
        "self_service": info["allow_self_service"],
        "domain": info["domain"],
        # Адрес, который карточка подставит сама, — сотруднику незачем его
        # набирать, а опечатка превратила бы понятный отказ в загадочный.
        "own_address": own_address,
        "mailbox": mailbox,
        "awaiting_password": awaiting,
        "suggest_connect": _suggest_connect(own_address, mailbox, info),
    }


def _suggest_connect(own_address: str, mailbox: dict | None, info: dict) -> bool:
    """Предлагать ли сотруднику подключить рабочий ящик паролем.

    Повод возникает, когда ящика у человека нет, а его рабочий адрес —
    корпоративный: скорее всего ящик на сервере есть, просто платформа о нём
    не знает (учётку завели до автоподключения, или оно не сработало).

    Дальше всё зависит от того, умеет ли сервер отвечать на вопрос «есть ли
    такой ящик»:

    * **умеет** (Mailcow, есть API) — верим ему. ``False`` означает, что
      ящика нет, и просить пароль не за чем: человек будет перебирать пароли
      от несуществующего ящика;
    * **не умеет** (голый IMAP: проверить можно ТОЛЬКО логином, а пароля у
      платформы нет) или молчит — остаётся предположение. Тогда порядок
      обратный тому, каким его хочется видеть: сначала спрашиваем пароль, а
      успешный вход и есть доказательство, что ящик существует и принадлежит
      спрашивающему.

    ``provisioner == "none"`` исключён: почтового сервера нет вовсе,
    подключаться некуда, и просьба ввести пароль была бы издевательством.
    """
    if not own_address or mailbox is not None or info["provisioner"] == "none":
        return False

    from apps.mail.services import lookup_service

    # С кэшем: ручку дёргает каждая загрузка страницы каждым сотрудником, а
    # ответ сервера про один адрес одинаков для всех и меняется редко.
    try:
        exists = lookup_service.remote_exists(own_address, use_cache=True)
    except Exception as exc:  # noqa: BLE001 — карточка не должна ронять ответ
        exists = fallback(
            "mail.connect_info.remote_lookup_failed", None,
            reason="не удалось спросить почтовый сервер про ящик сотрудника",
            exc=exc, address=own_address,
        )

    # None — «не знаю», и это НЕ «ящика нет»: приравняй одно к другому, и на
    # голом IMAP подсказка исчезла бы у всех разом.
    return exists is not False


def _own_corporate_address(user_id: int, domain: str) -> str:
    """Рабочий адрес сотрудника, если он в корпоративном домене, иначе ``""``.

    Берётся с сервера, а не из формы: адрес — это ещё и признак, по которому
    разрешено подключение без ``allow_self_service`` (см. self_service), и
    доверять тут присланному клиентом значению нельзя.
    """
    from apps.users import interface as users_interface

    if not domain:
        return ""
    try:
        brief = users_interface.get_user_brief(user_id)
    except Exception as exc:  # noqa: BLE001 — карточка не должна ронять ответ
        fallback("mail.connect_info.user_lookup_failed", "",
                 reason="не удалось узнать рабочий адрес сотрудника",
                 exc=exc, user_id=user_id)
        return ""
    email = ((brief or {}).get("email") or "").strip().lower()
    return email if email.endswith(f"@{domain.strip().lower()}") else ""


def _current_mailbox(user_id: int):
    """Ящик пользователя в форме, пригодной для показа ему самому."""
    from .models import ProvisionedMailbox

    mb = ProvisionedMailbox.objects.filter(user_id=user_id).exclude(status="deleted").first()
    return mbx_svc.serialize(mb) if mb is not None else None


@api_view(methods=("POST",), auth="jwt", body=schemas.MailboxConnectRequest, status=201)
def _corporate_connect(request, data: schemas.MailboxConnectRequest):
    try:
        return self_service.connect_own_mailbox(
            user_id=request.token.user_id, address=data.address, password=data.password,
        )
    except self_service.SelfServiceDisabled:
        return json_error(
            "Самостоятельное подключение ящиков отключено — обратитесь к администратору", 403,
        )
    except self_service.WrongDomain as exc:
        return json_error(exc.detail, 400)
    except self_service.MailboxTakenByAnotherUser as exc:
        return json_error(exc.detail, 409)
    except self_service.VerificationFailed as exc:
        return json_error(exc.detail, 400)


@api_view(methods=("DELETE",), auth="jwt")
def _corporate_disconnect(request):
    if not self_service.disconnect_own_mailbox(user_id=request.token.user_id):
        return json_error("Подключённого корпоративного ящика нет", 404)
    return HttpResponse(status=204)


def corporate_connect(request):
    if request.method == "GET":
        return corporate_connect_info(request)
    if request.method == "POST":
        return _corporate_connect(request)
    if request.method == "DELETE":
        return _corporate_disconnect(request)
    return json_error("Method Not Allowed", 405)


# ── /accounts/connect-imap/ — свой почтовый сервер ────────────────────────
#
# Третий способ добавить почту рядом с OAuth и корпоративным ящиком: любой
# сервер, реквизиты которого пользователь вводит сам. Ограничение по домену
# ЗДЕСЬ намеренно отсутствует (в отличие от connect-corporate): это личный
# ящик пользователя, а не ресурс платформы.


@api_view(methods=("GET",), auth="jwt")
def _imap_connect_hint(request):
    """Предзаполнение формы по адресу — чтобы не гадать над портами."""
    return imap_account_service.suggest_settings(request.GET.get("address", ""))


@api_view(methods=("POST",), auth="jwt", body=schemas.ImapAccountConnectRequest, status=201)
def _imap_connect(request, data: schemas.ImapAccountConnectRequest):
    try:
        account = imap_account_service.connect(user_id=request.token.user_id, payload=data)
    except imap_account_service.AccountAlreadyConnected as exc:
        return json_error(exc.detail, 409)
    except imap_account_service.ImapVerificationFailed as exc:
        return json_error(exc.detail, 400)
    return acct_svc.serialize(account)


def imap_connect(request):
    if request.method == "GET":
        return _imap_connect_hint(request)
    if request.method == "POST":
        return _imap_connect(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("POST",), auth="jwt", body=schemas.ImapAccountPasswordRequest)
def imap_account_password(request, account_id: int, data: schemas.ImapAccountPasswordRequest):
    """Сменить сохранённый пароль — пользователь поменял его на сервере."""
    from .models import EmailAccount

    try:
        account = imap_account_service.update_password(
            user_id=request.token.user_id, account_id=account_id, password=data.password,
        )
    except EmailAccount.DoesNotExist:
        return json_error("Account not found", 404)
    except imap_account_service.ImapVerificationFailed as exc:
        return json_error(exc.detail, 400)
    return acct_svc.serialize(account)


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
    """Завести ящик — со сверкой «а такого ящика уже нет?».

    ``provision`` вместо ``create``: если ящик с этим адресом уже существует
    (в платформе или на почтовом сервере) и его есть кому отдать, он
    подключается к пользователю, а дубль не создаётся. Ответ несёт
    ``attached`` и ``detail``, чтобы интерфейс не говорил «ящик создан» про
    ящик, который он не создавал, и ``awaiting_password`` — когда доступ к
    найденному ящику платформа получить не смогла и его введёт сам сотрудник.
    """
    try:
        result = mbx_svc.provision(data)
    except mbx_svc.MailboxDomainNotConfigured:
        return json_error("MAILCOW_DOMAIN not configured", 500)
    except mbx_svc.MailboxUserConflict as exc:
        return json_error(exc.detail, 409)
    except mbx_svc.MailboxUserSlotTaken as exc:
        return json_error(exc.detail, 409)
    except mbx_svc.MailboxAddressTaken as exc:
        return json_error(exc.detail, 409)
    except mbx_svc.MailboxVerificationFailed as exc:
        return json_error(exc.detail, 400)
    except mbx_svc.InvalidLocalPart:
        return json_error("Invalid local_part", 400)
    except mbx_svc.RemoteProvisioningFailed as exc:
        # Строка создана и помечена error — отдаём её вместе с текстом отказа,
        # чтобы админ видел, что именно чинить, и не создавал дубль.
        body = {"detail": exc.detail}
        if exc.mailbox is not None:
            body["mailbox"] = mbx_svc.serialize(exc.mailbox)
        return JsonResponse(body, status=502)
    return {
        **mbx_svc.serialize(result.mailbox),
        "generated_password": result.generated_password,
        "attached": result.attached,
        "detail": result.detail,
    }


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
    except mbx_svc.RemoteProvisioningFailed as exc:
        # Пароль на сервере НЕ сменился — сообщаем прямо, иначе админ будет
        # думать, что выдал сотруднику рабочий пароль.
        return json_error(exc.detail, 502)
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


# ── /mailboxes/status/ ────────────────────────────────────────────────────
#
# Что именно произойдёт при нажатии «Создать ящик»: подключён ли почтовый
# сервер, заведёт ли он ящик сам или только проверит существующий. Форма
# создания в админке читает это, чтобы не обещать невозможного.


@api_view(methods=("GET",), auth="jwt", admin=True)
def mailbox_status(request):
    return provisioning.describe()


# ── /mailboxes/lookup/ — сверка адреса до нажатия кнопки ──────────────────
#
# Отдельная ручка, а не поле в ответе создания: админ должен УВИДЕТЬ, что
# ящик уже есть, прежде чем что-то произойдёт. Читает те же данные, по
# которым потом примет решение ``mailbox_service.provision``, поэтому
# показанный вердикт и фактическое поведение не могут разойтись.


@api_view(methods=("GET",), auth="jwt", admin=True)
def mailbox_lookup(request):
    """``?address=`` — готовый адрес, либо поля формы: ``?local_part=``,
    ``?email=`` (корпоративный email пользователя — он же адрес ящика),
    ``?first_name=&last_name=``. ``?user_id=`` уточняет, кому предназначен
    ящик, — без него «занят другим сотрудником» не определить."""
    raw_user_id = (request.GET.get("user_id") or "").strip()
    user_id = None
    if raw_user_id:
        try:
            user_id = int(raw_user_id)
        except ValueError:
            return json_error("Invalid query parameter: user_id", 422)

    address = (request.GET.get("address") or "").strip()
    try:
        if address:
            found = lookup_service.lookup(address, for_user_id=user_id)
        else:
            found = lookup_service.lookup_candidate(
                local_part=request.GET.get("local_part", ""),
                email=request.GET.get("email", ""),
                first_name=request.GET.get("first_name", ""),
                last_name=request.GET.get("last_name", ""),
                user_id=user_id,
            )
    except mbx_svc.MailboxDomainNotConfigured:
        return json_error("MAILCOW_DOMAIN not configured", 500)
    except mbx_svc.InvalidLocalPart:
        return json_error("Invalid local_part", 400)
    return found.as_dict()


# ── /mailboxes/settings/ — реквизиты почтового сервера из интерфейса ──────
#
# GET  — что записано в БД + что реально действует (с учётом окружения).
# PUT  — сохранить; пустое поле = «вернуться к значению из окружения».
# POST /settings/test/ — прогнать ту же цепочку проверок, что и mail_check.


@api_view(methods=("GET",), auth="jwt", admin=True)
def _get_mail_settings(request):
    return settings_service.serialize()


@api_view(methods=("PUT",), auth="jwt", admin=True, body=schemas.MailSettingsRequest)
def _put_mail_settings(request, data: schemas.MailSettingsRequest):
    return settings_service.update(data, user_id=request.token.user_id)


def mail_settings(request):
    if request.method == "GET":
        return _get_mail_settings(request)
    if request.method == "PUT":
        return _put_mail_settings(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("POST",), auth="jwt", admin=True, body=schemas.MailConnectionTestRequest)
def test_mail_connection(request, data: schemas.MailConnectionTestRequest):
    """Проверка «на месте»: та же логика, что у ``manage.py mail_check``.

    Пароль принимается в теле и НИКУДА не сохраняется — он нужен только для
    одного пробного входа. Если его не передали, берётся сохранённый пароль
    уже заведённого ящика.
    """
    password = data.password
    if data.mailbox and not password:
        password = mbx_svc.stored_password(data.mailbox) or ""

    report = connection_check.run_check(
        mailbox=data.mailbox or None,
        password=password or None,
        send_to=data.send_to or None,
        timeout=data.timeout,
    )
    return report.to_dict()


# ── /mailboxes/reconcile/ ─────────────────────────────────────────────────
#
# GET  — только отчёт о расхождениях, ничего не меняет.
# POST — применить решение (direction=pull|push|both), тело — ReconcileRequest.


@api_view(methods=("GET",), auth="jwt", admin=True)
def _reconcile_report(request):
    return reconcile_service.reconcile(apply=False).to_dict()


@api_view(methods=("POST",), auth="jwt", admin=True, body=schemas.ReconcileRequest)
def _reconcile_apply(request, data: schemas.ReconcileRequest):
    return reconcile_service.reconcile(apply=data.apply, direction=data.direction).to_dict()


def reconcile_mailboxes(request):
    if request.method == "GET":
        return _reconcile_report(request)
    if request.method == "POST":
        return _reconcile_apply(request)
    return json_error("Method Not Allowed", 405)


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

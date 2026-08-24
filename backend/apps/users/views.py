"""HTTP views — ``/api/users/v1/*`` (token, profile, registration, admin/users).

Ported from ``services/user/app/api/v1/auth.py``. Views stay thin: parsing,
auth, and status codes only — domain logic lives in
``apps.users.services.auth_service`` (and the other ``*_service`` modules).

``token/`` and ``token/refresh/`` are plain JSON bodies and go through
``htqweb.http.api_view``'s ``body=`` machinery like every other app.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from pydantic import ValidationError

from apps.mail import interface as mail_interface
from htqweb.authn.jwt import AuthError, decode_token, issue_token_pair
from htqweb.http import api_view, json_error

from . import schemas
from .models import User, UserStatus
from .services import (
    admin_service,
    audit,
    auth_service,
    options_service,
    profile_service,
    registration_service,
)

logger = logging.getLogger(__name__)


# ── POST token/ — login by email or username ────────────────────────────────

@api_view(methods=("POST",), auth=None, body=schemas.TokenObtainRequest)
def obtain_token(request, data: schemas.TokenObtainRequest):
    try:
        user = auth_service.authenticate(data.email, data.password)
    except auth_service.AccountNotActivated:
        return json_error("Account is not activated", 401)
    except auth_service.InvalidCredentials:
        return json_error("Invalid credentials", 401)

    tokens = issue_token_pair(user)
    return schemas.TokenResponse(access=tokens["access"], refresh=tokens["refresh"])


# ── POST token/refresh/ — refresh-type tokens only ───────────────────────────

@api_view(methods=("POST",), auth=None, body=schemas.TokenRefreshRequest)
def refresh_token(request, data: schemas.TokenRefreshRequest):
    try:
        payload = decode_token(data.refresh)
    except (AuthError, ValidationError):
        return json_error("Invalid or expired refresh token", 401)

    if payload.token_type != "refresh":
        return json_error("Invalid or expired refresh token", 401)

    user = User.objects.filter(pk=payload.user_id).first()
    if user is None or user.status != UserStatus.ACTIVE:
        return json_error("User not found or inactive", 401)

    tokens = issue_token_pair(user)
    return schemas.TokenRefreshResponse(access=tokens["access"])


# ── Profile — GET/PATCH profile/me (+alias), change-password, avatar ────────
#
# Ported from services/user/app/api/v1/profile.py. Response shape and
# PATCH field precedence live in apps.users.services.profile_service — kept
# field-for-field/behaviour-for-behaviour identical to the FastAPI source
# (see that module's docstring for avatar storage's history, including the
# final-review-of-phases-2-3 fix).


def _get_profile_user(request):
    """Shared lookup: 404 if the JWT's user_id doesn't resolve (deleted
    user with a still-valid access token) — same guard the FastAPI source
    applies on every profile endpoint."""
    return User.objects.filter(pk=request.token.user_id).first()


@api_view(methods=("GET",), auth="jwt")
def _get_profile(request):
    user = _get_profile_user(request)
    if user is None:
        return json_error("User not found", 404)
    return profile_service.build_response(user)


def _parse_multipart_patch(request):
    """PATCH bodies aren't auto-parsed into request.POST/request.FILES by
    Django (HttpRequest._load_post_and_files only populates those for
    method == "POST") — so a multipart PATCH must be parsed by hand via the
    same MultiPartParser Django itself uses internally."""
    if request.content_type == "multipart/form-data":
        return request.parse_file_upload(request.META, request)
    return request.POST, request.FILES


@api_view(methods=("PATCH",), auth="jwt")
def _update_profile(request):
    """Patch the current user's profile.

    Content-Type: multipart/form-data (the frontend sends FormData so it
    can optionally attach an avatar file). Accepts both snake_case and
    camelCase aliases for first/last name (camelCase wins when both are
    present — see profile_service.apply_profile_fields).
    """
    user = _get_profile_user(request)
    if user is None:
        return json_error("User not found", 404)

    post_data, files_data = _parse_multipart_patch(request)

    def _coalesce(camel: str, snake: str) -> str | None:
        value = post_data.get(camel)
        return value if value is not None else post_data.get(snake)

    try:
        changes = profile_service.apply_profile_fields(
            user,
            display_name=post_data.get("display_name"),
            first_name=_coalesce("firstName", "first_name"),
            last_name=_coalesce("lastName", "last_name"),
            patronymic=post_data.get("patronymic"),
            bio=post_data.get("bio"),
            phone=post_data.get("phone"),
            settings_json=post_data.get("settings"),
        )
    except (profile_service.InvalidSettingsJSON, profile_service.FieldTooLong) as exc:
        return json_error(str(exc), 400)

    # update_fields = only the columns THIS request actually changed (review
    # Finding 1). Avatar storage I/O below is a real S3/network call, and an
    # unconditional full-row user.save() would rewrite every column from the
    # in-memory snapshot taken at request start — silently reverting any
    # concurrent write to this row (e.g. an admin toggling is_staff/
    # is_superuser/must_change_password) that lands during that window. Same
    # pattern remove_avatar/change_password already use below.
    update_fields = set(changes)

    avatar_file = files_data.get("avatar")
    if avatar_file is not None and avatar_file.name:
        # Routed through apps.media_files.interface.store_file(scope=
        # "avatar", ...) — the real upload pipeline (final review of
        # phases 2-3, Finding 2), not a direct htqweb.storage write.
        # Degrade, don't 500, on any failure (ServiceDisabled when media
        # is off, UploadValidationError, or a storage-backend error) — the
        # rest of the PATCH (fields already applied above) must still
        # land; only the avatar_url update is skipped.
        previous_avatar_url = user.avatar_url
        try:
            user.avatar_url = profile_service.save_avatar(
                user.id, avatar_file.name, avatar_file.read(), avatar_file.content_type,
            )
            update_fields.add("avatar_url")
        except Exception:  # noqa: BLE001
            logger.exception("avatar_save_failed user_id=%s", user.id)
        else:
            # R4 (orphan cleanup): the new avatar is live now — soft-delete
            # the PREVIOUS avatar's FileMetadata row so it doesn't sit
            # around forever as an orphaned object. Only runs once the new
            # avatar actually landed (this `else`, not `finally`) — a
            # failed upload above must leave the still-live old avatar
            # alone. profile_service.delete_avatar_object is already
            # best-effort internally (catches everything, including
            # ServiceDisabled when media is off, and only logs), but this
            # call site wraps it again anyway: the new avatar_url is
            # already set at this point, so cleanup of the OLD one must
            # NEVER be allowed to turn an otherwise-successful profile
            # PATCH into a 500, no matter how ``delete_avatar_object``
            # itself evolves.
            if previous_avatar_url:
                try:
                    profile_service.delete_avatar_object(previous_avatar_url)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "previous_avatar_cleanup_failed user_id=%s", user.id,
                    )

    if update_fields:
        # auto_now fields are NOT auto-added to a partial update_fields save —
        # must include updated_at explicitly whenever anything changed.
        update_fields.add("updated_at")
        user.save(update_fields=list(update_fields))
    return profile_service.build_response(user)


@csrf_exempt
def profile_me(request, *args, **kwargs):
    """profile/me (+ profile/ alias) — GET and PATCH share one path, so
    (unlike token/ vs token/refresh/) they need a method dispatcher rather
    than two separate ``path()`` entries: Django's URL resolver stops at
    the first pattern that matches the path regardless of method, so a
    second ``path("profile/me", ...)`` entry would simply be unreachable."""
    if request.method == "GET":
        return _get_profile(request, *args, **kwargs)
    if request.method == "PATCH":
        return _update_profile(request, *args, **kwargs)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("DELETE",), auth="jwt")
def remove_avatar(request):
    """Remove the user's avatar: best-effort delete of the underlying
    storage object, then always clear ``user.avatar_url``."""
    user = _get_profile_user(request)
    if user is None:
        return json_error("User not found", 404)

    profile_service.delete_avatar_object(user.avatar_url)
    user.avatar_url = None
    # auto_now fields are NOT auto-added to a partial update_fields save —
    # updated_at must be listed explicitly (R6 Fix 2).
    user.save(update_fields=["avatar_url", "updated_at"])
    return HttpResponse(status=204)


@api_view(methods=("POST",), auth="jwt", body=schemas.ChangePasswordRequest)
def change_password(request, data: schemas.ChangePasswordRequest):
    user = _get_profile_user(request)
    if user is None:
        return json_error("User not found", 404)

    try:
        profile_service.change_password(
            user, new_password=data.new_password, current_password=data.current_password,
        )
    except profile_service.CurrentPasswordRequired:
        return json_error("Current password is incorrect", 400)

    return {"detail": "Password changed successfully"}


# ── Registration + moderation — POST register/, GET pending-registrations/,
#    POST pending-registrations/{id}/approve|reject/ (Task 2.4) ────────────
#
# Ported from ``services/user/app/api/v1/registration.py``. Views stay
# thin — domain logic lives in ``apps.users.services.registration_service``.
#
# Decision Р2 (dropped, see that module's docstring): the FastAPI source
# publishes ``user_upserted``/``user_deactivated`` Redis pub/sub events
# after approve/reject for messenger/task/HR replica sync. This port does
# NOT re-publish those — noted at each call site below.


@api_view(methods=("POST",), auth=None, body=schemas.RegisterRequest, status=201)
def register(request, data: schemas.RegisterRequest):
    try:
        user = registration_service.register(
            email=data.email, password=data.password, full_name=data.full_name,
        )
    except registration_service.DuplicateEmail:
        return json_error("Email already registered", 400)
    return schemas.RegisterResponse(id=user.id, email=user.email)


@api_view(methods=("GET",), auth="jwt", admin=True)
def pending_registrations(request):
    users = registration_service.list_pending()
    return [
        schemas.PendingUserResponse(
            id=u.id,
            email=u.email,
            username=u.username,
            full_name=u.display_name or f"{u.first_name} {u.last_name}".strip(),
            date_joined=u.date_joined.isoformat(),
        )
        for u in users
    ]


@api_view(methods=("POST",), auth="jwt", admin=True)
def approve_registration(request, user_id: int):
    try:
        registration_service.approve(user_id)
    except registration_service.PendingRegistrationNotFound:
        return json_error("Pending registration not found", 404)
    # Decision Р2: source publishes user_upserted.send(_replica_payload(user)) here — dropped.
    audit.record_action(
        request,
        user_id=request.token.user_id,
        action="registration.approved",
        resource_type="User",
        resource_id=str(user_id),
        changes={"status": "active"},
    )
    return HttpResponse(status=204)


@api_view(methods=("POST",), auth="jwt", admin=True)
def reject_registration(request, user_id: int):
    try:
        registration_service.reject(user_id)
    except registration_service.PendingRegistrationNotFound:
        return json_error("Pending registration not found", 404)
    # Decision Р2: source publishes user_deactivated.send({"id": user.id}) here — dropped.
    audit.record_action(
        request,
        user_id=request.token.user_id,
        action="registration.rejected",
        resource_type="User",
        resource_id=str(user_id),
        changes={"status": "rejected"},
    )
    return HttpResponse(status=204)


# ── Admin: users list/create/patch/set-password/delete (Task 2.4) ──────────
#
# Ported from ``services/user/app/api/v1/admin.py``. Decisions Р2/Р3
# (dropped — see ``apps.users.services.admin_service``'s module docstring
# for the full inventory): Redis pub/sub broadcasts after create/update/
# delete, the S2S mailbox-archive call in delete, and Mailcow mailbox
# provisioning in create.


@api_view(methods=("GET",), auth="jwt", admin=True)
def _admin_list_users(request):
    users = admin_service.list_users()
    return [schemas.AdminUserResponse(**admin_service.serialize_admin_user(u)) for u in users]


@api_view(methods=("POST",), auth="jwt", body=schemas.AdminUserCreateRequest, status=201, admin=True)
def _admin_create_user(request, data: schemas.AdminUserCreateRequest):
    payload = data.model_dump()
    create_mailbox = payload.pop("create_mailbox")
    mailbox_local_part = payload.pop("mailbox_local_part", None) or ""
    mailbox_password = payload.pop("mailbox_password", None) or ""
    mailbox_quota_mb = payload.pop("mailbox_quota_mb", None) or 0
    try:
        user = admin_service.create_user(**payload)
    except admin_service.DuplicateEmail:
        return json_error("Email already in use", 400)
    except admin_service.DuplicateUsername:
        return json_error("Username already in use", 400)
    except admin_service.InvalidStatus as exc:
        return json_error(str(exc), 400)
    # Decision Р2: source publishes user_upserted.send(...) when status==ACTIVE — dropped.
    # Ящик заводится через apps.mail.interface (S2S-вызов в удалённый
    # email-сервис заменён обычным вызовом соседней аппки). Раньше здесь
    # стояла заглушка, которая на любую галочку отвечала "провижининг
    # недоступен" — из-за неё ящик при создании пользователя не появлялся.
    mailbox, mailbox_error = None, None
    if create_mailbox:
        mailbox, mailbox_error = mail_interface.provision_mailbox(
            user_id=user.id,
            first_name=user.first_name or "",
            last_name=user.last_name or "",
            full_name=user.display_name or "",
            local_part=mailbox_local_part,
            # Корпоративный email — это и есть адрес ящика: админ, вписавший
            # ruslan.amirov@htq.group, уже назвал его, и транслитерация ФИО
            # (r.amirov) дала бы ящик, не совпадающий с логином сотрудника.
            email=user.email or "",
            password=mailbox_password,
            quota_mb=mailbox_quota_mb,
        )
    else:
        # Галку не ставили — значит ящик не заказывали и создавать его нечего.
        # Но если ящик с таким адресом на почтовом сервере УЖЕ есть, оставлять
        # его неподключённым бессмысленно: сотрудник завтра откроет «Почту» и
        # не найдёт там своей рабочей переписки. Ничего не создаёт, молчит,
        # когда подключать нечего.
        mailbox = mail_interface.attach_mailbox_by_email(
            user_id=user.id, email=user.email or "",
        )
    # `payload` still has every field `admin_service.create_user` was called
    # with EXCEPT `password` — never let the plaintext password (or, were
    # this ever refactored, a hash) reach the audit log's `changes` JSON.
    audit.record_action(
        request,
        user_id=request.token.user_id,
        action="user.created",
        resource_type="User",
        resource_id=str(user.id),
        changes={k: v for k, v in payload.items() if k != "password"},
    )
    return schemas.AdminUserCreatedResponse(
        **admin_service.serialize_admin_user(user),
        mailbox=mailbox,
        mailbox_error=mailbox_error,
    )


@csrf_exempt
def admin_users_collection(request, *args, **kwargs):
    if request.method == "GET":
        return _admin_list_users(request, *args, **kwargs)
    if request.method == "POST":
        return _admin_create_user(request, *args, **kwargs)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("PATCH",), auth="jwt", body=schemas.AdminUserUpdateRequest, admin=True)
def _admin_update_user(request, user_id: int, data: schemas.AdminUserUpdateRequest):
    try:
        user = admin_service.get_user_or_404(user_id)
    except admin_service.UserNotFound:
        return json_error("User not found", 404)

    changes = data.model_dump(exclude_unset=True)
    # Snapshot pre-update values for every field the request touched, BEFORE
    # admin_service.update_user mutates `user` in place — the audit log
    # records a diff of what actually changed (old != new), not the raw
    # request payload (a field re-sent with its current value is a no-op
    # and shouldn't show up as "changed"), and privilege flags
    # (is_staff/is_superuser/status) are exactly the fields this diff exists
    # to make visible.
    before = {field: getattr(user, field, None) for field in changes}
    try:
        user = admin_service.update_user(user, changes)
    except admin_service.DuplicateEmail:
        return json_error("Email already in use", 400)
    except admin_service.DuplicateUsername:
        return json_error("Username already in use", 400)
    except admin_service.InvalidStatus as exc:
        return json_error(str(exc), 400)
    except admin_service.InvalidSettingsJSON as exc:
        return json_error(str(exc), 400)
    # Decision Р2: source publishes user_upserted/user_deactivated depending
    # on the new status — dropped.
    diff = {
        field: {"old": before[field], "new": getattr(user, field, None)}
        for field in changes
        if getattr(user, field, None) != before[field]
    }
    audit.record_action(
        request,
        user_id=request.token.user_id,
        action="user.updated",
        resource_type="User",
        resource_id=str(user.id),
        changes=diff,
    )
    return schemas.AdminUserResponse(**admin_service.serialize_admin_user(user))


@api_view(methods=("DELETE",), auth="jwt", admin=True)
def _admin_delete_user(request, user_id: int):
    if request.token.user_id == user_id:
        return json_error("Cannot delete yourself", 400)
    try:
        user = admin_service.get_user_or_404(user_id)
    except admin_service.UserNotFound:
        return json_error("User not found", 404)
    # Decisions Р2/Р3: source's S2S mailbox-archive call + user.deactivated/
    # user.deleted broadcasts dropped here — see admin_service module docstring.
    admin_service.delete_user(user)
    audit.record_action(
        request,
        user_id=request.token.user_id,
        action="user.suspended",
        resource_type="User",
        resource_id=str(user_id),
        changes={"status": "suspended", "is_staff": False, "is_superuser": False},
    )
    return HttpResponse(status=204)


@csrf_exempt
def admin_user_detail(request, user_id: int, *args, **kwargs):
    if request.method == "PATCH":
        return _admin_update_user(request, user_id, *args, **kwargs)
    if request.method == "DELETE":
        return _admin_delete_user(request, user_id, *args, **kwargs)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("POST",), auth="jwt", body=schemas.AdminSetPasswordRequest, admin=True)
def admin_set_password(request, user_id: int, data: schemas.AdminSetPasswordRequest):
    try:
        user = admin_service.get_user_or_404(user_id)
    except admin_service.UserNotFound:
        return json_error("User not found", 404)
    admin_service.set_password(
        user, new_password=data.new_password, must_change_password=data.must_change_password,
    )
    # `changes` records only that a reset happened + the resulting
    # must_change_password flag — NEVER the new password or its hash.
    audit.record_action(
        request,
        user_id=request.token.user_id,
        action="user.password_set",
        resource_type="User",
        resource_id=str(user.id),
        changes={"must_change_password": data.must_change_password},
    )
    return {"detail": "Password updated"}


# ── Client telemetry — POST client-errors(/), client-events(/) (Task 2.5) ──
#
# Ported from ``services/user/app/api/v1/client_errors.py``. Nothing is
# persisted to SQL — these are log-only endpoints (Loki is the source of
# truth for browser telemetry). Both accept anonymous callers: a missing or
# invalid Authorization header must never turn into a 401 here (pre-login
# crashes and logouts need to be captured too) — ``auth=None`` at the
# ``api_view`` layer already guarantees that; ``_maybe_user_id`` below is a
# best-effort enrichment on top, not a gate.


def _maybe_user_id(request) -> int | None:
    """Decode a bearer JWT if one is present and valid; otherwise ``None``.

    Mirrors the source's ``_maybe_decode`` — a garbage/expired/absent
    Authorization header is swallowed silently, never raised, so the caller
    stays anonymous-but-accepted rather than rejected.
    """
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    try:
        payload = decode_token(header[7:])
    except (AuthError, ValidationError):
        return None
    if payload.token_type != "access":
        return None
    return payload.user_id


@api_view(methods=("POST",), auth=None, body=schemas.ClientErrorReport, status=202)
def ingest_client_error(request, data: schemas.ClientErrorReport):
    """Log a frontend fatal error at ERROR level so Loki alerts can fire."""
    user_id = _maybe_user_id(request) or data.userId
    logger.error(
        "frontend_client_error message=%r stack=%r component_stack=%r "
        "client_url=%r user_agent=%r client_timestamp=%r user_id=%s ip=%s",
        data.message, data.stack, data.componentStack, data.url,
        data.userAgent, data.timestamp, user_id, request.META.get("REMOTE_ADDR"),
    )
    return {"ok": True}


@api_view(methods=("POST",), auth=None, body=schemas.UserActionEvent, status=202)
def ingest_user_action(request, data: schemas.UserActionEvent):
    """Log a user-action audit event at INFO level."""
    logger.info(
        "frontend_user_action action=%r resource=%r resource_id=%r meta=%r "
        "client_url=%r user_agent=%r client_timestamp=%r user_id=%s ip=%s",
        data.action, data.resource,
        str(data.resourceId) if data.resourceId is not None else None,
        data.meta, data.url, data.userAgent, data.timestamp,
        _maybe_user_id(request), request.META.get("REMOTE_ADDR"),
    )
    return {"ok": True}


# ── GET users/options/ — active-user picker (Task 2.5) ─────────────────────
#
# Ported from ``services/user/app/api/v1/users.py``. Any authenticated user
# may call this (no admin gate) — see ``apps.users.services.options_service``.


@api_view(methods=("GET",), auth="jwt")
def list_user_options(request):
    try:
        q = schemas.UserOptionsQuery.model_validate(dict(request.GET.items()))
    except ValidationError as exc:
        return JsonResponse({"detail": json.loads(exc.json())}, status=422)
    users = options_service.list_user_options(query=q.query, limit=q.limit)
    # Email is contact data, not an identity hint: a picker needs a name to
    # show, not a mailbox to harvest. Elevated callers keep it — admin
    # screens do use it to disambiguate namesakes.
    expose_email = request.token.is_elevated
    return [
        schemas.UserOption(
            id=u.id,
            full_name=options_service.full_name_for(u),
            email=(u.email or "") if expose_email else "",
        )
        for u in users
    ]

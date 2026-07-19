"""HTTP views — ``/api/users/v1/{token,token/refresh,admin-session}/*``.

Ported from ``services/user/app/api/v1/auth.py``. Views stay thin: parsing,
auth, and status codes only — domain logic lives in
``apps.users.services.auth_service``.

``token/`` and ``token/refresh/`` are plain JSON bodies and go through
``htqweb.http.api_view``'s ``body=`` machinery like every other app. The
``admin-session/*`` routes don't: ``login`` is form-urlencoded (sqladmin's
login page posts a plain HTML form, not JSON) and needs a redirect response
with a ``Set-Cookie`` header, which ``api_view`` doesn't model — both are
hand-rolled thin views instead, following the same "thin view, real logic in
the service" shape.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from pydantic import ValidationError

from htqweb.authn.jwt import AuthError, decode_token, issue_token_pair
from htqweb.http import api_view, json_error

from . import schemas
from .models import User, UserStatus
from .services import admin_service, auth_service, profile_service, registration_service

logger = logging.getLogger(__name__)


def _require_admin(request) -> None:
    """Gate on ``request.token.is_elevated`` (is_admin/is_staff/is_superuser).

    ``htqweb.http.api_view`` maps ``PermissionDenied`` to a 403 ``{"detail":
    "Forbidden"}`` envelope regardless of the message passed here (see
    ``apps.cms.views._require_admin`` for the same established pattern) — a
    missing/invalid token never reaches this far, ``api_view(auth="jwt")``
    already 401s first.
    """
    if not request.token.is_elevated:
        raise PermissionDenied("Admin access required")


ADMIN_COOKIE_NAME = "admin_session"


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


# ── POST admin-session/login ─────────────────────────────────────────────────

@csrf_exempt
def admin_login(request):
    """Set the ``admin_session`` cookie so sqladmin backends accept the
    user. After submission the user is redirected back to the original
    admin URL (``next``). Only ``is_staff``/``is_superuser`` users are
    accepted — ported verbatim from the FastAPI original's ``admin_login``.
    """
    if request.method != "POST":
        return json_error("Method Not Allowed", 405)

    # ``username``/``password`` are ``Form(...)`` (required) in the FastAPI
    # original — an OMITTED field must 422, same as there. Reading via
    # ``.get(..., "")`` before validation would silently turn "absent" into
    # "empty string", which the schema (str, no default) happily accepts,
    # so we check presence in request.POST ourselves first. A field that IS
    # present but empty is a value, not an absence — that still reaches the
    # schema/auth flow unchanged (matching the source).
    missing = [f for f in ("username", "password") if f not in request.POST]
    if missing:
        detail = [
            {"loc": ["body", f], "msg": "Field required", "type": "missing"}
            for f in missing
        ]
        return JsonResponse({"detail": detail}, status=422)

    try:
        data = schemas.AdminSessionLoginRequest(
            username=request.POST.get("username", ""),
            password=request.POST.get("password", ""),
            next=request.POST.get("next", "/sqladmin/"),
        )
    except ValidationError as exc:
        return JsonResponse({"detail": json.loads(exc.json())}, status=422)

    try:
        user = auth_service.authenticate_admin(data.username, data.password)
    except auth_service.NotAnAdminUser:
        return json_error("Not an admin user", 403)
    except auth_service.InvalidCredentials:
        return json_error("Invalid credentials", 401)

    tokens = issue_token_pair(user)

    # Flag the cookie Secure only when the request itself is HTTPS —
    # otherwise browsers on HTTP localhost would silently drop it. The
    # X-Forwarded-Proto header (set by nginx) wins over the raw request
    # scheme — same reasoning as the FastAPI original.
    forwarded_proto = request.headers.get("x-forwarded-proto", request.scheme)
    is_https = forwarded_proto == "https"

    response = HttpResponse(status=303)
    response["Location"] = data.next
    response.set_cookie(
        ADMIN_COOKIE_NAME,
        tokens["access"],
        max_age=settings.JWT_ACCESS_TTL_MIN * 60,
        httponly=True,
        secure=is_https,
        samesite="Lax",
        path="/",
    )
    logger.info("admin_session_issued user_id=%s username=%s next=%s",
                user.id, user.username, data.next)
    return response


# ── POST admin-session/logout ────────────────────────────────────────────────

@csrf_exempt
def admin_logout(request):
    if request.method != "POST":
        return json_error("Method Not Allowed", 405)
    response = JsonResponse({"ok": True})
    response.delete_cookie(ADMIN_COOKIE_NAME, path="/")
    return response


# ── Profile — GET/PATCH profile/me (+alias), change-password, avatar ────────
#
# Ported from services/user/app/api/v1/profile.py. Response shape and
# PATCH field precedence live in apps.users.services.profile_service — kept
# field-for-field/behaviour-for-behaviour identical to the FastAPI source
# (see that module's docstring for the one deliberate deviation: avatar
# storage, decision Р3).


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
    except profile_service.InvalidSettingsJSON as exc:
        return json_error(str(exc), 400)

    # update_fields = only the columns THIS request actually changed (review
    # Finding 1). Avatar storage I/O below is a real S3/network call, and an
    # unconditional full-row user.save() would rewrite every column from the
    # in-memory snapshot taken at request start — silently reverting any
    # concurrent write to this row (e.g. an admin toggling is_staff/
    # is_superuser/must_change_password) that lands during that window. Same
    # pattern remove_avatar/change_password already use below.
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
        # Decision Р3: write directly to htqweb.storage instead of an S2S
        # hop to media-service. Degrade, don't 500, on storage failure —
        # the rest of the PATCH (fields already applied above) must still
        # land; only the avatar_url update is skipped.
        try:
            user.avatar_url = profile_service.save_avatar(
                user.id, avatar_file.name, avatar_file.read(), avatar_file.content_type,
            )
            update_fields.add("avatar_url")
        except Exception:  # noqa: BLE001
            logger.exception("avatar_save_failed user_id=%s", user.id)

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
    user.save(update_fields=["avatar_url"])
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


@api_view(methods=("GET",), auth="jwt")
def pending_registrations(request):
    _require_admin(request)
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


@api_view(methods=("POST",), auth="jwt")
def approve_registration(request, user_id: int):
    _require_admin(request)
    try:
        registration_service.approve(user_id)
    except registration_service.PendingRegistrationNotFound:
        return json_error("Pending registration not found", 404)
    # Decision Р2: source publishes user_upserted.send(_replica_payload(user)) here — dropped.
    return HttpResponse(status=204)


@api_view(methods=("POST",), auth="jwt")
def reject_registration(request, user_id: int):
    _require_admin(request)
    try:
        registration_service.reject(user_id)
    except registration_service.PendingRegistrationNotFound:
        return json_error("Pending registration not found", 404)
    # Decision Р2: source publishes user_deactivated.send({"id": user.id}) here — dropped.
    return HttpResponse(status=204)


# ── Admin: users list/create/patch/set-password/delete (Task 2.4) ──────────
#
# Ported from ``services/user/app/api/v1/admin.py``. Decisions Р2/Р3
# (dropped — see ``apps.users.services.admin_service``'s module docstring
# for the full inventory): Redis pub/sub broadcasts after create/update/
# delete, the S2S mailbox-archive call in delete, and Mailcow mailbox
# provisioning in create.


@api_view(methods=("GET",), auth="jwt")
def _admin_list_users(request):
    _require_admin(request)
    users = admin_service.list_users()
    return [schemas.AdminUserResponse(**admin_service.serialize_admin_user(u)) for u in users]


@api_view(methods=("POST",), auth="jwt", body=schemas.AdminUserCreateRequest, status=201)
def _admin_create_user(request, data: schemas.AdminUserCreateRequest):
    _require_admin(request)
    try:
        user = admin_service.create_user(**data.model_dump())
    except admin_service.DuplicateEmail:
        return json_error("Email already in use", 400)
    except admin_service.DuplicateUsername:
        return json_error("Username already in use", 400)
    except admin_service.InvalidStatus as exc:
        return json_error(str(exc), 400)
    # Decision Р2: source publishes user_upserted.send(...) when status==ACTIVE — dropped.
    return schemas.AdminUserResponse(**admin_service.serialize_admin_user(user))


@csrf_exempt
def admin_users_collection(request, *args, **kwargs):
    if request.method == "GET":
        return _admin_list_users(request, *args, **kwargs)
    if request.method == "POST":
        return _admin_create_user(request, *args, **kwargs)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("PATCH",), auth="jwt", body=schemas.AdminUserUpdateRequest)
def _admin_update_user(request, user_id: int, data: schemas.AdminUserUpdateRequest):
    _require_admin(request)
    try:
        user = admin_service.get_user_or_404(user_id)
    except admin_service.UserNotFound:
        return json_error("User not found", 404)

    changes = data.model_dump(exclude_unset=True)
    try:
        user = admin_service.update_user(user, changes)
    except admin_service.DuplicateEmail:
        return json_error("Email already in use", 400)
    except admin_service.DuplicateUsername:
        return json_error("Username already in use", 400)
    except admin_service.InvalidSettingsJSON as exc:
        return json_error(str(exc), 400)
    # Decision Р2: source publishes user_upserted/user_deactivated depending
    # on the new status — dropped.
    return schemas.AdminUserResponse(**admin_service.serialize_admin_user(user))


@api_view(methods=("DELETE",), auth="jwt")
def _admin_delete_user(request, user_id: int):
    _require_admin(request)
    if request.token.user_id == user_id:
        return json_error("Cannot delete yourself", 400)
    try:
        user = admin_service.get_user_or_404(user_id)
    except admin_service.UserNotFound:
        return json_error("User not found", 404)
    # Decisions Р2/Р3: source's S2S mailbox-archive call + user.deactivated/
    # user.deleted broadcasts dropped here — see admin_service module docstring.
    admin_service.delete_user(user)
    return HttpResponse(status=204)


@csrf_exempt
def admin_user_detail(request, user_id: int, *args, **kwargs):
    if request.method == "PATCH":
        return _admin_update_user(request, user_id, *args, **kwargs)
    if request.method == "DELETE":
        return _admin_delete_user(request, user_id, *args, **kwargs)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("POST",), auth="jwt", body=schemas.AdminSetPasswordRequest)
def admin_set_password(request, user_id: int, data: schemas.AdminSetPasswordRequest):
    _require_admin(request)
    try:
        user = admin_service.get_user_or_404(user_id)
    except admin_service.UserNotFound:
        return json_error("User not found", 404)
    admin_service.set_password(
        user, new_password=data.new_password, must_change_password=data.must_change_password,
    )
    return {"detail": "Password updated"}

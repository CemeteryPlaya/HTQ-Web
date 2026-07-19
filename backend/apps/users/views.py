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
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from pydantic import ValidationError

from htqweb.authn.jwt import AuthError, decode_token, issue_token_pair
from htqweb.http import api_view, json_error

from . import schemas
from .models import User, UserStatus
from .services import auth_service

logger = logging.getLogger(__name__)


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

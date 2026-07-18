"""sqladmin AuthenticationBackend — cross-service JWT validation.

The `admin_session` cookie is minted by user-service after
`POST /api/users/v1/admin-session/login`. This backend verifies it locally
using the shared JWT secret; no HTTP call is needed on every request.

For first-time login via this service's own `/admin/login` form, we call
user-service's `/api/users/v1/token/` endpoint to verify credentials and receive a
JWT, then store it in the session.
"""

from __future__ import annotations

import httpx
import jwt
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.core.settings import settings


COOKIE_NAME = "admin_session"


class JWTAdminAuthBackend(AuthenticationBackend):
    def __init__(self, secret_key: str) -> None:
        super().__init__(secret_key=secret_key)

    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = str(form.get("username") or "")
        password = str(form.get("password") or "")
        if not username or not password:
            return False

        user_service_url = getattr(settings, "user_service_url", "http://user-service:8005")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{user_service_url}/api/users/v1/token/",
                    json={"email": username, "password": password},
                )
        except httpx.HTTPError:
            return False

        if resp.status_code != 200:
            return False

        access_token = resp.json().get("access")
        if not access_token:
            return False

        try:
            payload = jwt.decode(
                access_token,
                settings.jwt_secret,
                algorithms=[settings.jwt_algorithm],
                issuer=settings.jwt_issuer,
            )
        except jwt.PyJWTError:
            return False
        if not payload.get("is_admin"):
            return False

        request.session.update({"admin_jwt": access_token})
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool | RedirectResponse:
        token = request.session.get("admin_jwt") or request.cookies.get(COOKIE_NAME)
        if not token:
            return False
        try:
            payload = jwt.decode(
                token,
                settings.jwt_secret,
                algorithms=[settings.jwt_algorithm],
                issuer=settings.jwt_issuer,
                options={"verify_exp": True},
            )
        except jwt.PyJWTError:
            return False
        return bool(payload.get("is_admin"))

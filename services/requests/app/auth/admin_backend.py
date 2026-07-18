"""sqladmin AuthenticationBackend — validates JWT cookie issued by user-service.

Admin access requires a JWT with `is_admin: true` (issued by user-service when
an authenticated user with role=admin requests it). The token rides as a cookie
named `admin_session` so that browser-driven admin pages don't need to attach
an Authorization header.
"""

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
        # Login is performed against user-service, which sets the cookie.
        # sqladmin only needs to verify it on subsequent requests.
        return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool | RedirectResponse:
        token = request.cookies.get(COOKIE_NAME)
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

"""sqladmin AuthenticationBackend — validates the `admin_session` cookie.

The cookie is set by `POST /api/users/v1/admin-session/login` in user-service.
Admin access is granted when the JWT contains `is_admin: true`
(derived from `is_staff or is_superuser` at token issuance).

Because sqladmin renders a self-hosted `/admin/login` page, this backend's
`login()` method accepts the form submission and forwards it to the central
admin-session endpoint, so users experience a single login step.
"""

import jwt
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.core.settings import settings
from app.services.auth_service import create_token_pair, verify_password


COOKIE_NAME = "admin_session"


class JWTAdminAuthBackend(AuthenticationBackend):
    def __init__(self, secret_key: str) -> None:
        super().__init__(secret_key=secret_key)

    async def login(self, request: Request) -> bool:
        """Handle local sqladmin login — verify against User table directly.

        This runs inside user-service (the JWT authority) so we can look up
        credentials without an HTTP round-trip. In other services the backend
        instead relies on a cross-service cookie set by user-service.
        """
        from app.db import async_session_factory
        from app.models.user import User, UserStatus
        from sqlalchemy import select

        form = await request.form()
        username = str(form.get("username") or "")
        password = str(form.get("password") or "")
        if not username or not password:
            return False

        async with async_session_factory() as session:
            result = await session.execute(
                select(User).where(
                    (User.email == username.lower()) | (User.username == username)
                )
            )
            user = result.scalar_one_or_none()

        if (
            user is None
            or user.status != UserStatus.ACTIVE
            or not (user.is_staff or user.is_superuser)
            or not verify_password(password, user.password_hash)
        ):
            return False

        tokens = create_token_pair(
            user_id=user.id,
            username=user.username,
            email=user.email,
            is_staff=user.is_staff,
            is_superuser=user.is_superuser,
        )
        request.session.update({"admin_jwt": tokens.access})
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

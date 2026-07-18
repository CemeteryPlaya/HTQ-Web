"""
Authentication endpoints — JWT token issuance.

Replaces Django's SafeTokenObtainPairView and TokenRefreshView.
This is the entry point for all platform authentication.
"""

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.models.user import User, UserStatus
from app.services.auth_service import (
    create_token_pair,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
)


log = structlog.get_logger(__name__)


ADMIN_COOKIE_NAME = "admin_session"
ADMIN_COOKIE_MAX_AGE = 2 * 60 * 60  # 2 hours — matches access-token lifetime


router = APIRouter(prefix="/api/users/v1/token", tags=["auth"])


class TokenObtainRequest(BaseModel):
    """Login request — email or username + password."""
    email: str  # Primary login identifier (was 'username' in Django)
    password: str


class TokenRefreshRequest(BaseModel):
    """Refresh token request."""
    refresh: str


class TokenResponse(BaseModel):
    access: str
    refresh: str
    token_type: str = "Bearer"


class TokenRefreshResponse(BaseModel):
    access: str
    token_type: str = "Bearer"


@router.post("/", response_model=TokenResponse)
async def obtain_token(
    request: TokenObtainRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """
    Authenticate user and return JWT pair.

    Replaces Django's SafeTokenObtainPairView.
    Supports login by email (was EmailTokenObtainPairSerializer).
    """
    # Find user by email or username
    result = await db.execute(
        select(User).where(
            (User.email == request.email.lower()) |
            (User.username == request.email)
        )
    )
    user = result.scalar_one_or_none()

    if user is None:
        log.info("login_failed", login_id=request.email, reason="user_not_found")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if user.status != UserStatus.ACTIVE:
        log.info(
            "login_failed",
            login_id=request.email,
            user_id=user.id,
            reason="inactive",
            status=user.status.value if user.status else None,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is not activated",
        )

    if not verify_password(request.password, user.password_hash):
        log.info("login_failed", login_id=request.email, user_id=user.id, reason="wrong_password")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    # Legacy PBKDF2 hash — upgrade to bcrypt while we have the plain password
    # (get_db_session commits on request success).
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(request.password)
        log.info("password_rehashed", user_id=user.id)

    # Create JWT pair with custom claims
    tokens = create_token_pair(
        user_id=user.id,
        username=user.username,
        email=user.email,
        is_staff=user.is_staff,
        is_superuser=user.is_superuser,
    )

    log.info(
        "token_issued",
        user_id=user.id,
        username=user.username,
        is_admin=bool(user.is_staff or user.is_superuser),
    )

    return TokenResponse(
        access=tokens.access,
        refresh=tokens.refresh,
    )


@router.post("/refresh/", response_model=TokenRefreshResponse)
async def refresh_token(
    request: TokenRefreshRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """
    Refresh an access token using a valid refresh token.

    Replaces Django's TokenRefreshView.
    """
    try:
        payload = decode_token(request.refresh, require_type="refresh")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # Verify user still exists and is active
    result = await db.execute(select(User).where(User.id == payload.user_id))
    user = result.scalar_one_or_none()

    if user is None or user.status != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # Issue new token pair
    tokens = create_token_pair(
        user_id=user.id,
        username=user.username,
        email=user.email,
        is_staff=user.is_staff,
        is_superuser=user.is_superuser,
    )

    log.info("token_refreshed", user_id=user.id)

    return TokenRefreshResponse(access=tokens.access)


admin_router = APIRouter(prefix="/api/users/v1/admin-session", tags=["admin-auth"])


@admin_router.post("/login")
async def admin_login(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next: Annotated[str, Form()] = "/sqladmin/",
):
    """Set the `admin_session` cookie so sqladmin backends accept the user.

    Used by sqladmin login pages in every service. After submission the user
    is redirected back to the original admin URL (`next`). Only users with
    `is_staff` or `is_superuser` are accepted.
    """
    result = await db.execute(
        select(User).where(
            (User.email == username.lower()) | (User.username == username)
        )
    )
    user = result.scalar_one_or_none()

    if user is None or user.status != UserStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not (user.is_staff or user.is_superuser):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not an admin user")
    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        log.info("password_rehashed", user_id=user.id)

    tokens = create_token_pair(
        user_id=user.id,
        username=user.username,
        email=user.email,
        is_staff=user.is_staff,
        is_superuser=user.is_superuser,
    )

    # Flag the cookie Secure only when the request itself is HTTPS — otherwise
    # browsers on HTTP localhost would silently drop it. The X-Forwarded-Proto
    # header (set by nginx) wins over the raw request scheme.
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    is_https = forwarded_proto == "https"

    response = RedirectResponse(url=next, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=ADMIN_COOKIE_NAME,
        value=tokens.access,
        max_age=ADMIN_COOKIE_MAX_AGE,
        httponly=True,
        secure=is_https,
        samesite="lax",
        path="/",
    )
    log.info("admin_session_issued", user_id=user.id, username=user.username, next=next)
    return response


@admin_router.post("/logout")
async def admin_logout(response: Response):
    response.delete_cookie(ADMIN_COOKIE_NAME, path="/")
    return {"ok": True}

"""
User profile endpoints — read/update own profile.

Replaces Django's ProfileViewSet. The response shape matches what the
React SPA expects (camelCase aliases, `roles`, `fio`, etc.), so no frontend
changes are needed to light up the post-login page.
"""

import json
from typing import Annotated

import httpx
import structlog
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.core.settings import settings
from app.db import get_db_session
from app.models.user import User, UserStatus
from app.services.auth_service import hash_password, verify_password
from app.services.service_tokens import issue_service_token
from app.workers.actors import user_upserted


def _replica_payload(user: User) -> dict:
    """Same shape as ``admin._replica_payload``. Published on Redis so
    downstream replicas (messenger, task, HR) pick up the change."""
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "display_name": user.display_name or "",
        "phone": user.phone or "",
        "avatar_url": user.avatar_url,
        "status": user.status.value if hasattr(user.status, "value") else str(user.status),
        "is_active": user.status == UserStatus.ACTIVE,
    }


log = structlog.get_logger(__name__)


router = APIRouter(prefix="/api/users/v1/profile", tags=["profile"])


_FILE_ID_RE = __import__("re").compile(r"/files/([0-9a-f-]{36})", __import__("re").IGNORECASE)


def _avatar_payload(avatar_url: str | None) -> dict | None:
    """Build the structured ``avatar`` block from a stored URL.

    Always exposes the canonical thumbnail variants (32/96/256). The browser
    will 404 a variant that the worker hasn't generated yet and fall back
    to the original — that's fine.
    """
    if not avatar_url:
        return None
    m = _FILE_ID_RE.search(avatar_url)
    if not m:
        # Legacy / external URLs (e.g., i.pravatar.cc) — just expose `url`.
        return {"id": None, "url": avatar_url, "variants": {}}
    file_id = m.group(1)
    return {
        "id": file_id,
        "url": f"/api/media/v1/files/{file_id}",
        "variants": {
            "thumb_32": f"/api/media/v1/files/{file_id}/thumb_32",
            "thumb_96": f"/api/media/v1/files/{file_id}/thumb_96",
            "thumb_256": f"/api/media/v1/files/{file_id}/thumb_256",
        },
    }


def _roles_for(user: User) -> list[str]:
    roles: list[str] = []
    if user.is_superuser:
        roles.append("admin")
    if user.is_staff and not user.is_superuser:
        roles.append("staff")
    if not roles:
        roles.append("user")
    return roles


def _build_response(user: User) -> "ProfileResponse":
    first_name = user.first_name or ""
    last_name = user.last_name or ""
    patronymic = user.patronymic or ""
    fio_parts = [p for p in (last_name, first_name, patronymic) if p]
    fio = " ".join(fio_parts)
    return ProfileResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        first_name=first_name,
        last_name=last_name,
        firstName=first_name,
        lastName=last_name,
        patronymic=patronymic,
        display_name=user.display_name or "",
        fio=fio,
        bio=user.bio or "",
        phone=user.phone or "",
        avatar_url=user.avatar_url,
        avatarUrl=user.avatar_url,
        avatar=_avatar_payload(user.avatar_url),
        settings=user.settings or {},
        roles=_roles_for(user),
        department=None,
        department_id=None,
        position=None,
        must_change_password=bool(user.must_change_password),
        date_joined=user.date_joined.isoformat() if user.date_joined else None,
        last_login=user.last_login.isoformat() if user.last_login else None,
        created_at=user.created_at.isoformat() if user.created_at else None,
        updated_at=user.updated_at.isoformat() if user.updated_at else None,
    )


class ProfileResponse(BaseModel):
    # Identity
    id: str
    username: str
    email: str

    # Name fields — both snake_case (DB) and camelCase (frontend) on the wire.
    first_name: str
    last_name: str
    firstName: str
    lastName: str
    patronymic: str
    display_name: str
    fio: str

    # Profile content
    bio: str
    phone: str
    avatar_url: str | None
    avatarUrl: str | None
    # Structured avatar — exposes the file id + URL + thumbnail variants
    # (``{thumb_32, thumb_96, thumb_256}``) so the frontend can pick the
    # right size for each render context. ``null`` when the user has no
    # avatar or the URL points to an external host.
    avatar: dict | None
    settings: dict

    # Roles + org
    roles: list[str]
    department: str | None
    department_id: int | None
    position: str | None

    # Flags + timestamps
    must_change_password: bool
    date_joined: str | None
    last_login: str | None
    created_at: str | None
    updated_at: str | None


class ChangePasswordRequest(BaseModel):
    """Change-password payload.

    ``current_password`` is required for ordinary voluntary changes. When
    ``User.must_change_password`` is true (admin-forced reset), the current
    password check is relaxed so the blocked user can escape the force-screen.
    """

    new_password: str = Field(..., min_length=8)
    current_password: str | None = None


@router.get("/me", response_model=ProfileResponse)
@router.get("/", response_model=ProfileResponse)
async def get_profile(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Return the current user's profile (frontend-compatible shape)."""
    result = await db.execute(select(User).where(User.id == current_user.user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    log.info("profile_requested", user_id=user.id)
    return _build_response(user)


@router.patch("/me", response_model=ProfileResponse)
@router.patch("/", response_model=ProfileResponse)
async def update_profile(
    request: Request,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    # Profile fields — any combination may be present. Accept both snake_case
    # and camelCase aliases because the frontend mixes both.
    display_name: Annotated[str | None, Form()] = None,
    firstName: Annotated[str | None, Form(alias="firstName")] = None,
    first_name: Annotated[str | None, Form()] = None,
    lastName: Annotated[str | None, Form(alias="lastName")] = None,
    last_name: Annotated[str | None, Form()] = None,
    patronymic: Annotated[str | None, Form()] = None,
    bio: Annotated[str | None, Form()] = None,
    phone: Annotated[str | None, Form()] = None,
    settings_json: Annotated[str | None, Form(alias="settings")] = None,
    avatar: Annotated[UploadFile | None, File()] = None,
):
    """Patch the current user's profile.

    Content-Type: multipart/form-data (the frontend sends FormData so it can
    optionally attach an avatar file). When ``avatar`` is present, the file is
    forwarded to media-service via an S2S JWT (``SERVICE_JWT_SECRET``) and the
    returned download URL is persisted to ``user.avatar_url``.
    """
    # Avatar upload: forward to media-service with an S2S JWT + X-User-Id header.
    # Pass scope=avatar so media-service applies the avatar policy (forces
    # is_public=true so <img> can render without an Authorization header).
    #
    # Done FIRST, before opening any DB work: holding the request's pooled
    # asyncpg connection across this multipart upload stalls the httpx call
    # until it times out (asyncpg + httpx event-loop interaction on Python
    # 3.14) and surfaces as a false "media-service unavailable" 502. Since the
    # upload only needs ``current_user.user_id``, we run it before the first
    # query so no DB connection is checked out yet.
    new_url: str | None = None
    if avatar is not None and avatar.filename:
        data = await avatar.read()
        token = issue_service_token()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{settings.media_service_url}/api/media/v1/files/",
                    files={
                        "file": (
                            avatar.filename,
                            data,
                            avatar.content_type or "application/octet-stream",
                        ),
                    },
                    data={
                        "scope": "avatar",
                        "is_public": "true",
                    },
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-User-Id": str(current_user.user_id),
                    },
                )
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.error(
                "avatar_upload_failed",
                user_id=current_user.user_id,
                error=repr(exc),
                status=getattr(getattr(exc, "response", None), "status_code", None),
            )
            raise HTTPException(
                status_code=502,
                detail="Avatar upload failed (media-service unavailable)",
            )

        body = resp.json()
        # media-service returns computed `url` plus `id`/`path`.
        new_url = body.get("url") or f"/api/media/v1/files/{body['id']}"

    result = await db.execute(select(User).where(User.id == current_user.user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    changes: dict = {}

    # Name fields — coalesce camelCase aliases, then diff against current values.
    effective_first = firstName if firstName is not None else first_name
    effective_last = lastName if lastName is not None else last_name

    for field, value in [
        ("display_name", display_name),
        ("first_name", effective_first),
        ("last_name", effective_last),
        ("patronymic", patronymic),
        ("bio", bio),
        ("phone", phone),
    ]:
        if value is not None and getattr(user, field, None) != value:
            changes[field] = {"from": getattr(user, field, None), "to": value}
            setattr(user, field, value)

    if settings_json is not None:
        try:
            parsed = json.loads(settings_json) if settings_json else {}
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="settings must be valid JSON")
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="settings must be a JSON object")
        if parsed != (user.settings or {}):
            changes["settings"] = "updated"
            user.settings = parsed

    if new_url is not None:
        changes["avatar_url"] = {"from": user.avatar_url, "to": new_url}
        user.avatar_url = new_url

    if changes:
        await db.flush()

    await db.commit()
    await db.refresh(user)

    # Notify downstream replicas (messenger, task, HR) whenever a field that
    # they mirror has changed. Avatar updates are the obvious case but name /
    # status / display_name also matter for the chat user list rendering.
    if changes:
        try:
            user_upserted.send(_replica_payload(user))
        except Exception as exc:  # noqa: BLE001
            # Dramatiq broker is configured but Redis may flap — never let it
            # break the user-facing profile update.
            log.warning("profile_replica_publish_failed", user_id=user.id, err=str(exc))

    log.info(
        "profile_updated",
        user_id=user.id,
        fields=list(changes.keys()),
        via_multipart=True,
    )
    return _build_response(user)


@router.delete("/avatar", status_code=204)
@router.delete("/avatar/", status_code=204)
async def remove_avatar(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    """Remove the user's avatar.

    Soft-deletes the underlying media file (if it lives on the media-service)
    and clears ``user.avatar_url``. Failures from media-service are logged
    but don't prevent the user-facing detach — the file will be reaped by
    ``purge_soft_deleted`` later either way.
    """
    result = await db.execute(select(User).where(User.id == current_user.user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    previous = user.avatar_url
    if previous:
        m = _FILE_ID_RE.search(previous)
        if m:
            file_id = m.group(1)
            token = issue_service_token()
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.delete(
                        f"{settings.media_service_url}/api/media/v1/files/{file_id}",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "X-User-Id": str(user.id),
                        },
                    )
                    # 204 / 404 both fine — nothing left to clean up either way.
                    if resp.status_code not in (204, 404):
                        log.warning(
                            "avatar_delete_unexpected_status",
                            user_id=user.id,
                            file_id=file_id,
                            status=resp.status_code,
                        )
            except httpx.HTTPError as exc:
                log.warning(
                    "avatar_delete_media_unreachable",
                    user_id=user.id,
                    file_id=file_id,
                    error=repr(exc),
                )

    user.avatar_url = None
    await db.commit()
    await db.refresh(user)
    # Same broadcast as on PATCH — replicas need the NULL avatar_url to wipe
    # the cached photo, otherwise the chat header / employee card keeps showing
    # the deleted image until the next unrelated upsert.
    try:
        user_upserted.send(_replica_payload(user))
    except Exception as exc:  # noqa: BLE001
        log.warning("avatar_remove_replica_publish_failed", user_id=user.id, err=str(exc))
    log.info("avatar_removed", user_id=user.id)


@router.post("/change-password", status_code=200)
@router.post("/change-password/", status_code=200)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, str]:
    """Change the current user's password.

    If ``must_change_password`` flag is set (forced reset), ``current_password``
    is optional; otherwise it must match the stored hash.
    """
    result = await db.execute(select(User).where(User.id == current_user.user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if not user.must_change_password:
        if not payload.current_password or not verify_password(
            payload.current_password, user.password_hash
        ):
            log.info("password_change_rejected", user_id=user.id, reason="wrong_current")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect",
            )

    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    await db.commit()

    log.info(
        "password_changed",
        user_id=user.id,
        forced=not bool(payload.current_password),
    )
    return {"detail": "Password changed successfully"}

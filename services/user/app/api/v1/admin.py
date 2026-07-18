"""
Admin endpoints — user management by admins.

Replaces Django's AdminUserViewSet.
"""

from typing import Annotated, Any

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.core.settings import settings
from app.db import get_db_session
from app.models.user import User, UserStatus
from app.services.auth_service import hash_password
from app.services.service_tokens import issue_service_token
from app.workers.actors import user_deactivated, user_deleted, user_upserted


log = structlog.get_logger(__name__)


def _replica_payload(user: User) -> dict:
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


router = APIRouter(prefix="/api/users/v1/admin/users", tags=["admin-users"])


class AdminUserResponse(BaseModel):
    id: int
    username: str
    email: str
    # Name fields — both snake_case (DB) and camelCase (frontend wire format).
    first_name: str
    last_name: str
    firstName: str
    lastName: str
    patronymic: str
    display_name: str
    bio: str
    phone: str
    avatar_url: str | None
    avatarUrl: str | None
    settings: dict
    roles: list[str]
    status: str
    is_staff: bool
    is_superuser: bool
    must_change_password: bool
    date_joined: str
    last_login: str | None
    created_at: str | None
    updated_at: str | None


class AdminUserUpdateRequest(BaseModel):
    # Identity (admin can rename — HR rare-but-needed case).
    username: str | None = None
    email: str | None = None
    # Role / status flags
    is_staff: bool | None = None
    is_superuser: bool | None = None
    status: str | None = None
    must_change_password: bool | None = None
    # Profile fields — admins can edit on a user's behalf (HR /hr/profiles).
    display_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    patronymic: str | None = None
    bio: str | None = None
    phone: str | None = None
    avatar_url: str | None = None
    settings: dict | str | None = None  # JSON object or stringified JSON


class AdminUserCreateRequest(BaseModel):
    """Manual user creation by an admin — bypasses self-registration approval."""
    username: str = Field(..., min_length=1, max_length=150)
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=8)
    first_name: str = ""
    last_name: str = ""
    patronymic: str = ""
    display_name: str = ""
    bio: str = ""
    phone: str = ""
    status: str = "active"
    is_staff: bool = False
    is_superuser: bool = False
    # Default ON: admin sets a temp password, user changes it on first login.
    must_change_password: bool = True

    # ── Mailcow mailbox provisioning (optional) ──────────────────────────
    # When `create_mailbox` is true, a corporate mailbox is created via
    # email-service after the user row is committed. Empty fields are
    # auto-generated:
    #   local_part="" → "i.ivanov" from first_name + last_name (transliterated)
    #   password=""   → strong random, returned ONCE in `mailbox.generated_password`
    create_mailbox: bool = False
    mailbox_local_part: str = ""
    mailbox_password: str = ""
    mailbox_quota_mb: int = 0  # 0 = use email-service default


class AdminSetPasswordRequest(BaseModel):
    """Admin-initiated password reset — does not require the user's old password."""
    new_password: str = Field(..., min_length=8)
    must_change_password: bool = True


class MailboxInfo(BaseModel):
    """Echoed back from email-service after `POST /api/email/v1/mailboxes/`."""
    id: int
    address: str
    status: str
    generated_password: str | None = None


class AdminUserCreatedResponse(AdminUserResponse):
    """Same as AdminUserResponse + optional mailbox info from email-service.

    `mailbox` is None when the admin didn't ask for one, or when
    provisioning hit an error (the user row is still created — failures
    surface in `mailbox_error` so the admin can retry from the mailboxes UI).
    """
    mailbox: MailboxInfo | None = None
    mailbox_error: str | None = None


async def _archive_user_mailbox(user_id: int) -> str | None:
    """Archive (stage-1) the user's corporate mailbox via the email-service.

    Returns ``None`` on success or skip (no mailbox); a string on error.
    """
    if not settings.email_service_url:
        return None  # email-service not configured — nothing to archive
    token = issue_service_token(extra_claims={"user_id": user_id})
    headers = {"Authorization": f"Bearer {token}"}
    base = settings.email_service_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Look up the mailbox row by user_id.
            resp = await client.get(
                f"{base}/api/email/v1/mailboxes/?user_id={user_id}",
                headers=headers,
            )
            if resp.status_code == 404:
                return None  # no mailbox for this user
            resp.raise_for_status()
            rows = resp.json()
            mailbox_id = None
            if isinstance(rows, list):
                for row in rows:
                    if row.get("user_id") == user_id and row.get("status") == "active":
                        mailbox_id = row.get("id")
                        break
            if mailbox_id is None:
                return None
            archive = await client.post(
                f"{base}/api/email/v1/mailboxes/{mailbox_id}/archive/",
                headers=headers,
            )
            if archive.status_code >= 400:
                return f"archive {archive.status_code}: {archive.text[:200]}"
        return None
    except httpx.HTTPError as exc:
        return f"email-service unreachable: {exc}"


async def _provision_mailbox(
    *, user: User, payload: AdminUserCreateRequest,
) -> tuple[MailboxInfo | None, str | None]:
    """Call email-service to create a mailbox. Returns (info, error)."""
    if not settings.email_service_url:
        return None, "email_service_url not configured"
    token = issue_service_token(extra_claims={"user_id": user.id})
    body: dict[str, Any] = {
        "user_id": user.id,
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "full_name": user.display_name or f"{user.first_name} {user.last_name}".strip(),
        "must_change_password": payload.must_change_password,
    }
    if payload.mailbox_local_part:
        body["local_part"] = payload.mailbox_local_part
    if payload.mailbox_password:
        body["password"] = payload.mailbox_password
    if payload.mailbox_quota_mb:
        body["quota_mb"] = payload.mailbox_quota_mb

    url = f"{settings.email_service_url.rstrip('/')}/api/email/v1/mailboxes/"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=body, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code >= 400:
            detail = resp.json().get("detail", resp.text) if resp.content else resp.reason_phrase
            log.error("mailbox_provision_failed", user_id=user.id, status=resp.status_code, detail=detail)
            return None, f"email-service {resp.status_code}: {detail}"
        data = resp.json()
        return (
            MailboxInfo(
                id=data["id"],
                address=data["address"],
                status=data["status"],
                generated_password=data.get("generated_password"),
            ),
            None,
        )
    except httpx.HTTPError as exc:
        log.error("mailbox_provision_unreachable", user_id=user.id, error=repr(exc))
        return None, f"email-service unreachable: {exc}"


def _admin_user_response(user: User) -> "AdminUserResponse":
    first_name = user.first_name or ""
    last_name = user.last_name or ""
    roles: list[str] = []
    if user.is_superuser:
        roles.append("admin")
    if user.is_staff and not user.is_superuser:
        roles.append("staff")
    if not roles:
        roles.append("user")
    return AdminUserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        first_name=first_name,
        last_name=last_name,
        firstName=first_name,
        lastName=last_name,
        patronymic=user.patronymic or "",
        display_name=user.display_name or "",
        bio=user.bio or "",
        phone=user.phone or "",
        avatar_url=user.avatar_url,
        avatarUrl=user.avatar_url,
        settings=user.settings or {},
        roles=roles,
        status=user.status.value if isinstance(user.status, UserStatus) else str(user.status),
        is_staff=user.is_staff,
        is_superuser=user.is_superuser,
        must_change_password=bool(user.must_change_password),
        date_joined=user.date_joined.isoformat() if user.date_joined else "",
        last_login=user.last_login.isoformat() if user.last_login else None,
        created_at=user.created_at.isoformat() if user.created_at else None,
        updated_at=user.updated_at.isoformat() if user.updated_at else None,
    )


@router.get("/", response_model=list[AdminUserResponse])
async def list_users(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """
    List all users (admin view).
    Requires: staff or superuser.
    """
    if not current_user.is_staff and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    result = await db.execute(select(User).order_by(User.date_joined.desc()))
    users = result.scalars().all()

    return [_admin_user_response(u) for u in users]


@router.post("/", response_model=AdminUserCreatedResponse, status_code=201)
async def create_user(
    request: AdminUserCreateRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Create a new user manually (admin panel).

    Differs from self-registration: admin chooses the status (default ACTIVE)
    and may set role flags upfront. Username and email must be unique.
    """
    if not current_user.is_staff and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    email_norm = request.email.strip().lower()
    username_norm = request.username.strip()

    # Uniqueness — check both columns explicitly so the error message is clear.
    existing_email = await db.execute(select(User).where(User.email == email_norm))
    if existing_email.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already in use")

    existing_username = await db.execute(select(User).where(User.username == username_norm))
    if existing_username.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already in use")

    try:
        status_enum = UserStatus(request.status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {request.status}")

    user = User(
        username=username_norm,
        email=email_norm,
        password_hash=hash_password(request.password),
        first_name=request.first_name,
        last_name=request.last_name,
        patronymic=request.patronymic,
        display_name=request.display_name or f"{request.first_name} {request.last_name}".strip(),
        bio=request.bio,
        phone=request.phone,
        status=status_enum,
        is_staff=request.is_staff,
        is_superuser=request.is_superuser,
        must_change_password=request.must_change_password,
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    if user.status == UserStatus.ACTIVE:
        user_upserted.send(_replica_payload(user))

    log.info(
        "admin_user_created",
        user_id=user.id,
        email=user.email,
        created_by=current_user.user_id,
    )

    # Optional mailbox provisioning. Best-effort: failures don't roll back
    # the user — the admin sees the error and can retry from the mailboxes UI.
    mailbox_info: MailboxInfo | None = None
    mailbox_error: str | None = None
    if request.create_mailbox:
        mailbox_info, mailbox_error = await _provision_mailbox(user=user, payload=request)

    base = _admin_user_response(user)
    return AdminUserCreatedResponse(
        **base.model_dump(),
        mailbox=mailbox_info,
        mailbox_error=mailbox_error,
    )


@router.patch("/{user_id}/", response_model=AdminUserResponse)
async def update_user(
    user_id: int,
    request: AdminUserUpdateRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """
    Update user admin settings.
    Requires: staff or superuser.
    """
    if not current_user.is_staff and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    import json as _json

    update_data = request.model_dump(exclude_unset=True)

    # Normalise + uniqueness checks for identity columns before applying.
    new_email = update_data.get("email")
    if new_email is not None:
        new_email = new_email.strip().lower()
        if new_email != user.email:
            dupe = await db.execute(select(User).where(User.email == new_email, User.id != user.id))
            if dupe.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="Email already in use")
        update_data["email"] = new_email

    new_username = update_data.get("username")
    if new_username is not None:
        new_username = new_username.strip()
        if new_username != user.username:
            dupe = await db.execute(select(User).where(User.username == new_username, User.id != user.id))
            if dupe.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="Username already in use")
        update_data["username"] = new_username

    for field, value in update_data.items():
        if field == "status" and value:
            setattr(user, field, UserStatus(value))
        elif field == "settings" and value is not None:
            # Accept either a dict or a JSON-encoded string for forward-compat
            # with the HR profile editor that posts the field as a string.
            if isinstance(value, str):
                try:
                    parsed = _json.loads(value) if value else {}
                except _json.JSONDecodeError:
                    raise HTTPException(status_code=400, detail="settings must be valid JSON")
                if not isinstance(parsed, dict):
                    raise HTTPException(status_code=400, detail="settings must be a JSON object")
                user.settings = parsed
            else:
                user.settings = value
        else:
            setattr(user, field, value)

    await db.commit()
    await db.refresh(user)

    if user.status == UserStatus.ACTIVE:
        user_upserted.send(_replica_payload(user))
    else:
        user_deactivated.send({"id": user.id})

    return _admin_user_response(user)


@router.post("/{user_id}/set-password/", status_code=200)
async def admin_set_password(
    user_id: int,
    request: AdminSetPasswordRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, str]:
    """Admin-initiated password reset — bypasses current-password check.

    Pairs with `must_change_password=True` so the target user is forced through
    the change-password screen on next login (see ForcePasswordChange).
    """
    if not current_user.is_staff and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = hash_password(request.new_password)
    user.must_change_password = request.must_change_password
    await db.commit()

    log.info(
        "admin_password_reset",
        user_id=user.id,
        reset_by=current_user.user_id,
        force_change=request.must_change_password,
    )
    return {"detail": "Password updated"}


@router.delete("/{user_id}/", status_code=204)
async def delete_user(
    user_id: int,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    """Soft-delete a user + start the cascade.

    Two-stage delete (mirrors the mailbox lifecycle):
      * **Stage 1 (this endpoint)** — flip ``status=SUSPENDED`` so the user
        can no longer log in, archive the corporate mailbox via the
        email-service S2S call, publish ``user.deleted`` so the email
        scheduler kicks off the 30-day purge clock for personal accounts.
      * **Stage 2 (background)** — the email-service scheduler runs
        ``final_purge_archived_mailboxes`` daily and hard-deletes mailboxes
        whose ``archived_at`` is older than ``MAILBOX_PURGE_AFTER_DAYS``.

    Refusing self-delete is intentional — admins must use another admin
    account to remove a colleague.
    """
    if not current_user.is_staff and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin access required")
    if int(current_user.user_id) == int(user_id):
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Stage 1A: archive the mailbox synchronously so the operator gets a
    # clear failure if email-service is down.
    err = await _archive_user_mailbox(user.id)
    if err:
        log.warning("user_delete_mailbox_archive_failed", user_id=user.id, err=err)

    # Stage 1B: soft-delete the user row.
    from datetime import datetime, timezone
    user.status = UserStatus.SUSPENDED
    user.is_staff = False
    user.is_superuser = False
    await db.commit()

    deleted_at = datetime.now(timezone.utc).isoformat()
    user_deactivated.send({"id": user.id})
    user_deleted.send({
        "id": user.id,
        "email": user.email,
        "deleted_at": deleted_at,
    })
    log.info("user_deleted", user_id=user.id, by=current_user.user_id)

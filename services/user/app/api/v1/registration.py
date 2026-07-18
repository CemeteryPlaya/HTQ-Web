"""
Registration endpoints — user self-registration with admin approval.

Replaces Django's RegisterView and PendingRegistrationViewSet.
"""

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db import get_db_session
from app.models.user import User, UserStatus
from app.services.auth_service import hash_password
from app.workers.actors import user_deactivated, user_upserted


def _replica_payload(user: User) -> dict:
    """Shape used for `user.upserted` Redis events.

    Mirrors columns expected by ChatUserReplica + task.users replicas. Keep in
    sync with services/<svc>/app/workers/replica_sync.py when adding fields.
    """
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


router = APIRouter(prefix="/api/users/v1", tags=["registration"])


class RegisterRequest(BaseModel):
    """Self-registration request."""
    email: str
    password: str
    full_name: str  # Will be split into first_name + last_name


class RegisterResponse(BaseModel):
    id: int
    email: str
    message: str = "Registration submitted. Awaiting admin approval."


class PendingUserResponse(BaseModel):
    id: int
    email: str
    username: str
    full_name: str
    date_joined: str


@router.post("/register/", response_model=RegisterResponse, status_code=201)
async def register(
    request: RegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """
    Register a new user account.
    User is created with status=PENDING — requires admin approval.

    Replaces Django's RegisterView + RegisterSerializer.
    """
    # Check if email already exists
    existing = await db.execute(select(User).where(User.email == request.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Split full_name into first/last
    name_parts = request.full_name.strip().split(maxsplit=1)
    first_name = name_parts[0] if len(name_parts) > 0 else ""
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    # Generate username from email (same as Django behavior)
    username = request.email.lower()

    user = User(
        username=username,
        email=request.email.lower(),
        password_hash=hash_password(request.password),
        first_name=first_name,
        last_name=last_name,
        display_name=request.full_name.strip(),
        status=UserStatus.PENDING,
    )

    db.add(user)
    await db.flush()
    await db.refresh(user)

    log.info("user_registered", user_id=user.id, email=user.email, username=user.username)

    return RegisterResponse(
        id=user.id,
        email=user.email,
    )


@router.get("/pending-registrations/", response_model=list[PendingUserResponse])
async def list_pending(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """
    List all pending registrations (awaiting approval).
    Requires: staff or superuser.
    """
    if not current_user.is_staff and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    result = await db.execute(
        select(User)
        .where(User.status == UserStatus.PENDING)
        .order_by(User.date_joined)
    )
    users = result.scalars().all()

    return [
        PendingUserResponse(
            id=u.id,
            email=u.email,
            username=u.username,
            full_name=u.display_name or f"{u.first_name} {u.last_name}".strip(),
            date_joined=u.date_joined.isoformat(),
        )
        for u in users
    ]


@router.post("/pending-registrations/{user_id}/approve/", status_code=204)
async def approve_registration(
    user_id: int,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """
    Approve a pending registration — user can now login.

    Replaces PendingRegistrationViewSet.approve().
    """
    if not current_user.is_staff and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    result = await db.execute(
        select(User).where(User.id == user_id, User.status == UserStatus.PENDING)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pending registration not found",
        )

    user.status = UserStatus.ACTIVE
    await db.commit()
    await db.refresh(user)

    user_upserted.send(_replica_payload(user))

    log.info(
        "user_approved",
        user_id=user.id,
        email=user.email,
        approved_by=current_user.user_id,
    )


@router.post("/pending-registrations/{user_id}/reject/", status_code=204)
async def reject_registration(
    user_id: int,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """
    Reject a pending registration — user is marked as rejected.

    Replaces PendingRegistrationViewSet.reject().
    """
    if not current_user.is_staff and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    result = await db.execute(
        select(User).where(User.id == user_id, User.status == UserStatus.PENDING)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pending registration not found",
        )

    user.status = UserStatus.REJECTED
    await db.commit()

    user_deactivated.send({"id": user.id})

    log.info(
        "user_rejected",
        user_id=user.id,
        email=user.email,
        rejected_by=current_user.user_id,
    )

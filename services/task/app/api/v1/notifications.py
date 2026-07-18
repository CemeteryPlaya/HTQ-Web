"""Notification API endpoints.

Two shapes are exposed:

- ``GET /notifications/``         — flat list (legacy), used by the bell
                                    dropdown. Returns the 50 newest rows.
- ``GET /notifications/history/`` — paginated history, filterable by
                                    read state and target type. Powers
                                    the dedicated ``/notifications`` SPA
                                    page.
"""

from datetime import datetime, timezone
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.auth.dependencies import get_current_user
from app.models.notification import Notification
from app.models.task import Task
from app.models.user_replica import User as UserReplica
from app.schemas.notification import NotificationResponse, NotificationsPage

router = APIRouter(prefix="/notifications", tags=["notifications"])


async def _hydrate(
    db: AsyncSession, rows: list[Notification]
) -> list[NotificationResponse]:
    """Attach actor_name + task_key denormalized fields to each row.

    Done in two batched queries: the per-row lookup would be O(N) over
    pgbouncer. Notifications with NULL actor / unknown task keep the
    fields as ``None``.
    """
    if not rows:
        return []

    actor_ids = {r.actor_id for r in rows if r.actor_id}
    actor_names: dict[int, str] = {}
    actor_avatars: dict[int, str | None] = {}
    if actor_ids:
        actor_rows = await db.execute(
            select(UserReplica).where(UserReplica.id.in_(actor_ids))
        )
        for u in actor_rows.scalars().all():
            actor_names[u.id] = (
                f"{u.first_name} {u.last_name}".strip() or u.username
            )
            actor_avatars[u.id] = u.avatar_url

    # Tasks come either through the legacy FK column or via target_type='task'.
    task_ids: set[int] = set()
    for r in rows:
        if r.task_id:
            task_ids.add(r.task_id)
        if r.target_type == "task" and r.target_id:
            task_ids.add(r.target_id)
    task_keys: dict[int, str] = {}
    if task_ids:
        task_rows = await db.execute(
            select(Task.id, Task.key).where(Task.id.in_(task_ids))
        )
        for tid, tkey in task_rows.all():
            task_keys[tid] = tkey

    out: list[NotificationResponse] = []
    for r in rows:
        effective_task_id = r.task_id or (
            r.target_id if r.target_type == "task" else None
        )
        # Prefer the snapshot captured at write time (migration 011) so the
        # toast renders the actor's photo even when the task_users replica
        # hasn't caught up yet. Fall back to the replica row only for older
        # notifications that were created before the snapshot column existed.
        snapshot = getattr(r, "actor_avatar_url", None)
        avatar = snapshot or (actor_avatars.get(r.actor_id) if r.actor_id else None)
        out.append(
            NotificationResponse(
                id=r.id,
                recipient_id=r.recipient_id,
                actor_id=r.actor_id,
                actor_name=actor_names.get(r.actor_id) if r.actor_id else None,
                actor_avatar_url=avatar,
                verb=r.verb,
                task_id=r.task_id,
                task_key=task_keys.get(effective_task_id)
                if effective_task_id
                else None,
                target_type=r.target_type,
                target_id=r.target_id,
                is_read=r.is_read,
                read_at=r.read_at,
                created_at=r.created_at,
            )
        )
    return out


@router.get("/", response_model=list[NotificationResponse])
async def list_notifications(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: dict = Depends(get_current_user),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Latest notifications for the bell dropdown.

    Kept flat (no pagination envelope) for backwards compatibility with
    the existing ``NotificationsViewer`` component.
    """
    user_id = current_user.user_id
    stmt = (
        select(Notification)
        .where(Notification.recipient_id == user_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    return await _hydrate(db, rows)


@router.get("/history/", response_model=NotificationsPage)
async def list_notification_history(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: dict = Depends(get_current_user),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
    status: Literal["all", "unread", "read"] = "all",
    target_type: Optional[str] = None,
):
    """Paginated notification history with optional filters."""
    user_id = current_user.user_id

    base = select(Notification).where(Notification.recipient_id == user_id)
    if status == "unread":
        base = base.where(Notification.is_read.is_(False))
    elif status == "read":
        base = base.where(Notification.is_read.is_(True))
    if target_type:
        base = base.where(Notification.target_type == target_type)

    # Total + unread_total are computed against the same base — except the
    # unread counter ignores the read-state filter so the header badge
    # stays consistent regardless of the active tab.
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()
    unread_total = (
        await db.execute(
            select(func.count()).where(
                Notification.recipient_id == user_id,
                Notification.is_read.is_(False),
            )
        )
    ).scalar_one()

    rows = list(
        (
            await db.execute(
                base.order_by(Notification.created_at.desc())
                .offset((page - 1) * limit)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    pages = (total + limit - 1) // limit if total else 0
    return NotificationsPage(
        items=await _hydrate(db, rows),
        total=int(total),
        page=page,
        pages=int(pages),
        limit=limit,
        unread_total=int(unread_total),
    )


@router.post("/{notification_id}/mark_read/", status_code=204)
async def mark_notification_read(
    notification_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: dict = Depends(get_current_user),
):
    """Mark a notification as read and stamp ``read_at``."""
    user_id = current_user.user_id
    row = (
        await db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.recipient_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Notification not found")
    if not row.is_read:
        row.is_read = True
        row.read_at = datetime.now(timezone.utc)
        db.add(row)
        await db.commit()


@router.post("/{notification_id}/mark_unread/", status_code=204)
async def mark_notification_unread(
    notification_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: dict = Depends(get_current_user),
):
    """Reset a notification back to unread. Drops ``read_at`` to NULL."""
    user_id = current_user.user_id
    row = (
        await db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.recipient_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Notification not found")
    if row.is_read:
        row.is_read = False
        row.read_at = None
        db.add(row)
        await db.commit()


@router.post("/mark-all-read/", status_code=204)
async def mark_all_notifications_read(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: dict = Depends(get_current_user),
):
    """Mark all unread notifications as read for the caller."""
    user_id = current_user.user_id
    now = datetime.now(timezone.utc)
    await db.execute(
        update(Notification)
        .where(
            Notification.recipient_id == user_id,
            Notification.is_read.is_(False),
        )
        .values(is_read=True, read_at=now)
    )
    await db.commit()


@router.delete("/{notification_id}/", status_code=204)
async def delete_notification(
    notification_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: dict = Depends(get_current_user),
):
    """Remove a notification from history. Caller-scoped."""
    user_id = current_user.user_id
    row = (
        await db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.recipient_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Notification not found")
    await db.delete(row)
    await db.commit()

"""Notifications — the bell dropdown and the history page.

Ported from ``services/task/app/api/v1/notifications.py``. Every read and
write is scoped to ``recipient_id == caller``: a notification is private to
its recipient, so "not yours" and "does not exist" both answer 404 and the
endpoints cannot be used to probe other people's feeds.

``actor_avatar_url`` is the one denormalised field that does NOT come from
``apps.users.interface``: it is a snapshot taken when the row was written.
The original added it so a lagging replica could not blank the toast's
photo; here it survives for a better reason — it is a point-in-time record,
and a later avatar change should not rewrite history. The actor's *name*
still hydrates live, matching the original.
"""

from __future__ import annotations

from django.http import Http404
from django.utils import timezone

from .. import schemas
from ..models import Notification, Task
from . import hydration


def _hydrate(rows: list[Notification]) -> list[schemas.NotificationResponse]:
    if not rows:
        return []

    users = hydration.user_briefs([row.actor_id for row in rows])

    # A row points at a task either through the legacy FK or through the
    # generic ``target_type='task'`` pair; both are resolved in one query.
    task_ids: set[int] = set()
    for row in rows:
        if row.task_id:
            task_ids.add(row.task_id)
        if row.target_type == "task" and row.target_id:
            task_ids.add(row.target_id)
    task_keys = dict(Task.objects.filter(id__in=task_ids)
                     .values_list("id", "key")) if task_ids else {}

    out = []
    for row in rows:
        effective_task_id = row.task_id or (
            row.target_id if row.target_type == "task" else None)
        out.append(schemas.NotificationResponse.model_validate({
            "id": row.id,
            "recipient_id": row.recipient_id,
            "actor_id": row.actor_id,
            "actor_name": hydration.user_name(users, row.actor_id),
            # Snapshot first; the live brief carries no avatar today (see the
            # gap documented in services/hydration.py).
            "actor_avatar_url": (row.actor_avatar_url
                                 or hydration.user_avatar(users, row.actor_id)),
            "verb": row.verb,
            "task_id": row.task_id,
            "task_key": task_keys.get(effective_task_id) if effective_task_id
            else None,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "is_read": row.is_read,
            "read_at": row.read_at,
            "created_at": row.created_at,
        }))
    return out


def latest(user_id: int, limit: int = 50) -> list[schemas.NotificationResponse]:
    """Newest first, flat (no pagination envelope) — the bell dropdown's
    shape, kept for backwards compatibility with ``NotificationsViewer``."""
    rows = list(Notification.objects.filter(recipient_id=user_id)
                .order_by("-created_at")[:limit])
    return _hydrate(rows)


def history(user_id: int, *, page: int = 1, limit: int = 25,
            status: str = "all", target_type: str | None = None) -> schemas.NotificationsPage:
    qs = Notification.objects.filter(recipient_id=user_id)
    if status == "unread":
        qs = qs.filter(is_read=False)
    elif status == "read":
        qs = qs.filter(is_read=True)
    if target_type:
        qs = qs.filter(target_type=target_type)

    total = qs.count()
    # The unread counter deliberately ignores the read-state filter so the
    # header badge stays the same number whichever tab is open.
    unread_total = Notification.objects.filter(recipient_id=user_id,
                                               is_read=False).count()
    rows = list(qs.order_by("-created_at")[(page - 1) * limit:page * limit])
    pages = (total + limit - 1) // limit if total else 0
    return schemas.NotificationsPage(
        items=_hydrate(rows), total=total, page=page, pages=pages,
        limit=limit, unread_total=unread_total,
    )


def _own(notification_id: int, user_id: int) -> Notification:
    row = Notification.objects.filter(pk=notification_id,
                                      recipient_id=user_id).first()
    if row is None:
        raise Http404("Notification not found")
    return row


def mark_read(notification_id: int, user_id: int) -> None:
    row = _own(notification_id, user_id)
    if not row.is_read:
        row.is_read = True
        row.read_at = timezone.now()
        row.save(update_fields=["is_read", "read_at", "updated_at"])


def mark_unread(notification_id: int, user_id: int) -> None:
    row = _own(notification_id, user_id)
    if row.is_read:
        row.is_read = False
        row.read_at = None
        row.save(update_fields=["is_read", "read_at", "updated_at"])


def mark_all_read(user_id: int) -> None:
    Notification.objects.filter(recipient_id=user_id, is_read=False).update(
        is_read=True, read_at=timezone.now(), updated_at=timezone.now())


def delete(notification_id: int, user_id: int) -> None:
    _own(notification_id, user_id).delete()

"""Notification schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    """Notification response schema.

    ``target_type`` + ``target_id`` is the canonical "click here" reference.
    The frontend maps the type to a route, so the backend stays free of
    UI knowledge. ``task_key`` is filled when the row references a task
    (legacy ``task_id`` FK OR ``target_type='task'``) so the dropdown can
    show «В задаче: ABC-123» without a second roundtrip.
    """

    id: int
    recipient_id: int
    actor_id: int | None = None
    actor_name: str | None = None
    actor_avatar_url: str | None = None
    verb: str
    task_id: int | None = None
    task_key: str | None = None
    target_type: str | None = None
    target_id: int | None = None
    is_read: bool
    read_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationsPage(BaseModel):
    """Paginated history response."""

    items: list[NotificationResponse]
    total: int
    page: int
    pages: int
    limit: int
    unread_total: int

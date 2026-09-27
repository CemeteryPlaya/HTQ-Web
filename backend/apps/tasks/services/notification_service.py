"""Колокольчик и история — фасад над центром уведомлений (A1.5 модуля БЗО).

Хранит уведомления ``apps.notifications`` (public); этот модуль сохраняет
контракт ручек ``/api/tasks/v1/notifications…``, на который смонтированы
колокольчик и страница истории, и добавляет то, что знает только домен
задач: ключ задачи (``task_key``) и имя актора. Лента на поддомене —
уведомления этой компании плюс общие (без компании).

Каждое чтение и запись ограничены получателем: чужое уведомление и
несуществующее одинаково отвечают 404 — ручки нельзя использовать, чтобы
прощупать чужую ленту.

``actor_avatar_url`` — снимок на момент записи (точка во времени, смена
аватара историю не переписывает); имя актора гидрируется вживую.

``tasks.Notification`` больше не пишется: он остался только источником
переноса (``manage.py notifications_import_tasks --company <slug>``).
"""

from __future__ import annotations

from apps.notifications import interface as notifications
from htqweb.tenancy.context import current_company_or_none

from .. import schemas
from ..models import Task
from . import hydration


def _task_id(row: dict) -> int | None:
    target = row["target_id"] or ""
    return int(target) if row["target_type"] == "task" and target.isdigit() else None


def _hydrate(rows: list[dict]) -> list[schemas.NotificationResponse]:
    if not rows:
        return []
    users = hydration.user_briefs([row["actor_id"] for row in rows])
    task_ids = {tid for tid in (_task_id(row) for row in rows) if tid is not None}
    task_keys = dict(Task.objects.filter(id__in=task_ids)
                     .values_list("id", "key")) if task_ids else {}
    out = []
    for row in rows:
        task_id = _task_id(row)
        out.append(schemas.NotificationResponse.model_validate({
            "id": row["id"],
            "recipient_id": row["recipient_id"],
            "actor_id": row["actor_id"],
            "actor_name": hydration.user_name(users, row["actor_id"]),
            "actor_avatar_url": (row["actor_avatar_url"]
                                 or hydration.user_avatar(users, row["actor_id"])),
            "verb": row["title"],
            "task_id": task_id,
            "task_key": task_keys.get(task_id) if task_id else None,
            "target_type": row["target_type"],
            "target_id": row["target_id"],
            "url": row["url"] or None,
            "is_read": row["is_read"],
            "read_at": row["read_at"],
            "created_at": row["created_at"],
        }))
    return out


def latest(user_id: int, limit: int = 50) -> list[schemas.NotificationResponse]:
    """Newest first, flat (no pagination envelope) — the bell dropdown's
    shape, kept for backwards compatibility with ``NotificationsViewer``."""
    return _hydrate(notifications.latest(user_id, company_slug=current_company_or_none(),
                                         limit=limit))


def history(user_id: int, *, page: int = 1, limit: int = 25,
            status: str = "all", target_type: str | None = None) -> schemas.NotificationsPage:
    # unread_total считается центром без фильтра вкладки — счётчик в шапке
    # один и тот же, какая бы вкладка ни была открыта.
    data = notifications.history(user_id, company_slug=current_company_or_none(),
                                 page=page, limit=limit, status=status,
                                 target_type=target_type)
    return schemas.NotificationsPage(
        items=_hydrate(data["items"]), total=data["total"], page=data["page"],
        pages=data["pages"], limit=data["limit"], unread_total=data["unread_total"])


def mark_read(notification_id: str, user_id: int) -> None:
    notifications.mark_read(notification_id, user_id)


def mark_unread(notification_id: str, user_id: int) -> None:
    notifications.mark_unread(notification_id, user_id)


def mark_all_read(user_id: int) -> None:
    notifications.mark_all_read(user_id, company_slug=current_company_or_none())


def delete(notification_id: str, user_id: int) -> None:
    notifications.delete(notification_id, user_id)

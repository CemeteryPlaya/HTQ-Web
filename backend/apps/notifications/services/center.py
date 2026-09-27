"""Запись, лента и прочтение уведомлений (D-24)."""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone

from apps.notifications.models import Channel, ChannelPrefs, Delivery, Notification
from htqweb.fallback import fallback


def prefs_of(user_id: int) -> ChannelPrefs:
    return ChannelPrefs.objects.filter(user_id=user_id).first() or ChannelPrefs(user_id=user_id)


def serialize(row: Notification) -> dict:
    return {
        "id": str(row.id), "recipient_id": row.recipient_id,
        "company_slug": row.company_slug or None, "event": row.event, "title": row.title,
        "text": row.text, "url": row.url, "target_type": row.target_type or None,
        "target_id": row.target_id or None, "actor_id": row.actor_id,
        "actor_avatar_url": row.actor_avatar_url, "is_read": row.is_read,
        "read_at": row.read_at.isoformat() if row.read_at else None,
        "created_at": row.created_at.isoformat(),
    }


def _enqueue(delivery_ids: list[int]) -> None:
    from apps.notifications.tasks import deliver

    for delivery_id in delivery_ids:
        deliver.delay(delivery_id)


def _realtime(rows: list[Notification]) -> None:
    """Мгновенный показ в колокольчике — best-effort, через Socket.IO."""
    from apps.messenger import interface as messenger

    for row in rows:
        try:
            messenger.dispatch_notification([row.recipient_id], {
                "type": "notification", "id": str(row.id), "title": row.title,
                "url": row.url, "event": row.event})
        except Exception as exc:
            # Мессенджер выключен или недоступен — запись в ленте уже есть,
            # колокольчик покажет её при следующем опросе.
            fallback("notifications.center.realtime_failed", None,
                     reason="мгновенный показ уведомления не удался", exc=exc,
                     expected=True)


def notify(*, recipients, event, title, text="", url="", company_slug=None,
           target_type="", target_id="", actor_id=None, actor_avatar_url=None,
           deliver=True, dedupe_window_seconds=None) -> list[str]:
    """Записать уведомление каждому получателю.

    ``deliver=False`` — только колокольчик, без e-mail/Telegram: так пишет
    лента задач, переехавшая в центр (письмо о каждом сообщении мессенджера
    было бы новым поведением, а не переездом). ``dedupe_window_seconds`` —
    не писать, если такое же уведомление (получатель, актор, заголовок, цель)
    уже есть за это окно; такому получателю id не возвращается.
    """
    rows, deliveries = [], []
    title = title[:255]
    target_type, target_id = target_type or "", str(target_id or "")
    for user_id in dict.fromkeys(int(r) for r in recipients):
        # Компания — часть ключа: id задач и событий у каждой схемы свои, а
        # таблица центра одна на группу.
        if dedupe_window_seconds and Notification.objects.filter(
                recipient_id=user_id, company_slug=company_slug or "",
                actor_id=actor_id, title=title,
                target_type=target_type, target_id=target_id,
                created_at__gte=timezone.now() - timedelta(seconds=dedupe_window_seconds),
        ).exists():
            continue
        prefs = prefs_of(user_id)
        row = Notification.objects.create(
            recipient_id=user_id, company_slug=company_slug or "", event=event,
            title=title, text=text, url=url, target_type=target_type,
            target_id=target_id, actor_id=actor_id,
            actor_avatar_url=actor_avatar_url,
            # Колокольчик выключен — запись создаётся прочитанной и в ленту
            # не попадает (фильтр bell ниже): источник для e-mail/Telegram нужен.
            is_read=not prefs.bell, read_at=None if prefs.bell else timezone.now(),
        )
        rows.append(row)
        for channel, enabled in ((Channel.EMAIL, prefs.email), (Channel.TELEGRAM, prefs.telegram)):
            if deliver and enabled:
                deliveries.append(Delivery.objects.create(notification=row, channel=channel).id)
    transaction.on_commit(lambda: (_enqueue(deliveries), _realtime([r for r in rows])))
    return [str(r.id) for r in rows]


def unread_pairs(*, target_type: str, target_ids: list[str], recipient_ids: list[int],
                 company_slug: str | None) -> set[tuple[str, int]]:
    """Пары ``(target_id, recipient_id)`` с непрочитанным уведомлением о цели
    в этой компании — дедупликация напоминаний (``tasks.calendar_event_reminder``).
    Компания обязательна: id целей у каждой схемы свои."""
    return set(Notification.objects.filter(
        company_slug=company_slug or "",
        target_type=target_type, target_id__in=[str(i) for i in target_ids],
        recipient_id__in=recipient_ids, is_read=False,
    ).values_list("target_id", "recipient_id"))


def _feed(user_id: int, company_slug: str | None):
    rows = Notification.objects.filter(recipient_id=user_id)
    rows = rows.filter(Q(company_slug=company_slug or "") | Q(company_slug=""))
    if not prefs_of(user_id).bell:
        return rows.none()
    return rows


def latest(user_id: int, *, company_slug: str | None, limit: int = 50) -> list[dict]:
    return [serialize(r) for r in _feed(user_id, company_slug).order_by("-created_at")[:limit]]


def history(user_id: int, *, company_slug, page=1, limit=25, status="all",
            target_type=None) -> dict:
    feed = _feed(user_id, company_slug)
    rows = feed
    if status == "unread":
        rows = rows.filter(is_read=False)
    elif status == "read":
        rows = rows.filter(is_read=True)
    if target_type:
        rows = rows.filter(target_type=target_type)
    total = rows.count()
    items = rows.order_by("-created_at")[(page - 1) * limit:page * limit]
    return {"items": [serialize(r) for r in items], "total": total, "page": page,
            "pages": (total + limit - 1) // limit if total else 0, "limit": limit,
            "unread_total": feed.filter(is_read=False).count()}


def _own(notification_id: str, user_id: int) -> Notification:
    row = Notification.objects.filter(pk=notification_id, recipient_id=user_id).first()
    if row is None:
        raise Http404("Notification not found")
    return row


def mark_read(notification_id: str, user_id: int) -> None:
    row = _own(notification_id, user_id)
    if not row.is_read:
        row.is_read, row.read_at = True, timezone.now()
        row.save(update_fields=["is_read", "read_at"])


def mark_unread(notification_id: str, user_id: int) -> None:
    row = _own(notification_id, user_id)
    row.is_read, row.read_at = False, None
    row.save(update_fields=["is_read", "read_at"])


def mark_all_read(user_id: int, *, company_slug: str | None) -> None:
    _feed(user_id, company_slug).filter(is_read=False).update(is_read=True,
                                                               read_at=timezone.now())


def delete(notification_id: str, user_id: int) -> None:
    _own(notification_id, user_id).delete()

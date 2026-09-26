"""Доставка уведомления по каналу: e-mail и Telegram, с повтором (outbox).

Состояние ``sent`` проверяется первым: повторный запуск задачи (брокер
доставил её дважды) письма не дублирует. Сбой — ``RetryLater``: задача
Celery повторит с паузой; после ``MAX_ATTEMPTS`` — ``failed`` и строка
``FALLBACK`` в лог (алерт ``htqweb-fallback-worker-logs``).
"""

from __future__ import annotations

import httpx
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from apps.notifications.models import Delivery, DeliveryState, TelegramLink
from apps.users import interface as users
from htqweb.fallback import fallback

MAX_ATTEMPTS = 5


class RetryLater(Exception):
    pass


def _absolute(url: str) -> str:
    base = getattr(settings, "PUBLIC_BASE_URL", "").rstrip("/")
    return f"{base}{url}" if url.startswith("/") and base else url


def _send_email(item: Delivery) -> bool:
    briefs = users.get_users_brief([item.notification.recipient_id])
    email = briefs[0]["email"] if briefs else ""
    if not email:
        return False
    note = item.notification
    body = "\n\n".join(part for part in (note.title, note.text, _absolute(note.url)) if part)
    send_mail(note.title, body, None, [email], fail_silently=False)
    return True


def _send_telegram(item: Delivery) -> bool:
    token = getattr(settings, "NOTIFY_TELEGRAM_BOT_TOKEN", "")
    link = TelegramLink.objects.filter(user_id=item.notification.recipient_id).exclude(
        chat_id="").first()
    if not token or link is None:
        return False
    note = item.notification
    text = "\n".join(part for part in (note.title, note.text, _absolute(note.url)) if part)
    response = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": link.chat_id, "text": text,
                                "disable_web_page_preview": True}, timeout=10.0)
    response.raise_for_status()
    return True


_SENDERS = {"email": _send_email, "telegram": _send_telegram}


def deliver(delivery_id: int) -> None:
    retry: Exception | None = None
    with transaction.atomic():
        item = (Delivery.objects.select_for_update().select_related("notification")
                .filter(pk=delivery_id).first())
        if item is None or item.state != DeliveryState.PENDING:
            return
        item.attempts += 1
        try:
            sent = _SENDERS[item.channel](item)
        except Exception as exc:
            item.last_error = str(exc)[:1000]
            if item.attempts >= MAX_ATTEMPTS:
                item.state = DeliveryState.FAILED
                item.save(update_fields=["attempts", "last_error", "state"])
                fallback("notifications.delivery.gave_up", None,
                         reason="уведомление не доставлено", exc=exc, expected=True,
                         channel=item.channel)
                return
            # Счётчик и ошибка сохраняются в этой транзакции, а RetryLater
            # поднимается ПОСЛЕ неё: raise внутри atomic() откатил бы save.
            item.save(update_fields=["attempts", "last_error"])
            retry = exc
        else:
            item.state = DeliveryState.SENT if sent else DeliveryState.SKIPPED
            item.sent_at = timezone.now() if sent else None
            item.save(update_fields=["attempts", "state", "sent_at"])
    if retry is not None:
        raise RetryLater(str(retry)) from retry

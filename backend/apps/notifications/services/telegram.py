"""Привязка чата Telegram к учётной записи (Q-E20).

Пользователь жмёт «Подключить Telegram» → получает ссылку на бота с
одноразовым кодом (15 минут) → бот присылает вебхуком ``/start <код>`` →
сохраняем ``chat_id``. Вебхук проверяет секрет Telegram
(``X-Telegram-Bot-Api-Secret-Token``) — без него любой мог бы привязать
свой чат к чужому коду.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.notifications.models import TelegramLink
from htqweb.errors import DomainError

CODE_TTL = timedelta(minutes=15)


def available() -> bool:
    """Бот настроен целиком: токен (отправка), имя (ссылка на бота) и секрет
    вебхука (приём ``/start``). Без любого из трёх привязка не сработает."""
    return all(getattr(settings, name, "") for name in (
        "NOTIFY_TELEGRAM_BOT_TOKEN", "NOTIFY_TELEGRAM_BOT_NAME",
        "NOTIFY_TELEGRAM_WEBHOOK_SECRET"))


def start_link(user_id: int) -> str:
    if not available():
        raise DomainError(
            "E-NTF-03",
            "Telegram-бот портала не настроен — подключить Telegram пока нельзя. "
            "Пользуйтесь колокольчиком и e-mail или обратитесь к администратору.",
            status=503)
    code = secrets.token_urlsafe(12)
    TelegramLink.objects.update_or_create(
        user_id=user_id, defaults={"link_code": code,
                                   "code_expires_at": timezone.now() + CODE_TTL})
    return f"https://t.me/{settings.NOTIFY_TELEGRAM_BOT_NAME}?start={code}"


def secret_ok(header_value: str) -> bool:
    expected = getattr(settings, "NOTIFY_TELEGRAM_WEBHOOK_SECRET", "")
    return bool(expected) and secrets.compare_digest(header_value or "", expected)


def complete_link(update: dict) -> bool:
    message = update.get("message") or {}
    text = (message.get("text") or "").strip()
    chat_id = (message.get("chat") or {}).get("id")
    if not text.startswith("/start ") or chat_id is None:
        return False
    code = text.split(" ", 1)[1].strip()
    link = TelegramLink.objects.filter(link_code=code,
                                       code_expires_at__gt=timezone.now()).first()
    if link is None:
        return False
    link.chat_id, link.link_code, link.linked_at = str(chat_id), "", timezone.now()
    link.save(update_fields=["chat_id", "link_code", "linked_at"])
    return True


def is_linked(user_id: int) -> bool:
    return TelegramLink.objects.filter(user_id=user_id).exclude(chat_id="").exists()

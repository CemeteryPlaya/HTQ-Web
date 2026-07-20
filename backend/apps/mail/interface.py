"""Публичный API аппки mail для ДРУГИХ аппок (контракт PLAN.md §7).

Производитель: Поток A (фаза mail, PLAN.md §6.4). Потребитель: apps.users —
каскад деактивации пользователя (SUSPENDED → архивация почтовых ящиков).
Вызов из users добавляется на интеграции (PLAN.md §8). Прямой импорт
apps.mail.* из другой аппки запрещён (test_app_isolation.py).

Скаффолд-заглушка prep 4.0: сигнатура зафиксирована, тело появится в фазе
mail. Функция начинается с require_service("mail").
"""
from __future__ import annotations

from apps.core.services import require_service

_STUB = "apps.mail.interface: заглушка prep 4.0, реализуется в фазе mail (PLAN.md §6.4)"


def archive_user_mailboxes(user_id: int) -> None:
    require_service("mail")
    raise NotImplementedError(_STUB)

"""Публичный API аппки messenger для ДРУГИХ аппок (контракт PLAN.md §7).

Производитель: Поток A (фаза messenger, PLAN.md §6.5). Потребитель:
apps.approvals (диспатч уведомлений из workflow-движка). Прямой импорт
apps.messenger.* из другой аппки запрещён (test_app_isolation.py) — только
через этот модуль.

Скаффолд-заглушки prep 4.0: сигнатуры зафиксированы (менять только совместно
A↔B), тело появится в фазе messenger. Каждая функция начинается с
require_service("messenger").
"""
from __future__ import annotations

from apps.core.services import require_service

_STUB = "apps.messenger.interface: заглушка prep 4.0, реализуется в фазе messenger (PLAN.md §6.5)"


def dispatch_notification(user_ids: list[int], payload: dict) -> None:
    require_service("messenger")
    raise NotImplementedError(_STUB)


def send_system_message(room_id: int, text: str) -> None:
    require_service("messenger")
    raise NotImplementedError(_STUB)

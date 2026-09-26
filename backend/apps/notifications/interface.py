"""Межаппный интерфейс центра уведомлений (мастер-план §2.6)."""

from __future__ import annotations

from typing import Callable

from apps.core.services import require_service

from .services import center, digest


def notify(*, recipients: list[int], event: str, title: str, text: str = "", url: str = "",
           company_slug: str | None, target_type: str = "", target_id: str = "",
           actor_id: int | None = None, actor_avatar_url: str | None = None,
           deliver: bool = True, dedupe_window_seconds: int | None = None) -> list[str]:
    """Записать уведомление; ``deliver=False`` — только колокольчик,
    ``dedupe_window_seconds`` — без дубля за окно (см. ``services.center.notify``)."""
    require_service("notifications")
    return center.notify(recipients=recipients, event=event, title=title, text=text, url=url,
                         company_slug=company_slug, target_type=target_type,
                         target_id=target_id, actor_id=actor_id,
                         actor_avatar_url=actor_avatar_url, deliver=deliver,
                         dedupe_window_seconds=dedupe_window_seconds)


def unread_pairs(*, target_type: str, target_ids: list[str],
                 recipient_ids: list[int]) -> set[tuple[str, int]]:
    require_service("notifications")
    return center.unread_pairs(target_type=target_type, target_ids=target_ids,
                               recipient_ids=recipient_ids)


def latest(user_id: int, *, company_slug: str | None, limit: int = 50) -> list[dict]:
    require_service("notifications")
    return center.latest(user_id, company_slug=company_slug, limit=limit)


def history(user_id: int, *, company_slug: str | None, page: int = 1, limit: int = 25,
            status: str = "all", target_type: str | None = None) -> dict:
    require_service("notifications")
    return center.history(user_id, company_slug=company_slug, page=page, limit=limit,
                          status=status, target_type=target_type)


def mark_read(notification_id: str, user_id: int) -> None:
    require_service("notifications")
    center.mark_read(notification_id, user_id)


def mark_unread(notification_id: str, user_id: int) -> None:
    require_service("notifications")
    center.mark_unread(notification_id, user_id)


def mark_all_read(user_id: int, *, company_slug: str | None) -> None:
    require_service("notifications")
    center.mark_all_read(user_id, company_slug=company_slug)


def delete(notification_id: str, user_id: int) -> None:
    require_service("notifications")
    center.delete(notification_id, user_id)


def register_digest_source(key: str, fn: Callable[[int], list[dict]], *, tenant: bool) -> None:
    """Зарегистрировать источник ежедневной сводки: ``fn(user_id)`` возвращает
    ``[{title, url, since}]``; ``tenant=True`` — вызывается в контексте каждой
    действующей компании пользователя.

    Зовётся из ``AppConfig.ready()`` источника. ``require_service`` здесь нет
    намеренно: регистрация не трогает БД, а выключенный центр не должен ронять
    старт соседней аппки — сводку гейтит сама задача ``send_daily_digest``.
    """
    digest.register(key, fn, tenant=tenant)

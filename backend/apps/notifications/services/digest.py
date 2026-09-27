"""Ежедневная сводка ожидающих решений (D-23, Q-B21, Q-B30).

Одно сообщение на пользователя со списком «что ждёт вашего решения» —
текст-ссылками. Сроков согласования нет, сводка заменяет эскалацию.

Источники регистрируют сами аппки (``register_digest_source``): центр не
знает ни signoff, ни БЗО, и граф зависимостей идёт от источника к центру.
Тенантный источник вызывается в контексте каждой компании пользователя.
Сломанный источник не останавливает сводку — ``fallback`` и дальше.
"""

from __future__ import annotations

from typing import Callable

from django.conf import settings

from apps.companies import interface as companies
from apps.users import interface as users
from htqweb.fallback import fallback
from htqweb.tenancy.db import use_company

from . import center

_SOURCES: dict[str, tuple[Callable[[int], list[dict]], bool]] = {}


def register(key: str, fn: Callable[[int], list[dict]], *, tenant: bool) -> None:
    _SOURCES[key] = (fn, tenant)


def _recipients() -> list[int]:
    return users.active_user_ids()


def _companies_of(user_id: int) -> list[str]:
    active = set(companies.active_company_slugs())
    return [slug for slug in companies.user_company_slugs(user_id) if slug in active]


def _absolute(url: str, slug: str | None) -> str:
    """Ссылка позиции — абсолютная: в письме и Telegram относительный путь не
    кликабелен. Позиция компании ведёт на её поддомен (там её таблицы),
    общая — на голый домен ``PUBLIC_BASE_URL``."""
    if not url.startswith("/"):
        return url
    base = companies.public_url(slug) if slug else None
    base = base or (getattr(settings, "PUBLIC_BASE_URL", "") or "").rstrip("/")
    return f"{base}{url}" if base else url


def _collect(user_id: int) -> list[dict]:
    items: list[dict] = []
    for key, (fn, tenant) in _SOURCES.items():
        slugs = _companies_of(user_id) if tenant else [None]
        for slug in slugs:
            try:
                if slug is None:
                    got = fn(user_id)
                else:
                    with use_company(slug):
                        got = fn(user_id)
            except Exception as exc:
                fallback("notifications.digest.source_failed", None,
                         reason="источник сводки упал", exc=exc, expected=True, source=key)
                continue
            items.extend({**item, "url": _absolute(item.get("url") or "", slug)}
                         for item in got or [])
    return items


def send() -> int:
    sent = 0
    for user_id in _recipients():
        items = _collect(user_id)
        if not items:
            continue
        lines = [f"• {item['title']} — {item['url']}" for item in items]
        center.notify(recipients=[user_id], event="digest.daily",
                      title=f"Ждут вашего решения: {len(items)}",
                      text="\n".join(lines), url="/signoff", company_slug=None)
        sent += 1
    return sent

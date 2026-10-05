"""Ежедневная сводка ожидающих решений (D-23, Q-B21, Q-B30).

Одно сообщение на пользователя со списком «что ждёт вашего решения» —
текст-ссылками. Сроков согласования нет, сводка заменяет эскалацию.

Источники регистрируют сами аппки (``register_digest_source``): центр не
знает ни signoff, ни БЗО, и граф зависимостей идёт от источника к центру.
Тенантный источник вызывается в контексте каждой компании пользователя.
Сломанный источник не останавливает сводку — ``fallback`` и дальше.

Источник может назвать свой раздел (``section``): его позиции идут в письме
под этим заголовком после позиций без раздела. Так «ждут от вас закрывающих
документов» (БЗО, D-13) не смешиваются с решениями по согласованию.

Позиции без раздела — решения: «Ждут вашего решения: N» (N — число решений),
ссылка ``/signoff``. В сводке из одних разделов решений нет, поэтому заголовок
нейтральный — «Ждут вашего внимания: N» (N — все позиции), а ссылка ведёт на
единственную позицию или на страницу первого раздела (``landing_url``
источника). Ссылка уведомления остаётся относительной, как ``/signoff``: её
открывает SPA по клику в колокольчике, абсолютные ссылки — в тексте.
"""

from __future__ import annotations

from typing import Callable

from django.conf import settings

from apps.companies import interface as companies
from apps.users import interface as users
from htqweb.fallback import fallback
from htqweb.tenancy.db import use_company

from . import center

_SOURCES: dict[str, tuple[Callable[[int], list[dict]], bool, str | None, str]] = {}


def register(key: str, fn: Callable[[int], list[dict]], *, tenant: bool,
             section: str | None = None, landing_url: str = "") -> None:
    _SOURCES[key] = (fn, tenant, section, landing_url)


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
    for key, (fn, tenant, section, landing_url) in _SOURCES.items():
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
            items.extend({**item, "url": _absolute(item.get("url") or "", slug),
                          "path": item.get("url") or "", "section": section,
                          "landing_url": landing_url}
                         for item in got or [])
    return items


def _lines(items: list[dict]) -> list[str]:
    """Текст сводки: сначала позиции без раздела, затем разделы в порядке
    регистрации источников — заголовок и его позиции. Раздел без позиций не
    печатается вовсе."""
    def bullet(item: dict) -> str:
        return f"• {item['title']} — {item['url']}"

    lines = [bullet(item) for item in items if not item.get("section")]
    for heading in dict.fromkeys(item["section"] for item in items if item.get("section")):
        if lines:
            lines.append("")
        lines.append(f"{heading}:")
        lines.extend(bullet(item) for item in items if item.get("section") == heading)
    return lines


def _heading(items: list[dict]) -> tuple[str, str]:
    """Заголовок и ссылка уведомления. Есть решения (позиции без раздела) —
    «Ждут вашего решения» по их числу и ``/signoff``, разделы идут ниже. Одни
    разделы — «Ждут вашего внимания» по всем позициям; ссылка — на
    единственную позицию, иначе на страницу первого раздела."""
    decisions = [item for item in items if not item.get("section")]
    if decisions:
        return f"Ждут вашего решения: {len(decisions)}", "/signoff"
    # Решений нет — первая позиция принадлежит первому разделу письма (_lines).
    # Ссылка колокольчика относительная: у пользователя нескольких компаний
    # она откроется на текущем поддомене — точная ссылка на поддомен
    # компании есть в тексте сводки. Пустой адрес источника — на главную.
    url = (items[0]["path"] if len(items) == 1 else items[0]["landing_url"]) or "/"
    return f"Ждут вашего внимания: {len(items)}", url


def send() -> int:
    sent = 0
    for user_id in _recipients():
        items = _collect(user_id)
        if not items:
            continue
        lines = _lines(items)
        title, url = _heading(items)
        center.notify(recipients=[user_id], event="digest.daily",
                      title=title, text="\n".join(lines), url=url, company_slug=None)
        sent += 1
    return sent

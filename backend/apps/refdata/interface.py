"""Межаппный интерфейс справочников (мастер-план §2.6).

Каждая функция первой строкой зовёт ``require_service("refdata")``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.core.services import require_service

from .services import editing, lookup
from .services.lookup import RefdataMissing  # noqa: F401 — часть контракта

__all__ = ["RefdataMissing", "active_articles", "article_brief", "article_groups", "can_edit",
           "contract_threshold", "country_brief", "exchange_rate", "mrp", "uom_brief",
           "uom_id", "vat_rate"]


def vat_rate(country_code: str, on_date: date) -> Decimal | None:
    require_service("refdata")
    return lookup.vat_rate(country_code, on_date)


def mrp(on_date: date) -> Decimal:
    require_service("refdata")
    return lookup.mrp(on_date)


def contract_threshold(on_date: date) -> Decimal:
    require_service("refdata")
    return lookup.contract_threshold(on_date)


def exchange_rate(currency: str, on_date: date) -> Decimal | None:
    require_service("refdata")
    return lookup.exchange_rate(currency, on_date)


def article_brief(ids: list[str]) -> dict[str, dict]:
    require_service("refdata")
    return lookup.article_brief(ids)


def active_articles(group_code: str) -> list[dict]:
    """Действующие статьи группы (``supply``, ``pm``) по коду — ``[{id, code,
    name}]``; демо-данные модуля БЗО берут статьи отсюда."""
    require_service("refdata")
    return lookup.active_articles(group_code)


def uom_id(code: str) -> str | None:
    """Ключ действующей единицы измерения по коду (``pcs``, ``t``…)."""
    require_service("refdata")
    return lookup.uom_id(code)


def article_groups() -> list[dict]:
    require_service("refdata")
    return lookup.article_groups()


def uom_brief(ids: list[str]) -> dict[str, dict]:
    require_service("refdata")
    return lookup.uom_brief(ids)


def country_brief(codes: list[str]) -> dict[str, dict]:
    require_service("refdata")
    return lookup.country_brief(codes)


def can_edit(user, company_slug: str | None, node: str = "refdata") -> bool:
    require_service("refdata")
    return editing.can_edit(user, company_slug, node)

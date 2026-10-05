"""Межаппный интерфейс справочников (мастер-план §2.6).

Каждая функция первой строкой зовёт ``require_service("refdata")``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.core.services import require_service

from .services import editing, lookup
from .services import production_calendar as calendar
from .services.lookup import RefdataMissing  # noqa: F401 — часть контракта

__all__ = ["RefdataMissing", "active_articles", "add_bank_days", "add_working_days",
           "article_brief", "article_groups", "bank_days_before", "can_edit",
           "contract_threshold", "country_brief", "day_type", "days_between",
           "exchange_rate", "is_bank_day", "is_working_day", "mrp", "production_days",
           "uom_brief", "uom_id", "vat_rate", "working_days_between"]


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


def can_edit(user, company_slug: str | None, node: str = "refdata", *,
             flags: tuple[str, ...] = ("edit", "create")) -> bool:
    require_service("refdata")
    return editing.can_edit(user, company_slug, node, flags=flags)


# ── производственный календарь (A7.1, D-S7-1) ───────────────────────────

def day_type(day: date) -> str:
    """Тип дня с учётом ручных переопределений: working|weekend|holiday|short."""
    require_service("refdata")
    return calendar.day_type(day)


def is_working_day(day: date) -> bool:
    require_service("refdata")
    return calendar.is_working_day(day)


def working_days_between(start: date | None, end: date | None) -> int | None:
    """Рабочие дни отрезка включительно; ``None`` — перевёрнутый отрезок."""
    require_service("refdata")
    return calendar.working_days_between(start, end)


def days_between(start: date | None, end: date | None, *, working: bool) -> int | None:
    """Длительность отрезка: рабочие (``working=True``) или календарные дни."""
    require_service("refdata")
    return calendar.days_between(start, end, working=working)


def add_working_days(start: date, count: int, *, max_count: int = 3650) -> date | None:
    """Дата через ``count`` рабочих дней от ``start`` (сам ``start`` входит)."""
    require_service("refdata")
    return calendar.add_working_days(start, count, max_count=max_count)


def is_bank_day(day: date) -> bool:
    """Банковский день (A7.2, D-S7-7): Пн–Пт без праздников РК, но с днём
    переноса праздника, выпавшего на субботу; перенос с воскресенья — нет."""
    require_service("refdata")
    return calendar.is_bank_day(day)


def add_bank_days(start: date, count: int) -> date:
    """Дата через ``count`` банковских дней после ``start`` (срок оплаты)."""
    require_service("refdata")
    return calendar.add_bank_days(start, count)


def bank_days_before(day: date, count: int) -> date:
    """Дата ``count`` банковских дней назад от ``day`` («банк не подтвердил»)."""
    require_service("refdata")
    return calendar.bank_days_before(day, count)


def production_days(date_from: date, date_to: date) -> list[dict]:
    """Строки календаря ``[{date, day_type, note, working_days_since_epoch}]``."""
    require_service("refdata")
    return calendar.list_production_days(date_from, date_to)

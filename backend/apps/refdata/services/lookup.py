"""Значения справочников на дату — для соседей через ``refdata.interface``."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db.models import Q

from apps.refdata.models import Article, ArticleGroup, Country, ExchangeRate, MrpValue, Uom, VatRate

THRESHOLD_MRP = Decimal("1000")


class RefdataMissing(Exception):
    """В справочнике нет значения на нужную дату."""


def vat_rate(country_code: str, on_date: date) -> Decimal | None:
    row = (VatRate.objects.filter(country_code=country_code, date_from__lte=on_date)
           .filter(Q(date_to__isnull=True) | Q(date_to__gte=on_date))
           .order_by("-date_from").first())
    return row.rate if row else None


def mrp(on_date: date) -> Decimal:
    row = MrpValue.objects.filter(date_from__lte=on_date).order_by("-date_from").first()
    if row is None:
        raise RefdataMissing(f"Нет МРП на {on_date:%d.%m.%Y}")
    return row.value


def contract_threshold(on_date: date) -> Decimal:
    return (THRESHOLD_MRP * mrp(on_date)).quantize(Decimal("0.01"))


def exchange_rate(currency: str, on_date: date) -> Decimal | None:
    if currency == "KZT":
        return Decimal("1")
    row = ExchangeRate.objects.filter(currency_code=currency, on_date=on_date).first()
    return row.rate if row else None


def article_brief(ids: list[str]) -> dict[str, dict]:
    rows = Article.objects.filter(id__in=ids).select_related("group")
    return {str(a.id): {"id": str(a.id), "code": a.code, "name": a.name,
                        "group_id": str(a.group_id), "node_key": a.group.node_key,
                        "is_active": a.is_active} for a in rows}


def active_articles(group_code: str) -> list[dict]:
    rows = Article.objects.filter(group__code=group_code, is_active=True).order_by("code")
    return [{"id": str(a.id), "code": a.code, "name": a.name} for a in rows]


def uom_id(code: str) -> str | None:
    found = Uom.objects.filter(code=code, is_active=True).values_list("id", flat=True).first()
    return str(found) if found else None


def article_groups() -> list[dict]:
    return [{"id": str(g.id), "code": g.code, "name": g.name, "node_key": g.node_key,
             "is_active": g.is_active} for g in ArticleGroup.objects.all()]


def uom_brief(ids: list[str]) -> dict[str, dict]:
    return {str(u.id): {"id": str(u.id), "code": u.code, "short_name": u.short_name,
                        "is_active": u.is_active} for u in Uom.objects.filter(id__in=ids)}


def country_brief(codes: list[str]) -> dict[str, dict]:
    return {c.code: {"code": c.code, "name": c.name, "is_active": c.is_active}
            for c in Country.objects.filter(code__in=codes)}

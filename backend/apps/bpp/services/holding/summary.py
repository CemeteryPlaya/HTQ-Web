"""Сводка группы по БЗО: по каждой компании — лимит утверждённых бюджетов,
счета к оплате и оплаченные, действующие договоры (A8.1, D-S7-8).

Считается агрегатами SQL по представлениям ``holding.*`` (читатели —
``apps/bpp/holding_models.py``, только под ``use_holding()``), а не обходом
компаний. Определения — те же, что у реестров компании, чтобы число сводки
и ``total``/``totals`` реестра по своей ссылке не расходились:

* ``budgets`` — бюджеты со статусом «Утверждён»; ``limit_kzt`` — Σ лимитов
  строк ДЕЙСТВУЮЩЕЙ версии таких бюджетов в тенге (бюджеты в другой валюте в
  сумму не входят и считаются отдельно — ``budgets_other_currency``: суммы в
  разных валютах не складывают);
* ``invoices_to_pay`` — вкладка реестра «К оплате» (статусы «К оплате» и
  «Оплачено частично»): количество и Σ ``amount_kzt``;
* ``invoices_paid`` — «Оплачено»: статусы, подтверждающие оплату («Оплачено»,
  «Ждёт закрывающих», «Документы предоставлены», «Закрыт» —
  ``alternatives.kpi.INVOICE_CONFIRMS``): количество и Σ ``amount_kzt``;
* ``agreements_active`` — договоры «Действует».

«Задействовано» (считается на лету, D-08) в сводку не входит. Счёт без курса
(``amount_kzt`` пуст) в сумму не входит, в количество — входит (как в реестре).
Компания без единой строки остаётся строкой с нулями: список компаний — из
реестра, а не из представлений.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import ProgrammingError, connection
from django.db.models import Count, Q, Sum

from apps.companies import interface as companies
from htqweb.tenancy.context import HOLDING_SCHEMA
from htqweb.tenancy.db import use_holding

from ...holding_models import (
    HoldingAgreement,
    HoldingBudget,
    HoldingBudgetLine,
    HoldingBudgetVersion,
    HoldingInvoice,
)
from ...models import AgreementStatus, BudgetStatus, InvoiceStatus, VersionState

ZERO = Decimal("0.00")
KZT = "KZT"
TO_PAY = (InvoiceStatus.TO_PAY, InvoiceStatus.PARTIALLY_PAID)
PAID = (InvoiceStatus.PAID, InvoiceStatus.AWAITING_DOCS, InvoiceStatus.DOCS_PROVIDED,
        InvoiceStatus.CLOSED)


class HoldingViewsUnavailable(RuntimeError):
    """Представлений холдинга сейчас нет (``migrate_companies`` их сносит) —
    ручка отвечает 503, а не нулями."""


def _views_are_gone() -> bool:
    with connection.cursor() as cur:
        cur.execute("SELECT count(*) FROM information_schema.views WHERE table_schema = %s",
                    [HOLDING_SCHEMA])
        (count,) = cur.fetchone()
    return count == 0


def _by_company(queryset, **aggregates) -> dict[str, dict]:
    grouped = queryset.values("company_slug").annotate(**aggregates)
    return {row.pop("company_slug"): row for row in grouped}


def _name(slug: str) -> str:
    company = companies.get_company(slug)
    return company["name"] if company else slug


def _collect():
    with use_holding():
        approved = HoldingBudget.objects.filter(status=BudgetStatus.APPROVED)
        budgets = _by_company(
            approved,
            budgets=Count("id"),
            budgets_other_currency=Count("id", filter=~Q(currency_code=KZT)))
        active_versions = HoldingBudgetVersion.objects.filter(
            state=VersionState.ACTIVE,
            budget_id__in=approved.filter(currency_code=KZT).values("id")).values("id")
        limits = _by_company(
            HoldingBudgetLine.objects.filter(version_id__in=active_versions),
            limit_kzt=Sum("limit_amount"))
        invoices = _by_company(
            HoldingInvoice.objects.all(),
            to_pay_count=Count("id", filter=Q(status__in=TO_PAY)),
            to_pay_amount=Sum("amount_kzt", filter=Q(status__in=TO_PAY)),
            paid_count=Count("id", filter=Q(status__in=PAID)),
            paid_amount=Sum("amount_kzt", filter=Q(status__in=PAID)))
        agreements = _by_company(
            HoldingAgreement.objects.filter(status=AgreementStatus.ACTIVE),
            agreements_active=Count("id"))
    return budgets, limits, invoices, agreements


def summary() -> dict:
    """``{"companies": [...], "totals": {...}}`` по действующим компаниям группы."""
    try:
        budgets, limits, invoices, agreements = _collect()
    except ProgrammingError:
        if _views_are_gone():
            raise HoldingViewsUnavailable(
                "Сводные представления холдинга сейчас пересобираются") from None
        raise

    rows = []
    for slug in companies.active_company_slugs():
        b, inv = budgets.get(slug, {}), invoices.get(slug, {})
        rows.append({
            "company_slug": slug,
            "company_name": _name(slug),
            "budgets": int(b.get("budgets") or 0),
            "budgets_other_currency": int(b.get("budgets_other_currency") or 0),
            "limit_kzt": limits.get(slug, {}).get("limit_kzt") or ZERO,
            "invoices_to_pay": {"count": int(inv.get("to_pay_count") or 0),
                                "amount_kzt": inv.get("to_pay_amount") or ZERO},
            "invoices_paid": {"count": int(inv.get("paid_count") or 0),
                              "amount_kzt": inv.get("paid_amount") or ZERO},
            "agreements_active": int(agreements.get(slug, {}).get("agreements_active") or 0),
        })
    totals = {
        "budgets": sum(r["budgets"] for r in rows),
        "limit_kzt": sum((r["limit_kzt"] for r in rows), ZERO),
        "invoices_to_pay": {
            "count": sum(r["invoices_to_pay"]["count"] for r in rows),
            "amount_kzt": sum((r["invoices_to_pay"]["amount_kzt"] for r in rows), ZERO)},
        "invoices_paid": {
            "count": sum(r["invoices_paid"]["count"] for r in rows),
            "amount_kzt": sum((r["invoices_paid"]["amount_kzt"] for r in rows), ZERO)},
        "agreements_active": sum(r["agreements_active"] for r in rows),
    }
    return {"companies": rows, "totals": totals}

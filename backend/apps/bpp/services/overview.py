"""«Обзор» модуля БЗО — стартовая страница раздела по ролям (ТЗ §05 столбец
«Видят», §17; решение пользователя 01.10: ФД и ГД — всё, БУХ — свои очереди,
ПМ — только свои проекты и данные, СН, ТД, ОД, АДМ — по ТЗ; несколько ролей —
объединение).

Блок — только если у актора есть право просмотра своего узла и включён его
подмодуль: нет права или рубильник выключен — ключа в ответе нет, как у
дашборда D-01 (``services/dashboard/payments.py``). «По должности» — значит
по ролям ``bpp-*`` (их выдают должностям), поэтому здесь только права узлов
(``Actor.can``), без названий должностей.

Числа — на выборках реестров (``visible`` каждого): видимость («свои»,
проекты-участия ПМ, группы статей СН и ПМ) живёт там, и число блока
совпадает с ``total`` реестра по его ссылке. Деньги — только у тех, кто
видит счета (``bpp.invoices`` view): у АДМ — количества без сумм (ТЗ §17).
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Sum

from apps.bpp.models import (
    AccountableStatus,
    AgreementStatus,
    AlternativeOffer,
    BudgetStatus,
    InvoiceStatus,
    KpiRecord,
    KpiStatus,
    OfferStatus,
    RequestStatus,
)
from apps.bpp.services.accountable import read as accountable_read
from apps.bpp.services.actor import Actor
from apps.bpp.services.agreements import read as agreement_read
from apps.bpp.services.alternatives import kpi
from apps.bpp.services.alternatives import read as alternative_read
from apps.bpp.services.budget import read as budget_read
from apps.bpp.services.invoices import read as invoice_read
from apps.bpp.services.plan import service as plan_service
from apps.bpp.services.requests import read as request_read
from apps.core.services import service_enabled
from apps.signoff import interface as signoff

ZERO = Decimal("0.00")
BPP_SUBJECTS = "bpp."


def shows_money(actor: Actor) -> bool:
    """Деньги видят те, кому открыты счета (ТЗ §17: АДМ — без сумм)."""
    return actor.can("bpp.invoices", "view")


def _by_status(rows) -> dict[str, int]:
    """Число строк по статусу; сортировку реестра снять — иначе она уйдёт в
    GROUP BY и разобьёт группы."""
    return dict(rows.order_by().values_list("status").annotate(n=Count("pk")))


def _budgets(actor: Actor, money: bool) -> dict | None:
    if not (actor.can("bpp.budgets", "view") and service_enabled("bpp_budget")):
        return None
    counts = _by_status(budget_read.visible(actor))
    block = {"total": sum(counts.values()), "approved": counts.get(BudgetStatus.APPROVED, 0),
             "draft": counts.get(BudgetStatus.DRAFT, 0),
             "can_create": actor.can("bpp.budgets", "create")}
    if money:
        block["money"] = budget_read.money_totals(actor)
    return block


def _approvals(actor: Actor) -> dict:
    pending = [row for row in signoff.pending_for_user(actor.user_id)
               if row["subject_type"].startswith(BPP_SUBJECTS)]
    return {"pending": len(pending)}


def _requests(actor: Actor) -> dict | None:
    if not (actor.can("bpp.requests", "view") and service_enabled("bpp_requests")):
        return None
    counts = _by_status(request_read.visible(actor))
    return {"total": sum(counts.values()), "draft": counts.get(RequestStatus.DRAFT, 0),
            "in_approval": counts.get(RequestStatus.IN_APPROVAL, 0),
            "rework": counts.get(RequestStatus.REWORK, 0),
            "approved": counts.get(RequestStatus.APPROVED, 0),
            "can_create": actor.can("bpp.requests", "create")}


def _plan(actor: Actor) -> dict | None:
    """Тот же вход, что у реестра L-04: свои позиции или все (``bpp.plan.all``)."""
    allowed = actor.can("bpp.plan", "view") or plan_service.sees_all(actor)
    if not (allowed and service_enabled("bpp_requests")):
        return None
    return {"open": plan_service.visible(actor).count()}


def _agreements(actor: Actor) -> dict | None:
    if not (actor.can("bpp.agreements", "view") and service_enabled("bpp_agreements")):
        return None
    counts = _by_status(agreement_read.visible(actor))
    return {"total": sum(counts.values()), "draft": counts.get(AgreementStatus.DRAFT, 0),
            "on_review": counts.get(AgreementStatus.ON_REVIEW, 0),
            "rework": counts.get(AgreementStatus.REWORK, 0),
            "active": counts.get(AgreementStatus.ACTIVE, 0)}


def _invoices(actor: Actor) -> dict | None:
    """Всего и очереди — вкладки реестра L-06 (их ``tab`` и в ссылке)."""
    if not (actor.can("bpp.invoices", "view") and service_enabled("bpp_invoices")):
        return None
    counts = _by_status(invoice_read.visible(actor))
    block = {"total": sum(counts.values()), "draft": counts.get(InvoiceStatus.DRAFT, 0),
             "returned": counts.get(InvoiceStatus.RETURNED, 0), "tabs": {}}

    def tab(name: str) -> None:
        block["tabs"][name] = invoice_read.visible(actor, {"tab": name}).count()

    if actor.can("bpp.invoices.decision", "edit"):
        tab("fd")
    if actor.can("bpp.invoices.payment", "edit"):
        tab("to_pay"), tab("docs_provided")
    if actor.can("bpp.invoices", "create") or actor.can("bpp.invoices.closing_docs", "edit"):
        tab("awaiting_docs")
    if actor.can("bpp.bank", "view") and service_enabled("bpp_bank"):
        tab("bank_unconfirmed")
    return block


def _accountable(actor: Actor) -> dict | None:
    if not (actor.can("bpp.accountable", "view") and service_enabled("bpp_accountable")):
        return None
    counts = _by_status(accountable_read.visible(actor))
    block = {"total": sum(counts.values()),
             "awaiting_report": counts.get(AccountableStatus.AWAITING_REPORT, 0),
             "can_create": actor.can("bpp.accountable", "create")}
    if actor.can("bpp.accountable.payment", "edit"):
        block["awaiting_accounting"] = counts.get(AccountableStatus.AWAITING_ACCOUNTING, 0)
    return block


def _alternatives(actor: Actor) -> dict | None:
    if not (actor.can("bpp.alternatives", "view") and service_enabled("bpp_alternatives")):
        return None
    block = {"feed": alternative_read.feed(actor, page_size=25)["total"]}
    if alternative_read.sees_all(actor):
        block["submitted"] = AlternativeOffer.objects.filter(
            status=OfferStatus.SUBMITTED).count()
    if actor.can("bpp.alternatives", "create"):
        block["mine_submitted"] = alternative_read.my_offers(
            actor, statuses=[OfferStatus.SUBMITTED], page_size=25)["total"]
    return block


def _kpi(actor: Actor, money: bool) -> dict | None:
    if not (actor.can("bpp.kpi", "view") and service_enabled("bpp_alternatives")):
        return None
    rows = KpiRecord.objects.all() if kpi.sees_all(actor) \
        else KpiRecord.objects.filter(buyer_id=actor.user_id)
    counts = _by_status(rows)
    block = {"preliminary": counts.get(KpiStatus.PRELIMINARY, 0),
             "confirmed": counts.get(KpiStatus.CONFIRMED, 0)}
    if money:
        block["saving_confirmed"] = rows.filter(status=KpiStatus.CONFIRMED).aggregate(
            total=Sum("saving_amount"))["total"] or ZERO
    return block


def _admin(actor: Actor) -> dict | None:
    """Администрирование (АДМ; ФД — маршруты): без денег, только очереди и
    ссылки (ТЗ §05 п.10, §17)."""
    if not (actor.can("bpp.settings", "edit") or actor.can("bpp.routes", "edit")):
        return None
    return {"no_executor": signoff.count_no_executor(BPP_SUBJECTS),
            "routes": actor.can("bpp.routes", "edit"),
            "settings": actor.can("bpp.settings", "view"),
            "refdata": actor.can("refdata", "view"),
            "projects": actor.can("project", "view")}


def overview(actor: Actor) -> dict:
    """Блоки «Обзора», доступные актору; недоступных ключей нет."""
    money = shows_money(actor)
    blocks = {
        "budgets": _budgets(actor, money),
        "approvals": _approvals(actor),
        "requests": _requests(actor),
        "plan": _plan(actor),
        "agreements": _agreements(actor),
        "invoices": _invoices(actor),
        "accountable": _accountable(actor),
        "bank": {} if actor.can("bpp.bank", "view") and service_enabled("bpp_bank") else None,
        "dashboard": {} if actor.can("bpp.dashboard", "view") else None,
        "alternatives": _alternatives(actor),
        "kpi": _kpi(actor, money),
        "admin": _admin(actor),
    }
    return {"shows_money": money, **{key: value for key, value in blocks.items()
                                    if value is not None}}

"""Регистрация документов модуля БЗО в движке согласования ``signoff``.

Зовётся из ``BppConfig.ready()``. Движок не знает таблиц модуля: статус
документа он меняет только через эти колбэки, а ключ документа передаёт в
типе ключа модели — ``uuid.UUID`` (B0.1, ``registry.native_id``).

Маршрут не зашит в код: его заводит команда ``bpp_configure_routes`` (по
должностям), флаги маршрутов БЗО — самосогласование, комментарий ≥ 10,
ленивое разрешение исполнителей (D-21).

Маршруты документов модуля, кроме администратора платформы, правят ФД и
АДМ (В-09): узел ``bpp.routes`` — колбэк ``route_editors`` у каждого типа.

Каждый тип документа решается и из вышестоящей компании (B8.1, директора —
в штате холдинга): ``_cross_company`` — признак, рубильник подмодуля и
сводка позиций (``approval_summary``).

Здесь же — проверки доступа к «Истории изменений» (``audit.
register_history_access``): журнал документа читает тот, кто видит сам
документ.
"""

from __future__ import annotations

from apps.bpp import approval_summary
from apps.bpp.file_owners import actor_from_token
from apps.bpp.models import (
    AccountableFundsRequest,
    AdvanceReport,
    Agreement,
    AgreementType,
    Budget,
    Invoice,
    InvoiceBasis,
    PurchaseRequest,
    PurchaseType,
)
from apps.bpp.services.accountable import accountable as accountable_service
from apps.bpp.services.actor import Actor
from apps.bpp.services.agreements import agreements as agreement_service
from apps.bpp.services.counterparties import lookup as counterparty_lookup
from apps.bpp.services.invoices import invoices as invoice_service
from apps.bpp.services.budget import budgets as budget_service
from apps.bpp.services.core import audit
from apps.bpp.services.money import fmt
from apps.bpp.services.requests import requests as request_service
from apps.bpp.services.selection import voting
from apps.project import interface as projects
from apps.refdata import interface as refdata
from apps.signoff import interface as signoff


def _describe_request(subject_id) -> dict | None:
    req = PurchaseRequest.objects.filter(pk=subject_id).first()
    if req is None:
        return None
    code = (projects.project_brief([str(req.project_id)]).get(str(req.project_id))
            or {}).get("code", "")
    return {
        "title": f"Заявка {req.number} на {fmt(req.total_amount, req.currency_code)}"
                 + (f" по проекту {code}" if code else ""),
        "url": f"/bpp/requests/{req.pk}",
    }


def _request_facts(subject_id) -> dict:
    req = PurchaseRequest.objects.filter(pk=subject_id).first()
    if req is None:
        return {}
    group = ""
    if req.article_id:
        brief = refdata.article_brief([str(req.article_id)]).get(str(req.article_id))
        groups = {g["id"]: g["code"] for g in refdata.article_groups()}
        group = groups.get(brief["group_id"], "") if brief else ""
    return {"amount": req.total_amount, "currency": req.currency_code,
            "purchase_type": req.purchase_type, "article_group": group,
            "initiator_role": req.initiator_role}


def _request_fact_fields() -> list[dict]:
    return [
        {"key": "amount", "label": "Сумма заявки", "type": "number"},
        {"key": "currency", "label": "Валюта", "type": "string"},
        {"key": "purchase_type", "label": "Вид закупки", "type": "choice",
         "options": [{"value": v, "label": label} for v, label in PurchaseType.choices]},
        {"key": "article_group", "label": "Группа статей", "type": "choice",
         "options": [{"value": g["code"], "label": g["name"]}
                     for g in refdata.article_groups()]},
        {"key": "initiator_role", "label": "Роль инициатора", "type": "choice",
         "options": [{"value": "sn", "label": "Снабженец"},
                     {"value": "pm", "label": "Руководитель проекта"}]},
    ]


def _describe_accountable(subject_id) -> dict | None:
    req = AccountableFundsRequest.objects.filter(pk=subject_id).first()
    if req is None:
        return None
    return {"title": f"Подотчёт {req.number} на {fmt(req.amount, req.currency)}",
            "url": f"/bpp/accountable/{req.pk}"}


def _accountable_facts(subject_id) -> dict:
    req = AccountableFundsRequest.objects.filter(pk=subject_id).first()
    return {} if req is None else {"amount": req.amount, "currency": req.currency}


def _describe_report(subject_id) -> dict | None:
    report = AdvanceReport.objects.select_related("request").filter(pk=subject_id).first()
    if report is None:
        return None
    return {"title": f"Авансовый отчёт «{report.expense_name}» по {report.request.number} "
                     f"на {fmt(report.amount, report.request.currency)}",
            "url": f"/bpp/accountable/{report.request_id}"}


def _report_facts(subject_id) -> dict:
    report = AdvanceReport.objects.filter(pk=subject_id).first()
    return {} if report is None else {"amount": report.amount}


_AMOUNT_FIELDS = [{"key": "amount", "label": "Сумма", "type": "number"}]


def _describe_agreement(subject_id) -> dict | None:
    agr = Agreement.objects.select_related("counterparty").filter(pk=subject_id).first()
    if agr is None:
        return None
    kind = "Допсоглашение" if agr.parent_agreement_id else "Договор"
    who = f" с {counterparty_lookup.display_name(agr.counterparty)}" if agr.counterparty_id else ""
    amount = (f" на {fmt(agr.amount, agr.currency_code)}"
              if agr.amount is not None and not agr.is_open else "")
    return {"title": f"{kind} {agr.number}{who}{amount}", "url": f"/bpp/agreements/{agr.pk}"}


def _agreement_fact_fields() -> list[dict]:
    return [
        {"key": "amount", "label": "Сумма договора", "type": "number"},
        {"key": "amount_delta", "label": "Прирост суммы допсоглашения", "type": "number"},
        {"key": "is_supplement", "label": "Допсоглашение", "type": "bool"},
        {"key": "is_open", "label": "Открытый договор", "type": "bool"},
        {"key": "currency", "label": "Валюта", "type": "string"},
        {"key": "agreement_type", "label": "Тип договора", "type": "choice",
         "options": [{"value": v, "label": label} for v, label in AgreementType.choices]},
        {"key": "article_group", "label": "Группа статей", "type": "choice",
         "options": [{"value": g["code"], "label": g["name"]}
                     for g in refdata.article_groups()]},
    ]


def _describe_invoice(subject_id) -> dict | None:
    inv = Invoice.objects.select_related("counterparty").filter(pk=subject_id).first()
    if inv is None:
        return None
    who = f" {counterparty_lookup.display_name(inv.counterparty)}" if inv.counterparty_id else ""
    return {"title": f"Счёт {inv.number}{who} на {fmt(inv.amount, inv.currency_code)}",
            "url": f"/bpp/invoices/{inv.pk}"}


def _invoice_fact_fields() -> list[dict]:
    return [
        {"key": "amount", "label": "Сумма счёта", "type": "number"},
        {"key": "amount_kzt", "label": "Сумма счёта в KZT", "type": "number"},
        {"key": "currency", "label": "Валюта", "type": "string"},
        {"key": "basis", "label": "Основание оплаты", "type": "choice",
         "options": [{"value": v, "label": label} for v, label in InvoiceBasis.choices]},
        {"key": "purchase_type", "label": "Тип приобретения", "type": "choice",
         "options": [{"value": v, "label": label} for v, label in PurchaseType.choices]},
        {"key": "is_advance", "label": "Аванс (предоплата)", "type": "bool"},
    ]


def _invoice_requirements() -> list[dict]:
    return [{"key": "bpp:budget", "label": "Бюджет статьи не превышен на текущий момент"}]


def _agreement_scopes() -> list[dict]:
    return [{"scope": "", "label": "Договор"},
            {"scope": agreement_service.SUPPLEMENTARY, "label": "Дополнительное соглашение"}]


def _history_of(model, can_view):
    def check(request, object_id: str) -> bool:
        obj = model.objects.filter(pk=object_id).first()
        return obj is not None and can_view(Actor(request), obj)
    return check


def _valid_uuid_guard(check):
    """Ключ из URL не UUID — нет такого объекта, а не 500."""
    def guarded(request, object_id: str) -> bool:
        import uuid

        try:
            uuid.UUID(str(object_id))
        except ValueError:
            return False
        return check(request, object_id)
    return guarded


def _route_editors(token) -> bool:
    """Правит маршруты документов модуля (В-09: ФД и АДМ, access/0018)."""
    return actor_from_token(token).can("bpp.routes", "edit")


def _cross_company(service: str, summary) -> dict:
    """Документ модуля решается и из вышестоящей компании (B8.1): колбэки
    берут компанию из контекста, а требование этапа счёта ``bpp:budget`` —
    проверка состояния, а не работа согласующего. ``service`` — подмодуль,
    чей рубильник у компании документа гасит такое решение; ``summary`` —
    сводка позиций для карточки в холдинге (``approval_summary``). Включает
    это для маршрута флаг «Решение прямо из холдинга»."""
    return {"cross_company_decisions": True, "service": service, "summary": summary}


def register() -> None:
    signoff.register_subject(
        PurchaseRequest.SIGNOFF_SUBJECT_TYPE,
        label="Заявка на закупку",
        model=PurchaseRequest,
        on_started=request_service.on_started,
        on_approved=request_service.on_approved,
        on_rejected=request_service.on_rejected,
        on_rework=request_service.on_rework,
        on_cancelled=request_service.on_cancelled,
        describe=_describe_request,
        facts=_request_facts,
        fact_fields=_request_fact_fields,
        route_editors=_route_editors,
        **_cross_company("bpp_requests", approval_summary.request_summary),
    )
    signoff.register_subject(
        AccountableFundsRequest.SIGNOFF_SUBJECT_TYPE,
        label="Заявка на подотчётные средства",
        model=AccountableFundsRequest,
        on_started=accountable_service.on_request_started,
        on_approved=accountable_service.on_request_approved,
        on_rejected=accountable_service.on_request_back_to_draft,
        on_rework=accountable_service.on_request_back_to_draft,
        on_cancelled=accountable_service.on_request_back_to_draft,
        describe=_describe_accountable,
        facts=_accountable_facts,
        fact_fields=lambda: _AMOUNT_FIELDS,
        route_editors=_route_editors,
        **_cross_company("bpp_accountable", approval_summary.accountable_summary),
    )
    signoff.register_subject(
        AdvanceReport.SIGNOFF_SUBJECT_TYPE,
        label="Авансовый отчёт",
        model=AdvanceReport,
        on_approved=accountable_service.on_report_approved,
        describe=_describe_report,
        facts=_report_facts,
        fact_fields=lambda: _AMOUNT_FIELDS,
        route_editors=_route_editors,
        **_cross_company("bpp_accountable", approval_summary.advance_report_summary),
    )
    signoff.register_subject(
        Agreement.SIGNOFF_SUBJECT_TYPE,
        label="Договор",
        model=Agreement,
        on_started=agreement_service.on_started,
        on_approved=agreement_service.on_approved,
        on_rejected=agreement_service.on_rejected,
        on_rework=agreement_service.on_rework,
        on_cancelled=agreement_service.on_cancelled,
        describe=_describe_agreement,
        facts=agreement_service.facts,
        fact_fields=_agreement_fact_fields,
        scope_of=agreement_service.scope_of,
        scopes=_agreement_scopes,
        # Голос ФД и ГД за исходный договор или альтернативу (B5.1, D-25, D-26).
        options=voting.options,
        check_option=voting.check_option,
        on_option=voting.on_option,
        route_editors=_route_editors,
        **_cross_company("bpp_agreements", approval_summary.agreement_summary),
    )
    signoff.register_subject(
        Invoice.SIGNOFF_SUBJECT_TYPE,
        label="Счёт на оплату",
        model=Invoice,
        on_started=invoice_service.on_started,
        on_approved=invoice_service.on_approved,
        on_rejected=invoice_service.on_rejected,
        on_rework=invoice_service.on_rework,
        on_cancelled=invoice_service.on_cancelled,
        describe=_describe_invoice,
        facts=invoice_service.facts,
        fact_fields=_invoice_fact_fields,
        requirement_fields=_invoice_requirements,
        check_requirement=invoice_service.check_requirement,
        route_editors=_route_editors,
        **_cross_company("bpp_invoices", approval_summary.invoice_summary),
    )
    audit.register_history_access(
        Invoice._meta.label_lower,
        _valid_uuid_guard(_history_of(Invoice, invoice_service.can_view)))
    audit.register_history_access(
        Agreement._meta.label_lower,
        _valid_uuid_guard(_history_of(Agreement, agreement_service.can_view)))
    audit.register_history_access(
        AccountableFundsRequest._meta.label_lower,
        _valid_uuid_guard(_history_of(AccountableFundsRequest, accountable_service.can_view)))
    audit.register_history_access(
        Budget._meta.label_lower,
        _valid_uuid_guard(_history_of(Budget, budget_service.can_view)))
    audit.register_history_access(
        PurchaseRequest._meta.label_lower,
        _valid_uuid_guard(_history_of(PurchaseRequest, request_service.can_view)))

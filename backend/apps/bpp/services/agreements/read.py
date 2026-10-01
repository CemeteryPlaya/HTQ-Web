"""Чтение договора: карточка F-04, реестр L-05, поиск для счёта, блок
«Исполнение» (ТЗ §09, §19, B3.1).

Колонка «Сейчас у» — ``signoff.current_holders``. Поиск договора для счёта —
BR-046, AC-007: только «Действует», тот же проект и статья, срок не истёк,
у закрытого — остаток > 0 (CALC-009).
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from apps.bpp.models import Agreement, AgreementStatus
from apps.bpp.services.actor import Actor
from apps.bpp.services.budget import balance as budget_balance
from apps.bpp.services.counterparties import lookup as counterparties
from apps.project import interface as projects
from apps.refdata import interface as refdata
from apps.signoff import interface as signoff
from apps.users import interface as users
from htqweb.errors import DomainError

from apps.bpp.services.invoices import invoices as invoice_service
from apps.bpp.services.selection import checks as selection_checks

from . import agreements as service
from . import positions

SUBJECT = Agreement.SIGNOFF_SUBJECT_TYPE
ZERO = Decimal("0.00")

def invoiced_by_agreement(agreement_ids) -> dict[str, Decimal]:
    """Σ счетов по договору, кроме «Отменён», «Не к оплате», «Заменён» (CALC-009)."""
    return invoice_service.invoiced_by_agreement(agreement_ids)


def remaining(agr: Agreement, invoiced: Decimal | None = None) -> Decimal | None:
    """Остаток по договору (CALC-009); у открытого — ``None``."""
    total = service.effective_amount(agr)
    if total is None:
        return None
    if invoiced is None:
        invoiced = invoiced_by_agreement([str(agr.pk)]).get(str(agr.pk), ZERO)
    return total - invoiced


def _names(ids) -> dict[int, str]:
    ids = [uid for uid in set(ids) if uid]
    return {row["id"]: row["full_name"] for row in users.get_users_brief(ids)} if ids else {}


def _budget_block(agr: Agreement) -> dict | None:
    """ТЗ §9.3 п.5: превышение над планом позиций и доступный остаток статьи."""
    try:
        figures = budget_balance.balance(agr.project_id, agr.article_id)
    except DomainError:
        return None
    return {"available": figures["available"], "over_plan": service.over_plan(agr),
            "plan_total": sum((i.request_item.amount for i in
                               agr.items.select_related("request_item")), ZERO)}


def card(actor: Actor, agr: Agreement, *, vat_warning: str | None = None) -> dict:
    project = projects.project_brief([str(agr.project_id)]).get(str(agr.project_id)) or {}
    article = refdata.article_brief([str(agr.article_id)]).get(str(agr.article_id)) or {}
    items = list(agr.items.select_related("request_item", "request_item__request")
                 .order_by("request_item__sys_number"))
    left = positions.remaining([i.request_item for i in items], exclude_agreement_id=agr.pk)
    uoms = refdata.uom_brief(list({str(i.request_item.uom_id) for i in items}))
    cp = counterparties.brief([agr.counterparty_id]).get(str(agr.counterparty_id)) \
        if agr.counterparty_id else None
    names = _names([agr.author_id])
    holders = signoff.current_holders(SUBJECT, [str(agr.pk)]).get(str(agr.pk))
    editable = agr.status in service.EDITABLE
    supplements = list(agr.supplements.order_by("created_at"))
    return {
        "id": str(agr.pk), "number": agr.number, "status": agr.status,
        "is_migrated": agr.is_migrated,
        "approval_state": agr.approval_state, "version": agr.version,
        "author_id": agr.author_id, "author_name": names.get(agr.author_id),
        "created_at": agr.created_at,
        "project": {"id": str(agr.project_id), "code": project.get("code"),
                    "name": project.get("name")},
        "article": {"id": str(agr.article_id), "code": article.get("code"),
                    "name": article.get("name"),
                    "archived": not article.get("is_active", True)},
        "counterparty": cp,
        "counterparty_confirmed": agr.counterparty_confirmed,
        "name": agr.name, "ext_number": agr.ext_number, "ext_date": agr.ext_date,
        "agreement_type": agr.agreement_type, "is_open": agr.is_open,
        "amount": agr.amount, "currency_code": agr.currency_code,
        "with_vat": agr.with_vat, "vat_rate": agr.vat_rate, "vat_source": agr.vat_source,
        "vat_amount": agr.vat_amount,
        "amount_without_vat": (agr.amount - (agr.vat_amount or ZERO)
                               if agr.amount is not None else None),
        "vat_warning": vat_warning,
        "valid_to": agr.valid_to,
        "status_comment": agr.status_comment,
        "rework_comment": agr.rework_comment if agr.status == AgreementStatus.REWORK else "",
        "parent": None if agr.parent_agreement_id is None else {
            "id": str(agr.parent_agreement_id),
            "number": agr.parent_agreement.number},
        "supplements": [{"id": str(s.pk), "number": s.number, "status": s.status,
                         "amount": s.amount, "ext_date": s.ext_date} for s in supplements],
        "effective_amount": service.effective_amount(agr),
        "remaining": remaining(agr) if agr.status != AgreementStatus.DRAFT else None,
        "budget": _budget_block(agr) if editable else None,
        "items": [{
            "id": str(i.pk), "request_item_id": str(i.request_item_id),
            "sys_number": i.request_item.sys_number, "name": i.request_item.name,
            "request_id": str(i.request_item.request_id),
            "request_number": i.request_item.request.number,
            "uom": uoms.get(str(i.request_item.uom_id), {}).get("short_name"),
            "plan_qty": i.request_item.qty, "plan_amount": i.request_item.amount,
            "qty": i.qty, "amount": i.amount,
            "qty_available": left[str(i.request_item_id)]["qty_left"],
        } for i in items],
        "current_holders": holders,
        "alternative": selection_checks.alternative_links("agreement", agr),   # B5.1
        "allowed_actions": service.allowed_actions(actor, agr),
    }


def visible(actor: Actor, filters: dict | None = None):
    """Выборка реестра с фильтрами реестра — по ней считает «Обзор» модуля,
    чтобы его число совпадало с ``total`` реестра."""
    return _visible(actor, filters or {})


def _visible(actor: Actor, filters: dict):
    """Выборка реестра L-05 — одна на страницу и выгрузку."""
    # Перенесённые из «Договоров» — в реестре как обычные, с пометкой
    # (D-B61-8): их переносили, чтобы работать дальше.
    rows = Agreement.objects.all()
    if not service.sees_all(actor):
        # СН и ПМ: свои, ждущие их решения и договоры своих проектов и групп
        # статей (ТЗ §9.1 [Л]). Статьи группы — по статьям самих договоров
        # проекта: списка «статьи группы» в интерфейсе справочников нет.
        scoped = Agreement.objects.all()
        if not actor.sees_all_projects:
            scoped = scoped.filter(project_id__in=list(actor.member_project_ids))
        article_ids = {str(a) for a in scoped.values_list("article_id", flat=True).distinct()}
        briefs = refdata.article_brief(list(article_ids))
        allowed = [a for a in article_ids if actor.sees_article(briefs.get(a))]
        scope = Q(article_id__in=allowed)
        if not actor.sees_all_projects:
            scope &= Q(project_id__in=list(actor.member_project_ids))
        awaiting = [str(sid) for sid in signoff.list_awaiting_subject_ids(actor.user_id, SUBJECT)]
        rows = rows.filter(Q(author_id=actor.user_id) | scope | Q(pk__in=awaiting))
    if filters.get("statuses"):
        rows = rows.filter(status__in=filters["statuses"])
    if filters.get("project_ids"):
        rows = rows.filter(project_id__in=filters["project_ids"])
    if filters.get("article_ids"):
        rows = rows.filter(article_id__in=filters["article_ids"])
    if filters.get("counterparty_id"):
        rows = rows.filter(counterparty_id=filters["counterparty_id"])
    if filters.get("date_from"):
        rows = rows.filter(ext_date__gte=filters["date_from"])
    if filters.get("date_to"):
        rows = rows.filter(ext_date__lte=filters["date_to"])
    if filters.get("awaiting_me"):
        rows = rows.filter(pk__in=[str(sid) for sid in
                                   signoff.list_awaiting_subject_ids(actor.user_id, SUBJECT)])
    if filters.get("search"):
        text = filters["search"]
        rows = rows.filter(Q(number__icontains=text) | Q(ext_number__icontains=text)
                           | Q(name__icontains=text))
    return rows.select_related("counterparty").order_by("-created_at")


def _row(agr: Agreement, *, project_map, article_map, names, holders, invoiced) -> dict:
    return {
        "id": str(agr.pk), "number": agr.number, "status": agr.status,
        "is_migrated": agr.is_migrated,
        "created_at": agr.created_at, "author_id": agr.author_id,
        "author_name": names.get(agr.author_id),
        "ext_number": agr.ext_number, "ext_date": agr.ext_date, "name": agr.name,
        "project_id": str(agr.project_id),
        "project_code": project_map.get(str(agr.project_id), {}).get("code"),
        "article_id": str(agr.article_id),
        "article_name": article_map.get(str(agr.article_id), {}).get("name"),
        "counterparty_id": str(agr.counterparty_id) if agr.counterparty_id else None,
        "counterparty_name": (counterparties.display_name(agr.counterparty)
                              if agr.counterparty_id else None),
        "is_open": agr.is_open, "amount": agr.amount, "currency_code": agr.currency_code,
        "remaining": remaining(agr, invoiced.get(str(agr.pk), ZERO))
        if agr.status != AgreementStatus.DRAFT else None,
        "valid_to": agr.valid_to, "is_supplement": agr.parent_agreement_id is not None,
        "current_holders": holders.get(str(agr.pk)),
    }


def _rows(chunk: list[Agreement]) -> list[dict]:
    project_map = projects.project_brief(list({str(a.project_id) for a in chunk}))
    article_map = refdata.article_brief(list({str(a.article_id) for a in chunk}))
    names = _names([a.author_id for a in chunk])
    holders = signoff.current_holders(SUBJECT, [str(a.pk) for a in chunk]) if chunk else {}
    invoiced = invoiced_by_agreement([str(a.pk) for a in chunk])
    return [_row(a, project_map=project_map, article_map=article_map, names=names,
                 holders=holders, invoiced=invoiced) for a in chunk]


def registry(actor: Actor, *, filters: dict | None = None, page: int = 1,
             page_size: int = 50) -> dict:
    rows = _visible(actor, filters or {})
    total = rows.count()
    page_size = page_size if page_size in (25, 50, 100) else 50
    chunk = list(rows[(page - 1) * page_size: page * page_size])
    return {"items": _rows(chunk), "total": total, "page": page, "page_size": page_size}


def search_for_invoice(actor: Actor, *, project_id, article_id, query: str = "",
                       on_date=None) -> list[dict]:
    """BR-046, AC-007: договоры для счёта — только «Действует», тот же проект и
    статья, срок не истёк, у закрытого — остаток > 0; поиск по номеру по
    документу, системному номеру и наименованию от 2 символов."""
    on_date = on_date or timezone.localdate()
    rows = (Agreement.objects
            .filter(status=AgreementStatus.ACTIVE, parent_agreement__isnull=True,
                    project_id=project_id, article_id=article_id)
            .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=on_date))
            .select_related("counterparty"))
    query = (query or "").strip()
    if len(query) >= 2:
        rows = rows.filter(Q(ext_number__icontains=query) | Q(number__icontains=query)
                           | Q(name__icontains=query))
    chunk = [agr for agr in rows.order_by("-ext_date")[:50] if service.can_view(actor, agr)]
    invoiced = invoiced_by_agreement([str(a.pk) for a in chunk])
    out = []
    for agr in chunk:
        rest = remaining(agr, invoiced.get(str(agr.pk), ZERO))
        if rest is not None and rest <= 0:
            continue
        out.append({"id": str(agr.pk), "number": agr.number, "ext_number": agr.ext_number,
                    "ext_date": agr.ext_date, "name": agr.name, "is_open": agr.is_open,
                    "counterparty_id": str(agr.counterparty_id),
                    "counterparty_name": counterparties.display_name(agr.counterparty),
                    "currency_code": agr.currency_code,
                    "effective_amount": service.effective_amount(agr),
                    "remaining": rest, "valid_to": agr.valid_to,
                    "agreement_type": agr.agreement_type})
    return out


def execution(agr: Agreement) -> dict:
    """Блок «Исполнение» (ТЗ §9.2): счета по договору — номер, дата, сумма,
    статус, оплачено факт (по банку, A4.2); итог — остаток по договору
    (CALC-009)."""
    rows = [{"id": str(inv.pk), "number": inv.number, "ext_number": inv.ext_number,
             "ext_date": inv.ext_date, "amount": inv.amount, "currency_code": inv.currency_code,
             "status": inv.status, "paid_bank_amount": inv.paid_bank_amount}
            for inv in agr.invoices.order_by("created_at")]
    return {"invoices": rows, "effective_amount": service.effective_amount(agr),
            "remaining": remaining(agr)}


# ── выгрузка реестра в xlsx (ТЗ §19, контракт A: ``export.respond``) ────

#: Путь пересборки для фоновой выгрузки (строка — её везёт брокер Celery).
EXPORT_REBUILD_PATH = "apps.bpp.services.agreements.read.export_rows"
_EXPORT_CHUNK = 500


def export_count(*, user_id: int, company: str | None, is_superuser: bool = False,
                 filters: dict) -> int:
    actor = Actor.for_user(user_id, company=company, is_superuser=is_superuser)
    return _visible(actor, filters).count()


def export_rows(*, user_id: int, company: str | None, is_superuser: bool = False,
                filters: dict):
    """Строки выгрузки — та же выборка, что у страницы реестра, без пагинации."""
    actor = Actor.for_user(user_id, company=company, is_superuser=is_superuser)
    labels = dict(AgreementStatus.choices)
    chunk: list[Agreement] = []
    for agr in _visible(actor, filters).iterator(chunk_size=_EXPORT_CHUNK):
        chunk.append(agr)
        if len(chunk) == _EXPORT_CHUNK:
            for row in _rows(chunk):
                yield {**row, "status": labels.get(row["status"], row["status"])}
            chunk = []
    for row in _rows(chunk):
        yield {**row, "status": labels.get(row["status"], row["status"])}

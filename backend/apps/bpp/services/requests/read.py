"""Чтение заявки: карточка F-02, реестр L-02, блок «Исполнение» (ТЗ §07, §19).

Колонка «Сейчас у» — ``signoff.current_holders`` (B1.3): этап, ФИО, с какого
времени документ ждёт решения. «Ждёт моего решения» — фильтр по
``signoff.list_awaiting_subject_ids``.
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Q

from apps.bpp.models import PurchaseRequest, RequestStatus
from apps.bpp.services.actor import Actor
from apps.bpp.services.agreements import positions
from apps.bpp.services.budget import balance as budget_balance
from apps.bpp.services.core import files as core_files
from apps.project import interface as projects
from apps.refdata import interface as refdata
from apps.signoff import interface as signoff
from apps.users import interface as users
from htqweb.errors import DomainError

from . import requests as service

SUBJECT = PurchaseRequest.SIGNOFF_SUBJECT_TYPE
ZERO = Decimal("0.00")


def _names(ids) -> dict[int, str]:
    ids = [uid for uid in set(ids) if uid]
    return {row["id"]: row["full_name"] for row in users.get_users_brief(ids)} if ids else {}


def _budget_figures(req: PurchaseRequest) -> dict | None:
    """Блок 2 «Бюджет»: лимит, остаток и «Остаток после заявки». Пока заявка
    не в резерве, её сумма вычитается из остатка (ТЗ §7.3)."""
    if not req.article_id:
        return None
    try:
        now = budget_balance.balance(req.project_id, req.article_id)
    except DomainError:
        return None
    reserved = req.status in (RequestStatus.IN_APPROVAL, RequestStatus.APPROVED,
                              RequestStatus.CLOSED)
    # «Задействовано» и «Доступно» — как есть сейчас. Заявка в резерве уже
    # внутри них, и остаток после неё — это и есть «Доступно»; черновик ещё
    # не занял ничего, и его сумма вычитается.
    after = now["available"] if reserved else now["available"] - req.total_amount
    return {"limit": now["limit"], "committed": now["committed"],
            "available": now["available"], "after_request": after,
            "reserved": reserved, "as_of": now["as_of"]}


def execution(req: PurchaseRequest) -> list[dict]:
    """Блок 6 «Исполнение» (ТЗ §7.5): по позиции план / в договорах / в счетах /
    оплачено / остаток к закупке (CALC-005, CALC-006). Оплаты — со счетами (B3.2)."""
    items = list(req.items.all())
    left = positions.remaining(items)
    return [{
        "id": str(item.id), "sys_number": item.sys_number, "name": item.name,
        "status": item.status, "qty": item.qty,
        "qty_in_agreements": left[str(item.pk)]["qty_in_agreements"],
        "qty_in_invoices": left[str(item.pk)]["qty_in_invoices"], "amount": item.amount,
        "amount_in_invoices": left[str(item.pk)]["amount_in_invoices"], "amount_paid": ZERO,
        "amount_left": left[str(item.pk)]["amount_left"],
    } for item in items]


def card(actor: Actor, req: PurchaseRequest) -> dict:
    project = projects.project_brief([str(req.project_id)]).get(str(req.project_id)) or {}
    article = (refdata.article_brief([str(req.article_id)]).get(str(req.article_id))
               if req.article_id else None) or {}
    items = list(req.items.all())
    uoms = refdata.uom_brief(list({str(item.uom_id) for item in items}))
    names = _names([req.author_id])
    holders = signoff.current_holders(SUBJECT, [str(req.pk)]).get(str(req.pk))
    return {
        "id": str(req.id), "number": req.number, "status": req.status,
        "approval_state": req.approval_state, "version": req.version,
        "author_id": req.author_id, "author_name": names.get(req.author_id),
        "created_at": req.created_at, "initiator_role": req.initiator_role,
        "project": {"id": str(req.project_id), "code": project.get("code"),
                    "name": project.get("name")},
        "article": None if not req.article_id else {
            "id": str(req.article_id), "code": article.get("code"),
            "name": article.get("name"), "archived": not article.get("is_active", True)},
        "purchase_type": req.purchase_type, "need_date": req.need_date,
        "justification": req.justification, "currency_code": req.currency_code,
        "total_amount": req.total_amount, "status_comment": req.status_comment,
        "rework_comment": req.rework_comment if req.status == RequestStatus.REWORK else "",
        "budget": _budget_figures(req),
        "items": [{
            "id": str(item.id), "line_no": item.line_no, "sys_number": item.sys_number,
            "name": item.name, "specs": item.specs, "uom_id": str(item.uom_id),
            "uom": uoms.get(str(item.uom_id), {}).get("short_name"), "qty": item.qty,
            "price": item.price, "amount": item.amount, "need_date": item.need_date,
            "status": item.status,
        } for item in items],
        "current_holders": holders,
        "files": core_files.list_files(req),
        "allowed_actions": service.allowed_actions(actor, req),
    }


def visible(actor: Actor, filters: dict | None = None):
    """Выборка реестра с фильтрами реестра — по ней считает «Обзор» модуля,
    чтобы его число совпадало с ``total`` реестра."""
    return _visible(actor, filters or {})


def _visible(actor: Actor, filters: dict):
    """Выборка реестра L-02 — одна на страницу и выгрузку (ТЗ §19: экспорт —
    ровно то, что пользователь видит с этими фильтрами)."""
    rows = PurchaseRequest.objects.filter(is_migrated=False)
    if not service.sees_all(actor):
        awaiting = [str(sid) for sid in signoff.list_awaiting_subject_ids(actor.user_id, SUBJECT)]
        rows = rows.filter(Q(author_id=actor.user_id) | Q(pk__in=awaiting))
    if filters.get("awaiting_me"):
        rows = rows.filter(pk__in=[str(sid) for sid in
                                   signoff.list_awaiting_subject_ids(actor.user_id, SUBJECT)])
    if filters.get("statuses"):
        rows = rows.filter(status__in=filters["statuses"])
    if filters.get("project_ids"):
        rows = rows.filter(project_id__in=filters["project_ids"])
    if filters.get("article_ids"):
        rows = rows.filter(article_id__in=filters["article_ids"])
    if filters.get("author_id"):
        rows = rows.filter(author_id=filters["author_id"])
    if filters.get("created_from"):
        rows = rows.filter(created_at__date__gte=filters["created_from"])
    if filters.get("created_to"):
        rows = rows.filter(created_at__date__lte=filters["created_to"])
    if filters.get("search"):
        rows = rows.filter(number__icontains=filters["search"])
    return rows.order_by("-created_at")


def registry(actor: Actor, *, filters: dict | None = None, page: int = 1,
             page_size: int = 50) -> dict:
    rows = _visible(actor, filters or {})
    total = rows.count()
    totals_amount = sum((row for row in rows.values_list("total_amount", flat=True)), ZERO)
    page_size = page_size if page_size in (25, 50, 100) else 50
    chunk = list(rows[(page - 1) * page_size: page * page_size])
    project_map = projects.project_brief(list({str(r.project_id) for r in chunk}))
    article_map = refdata.article_brief(list({str(r.article_id) for r in chunk if r.article_id}))
    names = _names([r.author_id for r in chunk])
    holders = signoff.current_holders(SUBJECT, [str(r.pk) for r in chunk]) if chunk else {}
    items = [{
        "id": str(r.id), "number": r.number, "status": r.status, "created_at": r.created_at,
        "author_id": r.author_id, "author_name": names.get(r.author_id),
        "initiator_role": r.initiator_role, "project_id": str(r.project_id),
        "project_code": project_map.get(str(r.project_id), {}).get("code"),
        "article_id": str(r.article_id) if r.article_id else None,
        "article_name": article_map.get(str(r.article_id), {}).get("name"),
        "purchase_type": r.purchase_type, "need_date": r.need_date,
        "total_amount": r.total_amount, "currency_code": r.currency_code,
        "current_holders": holders.get(str(r.pk)),
    } for r in chunk]
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "totals": {"total_amount": totals_amount}}


# ── выгрузка реестра в xlsx (ТЗ §19, контракт A: ``export.respond``) ────

#: Путь пересборки для фоновой выгрузки (строка — её везёт брокер Celery).
EXPORT_REBUILD_PATH = "apps.bpp.services.requests.read.export_rows"
#: Сколько строк за раз дополняется «Сейчас у», проектами и статьями.
_EXPORT_CHUNK = 500


def export_count(*, user_id: int, company: str | None, is_superuser: bool = False,
                 filters: dict) -> int:
    actor = Actor.for_user(user_id, company=company, is_superuser=is_superuser)
    return _visible(actor, filters).count()


def _holder_text(entry: dict | None) -> str:
    if not entry:
        return ""
    if entry.get("no_executor"):
        return f"{entry['stage']}: нет исполнителя"
    names = ", ".join(user["name"] for user in entry["users"] if user["name"])
    return f"{entry['stage']}: {names}" if names else entry["stage"]


def export_rows(*, user_id: int, company: str | None, is_superuser: bool = False,
                filters: dict):
    """Строки выгрузки — та же выборка, что у страницы реестра, без пагинации.
    Права — заказчика выгрузки: фоновая задача зовёт это без запроса."""
    actor = Actor.for_user(user_id, company=company, is_superuser=is_superuser)
    rows = _visible(actor, filters)
    chunk: list[PurchaseRequest] = []
    for req in rows.iterator(chunk_size=_EXPORT_CHUNK):
        chunk.append(req)
        if len(chunk) == _EXPORT_CHUNK:
            yield from _export_chunk(chunk)
            chunk = []
    if chunk:
        yield from _export_chunk(chunk)


def _export_chunk(chunk: list[PurchaseRequest]):
    project_map = projects.project_brief(list({str(r.project_id) for r in chunk}))
    article_map = refdata.article_brief(list({str(r.article_id) for r in chunk if r.article_id}))
    names = _names([r.author_id for r in chunk])
    holders = signoff.current_holders(SUBJECT, [str(r.pk) for r in chunk])
    for r in chunk:
        yield {
            "number": r.number, "status": r.get_status_display(), "created_at": r.created_at,
            "author": names.get(r.author_id, ""),
            "project": project_map.get(str(r.project_id), {}).get("code"),
            "article": article_map.get(str(r.article_id), {}).get("name"),
            "purchase_type": r.get_purchase_type_display(), "need_date": r.need_date,
            "total_amount": r.total_amount, "currency_code": r.currency_code,
            "current_holder": _holder_text(holders.get(str(r.pk))),
        }

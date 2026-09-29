"""Чтение подотчёта: реестр и его выгрузка (ТЗ §19; задача B4.1, экраны).

Реестр — конверт реестров модуля ``{items, total, page, page_size,
totals}``, выборка одна на страницу и выгрузку (``_visible``): сотрудник
видит свои заявки и ждущие его решения, ФД и бухгалтер — все
(``accountable.sees_all``). «Подтверждено отчётами» — Σ одобренных
авансовых отчётов, как в карточке.
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Q, Sum

from apps.bpp.models import AccountableFundsRequest
from apps.bpp.services.actor import Actor
from apps.project import interface as projects
from apps.refdata import interface as refdata
from apps.signoff import interface as signoff
from apps.users import interface as users

from . import accountable as service

SUBJECT = service.REQUEST_SUBJECT
ZERO = Decimal("0.00")


def _names(ids) -> dict[int, str]:
    ids = [uid for uid in set(ids) if uid]
    return {row["id"]: row["full_name"] for row in users.get_users_brief(ids)} if ids else {}


def _visible(actor: Actor, filters: dict):
    rows = AccountableFundsRequest.objects.filter(is_migrated=False)
    if not service.sees_all(actor):
        awaiting = [str(sid) for sid in signoff.list_awaiting_subject_ids(actor.user_id, SUBJECT)]
        rows = rows.filter(Q(accountable_user_id=actor.user_id) | Q(pk__in=awaiting))
    if filters.get("awaiting_me"):
        rows = rows.filter(pk__in=[str(sid) for sid in
                                   signoff.list_awaiting_subject_ids(actor.user_id, SUBJECT)])
    if filters.get("statuses"):
        rows = rows.filter(status__in=filters["statuses"])
    if filters.get("project_ids"):
        rows = rows.filter(project_id__in=filters["project_ids"])
    if filters.get("article_ids"):
        rows = rows.filter(article_id__in=filters["article_ids"])
    if filters.get("date_from"):
        rows = rows.filter(created_at__date__gte=filters["date_from"])
    if filters.get("date_to"):
        rows = rows.filter(created_at__date__lte=filters["date_to"])
    if filters.get("search"):
        text = filters["search"]
        rows = rows.filter(Q(number__icontains=text) | Q(goal__icontains=text))
    return (rows.annotate(reported=Sum(
        "reports__amount", filter=Q(reports__approval_state=signoff.ApprovalState.APPROVED)))
        .order_by("-created_at"))


def _rows(chunk: list[AccountableFundsRequest]) -> list[dict]:
    project_map = projects.project_brief(list({str(r.project_id) for r in chunk}))
    article_map = refdata.article_brief(list({str(r.article_id) for r in chunk}))
    names = _names([r.accountable_user_id for r in chunk])
    holders = signoff.current_holders(SUBJECT, [str(r.pk) for r in chunk]) if chunk else {}
    out = []
    for r in chunk:
        reported = r.reported or ZERO
        out.append({
            "id": str(r.id), "number": r.number, "status": r.status,
            "created_at": r.created_at, "accountable_user_id": r.accountable_user_id,
            "accountable_user_name": names.get(r.accountable_user_id),
            "project_id": str(r.project_id),
            "project_code": project_map.get(str(r.project_id), {}).get("code"),
            "article_id": str(r.article_id),
            "article_name": article_map.get(str(r.article_id), {}).get("name"),
            "goal": r.goal, "amount": r.amount, "currency": r.currency,
            "reported_amount": reported, "remaining_amount": r.amount - reported,
            "current_holders": holders.get(str(r.pk)),
        })
    return out


def registry(actor: Actor, *, filters: dict | None = None, page: int = 1,
             page_size: int = 50) -> dict:
    rows = _visible(actor, filters or {})
    total = rows.count()
    amount = rows.aggregate(total=Sum("amount"))["total"] or ZERO
    page_size = page_size if page_size in (25, 50, 100) else 50
    chunk = list(rows[(page - 1) * page_size: page * page_size])
    return {"items": _rows(chunk), "total": total, "page": page, "page_size": page_size,
            "totals": {"amount": amount}}


# ── выгрузка реестра в xlsx (ТЗ §19, контракт A: ``export.respond``) ────

EXPORT_REBUILD_PATH = "apps.bpp.services.accountable.read.export_rows"
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
    """Та же выборка, что у страницы, без пагинации; права — заказчика выгрузки."""
    actor = Actor.for_user(user_id, company=company, is_superuser=is_superuser)
    chunk: list[AccountableFundsRequest] = []
    for req in _visible(actor, filters).iterator(chunk_size=_EXPORT_CHUNK):
        chunk.append(req)
        if len(chunk) == _EXPORT_CHUNK:
            yield from _export_chunk(chunk)
            chunk = []
    if chunk:
        yield from _export_chunk(chunk)


def _export_chunk(chunk: list[AccountableFundsRequest]):
    by_id = {str(r.pk): r for r in chunk}
    for row in _rows(chunk):
        req = by_id[row["id"]]
        yield {
            "number": row["number"], "status": req.get_status_display(),
            "created_at": row["created_at"], "accountable": row["accountable_user_name"] or "",
            "project": row["project_code"], "article": row["article_name"], "goal": row["goal"],
            "amount": row["amount"], "currency": row["currency"],
            "reported_amount": row["reported_amount"],
            "current_holder": _holder_text(row["current_holders"]),
        }

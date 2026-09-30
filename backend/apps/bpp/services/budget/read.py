"""Чтение бюджета: карточка F-01, реестр L-01, версии, строки для заявки.

Видимость строк (ТЗ §6.1): ФД, ГД, ТД, ОД, АДМ видят все строки — у их
ролей открыты обе группы статей; СН и ПМ — только строки своей группы
статей (BR-010) и своих проектов (у ПМ — проекты-участия, BR-014).
Группы и проекты считает ``Actor``, здесь они только применяются.

«Оплачено факт» (ТЗ §6.4, CALC-007, D-S4-7) — ``bank.recon.paid_fact_by_article``,
показывается там же, где «Задействовано» (после первого утверждения). При
выключенном у компании ``bpp_bank`` — ``None``, как на графике дашборда
«Оплаты» (``dashboard/payments.article_chart``): одно число, одно правило.
"""

from __future__ import annotations

from decimal import Decimal

from apps.bpp.models import Budget, BudgetStatus, BudgetVersion, VersionState
from apps.bpp.services.actor import ROLE_GROUP, Actor
from apps.bpp.services.bank import recon as bank_recon
from apps.core.services import service_enabled
from apps.project import interface as projects
from apps.refdata import interface as refdata
from apps.users import interface as users

from . import budgets
from . import committed as calc

ZERO = Decimal("0.00")
BANK = "bpp_bank"


def _groups() -> dict[str, dict]:
    return {group["id"]: group for group in refdata.article_groups()}


def _paid_fact(project_id) -> dict[str, Decimal] | None:
    """``{article_id: оплачено факт}`` проекта; ``None`` — подмодуль выписки выключен."""
    return bank_recon.paid_fact_by_article(project_id) if service_enabled(BANK) else None


def _line_rows(actor: Actor, version: BudgetVersion, committed: dict[str, Decimal],
               *, show_committed: bool, paid: dict[str, Decimal] | None = None) -> list[dict]:
    lines = list(version.lines.all())
    briefs = refdata.article_brief([str(line.article_id) for line in lines])
    groups = _groups()
    rows = []
    for line in lines:
        brief = briefs.get(str(line.article_id))
        if not actor.sees_article(brief):
            continue
        group = groups.get(brief["group_id"], {})
        used = committed.get(str(line.article_id), ZERO) if show_committed else None
        paid_fact = (paid.get(str(line.article_id), ZERO)
                     if show_committed and paid is not None else None)
        rows.append({
            "id": str(line.id), "article_id": str(line.article_id),
            "article_code": brief["code"], "article_name": brief["name"],
            "article_archived": not brief["is_active"],
            "group_code": group.get("code", ""), "group_name": group.get("name", ""),
            "limit_amount": line.limit_amount, "comment": line.comment,
            "committed": used, "paid_fact": paid_fact,
            "available": None if used is None else line.limit_amount - used,
        })
    return rows


def _totals(rows: list[dict]) -> dict:
    """Итоги по бюджету и по группам статей; ``paid_fact`` — ``None``, если в
    строках его нет (бюджет не утверждён или выписка выключена)."""
    def total(key):
        return sum((row[key] or ZERO for row in rows), ZERO)

    paid_shown = any(row["paid_fact"] is not None for row in rows)
    by_group: dict[str, dict] = {}
    for row in rows:
        entry = by_group.setdefault(row["group_code"], {
            "group_code": row["group_code"], "group_name": row["group_name"],
            "limit_amount": ZERO, "committed": ZERO,
            "paid_fact": ZERO if paid_shown else None, "available": ZERO})
        entry["limit_amount"] += row["limit_amount"]
        entry["committed"] += row["committed"] or ZERO
        if paid_shown:
            entry["paid_fact"] += row["paid_fact"] or ZERO
        entry["available"] += row["available"] or ZERO
    return {"limit_amount": total("limit_amount"), "committed": total("committed"),
            "paid_fact": total("paid_fact") if paid_shown else None,
            "available": total("available"), "by_group": list(by_group.values())}


def _version_out(version: BudgetVersion | None, names: dict[int, str]) -> dict | None:
    if version is None:
        return None
    return {"id": str(version.id), "version_no": version.version_no, "state": version.state,
            "comment": version.comment, "approved_at": version.approved_at,
            "approved_by": version.approved_by,
            "approved_by_name": names.get(version.approved_by)}


def _names(user_ids) -> dict[int, str]:
    ids = [uid for uid in set(user_ids) if uid]
    return {row["id"]: row["full_name"] for row in users.get_users_brief(ids)} if ids else {}


def card(actor: Actor, budget: Budget) -> dict:
    project = projects.project_brief([str(budget.project_id)]).get(str(budget.project_id)) or {}
    active = budget.active_version
    draft = budget.versions.filter(state=VersionState.DRAFT).first()
    committed = calc.committed_by_article(budget.project_id)
    paid = _paid_fact(budget.project_id) if active is not None else None
    # Черновик бюджета — единственная версия и она же в форме; задействовано
    # по нему ещё не показывается (ТЗ §6.4: «после первого утверждения»).
    shown = active or budget.versions.get(version_no=1)
    rows = _line_rows(actor, shown, committed, show_committed=active is not None, paid=paid)
    correction = (_line_rows(actor, draft, committed, show_committed=True, paid=paid)
                  if draft is not None and active is not None else None)
    names = _names([budget.created_by, budget.updated_by,
                    active.approved_by if active else None])
    return {
        "id": str(budget.id), "number": budget.number, "status": budget.status,
        "version": budget.version, "currency_code": budget.currency_code,
        "project": {"id": str(budget.project_id), "code": project.get("code"),
                    "name": project.get("name"),
                    "customer_name": project.get("customer_name"),
                    "manager_user_id": project.get("manager_user_id")},
        "date_from": budget.date_from, "date_to": budget.date_to,
        "status_comment": budget.status_comment,
        "active_version": _version_out(active, names),
        "correction": None if correction is None else {
            "version_no": draft.version_no, "comment": draft.comment,
            "lines": correction, "totals": _totals(correction)},
        "lines": rows, "totals": _totals(rows),
        "created_at": budget.created_at, "created_by": budget.created_by,
        "created_by_name": names.get(budget.created_by),
        "updated_at": budget.updated_at,
        "allowed_actions": budgets.allowed_actions(actor, budget),
    }


def _visible(actor: Actor, *, status: str | None = None, project_id: str | None = None):
    """Выборка реестра L-01 — одна на страницу и выгрузку."""
    rows = Budget.objects.all().order_by("-created_at")
    if status:
        rows = rows.filter(status=status)
    if project_id:
        rows = rows.filter(project_id=project_id)
    if not actor.sees_all_projects:
        rows = rows.filter(project_id__in=list(actor.member_project_ids))
    return rows


def _registry_rows(actor: Actor, chunk: list[Budget]) -> list[dict]:
    briefs = projects.project_brief([str(b.project_id) for b in chunk])
    names = _names([b.active_version.approved_by for b in chunk if b.active_version])
    items = []
    for budget in chunk:
        version = budget.active_version or budget.versions.get(version_no=1)
        approved = budget.active_version is not None
        shown = _line_rows(actor, version, calc.committed_by_article(budget.project_id),
                           show_committed=approved,
                           paid=_paid_fact(budget.project_id) if approved else None)
        totals = _totals(shown)
        project = briefs.get(str(budget.project_id), {})
        items.append({
            "id": str(budget.id), "number": budget.number, "status": budget.status,
            "currency_code": budget.currency_code,
            "project": {"id": str(budget.project_id), "code": project.get("code"),
                        "name": project.get("name")},
            "version_no": budget.active_version.version_no if budget.active_version else 1,
            "limit_amount": totals["limit_amount"], "committed": totals["committed"],
            "paid_fact": totals["paid_fact"], "available": totals["available"],
            "approved_at": budget.active_version.approved_at if budget.active_version else None,
            "approved_by_name": names.get(budget.active_version.approved_by)
            if budget.active_version else None,
        })
    return items


def registry(actor: Actor, *, status: str | None = None, project_id: str | None = None,
             page: int = 1, page_size: int = 50) -> dict:
    """Реестр L-01: бюджеты видимых проектов со своими итогами."""
    rows = _visible(actor, status=status, project_id=project_id)
    total = rows.count()
    page_size = max(1, min(int(page_size or 50), 100))
    chunk = list(rows.select_related("active_version")[(page - 1) * page_size: page * page_size])
    items = _registry_rows(actor, chunk)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


# ── выгрузка реестра в xlsx (ТЗ §19, контракт A: ``export.respond``) ────

#: Путь пересборки для фоновой выгрузки (строка — её везёт брокер Celery).
EXPORT_REBUILD_PATH = "apps.bpp.services.budget.read.export_rows"
_EXPORT_CHUNK = 200


def export_count(*, user_id: int, company: str | None, is_superuser: bool = False,
                 filters: dict) -> int:
    actor = Actor.for_user(user_id, company=company, is_superuser=is_superuser)
    return _visible(actor, **filters).count()


def export_rows(*, user_id: int, company: str | None, is_superuser: bool = False,
                filters: dict):
    """Строки выгрузки — те же итоги, что на странице реестра: лимит,
    «Задействовано» и остаток по видимым пользователю строкам (BR-010)."""
    actor = Actor.for_user(user_id, company=company, is_superuser=is_superuser)
    rows = _visible(actor, **filters).select_related("active_version")
    chunk: list[Budget] = []
    for budget in rows.iterator(chunk_size=_EXPORT_CHUNK):
        chunk.append(budget)
        if len(chunk) == _EXPORT_CHUNK:
            yield from _export_chunk(actor, chunk)
            chunk = []
    if chunk:
        yield from _export_chunk(actor, chunk)


def _export_chunk(actor: Actor, chunk: list[Budget]):
    for row in _registry_rows(actor, chunk):
        yield {
            "number": row["number"], "project": row["project"]["code"],
            "project_name": row["project"]["name"],
            "status": BudgetStatus(row["status"]).label, "version_no": row["version_no"],
            "currency_code": row["currency_code"], "limit_amount": row["limit_amount"],
            "committed": row["committed"], "paid_fact": row["paid_fact"],
            "available": row["available"],
            "approved_at": row["approved_at"], "approved_by": row["approved_by_name"] or "",
        }


def versions(actor: Actor, budget: Budget) -> list[dict]:
    rows = list(budget.versions.exclude(state=VersionState.DRAFT))
    names = _names([v.approved_by for v in rows])
    return [_version_out(version, names) for version in rows]


def version_snapshot(actor: Actor, budget: Budget, version_no: int) -> dict:
    version = budget.versions.filter(version_no=version_no).exclude(
        state=VersionState.DRAFT).first()
    if version is None:
        from htqweb.errors import DomainError
        raise DomainError("E-NOT-FOUND", "Версия бюджета не найдена.", status=404)
    rows = _line_rows(actor, version, {}, show_committed=False)
    return {**_version_out(version, _names([version.approved_by])), "lines": rows,
            "totals": _totals(rows)}


def uuid_param(value, field: str) -> str:
    import uuid

    from htqweb.errors import DomainError

    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError):
        raise DomainError("E-VAL-01", "Некорректный идентификатор.",
                          fields=[{"field": field, "message": "Ожидается UUID"}]) from None


def require_article_visible(actor: Actor, project_id, article_id) -> None:
    """Остаток статьи — только тому, кто видит проект и группу статьи (ТЗ
    §28.1: «Backend проверяет роль и группу статьи»)."""
    from htqweb.errors import DomainError

    project_id, article_id = uuid_param(project_id, "project_id"), uuid_param(article_id, "article_id")
    brief = refdata.article_brief([article_id]).get(article_id)
    if not actor.sees_project(project_id) or not actor.sees_article(brief):
        raise DomainError("E-ACC-01", "У вас нет доступа к остатку этой статьи. Если это "
                                      "ошибка, обратитесь к администратору.", status=403)


def lines_for_request(actor: Actor, *, project_id, role: str) -> list[dict]:
    """GetBudgetLines (ТЗ §23): строки утверждённого бюджета проекта в группе
    роли инициатора, с остатком — для формы заявки."""
    project_id = uuid_param(project_id, "project_id")
    if role not in actor.initiator_roles() or not actor.sees_project(project_id):
        return []
    budget = Budget.objects.filter(project_id=project_id,
                                   status=BudgetStatus.APPROVED).first()
    if budget is None or budget.active_version is None:
        return []
    group_code = ROLE_GROUP.get(role)
    committed = calc.committed_by_article(project_id)
    rows = _line_rows(actor, budget.active_version, committed, show_committed=True)
    return [
        {"article_id": row["article_id"], "article_code": row["article_code"],
         "article_name": row["article_name"], "limit": row["limit_amount"],
         "committed": row["committed"], "available": row["available"]}
        for row in rows if row["group_code"] == group_code and not row["article_archived"]
    ]

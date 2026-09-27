"""План закупок — не модель, а выборка позиций (ТЗ §08, BR-020, BR-021, B2.3).

Позиции утверждённых заявок, у которых остаток к закупке > 0:

- СН и ПМ видят позиции, где они исполнители, в той роли инициатора, в
  которой смотрят план (ТЗ §8.1: СН — роль «СН», ПМ — роль «ПМ»);
- держатель ``bpp.plan.all`` (ФД) видит все позиции без действий.

Остатки — CALC-005 (количество) и CALC-006 (сумма). На этапе 2 договоров и
счетов нет, поэтому остаток равен плану; этап 3 (B3.3) вычитает договоры и
счета здесь же, в ``_remaining``.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.bpp.models import InitiatorRole, ItemStatus, PurchaseRequestItem, RequestStatus
from apps.bpp.services.actor import Actor
from apps.bpp.services.core import audit
from apps.project import interface as projects
from apps.refdata import interface as refdata
from apps.users import interface as users
from htqweb.errors import DomainError

OPEN = (ItemStatus.OPEN, ItemStatus.PARTIALLY_CLOSED)
SORTS = {
    "need_date": ("need_date", "sys_number"), "-need_date": ("-need_date", "sys_number"),
    "sys_number": ("sys_number",), "-sys_number": ("-sys_number",),
    "amount": ("amount", "sys_number"), "-amount": ("-amount", "sys_number"),
}
TARGETS = ("agreement", "invoice")


def _deny(text: str) -> DomainError:
    return DomainError("E-ACC-01", f"{text} Если это ошибка, обратитесь к администратору.",
                       status=403)


def sees_all(actor: Actor) -> bool:
    return actor.can("bpp.plan.all", "view")


def _role(actor: Actor, wanted: str | None) -> str:
    roles = actor.initiator_roles()
    if wanted:
        if wanted not in roles:
            raise _deny(f"Роль «{InitiatorRole(wanted).label}» вам не назначена.")
        return wanted
    if not roles:
        raise _deny("План закупок ведут снабженцы и руководители проектов.")
    return roles[0]


def _base():
    return (PurchaseRequestItem.objects
            .filter(request__status=RequestStatus.APPROVED, status__in=OPEN,
                    request__is_migrated=False)
            .select_related("request"))


def _remaining(item: PurchaseRequestItem) -> tuple[Decimal, Decimal]:
    """(остаток кол-ва CALC-005, остаток суммы CALC-006)."""
    return item.qty, item.amount


def _scoped(actor: Actor, role: str | None):
    rows = _base()
    if sees_all(actor) and not role:
        return rows, True
    role = _role(actor, role)
    return rows.filter(executor_id=actor.user_id, request__initiator_role=role), False


def _filtered(rows, filters: dict):
    if filters.get("project_ids"):
        rows = rows.filter(request__project_id__in=filters["project_ids"])
    if filters.get("article_ids"):
        rows = rows.filter(request__article_id__in=filters["article_ids"])
    if filters.get("name"):
        rows = rows.filter(name__icontains=filters["name"])
    if filters.get("search"):
        rows = rows.filter(Q(sys_number__icontains=filters["search"])
                           | Q(request__number__icontains=filters["search"]))
    if filters.get("purchase_type"):
        rows = rows.filter(request__purchase_type=filters["purchase_type"])
    if filters.get("need_from"):
        rows = rows.filter(need_date__gte=filters["need_from"])
    if filters.get("need_to"):
        rows = rows.filter(need_date__lte=filters["need_to"])
    if filters.get("overdue"):
        rows = rows.filter(need_date__lt=timezone.localdate())
    return rows


def plan_items(actor: Actor, *, role: str | None = None, filters: dict | None = None,
               sort: str = "need_date", page: int = 1, page_size: int = 50) -> dict:
    if not actor.can("bpp.plan", "view") and not sees_all(actor):
        raise _deny("У вас нет доступа к плану закупок.")
    rows, read_only = _scoped(actor, role)
    rows = _filtered(rows, filters or {}).order_by(*SORTS.get(sort, SORTS["need_date"]))
    total = rows.count()
    page_size = page_size if page_size in (25, 50, 100) else 50
    chunk = list(rows[(page - 1) * page_size: page * page_size])
    project_ids = {str(i.request.project_id) for i in chunk}
    article_ids = {str(i.request.article_id) for i in chunk if i.request.article_id}
    project_map = projects.project_brief(list(project_ids))
    article_map = refdata.article_brief(list(article_ids))
    uom_map = refdata.uom_brief(list({str(i.uom_id) for i in chunk}))
    names = ({row["id"]: row["full_name"]
              for row in users.get_users_brief(list({i.executor_id for i in chunk}))}
             if read_only and chunk else {})
    today = timezone.localdate()
    items = []
    for item in chunk:
        qty_left, amount_left = _remaining(item)
        req = item.request
        items.append({
            "id": str(item.id), "sys_number": item.sys_number,
            "request_id": str(req.id), "request_number": req.number,
            "project_id": str(req.project_id),
            "project_code": project_map.get(str(req.project_id), {}).get("code"),
            "article_id": str(req.article_id) if req.article_id else None,
            "article_name": article_map.get(str(req.article_id), {}).get("name"),
            "name": item.name, "uom": uom_map.get(str(item.uom_id), {}).get("short_name"),
            "qty": item.qty, "qty_in_agreements": Decimal("0"), "qty_in_invoices": Decimal("0"),
            "qty_left": qty_left, "amount": item.amount, "amount_in_invoices": Decimal("0.00"),
            "amount_left": amount_left, "need_date": item.need_date,
            "overdue": item.need_date < today, "purchase_type": req.purchase_type,
            "in_agreement_on_review": False,  # метка с этапа 3 (B3.1)
            "executor_id": item.executor_id, "executor_name": names.get(item.executor_id),
            "selectable": not read_only and qty_left > 0,
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "read_only": read_only}


def validate_selection(actor: Actor, item_ids: list[str], *, target: str,
                       role: str | None = None) -> dict:
    """ValidatePlanSelection (ТЗ §23): один проект и одна статья (BR-021),
    остаток > 0, позиции пользователя. Ответ — заготовка мастера F-03."""
    if target not in TARGETS:
        raise DomainError("E-VAL-01", "Неизвестный вид документа.",
                          fields=[{"field": "target", "message": "agreement или invoice"}])
    if not item_ids:
        raise DomainError("E-VAL-01", "Отметьте хотя бы одну позицию.",
                          fields=[{"field": "item_ids", "message": "Нет позиций"}])
    role = _role(actor, role)
    rows = list(_base().filter(pk__in=item_ids, executor_id=actor.user_id,
                               request__initiator_role=role))
    if len(rows) != len(set(map(str, item_ids))):
        raise DomainError(
            "E-PLAN-02", "Часть отмеченных позиций недоступна: их уже нет в вашем плане закупок. "
                         "Обновите список.",
            status=409, fields=[{"field": "item_ids", "message": "Позиции недоступны"}])
    pairs = {(str(r.request.project_id), str(r.request.article_id)) for r in rows}
    if len(pairs) > 1:
        raise DomainError(
            "BR-021", "Для одного документа выберите позиции одного проекта и одной статьи.",
            fields=[{"field": "item_ids", "message": "Разные проекты или статьи"}])
    empty = [r.sys_number for r in rows if _remaining(r)[0] <= 0]
    if empty:
        raise DomainError(
            "E-PLAN-01", f"У позиций {', '.join(empty)} не осталось количества к закупке.",
            fields=[{"field": "item_ids", "message": "Остаток 0"}])
    project_id, article_id = pairs.pop()
    purchase_types = {r.request.purchase_type for r in rows}
    return {
        "ok": True, "target": target, "project_id": project_id, "article_id": article_id,
        "purchase_type": purchase_types.pop() if len(purchase_types) == 1 else None,
        "items": [{"id": str(r.id), "sys_number": r.sys_number, "name": r.name,
                   "qty_left": _remaining(r)[0], "amount_left": _remaining(r)[1]}
                  for r in sorted(rows, key=lambda r: r.sys_number)],
    }


@transaction.atomic
def reassign(actor: Actor, item_ids: list[str], *, to_user_id: int) -> int:
    """«Переназначить исполнителя позиций» — АДМ (ТЗ §8.1): при увольнении
    позиции передаются другому снабженцу или ПМ."""
    if not actor.can("bpp.settings", "edit"):
        raise _deny("Переназначать исполнителя позиций может администратор модуля.")
    if not users.get_users_brief([to_user_id]):
        raise DomainError("E-NOT-FOUND", "Пользователь не найден.", status=404,
                          fields=[{"field": "to_user_id", "message": "Нет пользователя"}])
    rows = list(_base().select_for_update(of=("self",)).filter(pk__in=item_ids))
    for item in rows:
        before = item.executor_id
        item.executor_id, item.updated_by = to_user_id, actor.user_id
        item.version += 1
        item.save(update_fields=["executor_id", "updated_by", "version", "updated_at"])
        audit.record(item.request, "item_reassigned", actor_id=actor.user_id,
                     changes={"item": item.sys_number, "executor_id": [before, to_user_id]})
    return len(rows)

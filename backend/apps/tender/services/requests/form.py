"""Подсказки формы заявки tender: проекты, статьи бюджета и остаток статьи
(T1.3; план этапов 0–2, §3.4; мастер-план T-06).

Остаток и статьи даёт БЗО (``bpp.budget_available``, ``bpp.budget_articles``)
в правах пользователя и в роли заявки: ПМ — только проекты-участия (BR-014),
статьи — только группы роли (BR-010). Роль не передана — единственная роль
пользователя; если их две — E-REQ-01 «выберите роль».
"""

from __future__ import annotations

from apps.bpp import interface as bpp
from apps.project import interface as projects
from apps.tender.models import InitiatorRole
from htqweb.errors import DomainError

from . import crud
from .submit import tender_actor

PROJECTS_LIMIT = 20


def _role(ctx: crud.Ctx, role: str | None) -> str:
    if role and role not in InitiatorRole.values:
        raise crud._bad("role", "роль — sn или pm")
    return crud._role_for(ctx, role or None)


def _required(**params) -> None:
    missing = [name for name, value in params.items() if not value]
    if missing:
        raise DomainError("E-VAL-01", "Не заполнены параметры запроса.",
                          fields=[{"field": name, "message": "Обязательный параметр"}
                                  for name in missing])


def budget(ctx: crud.Ctx, *, project_id: str | None, article_id: str | None,
           role: str | None) -> dict:
    """``{limit, committed, available, currency_code}`` статьи по действующей
    версии бюджета проекта; резерв отправленных ЗЗ уже вычтен."""
    crud.require(ctx, "view")
    _required(project_id=project_id, article_id=article_id)
    figures = bpp.budget_available(project_id, article_id, actor=tender_actor(ctx),
                                   role=_role(ctx, role))
    return figures.model_dump(mode="json")


def articles(ctx: crud.Ctx, *, project_id: str | None, role: str | None) -> list[dict]:
    """Статьи утверждённого бюджета проекта из группы роли, с остатком."""
    crud.require(ctx, "view")
    _required(project_id=project_id)
    rows = bpp.budget_articles(project_id, actor=tender_actor(ctx), role=_role(ctx, role))
    return [row.model_dump(mode="json") for row in rows]


def project_list(ctx: crud.Ctx, *, query: str, role: str | None) -> list[dict]:
    """Действующие проекты для заявки ``[{id, code, name}]``: ПМ — только
    участия; СН — все. Нет роли БЗО, в которой подают заявки, — 403."""
    crud.require(ctx, "view")
    roles = crud.initiator_roles(ctx)
    if not roles:
        raise crud._deny("У вас нет роли БЗО, в которой подают заявки на закупку.")
    if role:
        role = _role(ctx, role)
        only_member = role == InitiatorRole.PM
    else:
        only_member = InitiatorRole.SN not in roles
    rows = projects.search_projects(query, user_id=ctx.user_id, only_member=only_member,
                                    limit=PROJECTS_LIMIT)
    return [{"id": row["id"], "code": row["code"], "name": row["name"]}
            for row in rows if row.get("status", "active") == "active"]

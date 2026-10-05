"""Помощники тестов этапа 2 (бюджет, заявка, план закупок — задачи B2.x).

Справочники (``refdata``) и пользователи живут в ``public``, проект,
бюджет, заявки и согласование — в схеме компании (``company_context``).
Роли модуля — системные ``bpp-*`` из миграции ``access/0014``.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.test import RequestFactory
from django.utils import timezone

from apps.access.models import Role, RoleAssignment, ScopeKind
from apps.access.tests.helpers import token
from apps.bpp.models import Budget
from apps.bpp.services.actor import Actor
from apps.bpp.services.budget import budgets
from apps.project.services import projects
from apps.refdata.models import Article, ArticleGroup, Uom
from apps.signoff import interface as signoff
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import decode_token

FD, TD, OD, SN, PM, SN2 = 901, 902, 903, 904, 905, 906


def user(user_id: int, name: str | None = None) -> User:
    found = User.objects.filter(pk=user_id).first()
    if found:
        return found
    name = name or f"u{user_id}"
    return User.objects.create(id=user_id, username=name, email=f"{name}@htq.test",
                               password="x", status=UserStatus.ACTIVE,
                               last_name=name.capitalize(), first_name="Тест")


def grant(slug: str | None, user_id: int, *codes: str) -> None:
    user(user_id)
    for code in codes:  # роли bpp-* — из миграции access/0014
        RoleAssignment.objects.get_or_create(
            company_slug=slug or "", user_id=user_id, role=Role.objects.get(code=code),
            scope_kind=ScopeKind.COMPANY, scope_id=None)


def actor(slug: str | None, user_id: int, *codes: str, superuser: bool = False) -> Actor:
    # Суперпользователю роли не нужны — и не выдаются: транзакционные тесты
    # идут после остальных, когда очистка базы уже стёрла посеянные роли.
    grant(slug, user_id, *(() if superuser else codes))
    request = RequestFactory().get("/")
    request.token = decode_token(token(user_id=user_id, sub=str(user_id), company=slug,
                                       is_superuser=superuser))
    request.company = {"slug": slug} if slug else None
    return Actor(request)


def auth(slug: str, user_id: int) -> dict:
    tok = token(user_id=user_id, sub=str(user_id), company=slug)
    return {"HTTP_AUTHORIZATION": f"Bearer {tok}", "HTTP_X_HTQ_COMPANY": slug,
            "content_type": "application/json"}


def project(code: str = "П-015", *, manager: int | None = None, members=()):
    obj = projects.create(code=code, name=f"Объект {code}", country_code="KZ",
                          manager_user_id=manager, actor_id=1)
    for member in members:
        projects.add_member(obj, member, actor_id=1)
    return obj


#: Группы статей из сида refdata/0002: транзакционный тест идёт после
#: очистки базы, где посеянных строк уже нет, поэтому — get_or_create.
GROUPS = {"supply": ("Снабжение", "bpp.articles.supply"),
          "pm": ("Проектное управление", "bpp.articles.pm")}


def article(code: str, name: str, group: str) -> Article:
    title, node = GROUPS[group]
    group_row = ArticleGroup.objects.get_or_create(
        code=group, defaults={"name": title, "node_key": node})[0]
    return Article.objects.get_or_create(code=code, defaults={"name": name, "group": group_row})[0]


def metal() -> Article:
    return article("T-METAL", "Металлопрокат", "supply")


def design() -> Article:
    return article("T-DESIGN", "Проектные работы", "pm")


def pcs() -> Uom:
    return Uom.objects.get_or_create(code="pcs", defaults={"short_name": "шт",
                                                            "name": "Штука"})[0]


def approved_budget(slug: str | None, proj, limits: dict, *, superuser=False) -> Budget:
    fd = actor(slug, FD, "bpp-fd", superuser=superuser)
    budget = budgets.create(fd, project_id=proj.id, lines=[
        {"article_id": str(art.id), "limit_amount": Decimal(str(limit))}
        for art, limit in limits.items()])
    return budgets.approve(fd, budget.id, expected_version=None)


def items(*pairs, days: int = 10) -> list[dict]:
    """Позиции ``(qty, price)`` — одна штука по цене = сумма."""
    need = timezone.localdate() + timedelta(days=days)
    return [{"name": f"Позиция {n}", "uom_id": str(pcs().id), "qty": Decimal(str(qty)),
             "price": Decimal(str(price)), "need_date": need}
            for n, (qty, price) in enumerate(pairs, start=1)]


def header(proj, art, *, role: str = "sn", days: int = 10) -> dict:
    return {"initiator_role": role, "project_id": str(proj.id), "article_id": str(art.id),
            "purchase_type": "goods",
            "need_date": timezone.localdate() + timedelta(days=days),
            "justification": "Нужно для монтажа каркаса"}


def request_route(*, td: int = TD, od: int = OD, comment_min: int = 10) -> int:
    """Маршрут заявки «ТД → ОД» поимённо (без HR-должностей) с флагами БЗО."""
    user(td), user(od)
    return signoff.configure_route(
        subject_type="bpp.purchase_request", name="ТД → ОД",
        stages=[{"order": 1, "name": "ТД", "quorum": "any", "approver_kind": "users",
                 "user_ids": [td]},
                {"order": 2, "name": "ОД", "quorum": "any", "approver_kind": "users",
                 "user_ids": [od]}],
        flags={"forbid_self_approval": True, "reject_comment_min": comment_min})


def task_of(req, user_id: int) -> int:
    process = signoff.get_process_for("bpp.purchase_request", str(req.pk))
    for stage in process["stages"]:
        for task in stage["tasks"]:
            if task["user_id"] == user_id and task["state"] == "pending":
                return task["id"]
    raise AssertionError(f"нет задачи пользователя {user_id}")


def decide(req, user_id: int, decision: str, comment: str = "") -> dict:
    return signoff.decide_many(actor_id=user_id, items=[
        {"task_id": task_of(req, user_id), "decision": decision, "comment": comment}])[0]

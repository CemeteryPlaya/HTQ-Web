"""Помощники тестов тендерного модуля.

Справочники (``refdata``) и пользователи живут в ``public``, проекты и заявки —
в схеме компании (``company_context``). Роли — системные ``tender-*``
(access/0027) и ``bpp-*`` (access/0014): закупщик подаёт заявку в роли БЗО.
"""

from __future__ import annotations

import json
from datetime import timedelta

from django.test import Client
from django.utils import timezone

from apps.access.models import Role, RoleAssignment, ScopeKind
from apps.access.tests.helpers import token
from apps.project.services import projects
from apps.refdata.models import Article, ArticleGroup, Uom
from apps.users.models import User, UserStatus

BASE = "/api/tender/v1"

#: Ключи, которых в ответе портала поставщика нет ни на какой глубине (план
#: этапа 3, §1): плановые цены, бюджет, другие участники, служебные ключи.
PORTAL_FORBIDDEN = {"plan_price", "delivery_plan_amount", "works_plan_amount", "budget",
                    "invitations", "counters", "token", "token_hash", "secret_hash",
                    "author_id"}
PORTAL_FORBIDDEN_PREFIXES = ("quality_reviewer", "bpp_")


def portal_forbidden_keys(value, path: str = "") -> list[str]:
    """Пути запрещённых ключей в ответе портала — рекурсивно."""
    found = []
    if isinstance(value, dict):
        for key, inner in value.items():
            if key in PORTAL_FORBIDDEN or key.startswith(PORTAL_FORBIDDEN_PREFIXES):
                found.append(f"{path}.{key}")
            found += portal_forbidden_keys(inner, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, inner in enumerate(value):
            found += portal_forbidden_keys(inner, f"{path}[{index}]")
    return found

SN, SN2, PM, FD, VIEWER, TD = 951, 952, 953, 954, 955, 956

GROUPS = {"supply": ("Снабжение", "bpp.articles.supply"),
          "pm": ("Проектное управление", "bpp.articles.pm")}


def user(user_id: int) -> User:
    found = User.objects.filter(pk=user_id).first()
    if found:
        return found
    name = f"t{user_id}"
    return User.objects.create(id=user_id, username=name, email=f"{name}@htq.test",
                               password="x", status=UserStatus.ACTIVE,
                               last_name=f"Тестов{user_id}", first_name="Иван")


def grant(slug: str, user_id: int, *codes: str) -> None:
    user(user_id)
    for code in codes:
        RoleAssignment.objects.get_or_create(
            company_slug=slug, user_id=user_id, role=Role.objects.get(code=code),
            scope_kind=ScopeKind.COMPANY, scope_id=None)


def staff(slug: str) -> None:
    """Закупщик-СН (два), ПМ, ФД, наблюдатель (ОД/БУХ), проверяющий (ТД)."""
    grant(slug, SN, "tender-buyer", "bpp-sn")
    grant(slug, SN2, "tender-buyer", "bpp-sn")
    grant(slug, PM, "tender-buyer", "bpp-pm")
    grant(slug, FD, "tender-fd", "bpp-fd")
    grant(slug, VIEWER, "tender-viewer")
    grant(slug, TD, "tender-quality")


def auth(slug: str, user_id: int) -> dict:
    tok = token(user_id=user_id, sub=str(user_id), company=slug)
    return {"HTTP_AUTHORIZATION": f"Bearer {tok}", "HTTP_X_HTQ_COMPANY": slug}


def call(method: str, path: str, slug: str, user_id: int, body=None):
    client = Client()
    kwargs = auth(slug, user_id)
    if body is not None:
        kwargs.update(data=json.dumps(body, default=str), content_type="application/json")
    return getattr(client, method)(f"{BASE}/{path}", **kwargs)


def project(code: str = "П-101", *, members=()):
    obj = projects.create(code=code, name=f"Объект {code}", country_code="KZ",
                          manager_user_id=None, actor_id=1)
    for member in members:
        projects.add_member(obj, member, actor_id=1)
    return obj


def article(code: str = "T-METAL", name: str = "Металлопрокат", group: str = "supply"):
    title, node = GROUPS[group]
    group_row = ArticleGroup.objects.get_or_create(
        code=group, defaults={"name": title, "node_key": node})[0]
    return Article.objects.get_or_create(code=code,
                                         defaults={"name": name, "group": group_row})[0]


def pcs() -> Uom:
    return Uom.objects.get_or_create(code="pcs", defaults={"short_name": "шт",
                                                            "name": "Штука"})[0]


def item(name: str = "Труба 57×3,5", qty="10", price="1500", **extra) -> dict:
    return {"name": name, "specs": "ГОСТ 8732", "uom_id": str(pcs().id), "qty": qty,
            "plan_price": price, **extra}


def body(proj, art=None, *, role: str = "sn", items=None, **extra) -> dict:
    data = {"initiator_role": role, "project_id": str(proj.id),
            "article_id": str((art or article()).id), "purchase_type": "goods",
            "need_date": str(timezone.localdate() + timedelta(days=14)),
            "justification": "Нужно для монтажа каркаса",
            "items": items if items is not None else [item()]}
    data.update(extra)
    return data


# ── тендеры и участники (T2.1, T2.2) ───────────────────────────────────────

def approved_request(slug: str, proj=None, *, author: int = SN):
    """Заявка автора в статусе «Утверждена» — прямо в таблице: отправку и
    свёртку статусов делает T1.3, тендеру нужна только утверждённая заявка."""
    from apps.tender.models import TenderRequest
    from htqweb.tenancy.db import use_company

    with use_company(slug):
        proj = proj or project(f"П-{900 + TenderRequest.objects.count()}")
    created = call("post", "requests", slug, author, body(proj))
    assert created.status_code == 201, created.content
    # Клиент после ответа возвращает search_path на public — контекст заново.
    with use_company(slug):
        TenderRequest.objects.filter(pk=created.json()["id"]).update(status="approved")
        return TenderRequest.objects.get(pk=created.json()["id"])


def counterparty(reg: str = "100000000001", *, status: str = "active", email: str = "",
                 name: str = "ТОО «Альфа»"):
    """Контрагент БЗО прямо в его таблице (тест — не сосед: сторож изоляции
    тесты не читает); в tender он виден только через ``bpp.interface``."""
    from apps.bpp.models import Counterparty

    return Counterparty.objects.create(name=name, kind="legal", country_code="KZ",
                                       reg_number=reg, status=status, email=email)


def future(days: int = 7) -> str:
    return (timezone.now() + timedelta(days=days)).isoformat()


def tender_body(req, **extra) -> dict:
    return {"request_id": str(req.id), "deadline_at": future(), "currency_code": "KZT",
            "delivery_terms": "DAP Астана", **extra}

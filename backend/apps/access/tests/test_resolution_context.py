"""Контекст разрешения: один расчёт на запрос вместо 35.

/me зовёт page_hidden по каждому узлу-странице (их 32) плюс permissions_for и
depth_map. Пока расчёт был внутри каждой функции, один запрос /me стоил 35
пересчётов ролей; после наследования (задача 5) каждый из них стоил бы ещё и
переключения схемы. Тест считает ЗАПРОСЫ, а не время: он обязан падать, если
кто-нибудь снова начнёт считать роли внутри цикла.
"""

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from apps.access.models import Role, RoleAssignment, ScopeKind
from apps.access.services import resolve
from apps.access.tests.helpers import BASE, auth, grant, token
from apps.companies.models import Company, CompanyKind

COMPANY = "htq-holding"


@pytest.fixture
def client():
    return Client()


@pytest.mark.django_db
def test_resolution_is_computed_once_and_reused(user, employee_with_position):
    res = resolve.resolve_for(user, COMPANY)
    with CaptureQueriesContext(connection) as ctx:
        resolve.permissions_for(user, COMPANY, resolution=res)
        resolve.depth_map(user, COMPANY, resolution=res)
        for route in ("/hr/employees", "/tasks", "/companies"):
            resolve.page_hidden(user, route, COMPANY, resolution=res)
    assert len(ctx.captured_queries) == 0, (
        "переданный Resolution не должен порождать запросов: "
        f"{[q['sql'] for q in ctx.captured_queries]}"
    )


@pytest.mark.django_db
def test_without_resolution_the_answer_is_the_same(user, employee_with_position):
    """Параметр — оптимизация, а не второй ответ."""
    res = resolve.resolve_for(user, COMPANY)
    assert (resolve.permissions_for(user, COMPANY)
            == resolve.permissions_for(user, COMPANY, resolution=res))
    assert (resolve.depth_map(user, COMPANY)
            == resolve.depth_map(user, COMPANY, resolution=res))


@pytest.mark.django_db
def test_me_endpoint_computes_roles_once(client, user, employee_with_position):
    """Сторож на сам эндпоинт: 32 страницы не должны стоить 32 расчётов.

    До починки MeView зовёт page_hidden один раз на узел-страницу (их 32)
    плюс permissions_for и depth_map — каждый вызов пересчитывал роли и
    отдельно бил в access_rolepermission, то есть запросов к этой таблице
    было ПОРЯДКА ЧИСЛА СТРАНИЦ (фактически — 34 при прогоне этого же теста
    против кода до Step 3-4 брифа). После починки Resolution строится один
    раз на весь запрос, а _rows_by_role (единственное место, читающее
    access_rolepermission) вызывается ровно один раз внутри resolve_for —
    отсюда точное число "1", а не просто верхняя граница: число подобрано
    наблюдением за фактическим прогоном этого теста, а не взято с потолка.
    "==1", а не "<=1" — точное равенство ловит и рост (снова считать роли
    в цикле), и случайное исчезновение этого единственного запроса (кто-то
    закэшировал не то и сломал наблюдаемость), а не только регрессию в одну
    сторону.
    """
    Company.objects.create(slug=COMPANY, name="ХТЛ Холдинг", kind=CompanyKind.HOLDING)
    role = Role.objects.create(code="r-me", title="Роль /me")
    grant(role, "hr", "write")
    RoleAssignment.objects.create(company_slug=COMPANY, user_id=user.id, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)

    tok = token(user_id=user.id, sub=str(user.id), company=COMPANY)
    with CaptureQueriesContext(connection) as ctx:
        resp = client.get(f"{BASE}/me", HTTP_X_HTQ_COMPANY=COMPANY, **auth(tok))
    assert resp.status_code == 200

    role_permission_queries = [
        q for q in ctx.captured_queries if "access_rolepermission" in q["sql"]
    ]
    assert len(role_permission_queries) == 1, (
        f"запросов к access_rolepermission: {len(role_permission_queries)} — "
        "должен быть ровно 1 (один расчёт Resolution на /me), не должно расти "
        "с числом страниц: "
        f"{[q['sql'] for q in role_permission_queries]}"
    )

"""Роль может принадлежать компании (блок I.2, R2).

Каталог ролей общий на группу, но именная роль должности несёт её название.
Показывать её соседним компаниям незачем, выдавать — тем более.

``member_auth`` собран здесь же (в файле ``test_module_gate.py`` фикстуры с
таким именем нет): токен обычного вошедшего пользователя + заголовок
компании, тем же приёмом, что и ``headers()`` в соседних тестах каталога
(``test_module_gate.py``). Чтение каталога — ручка без гейта модуля (реестр
самообслуживания, причина ``open``), ей нужен только JWT.
"""

import pytest
from django.test import Client

from apps.access.models import Role
from apps.access.tests.helpers import BASE, auth, put_json, staff_token, token


@pytest.fixture
def member_auth(company_row):
    return {"HTTP_X_HTQ_COMPANY": company_row, **auth(token(company=company_row))}


@pytest.mark.django_db
def test_catalog_hides_roles_of_other_companies(company_row, member_auth):
    Role.objects.create(code="hr-custom-other-7", title="Кадры: должность X",
                        company_slug="other-company")
    resp = Client().get(f"{BASE}/roles", **member_auth)
    codes = {row["code"] for row in resp.json()}
    assert "hr-custom-other-7" not in codes


@pytest.mark.django_db
def test_catalog_shows_roles_of_own_company(company_row, member_auth):
    Role.objects.create(code=f"hr-custom-{company_row}-7", title="Кадры: должность Y",
                        company_slug=company_row)
    resp = Client().get(f"{BASE}/roles", **member_auth)
    codes = {row["code"] for row in resp.json()}
    assert f"hr-custom-{company_row}-7" in codes


@pytest.mark.django_db
def test_catalog_shows_group_wide_roles(company_row, member_auth):
    resp = Client().get(f"{BASE}/roles", **member_auth)
    codes = {row["code"] for row in resp.json()}
    assert "employee-basic" in codes


@pytest.mark.django_db
def test_catalog_without_company_context_shows_only_group_wide_roles(company_row):
    """Голый домен: заголовка компании нет, ``current_company_or_none`` — None.

    Фильтр ``Q(company_slug__isnull=True) | Q(company_slug=None)`` в этом
    случае отдаёт только общие роли — соседняя роль не должна протечь просто
    потому, что контекста компании нет вовсе.
    """
    Role.objects.create(code=f"hr-custom-{company_row}-9", title="Кадры: должность Z",
                        company_slug=company_row)
    resp = Client().get(f"{BASE}/roles", **auth(token()))
    assert resp.status_code == 200
    codes = {row["code"] for row in resp.json()}
    assert f"hr-custom-{company_row}-9" not in codes
    assert "employee-basic" in codes


@pytest.mark.django_db
def test_position_role_of_another_company_is_rejected(company_row):
    from apps.access.services import assignment

    role = Role.objects.create(code="hr-custom-other-7", title="Чужая",
                               company_slug="other-company")
    with pytest.raises(assignment.RoleNotInCompany):
        assignment.set_position_roles(company_row, 7, [role.id])


@pytest.mark.django_db
def test_user_assignment_of_another_companys_role_is_rejected(company_row):
    """Функция выдачи роли пользователю в этом кодовой базе — не ``assign_role``
    (такой функции нет), а ``set_user_assignments`` — замена набора личных
    назначений целиком; PUT ``assignments/<user_id>`` — её единственный
    HTTP-вход (``UserAssignmentsView.put``)."""
    from apps.access.services import assignment

    role = Role.objects.create(code="hr-custom-other-7", title="Чужая",
                               company_slug="other-company")
    with pytest.raises(assignment.RoleNotInCompany):
        assignment.set_user_assignments(
            company_row, 5,
            [{"role_id": role.id, "scope_kind": "company", "scope_id": None}],
        )


@pytest.mark.django_db
def test_api_rejects_assigning_another_companys_role_with_422(company_row):
    """Исключение ``RoleNotInCompany`` доходит до клиента как 422, не 500."""
    from apps.access.tests.helpers import assign

    role = Role.objects.create(code="hr-custom-other-7", title="Чужая",
                               company_slug="other-company")
    # staff_token несёт user_id=8 (helpers.py) — ему выдаём admin-уровень на
    # модуль access, иначе запрос остановится на гейте раньше вьюхи.
    assign(company_row, 8, "access", "full")
    head = {"HTTP_X_HTQ_COMPANY": company_row, **auth(staff_token(company=company_row))}
    resp = put_json(
        Client(), f"{BASE}/assignments/5",
        [{"role_id": role.id, "scope_kind": "company", "scope_id": None}],
        **head,
    )
    assert resp.status_code == 422

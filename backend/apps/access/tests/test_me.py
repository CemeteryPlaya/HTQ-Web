"""Задача 8 плана A: ``GET /me`` и та же карта прав в ответе профиля (§4.5)."""

import datetime

import pytest
from django.test import Client

from apps.access.models import Level, PositionRole, Role, RoleAssignment, ScopeKind
from apps.access.tests.helpers import BASE, auth, superuser_token, token
from apps.access.tests.helpers import grant
from apps.access.views import cap_for_archive
from apps.companies.models import Company, CompanyStatus


@pytest.fixture
def client():
    return Client()


@pytest.mark.django_db
def test_me_requires_authentication(client):
    assert client.get(f"{BASE}/me").status_code == 401


@pytest.mark.django_db
def test_me_without_company_is_not_an_error(client):
    """Переходный режим подпроекта 1: контекста компании нет — это не сбой."""
    resp = client.get(f"{BASE}/me", **auth(token()))
    assert resp.status_code == 200
    assert resp.json() == {"company": None, "permissions": {}, "depth": {},
                           "hidden_pages": [], "subordinate_companies": [],
                           "inherited_from": [], "company_archived": False}


@pytest.mark.django_db
def test_me_returns_permissions_of_the_request_company(client, company_schema):
    slug = company_schema["slug"]
    role = Role.objects.create(code="r", title="Роль")
    grant(role, "hr", "write")
    RoleAssignment.objects.create(company_slug=slug, user_id=7, role=role,
                                  scope_kind=ScopeKind.DEPARTMENT, scope_id=3)

    resp = client.get(f"{BASE}/me", HTTP_X_HTQ_COMPANY=slug,
                      **auth(token(company=slug)))
    assert resp.status_code == 200
    assert resp.json() == {
        "company": slug,
        "permissions": {"hr": {"level": "write",
                               "scope": {"kind": "department", "id": 3}}},
        # Полная картина по узлам — из неё уровень модуля и посчитан.
        "depth": {"hr": ["create", "edit", "view"]},
        # Страница — вето: без явного запрета список пуст.
        "hidden_pages": [],
        "subordinate_companies": [],
        "inherited_from": [],
        "company_archived": False,
    }


@pytest.mark.django_db
def test_modules_with_none_are_absent_from_me(client, company_schema):
    slug = company_schema["slug"]
    resp = client.get(f"{BASE}/me", HTTP_X_HTQ_COMPANY=slug,
                      **auth(token(company=slug)))
    assert resp.json()["permissions"] == {}


@pytest.mark.django_db
def test_superuser_sees_admin_on_every_module(client, company_schema):
    from apps.core.models import KNOWN_SERVICES

    slug = company_schema["slug"]
    resp = client.get(f"{BASE}/me", HTTP_X_HTQ_COMPANY=slug,
                      **auth(superuser_token(company=slug)))
    perms = resp.json()["permissions"]
    assert set(perms) == set(KNOWN_SERVICES)
    assert all(entry["level"] == "admin" for entry in perms.values())


# ── Та же карта в профиле ─────────────────────────────────────────────────


@pytest.mark.django_db
def test_profile_carries_the_same_permission_map(client, company_schema, django_user_model):
    """Чтобы фронт не делал второй запрос на каждой загрузке (спека A7)."""
    slug = company_schema["slug"]
    user = django_user_model.objects.create_user(username="u", email="u@htq.test",
                                                 password="x")
    role = Role.objects.create(code="r", title="Роль")
    grant(role, "tasks", "read")
    RoleAssignment.objects.create(company_slug=slug, user_id=user.id, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)

    tok = token(user_id=user.id, sub=str(user.id), company=slug)
    me = client.get(f"{BASE}/me", HTTP_X_HTQ_COMPANY=slug, **auth(tok)).json()
    profile = client.get("/api/users/v1/profile/me", HTTP_X_HTQ_COMPANY=slug,
                         **auth(tok)).json()

    assert profile["permissions"] == me["permissions"]
    assert profile["company"] == me["company"]
    assert profile["subordinate_companies"] == me["subordinate_companies"]


# ── Задача 6 блока C: /me называет источник наследованных прав ─────────────
#
# Схемы компаний здесь настоящие (``two_company_schemas``/``company_schema``
# из корневого conftest) — тот же приём, что в ``test_inheritance.py``:
# кадровая карточка обязана лечь в СВОЮ физическую схему, иначе тест не
# отличит «дошли до предка через его схему» от случайного совпадения с
# default.


def _link(child_slug: str, parent_slug: str) -> None:
    from apps.companies.models import Company

    child = Company.objects.get(slug=child_slug)
    child.parent = Company.objects.get(slug=parent_slug)
    child.save(update_fields=["parent"])


def _grant_serving_position(company_slug: str, user, role: Role, *, weight: int):
    from apps.hr.models import Department, Employee, Position
    from htqweb.tenancy.db import use_company

    with use_company(company_slug):
        dep = Department.objects.create(name=f"Отдел-{weight}", path=f"root-{weight}")
        pos = Position.objects.create(
            title=f"Должность-{weight}", department=dep, weight=weight,
            serves_subsidiaries=True,
        )
        Employee.objects.create(
            first_name="Имя", last_name="Фамилия", email=f"e-{weight}@htq.test",
            department=dep, position=pos,
            hire_date=datetime.date(2024, 1, 9), user_id=user.id,
        )
        PositionRole.objects.create(
            company_slug=company_slug, position_id=pos.id, role=role)


@pytest.mark.django_db(transaction=True)
def test_me_names_the_serving_ancestor(client, two_company_schemas, user):
    """Единственный обслуживающий предок — ``inherited_from == [его слаг]``."""
    holding, subsidiary = two_company_schemas
    _link(subsidiary, holding)

    role = Role.objects.create(code="r-me-inh", title="Роль наследуется")
    _grant_serving_position(holding, user, role, weight=1)

    tok = token(user_id=user.id, sub=str(user.id), company=subsidiary)
    resp = client.get(f"{BASE}/me", HTTP_X_HTQ_COMPANY=subsidiary, **auth(tok))
    assert resp.status_code == 200
    assert resp.json()["inherited_from"] == [holding]


@pytest.mark.django_db(transaction=True)
def test_me_inherited_from_empty_for_ordinary_subsidiary_employee(
        client, two_company_schemas, user):
    """Предок существует, но не обслуживает — объяснять пользователю нечего."""
    holding, subsidiary = two_company_schemas
    _link(subsidiary, holding)

    tok = token(user_id=user.id, sub=str(user.id), company=subsidiary)
    resp = client.get(f"{BASE}/me", HTTP_X_HTQ_COMPANY=subsidiary, **auth(tok))
    assert resp.status_code == 200
    assert resp.json()["inherited_from"] == []


@pytest.mark.django_db
def test_me_inherited_from_empty_for_superuser(client, company_schema):
    """Суперпользователь: права ниоткуда не наследуются, а не «неизвестно откуда»."""
    slug = company_schema["slug"]
    resp = client.get(f"{BASE}/me", HTTP_X_HTQ_COMPANY=slug,
                      **auth(superuser_token(company=slug)))
    assert resp.status_code == 200
    assert resp.json()["inherited_from"] == []


@pytest.mark.django_db(transaction=True)
def test_me_names_both_serving_ancestors_sorted(
        client, two_company_schemas, company_schema, user):
    """Два обслуживающих предка (решение 7: не взаимоисключающи) — оба, по алфавиту."""
    grandparent, parent = two_company_schemas
    bottom = company_schema["slug"]
    _link(parent, grandparent)
    _link(bottom, parent)

    role_grandparent = Role.objects.create(code="r-me-gp", title="Роль деда")
    role_parent = Role.objects.create(code="r-me-p", title="Роль родителя")
    _grant_serving_position(grandparent, user, role_grandparent, weight=1)
    _grant_serving_position(parent, user, role_parent, weight=2)

    tok = token(user_id=user.id, sub=str(user.id), company=bottom)
    resp = client.get(f"{BASE}/me", HTTP_X_HTQ_COMPANY=bottom, **auth(tok))
    assert resp.status_code == 200
    assert resp.json()["inherited_from"] == sorted([grandparent, parent])


@pytest.mark.django_db
def test_roles_for_still_returns_three_values(django_user_model):
    """Снимать их до задачи B4 значит уронить вход в систему (спека A7)."""
    from apps.users.services.profile_service import roles_for

    user = django_user_model.objects.create_user(username="plain", email="p@htq.test",
                                                 password="x")
    assert roles_for(user) == ["user"]
    user.is_staff = True
    assert roles_for(user) == ["staff"]
    user.is_superuser = True
    assert roles_for(user) == ["admin"]


@pytest.mark.django_db
def test_me_in_archived_company_caps_everything_at_read(client, company_schema):
    """Архив — только чтение (спека архива §7.1): сюда доходит только
    суперпользователь, и его ``admin`` везде понижается до ``read`` — кнопки,
    скрытые по usePermissions, исчезают сами. Сервер на уровень не опирается:
    запись закрыта middleware."""
    slug = company_schema["slug"]
    Company.objects.filter(slug=slug).update(status=CompanyStatus.ARCHIVED)

    resp = client.get(f"{BASE}/me", HTTP_X_HTQ_COMPANY=slug,
                      **auth(superuser_token(company=slug)))

    assert resp.status_code == 200
    body = resp.json()
    assert body["company_archived"] is True
    assert body["permissions"], "у суперпользователя модули есть всегда"
    assert {entry["level"] for entry in body["permissions"].values()} == {"read"}
    assert body["depth"]
    assert all(flags == ["view"] for flags in body["depth"].values())


@pytest.mark.django_db
def test_me_in_active_company_is_not_capped(client, company_schema):
    slug = company_schema["slug"]

    resp = client.get(f"{BASE}/me", HTTP_X_HTQ_COMPANY=slug,
                      **auth(superuser_token(company=slug)))

    assert resp.status_code == 200
    body = resp.json()
    assert body["company_archived"] is False
    assert {entry["level"] for entry in body["permissions"].values()} == {"admin"}


def test_cap_for_archive_keeps_explicit_node_denial_empty():
    """Узел без ``view`` — явный запрет, а не наследование (ревью задачи 5a).

    ``depthFor`` на фронте (``lib/auth/permissions.ts``) трактует
    ОТСУТСТВУЮЩИЙ ключ как «взять права предка», а пустой список — как явный
    запрет. Выбрасывать такие узлы из карты (как было раньше) значило бы
    превращать запрет в наследование прав предка в архиве.
    """
    depth = {"hr": ["view", "edit"], "hr.employees.salary": [], "hr.x": ["create"]}
    _, capped_depth = cap_for_archive({}, depth)
    assert capped_depth == {"hr": ["view"], "hr.employees.salary": [], "hr.x": []}


def test_cap_for_archive_lowers_permission_levels_to_read():
    permissions = {
        "hr": {"level": "admin", "scope": {"kind": "company", "id": None}},
        "tasks": {"level": "write", "scope": {"kind": "department", "id": 3}},
        "mail": {"level": "read", "scope": {"kind": "company", "id": None}},
    }
    capped_permissions, _ = cap_for_archive(permissions, {})
    assert capped_permissions == {
        "hr": {"level": "read", "scope": {"kind": "company", "id": None}},
        "tasks": {"level": "read", "scope": {"kind": "department", "id": 3}},
        "mail": {"level": "read", "scope": {"kind": "company", "id": None}},
    }

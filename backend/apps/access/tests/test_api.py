"""Задача 7 плана A: API по замороженному контракту §4 спеки.

Проверяются КОДЫ ОТВЕТОВ и форма тел — то, на что опирается исполнитель B.
Доменное поведение (замена набора целиком, изоляция компаний) закрыто тестами
сервисов; здесь — только стык.
"""

import pytest
from django.test import Client

from apps.access.models import (
    Level,
    PositionRole,
    Role,
    RoleAssignment,
    ScopeKind,
)
from apps.access.tests.helpers import (
    grant,
    BASE,
    auth,
    patch_json,
    post_json,
    put_json,
    staff_token,
    superuser_token,
    token,
)


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def company(company_schema):
    """Компания с мигрированной схемой + заголовок шлюза и claim токена."""
    return company_schema["slug"]


def headers(slug: str, tok: str) -> dict:
    """Заголовки как их ставит шлюз: слаг компании + токен, выданный на неё."""
    return {"HTTP_X_HTQ_COMPANY": slug, **auth(tok)}


# ── Каталог ролей (§4.1) ──────────────────────────────────────────────────


@pytest.mark.django_db
def test_roles_require_authentication(client):
    assert client.get(f"{BASE}/roles").status_code == 401


@pytest.mark.django_db
def test_list_roles(client):
    """В каталоге уже есть засеянная platform-admin — проверяем состав, а не длину.

    Роль-минимум приходит миграцией 0002 и существует в любой базе: без неё
    систему прав некому раздать. Тест, ожидающий пустой каталог, проверял бы
    отсутствие этого засева, а не работу ручки.
    """
    Role.objects.create(code="a", title="Альфа")
    resp = client.get(f"{BASE}/roles", **auth(token()))
    assert resp.status_code == 200
    by_code = {row["code"]: row for row in resp.json()}
    assert by_code["a"] == {"id": Role.objects.get(code="a").id, "code": "a",
                            "title": "Альфа", "is_system": False}
    assert by_code["platform-admin"]["is_system"] is True


@pytest.mark.django_db
def test_both_spellings_answer_the_same(client):
    tok = auth(token())
    assert (client.get(f"{BASE}/roles", **tok).status_code
            == client.get(f"{BASE}/roles/", **tok).status_code == 200)


@pytest.mark.django_db
def test_superuser_creates_a_role(client):
    resp = post_json(client, f"{BASE}/roles", {"code": "hr-admin", "title": "Кадры"},
                     **auth(superuser_token()))
    assert resp.status_code == 201
    assert resp.json()["code"] == "hr-admin"


@pytest.mark.django_db
def test_staff_may_not_touch_the_shared_catalog(client):
    """Каталог общий: правка меняет доступ во всех компаниях сразу (§4.1)."""
    resp = post_json(client, f"{BASE}/roles", {"code": "x", "title": "X"},
                     **auth(staff_token()))
    assert resp.status_code == 403
    assert not Role.objects.filter(code="x").exists()


@pytest.mark.django_db
def test_plain_user_may_not_create_a_role(client):
    resp = post_json(client, f"{BASE}/roles", {"code": "x", "title": "X"},
                     **auth(token()))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_duplicate_code_is_422(client):
    Role.objects.create(code="dup", title="Первая")
    resp = post_json(client, f"{BASE}/roles", {"code": "dup", "title": "Вторая"},
                     **auth(superuser_token()))
    assert resp.status_code == 422


@pytest.mark.django_db
def test_bad_code_is_422(client):
    resp = post_json(client, f"{BASE}/roles", {"code": "с пробелом", "title": "X"},
                     **auth(superuser_token()))
    assert resp.status_code == 422


@pytest.mark.django_db
def test_rename_role(client):
    role = Role.objects.create(code="r", title="Старое")
    resp = patch_json(client, f"{BASE}/roles/{role.id}", {"title": "Новое"},
                      **auth(superuser_token()))
    assert resp.status_code == 200
    assert resp.json()["title"] == "Новое"


@pytest.mark.django_db
def test_rename_missing_role_is_404(client):
    resp = patch_json(client, f"{BASE}/roles/999999", {"title": "Новое"},
                      **auth(superuser_token()))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_delete_unused_role(client):
    role = Role.objects.create(code="temp", title="Временная")
    assert client.delete(f"{BASE}/roles/{role.id}",
                         **auth(superuser_token())).status_code == 200
    assert not Role.objects.filter(id=role.id).exists()


@pytest.mark.django_db
def test_delete_used_role_returns_409_with_counts(client):
    role = Role.objects.create(code="used", title="Занятая")
    PositionRole.objects.create(company_slug="htq-kz", position_id=1, role=role)
    RoleAssignment.objects.create(company_slug="htq-kz", user_id=1, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)
    resp = client.delete(f"{BASE}/roles/{role.id}", **auth(superuser_token()))
    assert resp.status_code == 409
    assert resp.json() == {"detail": "in_use", "positions": 1, "users": 1}


@pytest.mark.django_db
def test_delete_system_role_is_409(client):
    role = Role.objects.create(code="sys", title="Системная", is_system=True)
    assert client.delete(f"{BASE}/roles/{role.id}",
                         **auth(superuser_token())).status_code == 409


# ── Права роли (§4.2) ─────────────────────────────────────────────────────


@pytest.mark.django_db
def test_get_role_permissions(client):
    role = Role.objects.create(code="r", title="Роль")
    grant(role, "hr", "write")
    resp = client.get(f"{BASE}/roles/{role.id}/permissions", **auth(token()))
    assert resp.status_code == 200
    assert resp.json() == [{"node": "hr", "flags": ["create", "edit", "view"],
                            "preset": "edit"}]


@pytest.mark.django_db
def test_put_role_permissions_replaces_the_whole_set(client):
    role = Role.objects.create(code="r", title="Роль")
    grant(role, "tasks", "admin")
    resp = put_json(client, f"{BASE}/roles/{role.id}/permissions",
                    [{"node": "hr", "preset": "view"}], **auth(superuser_token()))
    assert resp.status_code == 200
    assert resp.json() == [{"node": "hr", "flags": ["view"], "preset": "view"}]


@pytest.mark.django_db
def test_put_role_permissions_rejects_unknown_node(client):
    """Право на несуществующую функцию никогда ни на что не влияет."""
    role = Role.objects.create(code="r", title="Роль")
    resp = put_json(client, f"{BASE}/roles/{role.id}/permissions",
                    [{"node": "hr.выдумка", "preset": "view"}],
                    **auth(superuser_token()))
    assert resp.status_code == 422


@pytest.mark.django_db
def test_put_role_permissions_accepts_a_field_node(client):
    """Глубина назначается и на поле — третий уровень реестра."""
    role = Role.objects.create(code="r", title="Роль")
    resp = put_json(client, f"{BASE}/roles/{role.id}/permissions", [
        {"node": "hr", "preset": "view"},
        {"node": "hr.employees.salary", "preset": "none"},
    ], **auth(superuser_token()))
    assert resp.status_code == 200
    nodes = {row["node"]: row["preset"] for row in resp.json()}
    assert nodes == {"hr": "view", "hr.employees.salary": "none"}


@pytest.mark.django_db
def test_preset_and_flags_together_are_422(client):
    """Два способа сказать одно и то же — угадывать в правах нельзя."""
    role = Role.objects.create(code="r", title="Роль")
    resp = put_json(client, f"{BASE}/roles/{role.id}/permissions",
                    [{"node": "hr", "preset": "view", "flags": ["view"]}],
                    **auth(superuser_token()))
    assert resp.status_code == 422


@pytest.mark.django_db
def test_functions_registry_is_readable(client):
    resp = client.get(f"{BASE}/functions", **auth(token()))
    assert resp.status_code == 200
    body = resp.json()
    modules = {row["path"] for row in body["tree"]}
    assert "hr" in modules
    assert [f["key"] for f in body["flags"]] == ["view", "create", "edit", "delete"]
    assert {"none", "view", "create", "edit", "delete", "full"} <= {
        p["key"] for p in body["presets"]}
    # Страницы приезжают отдельным списком: они не входят в точечное дерево
    # модулей, потому что страница может собирать данные нескольких доменов.
    assert any(page["route"] == "/hr/employees" for page in body["pages"])


@pytest.mark.django_db
def test_put_role_permissions_is_platform_only(client):
    role = Role.objects.create(code="r", title="Роль")
    resp = put_json(client, f"{BASE}/roles/{role.id}/permissions",
                    [{"node": "hr", "preset": "view"}], **auth(staff_token()))
    assert resp.status_code == 403


# ── Роли должности (§4.3) ─────────────────────────────────────────────────


@pytest.fixture
def position(company):
    """Должность внутри схемы компании — как она и живёт в проде."""
    from django.db import connection
    from htqweb.tenancy.db import use_company

    with use_company(company):
        from apps.hr.models import Department, Position

        dep = Department.objects.create(name="ИТ", path="it")
        pos = Position.objects.create(title="Инженер", department=dep, weight=100)
        position_id = pos.id

    yield position_id

    # Отложенные FK-триггеры этих вставок висят «pending» до конца транзакции
    # теста, а ``_truncate_schema`` в teardown фикстуры ``company_schema``
    # выполняет TRUNCATE — Postgres отказывает, пока в транзакции есть
    # несработавшие события триггеров. Форсируем их здесь: teardown фикстур
    # идёт в обратном порядке, поэтому это выполняется ДО очистки схемы.
    connection.check_constraints()


@pytest.mark.django_db
def test_put_position_roles(client, company, position):
    role = Role.objects.create(code="r", title="Роль")
    resp = put_json(client, f"{BASE}/positions/{position}/roles",
                    {"role_ids": [role.id]},
                    **headers(company, superuser_token(company=company)))
    assert resp.status_code == 200
    assert resp.json() == [{"role_id": role.id, "code": "r", "title": "Роль"}]


@pytest.mark.django_db
def test_put_position_roles_rejects_unknown_role(client, company, position):
    resp = put_json(client, f"{BASE}/positions/{position}/roles",
                    {"role_ids": [999999]},
                    **headers(company, superuser_token(company=company)))
    assert resp.status_code == 422


@pytest.mark.django_db
def test_unknown_position_is_404(client, company):
    resp = put_json(client, f"{BASE}/positions/999999/roles", {"role_ids": []},
                    **headers(company, superuser_token(company=company)))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_position_roles_without_company_context_are_404(client, position):
    """Вне компании привязки не существует — это 404, а не 400."""
    resp = client.get(f"{BASE}/positions/{position}/roles", **auth(token()))
    assert resp.status_code == 404


# ── Личные назначения (§4.4) ──────────────────────────────────────────────


@pytest.mark.django_db
def test_put_user_assignments(client, company):
    role = Role.objects.create(code="r", title="Роль")
    resp = put_json(client, f"{BASE}/assignments/42",
                    [{"role_id": role.id, "scope_kind": "company", "scope_id": None}],
                    **headers(company, superuser_token(company=company)))
    assert resp.status_code == 200
    assert resp.json() == [{"role_id": role.id, "scope_kind": "company",
                            "scope_id": None}]


@pytest.mark.django_db
def test_company_scope_with_scope_id_is_422(client, company):
    role = Role.objects.create(code="r", title="Роль")
    resp = put_json(client, f"{BASE}/assignments/42",
                    [{"role_id": role.id, "scope_kind": "company", "scope_id": 3}],
                    **headers(company, superuser_token(company=company)))
    assert resp.status_code == 422


@pytest.mark.django_db
def test_department_scope_without_scope_id_is_422(client, company):
    role = Role.objects.create(code="r", title="Роль")
    resp = put_json(client, f"{BASE}/assignments/42",
                    [{"role_id": role.id, "scope_kind": "department", "scope_id": None}],
                    **headers(company, superuser_token(company=company)))
    assert resp.status_code == 422


@pytest.mark.django_db
def test_unknown_scope_kind_is_422(client, company):
    role = Role.objects.create(code="r", title="Роль")
    resp = put_json(client, f"{BASE}/assignments/42",
                    [{"role_id": role.id, "scope_kind": "вселенная", "scope_id": None}],
                    **headers(company, superuser_token(company=company)))
    assert resp.status_code == 422


@pytest.mark.django_db
def test_assignments_are_scoped_to_the_request_company(client, company):
    """Слаг компании берётся из контекста, а не из тела — подставить нельзя."""
    role = Role.objects.create(code="r", title="Роль")
    RoleAssignment.objects.create(company_slug="чужая", user_id=42, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)
    resp = client.get(f"{BASE}/assignments/42",
                      **headers(company, superuser_token(company=company)))
    assert resp.status_code == 200
    assert resp.json() == []

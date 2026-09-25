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
from django.core.exceptions import ValidationError
from django.test import Client

from apps.access.models import PositionRole, Role, RoleAssignment, ScopeKind
from apps.access.tests.helpers import (
    BASE, assign, auth, put_json, staff_token, superuser_token, token,
)


@pytest.fixture
def member_auth(company_row):
    # access:view — иначе гейт модуля (``module="access", level="read"``) на
    # ``roles/<id>/permissions``/``roles/<id>/holders`` (фикс-раунд 1, I-1)
    # остановит запрос раньше вьюхи, до проверки принадлежности роли.
    assign(company_row, 7, "access", "view")
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


# ── Фикс-раунд 1, I-1: соседние чтения роли по id ───────────────────────────
#
# Спека R2: «Каталог и СОСЕДНИЕ чтения ролей». GET roles уже прячет чужую
# именную роль из списка (тесты выше); держатель, перебирающий id напрямую,
# не должен обходить это тем же перебором.


@pytest.mark.django_db
def test_role_permissions_of_another_company_returns_404(company_row, member_auth):
    role = Role.objects.create(code="hr-custom-other-7", title="Чужая",
                               company_slug="other-company")
    resp = Client().get(f"{BASE}/roles/{role.id}/permissions", **member_auth)
    assert resp.status_code == 404


@pytest.mark.django_db
def test_role_holders_of_another_company_returns_404(company_row, member_auth):
    role = Role.objects.create(code="hr-custom-other-7", title="Чужая",
                               company_slug="other-company")
    resp = Client().get(f"{BASE}/roles/{role.id}/holders", **member_auth)
    assert resp.status_code == 404


@pytest.mark.django_db
def test_role_permissions_of_own_company_returns_200(company_row, member_auth):
    role = Role.objects.create(code=f"hr-custom-{company_row}-7", title="Своя",
                               company_slug=company_row)
    resp = Client().get(f"{BASE}/roles/{role.id}/permissions", **member_auth)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_role_holders_of_own_company_returns_200(company_row, member_auth):
    role = Role.objects.create(code=f"hr-custom-{company_row}-7", title="Своя",
                               company_slug=company_row)
    resp = Client().get(f"{BASE}/roles/{role.id}/holders", **member_auth)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_role_permissions_of_general_role_returns_200(company_row, member_auth):
    role = Role.objects.create(code="general-role-x", title="Общая")
    resp = Client().get(f"{BASE}/roles/{role.id}/permissions", **member_auth)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_role_holders_of_general_role_returns_200(company_row, member_auth):
    role = Role.objects.create(code="general-role-y", title="Общая")
    resp = Client().get(f"{BASE}/roles/{role.id}/holders", **member_auth)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_superuser_sees_permissions_of_another_companys_role(company_row):
    role = Role.objects.create(code="hr-custom-other-7", title="Чужая",
                               company_slug="other-company")
    head = {"HTTP_X_HTQ_COMPANY": company_row,
           **auth(superuser_token(company=company_row))}
    resp = Client().get(f"{BASE}/roles/{role.id}/permissions", **head)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_superuser_sees_holders_of_another_companys_role(company_row):
    role = Role.objects.create(code="hr-custom-other-7", title="Чужая",
                               company_slug="other-company")
    head = {"HTTP_X_HTQ_COMPANY": company_row,
           **auth(superuser_token(company=company_row))}
    resp = Client().get(f"{BASE}/roles/{role.id}/holders", **head)
    assert resp.status_code == 200


# ── Фикс-раунд 1, I-2: django-admin — шестой путь выдачи ────────────────────
#
# Проверка стоит на уровне МОДЕЛИ (``clean()``), а не только сервиса: голый
# ``ModelAdmin`` без своей формы правит строки через ``ModelForm``, чей
# ``_post_clean`` зовёт ``instance.full_clean()`` — тот же путь, что и прямой
# вызов ``full_clean()`` в тесте ниже.


@pytest.mark.django_db
def test_position_role_full_clean_rejects_another_companys_role(company_row):
    role = Role.objects.create(code="hr-custom-other-7", title="Чужая",
                               company_slug="other-company")
    link = PositionRole(company_slug=company_row, position_id=1, role=role)
    with pytest.raises(ValidationError):
        link.full_clean()


@pytest.mark.django_db
def test_position_role_full_clean_accepts_general_role(company_row):
    role = Role.objects.create(code="general-role-z", title="Общая")
    link = PositionRole(company_slug=company_row, position_id=1, role=role)
    link.full_clean()  # не должно поднять ValidationError


@pytest.mark.django_db
def test_role_assignment_full_clean_rejects_another_companys_role(company_row):
    role = Role.objects.create(code="hr-custom-other-7", title="Чужая",
                               company_slug="other-company")
    row = RoleAssignment(company_slug=company_row, user_id=5, role=role,
                         scope_kind=ScopeKind.COMPANY, scope_id=None)
    with pytest.raises(ValidationError):
        row.full_clean()


@pytest.mark.django_db
def test_role_assignment_full_clean_accepts_general_role(company_row):
    role = Role.objects.create(code="general-role-w", title="Общая")
    row = RoleAssignment(company_slug=company_row, user_id=5, role=role,
                         scope_kind=ScopeKind.COMPANY, scope_id=None)
    row.full_clean()  # не должно поднять ValidationError


# ── Фикс-раунд 1, M-2: копия роли наследует company_slug ────────────────────


@pytest.mark.django_db
def test_copy_role_inherits_company_slug_of_the_source(company_row):
    from apps.access.services import catalog

    source = Role.objects.create(code="hr-custom-other-7", title="Чужая",
                                 company_slug="other-company")
    clone = catalog.copy_role(source.id, "hr-custom-other-7-copy", "Копия чужой")
    assert clone.company_slug == "other-company"


@pytest.mark.django_db
def test_copy_role_of_a_general_role_stays_general():
    from apps.access.services import catalog

    source = Role.objects.create(code="general-copy-source", title="Общая")
    clone = catalog.copy_role(source.id, "general-copy-clone", "Копия общей")
    assert clone.company_slug is None


# ── Фикс-раунд 1, M-3: недостающие тесты ────────────────────────────────────


@pytest.mark.django_db
def test_migration_0010_fills_slug_from_custom_role_code():
    """Данные миграции ``0010`` — регэксп и идемпотентность, на реальной модели.

    Вызывает функцию миграции напрямую на текущей ``django.apps.apps``: схема
    не менялась с ``0009`` (только добавлено поле), так что модель на выходе
    той же формы, что и историческая — вызов через ``MigrationExecutor``
    добавил бы только накладные расходы поднятия отдельного состояния графа.
    """
    import importlib

    from django.apps import apps as django_apps

    migration = importlib.import_module(
        "apps.access.migrations.0010_backfill_role_company_slug")

    numeric = Role.objects.create(code="hr-custom-co-2-7", title="A")
    no_tail = Role.objects.create(code="hr-custom-onlyslug", title="B")
    already = Role.objects.create(code="hr-custom-x-1", title="C",
                                  company_slug="preset")

    migration.fill(django_apps, None)

    numeric.refresh_from_db()
    no_tail.refresh_from_db()
    already.refresh_from_db()
    assert numeric.company_slug == "co-2"
    # Код без числового хвоста не совпадает с регэкспом — не трогается.
    assert no_tail.company_slug is None
    # Уже заполненная строка не переписывается.
    assert already.company_slug == "preset"


# HTTP-тест 422 на ``PUT positions/<id>/roles`` с чужой ролью (M-3) живёт в
# ``test_api.py`` — та ручка требует настоящую должность в схеме компании
# (``position_or_404``), а фикстуры для неё (``company``, ``position``, живая
# схема Postgres) уже есть только там; заводить их копию здесь — дублирование
# ради дублирования.


@pytest.mark.django_db
def test_access_grant_command_rejects_another_companys_role(company_row):
    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.core.management.base import CommandError

    user = get_user_model().objects.create_user(
        username="grantee", email="grantee@htq.test", password="x")
    Role.objects.create(code="hr-custom-other-7", title="Чужая",
                        company_slug="other-company")

    with pytest.raises(CommandError):
        call_command("access_grant", user=str(user.id), role_code="hr-custom-other-7",
                     company_slug=company_row)

    assert not RoleAssignment.objects.filter(user_id=user.id).exists()

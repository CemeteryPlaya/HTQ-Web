"""Задача 1b блока I: область у роли ДОЛЖНОСТИ («свой отдел» или компания).

Старая кадровая модель сужала список сотрудников до СВОЕГО ОТДЕЛА для
junior/middle (``apps/hr/views.py`` — ``if not access.can_read_all``). В новой
модели это различие выражается областью роли, а не отдельным ключом, но
``PositionRole`` до этой задачи не умел нести ничего, кроме безусловного
``COMPANY`` (``_role_scopes`` отдавала его каждой должностной роли жёстко).
Этот файл проверяет, что ``PositionRole.scope_kind`` действительно меняет
резолвер, а не просто существует как поле.

Главный тест — ``test_department_scope_resolves_to_holders_department``: два
человека на ОДНОЙ должности в РАЗНЫХ отделах обязаны получить РАЗНЫЕ области.
Это отличает «свой отдел, вычисленный по держателю» от «отдела, записанного
при выдаче» — второго у ``PositionRole`` нет и не должно быть вовсе (см.
докстринг модели): будь область записана при выдаче, оба сотрудника получили
бы отдел ДОЛЖНОСТИ (тот, что был при её создании), а не свой собственный.

Раунд правок 1 (ревью): ``ScopeKind.SITE`` был формально достижим через
``/django-admin/`` (``PositionRoleAdmin`` рендерит форму по всем полям
модели, а штатный API ``scope_kind`` не принимает вовсе) и резолвером тихо
пропускался — человек терял доступ без единой записи в логе. Два теста ниже
проверяют оба закрытых конца: ``site`` больше не проходит валидацию модели
(``full_clean``), а значение, которое всё же обошло эту защиту (прямой SQL —
здесь имитируется ``.objects.create()`` мимо ``full_clean``, как и было бы
доступно раньше через админку), резолвер отдаёт не молча, а через
``fallback(..., expected=False)`` — в тестовой среде (``FALLBACK_MODE=strict``)
это ``FallbackNotAllowed``, а не тихая пустая карта прав.
"""

from __future__ import annotations

import datetime

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.access.models import Level, PositionRole, Role, RoleAssignment, ScopeKind
from apps.access.services import resolve
from apps.access.tests.helpers import grant
from htqweb.fallback import FallbackNotAllowed

COMPANY = "htq-kz"


def _role(code: str, node: str, level: str = Level.WRITE) -> Role:
    role = Role.objects.create(code=code, title=code)
    grant(role, node, level)
    return role


def _employee(user, department, position):
    from apps.hr.models import Employee

    return Employee.objects.create(
        first_name="Т", last_name=user.username, email=f"{user.username}@htq.test",
        department=department, position=position,
        hire_date=datetime.date(2024, 1, 9), user_id=user.id,
    )


@pytest.fixture
def two_holders_same_position(db):
    """Два сотрудника на одной должности, в разных отделах.

    Ядро теста: одна и та же должность (``position``) — но держатели сидят в
    ``dep_a`` и ``dep_b``. Если резолвер по ошибке брал бы отдел САМОЙ
    должности (``Position.department``, зафиксированный при её создании —
    ``dep_a``), а не отдел ДЕРЖАТЕЛЯ, оба пользователя получили бы одну и ту
    же область, и тест это поймает.
    """
    from apps.hr.models import Department, Position

    dep_a = Department.objects.create(name="Продажи", path="sales")
    dep_b = Department.objects.create(name="Финансы", path="finance")
    position = Position.objects.create(title="Специалист", department=dep_a, weight=10)

    users = get_user_model()
    user_a = users.objects.create_user(username="a", email="a@htq.test", password="x")
    user_b = users.objects.create_user(username="b", email="b@htq.test", password="x")
    _employee(user_a, dep_a, position)
    _employee(user_b, dep_b, position)
    return {
        "position": position, "dep_a": dep_a, "dep_b": dep_b,
        "user_a": user_a, "user_b": user_b,
    }


# ── По умолчанию — вся компания, как и было ─────────────────────────────────


@pytest.mark.django_db
def test_position_role_default_scope_kind_is_company():
    """Существующие выдачи не меняют смысла: без явного scope_kind — COMPANY."""
    role = Role.objects.create(code="r1", title="r1")
    row = PositionRole.objects.create(company_slug=COMPANY, position_id=1, role=role)
    assert row.scope_kind == ScopeKind.COMPANY


@pytest.mark.django_db
def test_company_scope_kind_grants_whole_company_for_any_holder(
        two_holders_same_position):
    """scope_kind=COMPANY (или default) не зависит от отдела держателя —
    ни для одного из двух сотрудников на этой должности."""
    h = two_holders_same_position
    role = _role("company-role", "hr")
    PositionRole.objects.create(
        company_slug=COMPANY, position_id=h["position"].id, role=role,
        scope_kind=ScopeKind.COMPANY,
    )
    for user in (h["user_a"], h["user_b"]):
        perms = resolve.permissions_for(user, COMPANY)
        assert perms["hr"]["scope"] == {"kind": ScopeKind.COMPANY, "id": None}


# ── DEPARTMENT — вычисляется по держателю, не по должности ─────────────────


@pytest.mark.django_db
def test_department_scope_resolves_to_holders_department(two_holders_same_position):
    h = two_holders_same_position
    role = _role("dept-role", "hr")
    PositionRole.objects.create(
        company_slug=COMPANY, position_id=h["position"].id, role=role,
        scope_kind=ScopeKind.DEPARTMENT,
    )

    perms_a = resolve.permissions_for(h["user_a"], COMPANY)
    perms_b = resolve.permissions_for(h["user_b"], COMPANY)

    assert h["dep_a"].id != h["dep_b"].id, "фикстура сломана: отделы совпали"
    assert perms_a["hr"]["scope"] == {"kind": ScopeKind.DEPARTMENT, "id": h["dep_a"].id}
    assert perms_b["hr"]["scope"] == {"kind": ScopeKind.DEPARTMENT, "id": h["dep_b"].id}


@pytest.mark.django_db
def test_department_scope_is_exposed_through_permissions_for(
        two_holders_same_position):
    """``permissions_for`` — это то, что будет читать задача 9: область
    обязана дойти до него, а не потеряться внутри резолвера."""
    h = two_holders_same_position
    role = _role("dept-role-2", "hr")
    PositionRole.objects.create(
        company_slug=COMPANY, position_id=h["position"].id, role=role,
        scope_kind=ScopeKind.DEPARTMENT,
    )
    entry = resolve.permissions_for(h["user_a"], COMPANY)["hr"]
    assert entry["scope"]["kind"] == ScopeKind.DEPARTMENT
    assert entry["scope"]["id"] == h["dep_a"].id


# ── Держатель без карточки — не COMPANY-призрак ─────────────────────────────


@pytest.mark.django_db
def test_holder_without_employee_card_grants_nothing(user):
    """Без кадровой карточки не определить ни должность, ни отдел держателя —
    роль этой должности не действует вовсе (fail closed), а не молча
    расширяется до COMPANY. ``user`` (фикстура conftest) — обычный
    пользователь платформы без ``Employee``."""
    role = _role("orphan-role", "hr", Level.ADMIN)
    PositionRole.objects.create(
        company_slug=COMPANY, position_id=999999, role=role,
        scope_kind=ScopeKind.DEPARTMENT,
    )
    assert resolve.permissions_for(user, COMPANY) == {}


# ── Более широкая область побеждает (тот же _SCOPE_WIDTH) ───────────────────


@pytest.mark.django_db
def test_wider_personal_assignment_beats_department_position_scope(
        two_holders_same_position):
    """Своя должность даёт DEPARTMENT, личное назначение той же роли —
    COMPANY: побеждает более широкая (правило ``_SCOPE_WIDTH``, уже
    существующее в ``_role_scopes`` — не второе правило, то же самое)."""
    h = two_holders_same_position
    role = _role("shared-role", "hr")
    PositionRole.objects.create(
        company_slug=COMPANY, position_id=h["position"].id, role=role,
        scope_kind=ScopeKind.DEPARTMENT,
    )
    RoleAssignment.objects.create(
        company_slug=COMPANY, user_id=h["user_a"].id, role=role,
        scope_kind=ScopeKind.COMPANY, scope_id=None,
    )

    perms = resolve.permissions_for(h["user_a"], COMPANY)
    assert perms["hr"]["scope"] == {"kind": ScopeKind.COMPANY, "id": None}


@pytest.mark.django_db
def test_narrower_personal_assignment_does_not_shrink_department_scope(
        two_holders_same_position):
    """И наоборот: личное назначение УЖЕ должностной DEPARTMENT-области не
    должно её сузить — у ``_SCOPE_WIDTH`` строгое ``>``, а не ``>=``."""
    h = two_holders_same_position
    role = _role("shared-role-2", "hr")
    PositionRole.objects.create(
        company_slug=COMPANY, position_id=h["position"].id, role=role,
        scope_kind=ScopeKind.DEPARTMENT,
    )
    RoleAssignment.objects.create(
        company_slug=COMPANY, user_id=h["user_a"].id, role=role,
        scope_kind=ScopeKind.SITE, scope_id=42,
    )

    perms = resolve.permissions_for(h["user_a"], COMPANY)
    assert perms["hr"]["scope"] == {
        "kind": ScopeKind.DEPARTMENT, "id": h["dep_a"].id,
    }


# ── Лишних запросов к БД не появилось ───────────────────────────────────────


@pytest.mark.django_db
def test_department_scope_adds_no_extra_queries(two_holders_same_position):
    """Отдел держателя берётся из уже полученного ``brief``
    (``hr.get_employee_brief``) — ни второго похода в ``hr_employee``, ни
    лишнего похода в ``access_positionrole`` появиться не должно."""
    h = two_holders_same_position
    role = _role("dept-role-q", "hr")
    PositionRole.objects.create(
        company_slug=COMPANY, position_id=h["position"].id, role=role,
        scope_kind=ScopeKind.DEPARTMENT,
    )

    with CaptureQueriesContext(connection) as ctx:
        perms = resolve.permissions_for(h["user_a"], COMPANY)
    assert perms["hr"]["scope"]["kind"] == ScopeKind.DEPARTMENT

    hr_employee_queries = [q for q in ctx.captured_queries if "hr_employee" in q["sql"]]
    position_role_queries = [
        q for q in ctx.captured_queries if "access_positionrole" in q["sql"]
    ]
    assert len(hr_employee_queries) == 1, (
        f"ожидали ровно один запрос к hr_employee: {hr_employee_queries}"
    )
    assert len(position_role_queries) == 1, (
        f"ожидали ровно один запрос к access_positionrole: {position_role_queries}"
    )


# ── Раунд правок 1: SITE закрыт с обоих концов ──────────────────────────────


@pytest.mark.django_db
def test_site_scope_kind_rejected_by_model_validation():
    """Сужение choices (0007): ``site`` больше не проходит валидацию модели —
    ни формы (django-admin), ни явный ``full_clean()``."""
    role = Role.objects.create(code="r-site", title="r-site")
    row = PositionRole(company_slug=COMPANY, position_id=1, role=role,
                       scope_kind=ScopeKind.SITE)
    with pytest.raises(ValidationError) as excinfo:
        row.full_clean()
    assert "scope_kind" in excinfo.value.message_dict


@pytest.mark.django_db
def test_unsupported_scope_kind_is_loud_not_silent(two_holders_same_position):
    """Значение вне ``POSITION_ROLE_SCOPE_KINDS``, попавшее в таблицу в обход
    ``choices`` (здесь — ``.objects.create()`` мимо ``full_clean()``, тем же
    путём, каким раньше это делала форма ``/django-admin/``), не должно
    молча терять роль. Тестовая среда — ``FALLBACK_MODE=strict``
    (``htqweb/settings/test.py``), поэтому ``fallback(expected=False)``
    поднимает ``FallbackNotAllowed`` вместо тихого лога — ровно то падение,
    которого strict-режим и добивается: автор видит причину сразу, а не
    пустую карту прав."""
    h = two_holders_same_position
    role = _role("bad-scope-role", "hr")
    PositionRole.objects.create(
        company_slug=COMPANY, position_id=h["position"].id, role=role,
        scope_kind=ScopeKind.SITE,
    )

    with pytest.raises(FallbackNotAllowed) as excinfo:
        resolve.permissions_for(h["user_a"], COMPANY)
    assert "access.resolve.position_role_scope_kind_invalid" in str(excinfo.value)

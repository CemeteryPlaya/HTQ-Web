"""Задача 6 плана A: роли должности и личные назначения.

Каждая операция ограничена ОДНОЙ компанией. Это не деталь реализации: таблицы
лежат в public, ``search_path`` их не изолирует, и замена набора без фильтра
стёрла бы назначения соседней компании (спека §1.3, риск 3).
"""

import pytest

from apps.access.models import PositionRole, Role, RoleAssignment, ScopeKind
from apps.access.services import assignment
from apps.access.services.errors import ScopeInvalid, UnknownRole

COMPANY = "htq-kz"
OTHER = "kurly-kg"


@pytest.fixture
def roles(db):
    return (Role.objects.create(code="a", title="A"),
            Role.objects.create(code="b", title="B"))


# ── Роли должности ────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_set_position_roles_replaces_whole_set(roles):
    a, b = roles
    assignment.set_position_roles(COMPANY, 5, [a.id, b.id])
    assignment.set_position_roles(COMPANY, 5, [b.id])
    assert list(PositionRole.objects
                .filter(company_slug=COMPANY, position_id=5)
                .values_list("role_id", flat=True)) == [b.id]


@pytest.mark.django_db
def test_empty_set_clears_the_position(roles):
    a, _ = roles
    assignment.set_position_roles(COMPANY, 5, [a.id])
    assignment.set_position_roles(COMPANY, 5, [])
    assert not PositionRole.objects.filter(company_slug=COMPANY, position_id=5).exists()


@pytest.mark.django_db
def test_position_roles_of_another_company_are_untouched(roles):
    a, _ = roles
    assignment.set_position_roles(OTHER, 5, [a.id])
    assignment.set_position_roles(COMPANY, 5, [])
    assert PositionRole.objects.filter(company_slug=OTHER, position_id=5).count() == 1


@pytest.mark.django_db
def test_other_positions_of_the_same_company_are_untouched(roles):
    a, _ = roles
    assignment.set_position_roles(COMPANY, 6, [a.id])
    assignment.set_position_roles(COMPANY, 5, [])
    assert PositionRole.objects.filter(company_slug=COMPANY, position_id=6).count() == 1


@pytest.mark.django_db
def test_repeated_role_id_does_not_break_uniqueness(roles):
    a, _ = roles
    assignment.set_position_roles(COMPANY, 5, [a.id, a.id])
    assert PositionRole.objects.filter(company_slug=COMPANY, position_id=5).count() == 1


@pytest.mark.django_db
def test_unknown_role_is_rejected(roles):
    with pytest.raises(UnknownRole):
        assignment.set_position_roles(COMPANY, 5, [999_999])


@pytest.mark.django_db
def test_rejected_set_leaves_the_previous_one_intact(roles):
    a, _ = roles
    assignment.set_position_roles(COMPANY, 5, [a.id])
    with pytest.raises(UnknownRole):
        assignment.set_position_roles(COMPANY, 5, [a.id, 999_999])
    assert PositionRole.objects.filter(company_slug=COMPANY, position_id=5).count() == 1


@pytest.mark.django_db
def test_position_roles_are_readable(roles):
    a, _ = roles
    assignment.set_position_roles(COMPANY, 5, [a.id])
    assert assignment.position_roles(COMPANY, 5) == [
        {"role_id": a.id, "code": "a", "title": "A"},
    ]


# ── Личные назначения ─────────────────────────────────────────────────────


@pytest.mark.django_db
def test_set_user_assignments_replaces_whole_set(roles):
    a, b = roles
    assignment.set_user_assignments(COMPANY, 1, [
        {"role_id": a.id, "scope_kind": ScopeKind.COMPANY, "scope_id": None},
        {"role_id": b.id, "scope_kind": ScopeKind.DEPARTMENT, "scope_id": 3},
    ])
    assignment.set_user_assignments(COMPANY, 1, [
        {"role_id": b.id, "scope_kind": ScopeKind.DEPARTMENT, "scope_id": 3},
    ])
    assert RoleAssignment.objects.filter(company_slug=COMPANY, user_id=1).count() == 1


@pytest.mark.django_db
def test_user_assignments_of_another_company_are_untouched(roles):
    a, _ = roles
    assignment.set_user_assignments(OTHER, 1, [
        {"role_id": a.id, "scope_kind": ScopeKind.COMPANY, "scope_id": None}])
    assignment.set_user_assignments(COMPANY, 1, [])
    assert RoleAssignment.objects.filter(company_slug=OTHER, user_id=1).count() == 1


@pytest.mark.django_db
def test_company_scope_with_scope_id_is_rejected(roles):
    a, _ = roles
    with pytest.raises(ScopeInvalid):
        assignment.set_user_assignments(COMPANY, 1, [
            {"role_id": a.id, "scope_kind": ScopeKind.COMPANY, "scope_id": 3}])


@pytest.mark.django_db
def test_department_scope_without_scope_id_is_rejected(roles):
    a, _ = roles
    with pytest.raises(ScopeInvalid):
        assignment.set_user_assignments(COMPANY, 1, [
            {"role_id": a.id, "scope_kind": ScopeKind.DEPARTMENT, "scope_id": None}])


@pytest.mark.django_db
def test_site_scope_without_scope_id_is_rejected(roles):
    a, _ = roles
    with pytest.raises(ScopeInvalid):
        assignment.set_user_assignments(COMPANY, 1, [
            {"role_id": a.id, "scope_kind": ScopeKind.SITE, "scope_id": None}])


@pytest.mark.django_db
def test_unknown_scope_kind_is_rejected(roles):
    a, _ = roles
    with pytest.raises(ScopeInvalid):
        assignment.set_user_assignments(COMPANY, 1, [
            {"role_id": a.id, "scope_kind": "вселенная", "scope_id": None}])


@pytest.mark.django_db
def test_user_assignments_are_readable(roles):
    a, _ = roles
    assignment.set_user_assignments(COMPANY, 1, [
        {"role_id": a.id, "scope_kind": ScopeKind.DEPARTMENT, "scope_id": 3}])
    assert assignment.user_assignments(COMPANY, 1) == [
        {"role_id": a.id, "scope_kind": ScopeKind.DEPARTMENT, "scope_id": 3},
    ]

"""Юнит-тесты слоя доступа apps.hr.access — паритет с
services/hr/app/auth/hr_access.py (HRAccess, classify_hr_level,
resolve_hr_access, require_hr_access, require_can_write_basic).

Отдельно от test_employees_api.py: здесь проверяется чистая логика
(dataclass/эвристика/резолюция), без HTTP-слоя — как и в исходнике
test_permission_enforcement.py (юнит) vs эндпойнт-тесты.

План: docs/plans/2026-07-20-hr-domain.md
"""
from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest

from apps.hr import access
from apps.hr.models import Department, Employee, Position
from apps.hr.permissions import ALL_KEYS, LEVEL_PRESETS


def _dep(name, path="dep", **kw):
    return Department.objects.create(name=name, path=path, **kw)


def _pos(title, dep, weight, **kw):
    return Position.objects.create(title=title, department=dep, weight=weight, **kw)


def _emp(dep, pos, email="a@htq.test", user_id=None, **kw):
    return Employee.objects.create(
        first_name="И", last_name="И", email=email, department=dep, position=pos,
        hire_date=datetime.date(2024, 1, 9), user_id=user_id, **kw,
    )


def _token(user_id=1, email=None, is_staff=False, is_superuser=False, is_admin=False):
    return SimpleNamespace(
        user_id=user_id, email=email, is_staff=is_staff, is_superuser=is_superuser,
        is_admin=is_admin, is_elevated=bool(is_admin or is_staff or is_superuser),
    )


# ── HRAccess dataclass ───────────────────────────────────────────────────────

def test_has_checks_membership():
    acc = access.HRAccess(level="junior", permissions=frozenset({"hr.employees.view"}))
    assert acc.has("hr.employees.view")
    assert not acc.has("hr.employees.delete")


def test_wildcard_has_everything():
    acc = access.HRAccess(level="lead", permissions=frozenset({"*"}))
    assert acc.has("hr.employees.delete")
    assert acc.has("anything.at.all")


def test_has_access_true_with_level_or_permissions():
    assert access.HRAccess(level="junior").has_access
    assert access.HRAccess(level=None, permissions=frozenset({"hr.employees.view"})).has_access
    assert not access.HRAccess(level=None, permissions=frozenset()).has_access


@pytest.mark.parametrize("level,expected", [
    ("junior", dict(can_read_all=False, can_write_basic=False, can_create_employee=False,
                    can_transfer_employee=False, can_delete_employee=False)),
    ("middle", dict(can_read_all=False, can_write_basic=True, can_create_employee=False,
                    can_transfer_employee=False, can_delete_employee=False)),
    ("senior", dict(can_read_all=True, can_write_basic=True, can_create_employee=True,
                    can_transfer_employee=True, can_delete_employee=False)),
    ("lead", dict(can_read_all=True, can_write_basic=True, can_create_employee=True,
                  can_transfer_employee=True, can_delete_employee=True)),
])
def test_can_wrappers_match_preset_matrix(level, expected):
    acc = access.HRAccess(level=level, permissions=LEVEL_PRESETS[level])
    for attr, value in expected.items():
        assert getattr(acc, attr) is value, f"{level}.{attr}"


def test_can_see_department_read_all_sees_everything():
    acc = access.HRAccess(level="lead", permissions=frozenset({"*"}), department_id=None)
    assert acc.can_see_department(999)
    assert acc.can_see_department(None)


def test_can_see_department_scoped_to_own():
    acc = access.HRAccess(level="junior", permissions=LEVEL_PRESETS["junior"], department_id=5)
    assert acc.can_see_department(5)
    assert not acc.can_see_department(6)
    assert not acc.can_see_department(None)


# ── classify_hr_level ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_classify_none_for_no_employee():
    assert access.classify_hr_level(None) is None


@pytest.mark.django_db
def test_classify_none_for_non_hr_employee():
    dep = _dep("Финансы", "fin")
    pos = _pos("Бухгалтер", dep, 100)
    emp = _emp(dep, pos)
    assert access.classify_hr_level(emp) is None


@pytest.mark.django_db
def test_classify_explicit_permissions_hr_level_wins():
    dep = _dep("Финансы", "fin")
    pos = _pos("Специалист по обучению", dep, 100, permissions={"hr_level": "senior", "permissions": []})
    emp = _emp(dep, pos)
    assert access.classify_hr_level(emp) == "senior"


@pytest.mark.django_db
@pytest.mark.parametrize("title,department,expected", [
    ("HR Director", "HR", "lead"),
    ("Директор по персоналу", "Кадры", "lead"),
    ("Chief HR Officer", "People", "lead"),
    ("Senior HR Manager", "HR", "senior"),
    ("Ведущий HR-специалист", "Кадры", "senior"),
    ("HR Manager", "HR", "middle"),
    ("Специалист по персоналу", "Кадры", "middle"),
    ("HR Assistant", "HR", "junior"),
    ("Стажёр отдела кадров", "Кадры", "junior"),
    ("HR Coordinator", "HR", "junior"),  # HR-маркер есть, других — нет -> junior по умолчанию
])
def test_classify_heuristic_markers(title, department, expected):
    dep = _dep(department, "dep-" + department.lower().replace(" ", "-"))
    pos = _pos(title, dep, 100)
    emp = _emp(dep, pos, email=f"{title}{department}@htq.test")
    assert access.classify_hr_level(emp) == expected


# ── resolve_hr_access ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_resolve_elevated_token_is_lead_wildcard():
    acc = access.resolve_hr_access(_token(is_staff=True))
    assert acc.level == "lead"
    assert acc.permissions == frozenset({"*"})
    assert acc.employee_id is None
    assert acc.department_id is None


@pytest.mark.django_db
def test_resolve_no_matching_employee_has_no_access():
    acc = access.resolve_hr_access(_token(user_id=999_999, email="nobody@htq.test"))
    assert acc.level is None
    assert acc.permissions == frozenset()
    assert not acc.has_access


@pytest.mark.django_db
def test_resolve_matches_by_user_id():
    dep = _dep("HR", "hr")
    pos = _pos("HR Manager", dep, 100)
    emp = _emp(dep, pos, email="hr1@htq.test", user_id=42)

    acc = access.resolve_hr_access(_token(user_id=42, email="other@htq.test"))
    assert acc.level == "middle"
    assert acc.employee_id == emp.id
    assert acc.department_id == dep.id
    assert acc.permissions == LEVEL_PRESETS["middle"]


@pytest.mark.django_db
def test_resolve_falls_back_to_email_match():
    dep = _dep("HR", "hr")
    pos = _pos("HR Manager", dep, 100)
    emp = _emp(dep, pos, email="hr2@htq.test", user_id=None)

    acc = access.resolve_hr_access(_token(user_id=999_999, email="hr2@htq.test"))
    assert acc.employee_id == emp.id
    assert acc.level == "middle"


@pytest.mark.django_db
def test_resolve_ignores_soft_deleted_employee():
    dep = _dep("HR", "hr")
    pos = _pos("HR Manager", dep, 100)
    _emp(dep, pos, email="gone@htq.test", user_id=7, is_deleted=True)

    acc = access.resolve_hr_access(_token(user_id=7, email="gone@htq.test"))
    assert not acc.has_access


@pytest.mark.django_db
def test_resolve_uses_explicit_permissions_matrix_intersected_with_all_keys():
    dep = _dep("Финансы", "fin")
    pos = _pos(
        "Специалист по обучению", dep, 100,
        permissions={"hr_level": "senior", "permissions": ["hr.employees.view", "not.a.real.key"]},
    )
    emp = _emp(dep, pos, email="x@htq.test", user_id=11)

    acc = access.resolve_hr_access(_token(user_id=11))
    assert acc.permissions == frozenset({"hr.employees.view"}) & ALL_KEYS
    assert "not.a.real.key" not in acc.permissions
    assert acc.employee_id == emp.id


@pytest.mark.django_db
def test_resolve_empty_explicit_permissions_list_falls_back_to_level_preset():
    dep = _dep("HR", "hr")
    pos = _pos("HR Manager", dep, 100, permissions={"hr_level": None, "permissions": []})
    _emp(dep, pos, email="y@htq.test", user_id=12)

    acc = access.resolve_hr_access(_token(user_id=12))
    assert acc.permissions == LEVEL_PRESETS["middle"]


# ── require_hr_access / require_can_write_basic ──────────────────────────────

def test_require_hr_access_raises_with_exact_detail():
    with pytest.raises(access.HRAccessDenied) as exc_info:
        access.require_hr_access(access.HRAccess(level=None, permissions=frozenset()))
    assert exc_info.value.detail == "HR access required"


def test_require_hr_access_passthrough_when_has_access():
    acc = access.HRAccess(level="junior", permissions=LEVEL_PRESETS["junior"])
    assert access.require_hr_access(acc) is acc


def test_require_can_write_basic_raises_hr_access_required_first():
    with pytest.raises(access.HRAccessDenied) as exc_info:
        access.require_can_write_basic(access.HRAccess(level=None, permissions=frozenset()))
    assert exc_info.value.detail == "HR access required"


def test_require_can_write_basic_raises_write_access_required_for_junior():
    acc = access.HRAccess(level="junior", permissions=LEVEL_PRESETS["junior"])
    with pytest.raises(access.HRAccessDenied) as exc_info:
        access.require_can_write_basic(acc)
    assert exc_info.value.detail == "HR write access required"


def test_require_can_write_basic_passthrough_for_middle_and_up():
    acc = access.HRAccess(level="middle", permissions=LEVEL_PRESETS["middle"])
    assert access.require_can_write_basic(acc) is acc

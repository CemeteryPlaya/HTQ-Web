"""Юнит-тесты ``apps.hr.access.classify_hr_level`` — эвристики ПЕРЕНОСА.

До задачи 9 блока I «Единая модель прав» этот файл проверял ВЕСЬ модуль
``apps.hr.access`` как параллельную модель прав: dataclass ``HRAccess``,
резолвер ``resolve_hr_access`` (по живому JWT-токену) и ворота
``require_hr_access``/``require_can_write_basic``. Задача 9 сняла эти четыре
символа целиком (правки прав живут в ``apps.hr.rbac`` — см. его докстринг и
``test_single_rbac_guards.py::test_the_old_resolver_is_gone``), и тесты на
них ушли вместе с кодом, который проверяли: ``test_has_checks_membership``,
``test_wildcard_has_everything``, ``test_has_access_true_with_level_or_
permissions``, ``test_can_wrappers_match_preset_matrix``, ``test_can_see_
department_read_all_sees_everything``, ``test_can_see_department_scoped_to_
own`` (dataclass ``HRAccess``); ``test_resolve_elevated_token_is_lead_
wildcard``, ``test_resolve_no_matching_employee_has_no_access``,
``test_resolve_matches_by_user_id``, ``test_resolve_falls_back_to_email_
match``, ``test_resolve_ignores_soft_deleted_employee``, ``test_resolve_
uses_explicit_permissions_matrix_intersected_with_all_keys``, ``test_
resolve_empty_explicit_permissions_list_falls_back_to_level_preset``
(``resolve_hr_access``); ``test_require_hr_access_raises_with_exact_detail``,
``test_require_hr_access_passthrough_when_has_access``, ``test_require_can_
write_basic_raises_hr_access_required_first``, ``test_require_can_write_
basic_raises_write_access_required_for_junior``, ``test_require_can_write_
basic_passthrough_for_middle_and_up`` (``require_hr_access``/``require_can_
write_basic``) — их поведение теперь у гейта ``api_view(module="hr",
level=…)`` и у ``apps.hr.rbac.NodeAccess``, оба покрыты своими наборами
тестов (``apps/access/tests/test_module_gate.py``,
``apps/hr/tests/test_employees_api.py`` и соседи).

Что осталось: ``classify_hr_level`` — эвристика по названию должности/отдела
(плюс явный оверрайд ``Position.permissions["hr_level"]``), единственное
легитимное применение которой теперь — перенос уровней в роли
(``apps.hr.interface.list_positions_hr_levels`` →
``manage.py access_backfill_positions``, Ruling C задачи 9). Она живёт и
тестируется здесь отдельно от резолюции токена — чистая логика классификации
по карточке сотрудника, без HTTP-слоя.
"""
from __future__ import annotations

import datetime

import pytest

from apps.hr import access
from apps.hr.models import Department, Employee, Position


def _dep(name, path="dep", **kw):
    return Department.objects.create(name=name, path=path, **kw)


def _pos(title, dep, weight, **kw):
    return Position.objects.create(title=title, department=dep, weight=weight, **kw)


def _emp(dep, pos, email="a@htq.test", user_id=None, **kw):
    return Employee.objects.create(
        first_name="И", last_name="И", email=email, department=dep, position=pos,
        hire_date=datetime.date(2024, 1, 9), user_id=user_id, **kw,
    )


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

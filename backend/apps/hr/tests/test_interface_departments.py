"""Контракт трёх функций оргструктуры для досок задач (канбан, этап 1 K1.1).

Потребитель — ``apps.tasks`` (``TaskScope``): видимость задачи по поддереву
отдела и права главы отдела (мастер-план канбан-досок §4, спека этапа 1
§K1.1). Поддерево — по строке ``Department.path`` с разделителем «.»: отдел
``it`` не должен захватывать ``itops``, а ``_`` в пути — не подстановочный
знак ``LIKE``.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.db import connection

from apps.core.services import ServiceDisabled
from apps.hr import interface
from apps.hr.models import Department, Employee, EmployeeStatus, Position

pytestmark = pytest.mark.django_db

HIRED = dt.date(2025, 1, 1)


def _dep(path: str, *, active: bool = True) -> Department:
    return Department.objects.create(name=f"Отдел {path}", path=path, is_active=active)


def _employee(seq: int, department: Department, position: Position, *,
              user_id: int | None, status: str = EmployeeStatus.ACTIVE,
              deleted: bool = False) -> Employee:
    return Employee.objects.create(
        user_id=user_id, first_name=f"Имя{seq}", last_name=f"Фамилия{seq}",
        email=f"emp{seq}@kanban.test", department=department, position=position,
        hire_date=HIRED, status=status, is_deleted=deleted)


@pytest.fixture
def org():
    deps = {path: _dep(path) for path in
            ("it", "it.dev", "it.dev.backend", "itops", "a_b", "aXb", "aXb.c", "hq")}
    deps["it.old"] = _dep("it.old", active=False)
    deps["closed"] = _dep("closed", active=False)
    position = Position.objects.create(title="Сотрудник (канбан)", department=deps["hq"],
                                       weight=9101)
    head = _employee(1, deps["hq"], position, user_id=9001)
    fired = _employee(2, deps["hq"], position, user_id=9002, status=EmployeeStatus.INACTIVE)
    deleted = _employee(3, deps["hq"], position, user_id=9003, deleted=True)
    no_account = _employee(4, deps["hq"], position, user_id=None)
    closed_head = _employee(5, deps["hq"], position, user_id=9005)
    # Глава двух отделов — один человек; отдел может вести сотрудник другого отдела.
    for path in ("it", "itops"):
        deps[path].manager = head
    deps["a_b"].manager = fired
    deps["aXb"].manager = deleted
    deps["aXb.c"].manager = no_account
    deps["closed"].manager = closed_head
    for dep in deps.values():
        dep.save(update_fields=["manager"])
    return deps


def _ids(deps, *paths):
    return sorted(deps[p].id for p in paths)


# ── department_subtree_ids ───────────────────────────────────────────────

def test_subtree_by_dot_separator(org):
    result = interface.department_subtree_ids([org["it"].id])
    assert sorted(result[org["it"].id]) == _ids(org, "it", "it.dev", "it.dev.backend", "it.old")


def test_subtree_includes_inactive_subdepartments(org):
    """Задачи закрытого подотдела не должны пропасть с доски родителя (S1-02)."""
    assert org["it.old"].id in interface.department_subtree_ids([org["it"].id])[org["it"].id]


def test_underscore_is_not_a_wildcard(org):
    """``a_b`` в ``LIKE`` без экранирования поймал бы ``aXb`` и ``aXb.c``."""
    result = interface.department_subtree_ids([org["a_b"].id])
    assert result[org["a_b"].id] == [org["a_b"].id]


def test_subtree_two_roots_one_call(org):
    result = interface.department_subtree_ids([org["it.dev"].id, org["aXb"].id])
    assert sorted(result[org["it.dev"].id]) == _ids(org, "it.dev", "it.dev.backend")
    assert sorted(result[org["aXb"].id]) == _ids(org, "aXb", "aXb.c")


def test_ancestor_and_descendant_in_one_call(org):
    result = interface.department_subtree_ids([org["it"].id, org["it.dev"].id])
    assert org["it.dev.backend"].id in result[org["it"].id]
    assert sorted(result[org["it.dev"].id]) == _ids(org, "it.dev", "it.dev.backend")


def test_subtree_unknown_id_absent(org):
    assert interface.department_subtree_ids([10_000_000]) == {}


def test_subtree_empty_input(org):
    assert interface.department_subtree_ids([]) == {}


def test_subtree_query_count_does_not_grow_with_roots(org):
    """Два запроса при любом числе корней. Первый вызов — разогрев: рубильник
    сервиса (``require_service``) кэшируется на 5 с, а кэш чистится перед
    каждым тестом — иначе считался бы и его запрос."""
    from django.db import connection as conn
    from django.test.utils import CaptureQueriesContext

    interface.department_subtree_ids([org["it"].id])
    with CaptureQueriesContext(conn) as one:
        interface.department_subtree_ids([org["it"].id])
    roots = [org[p].id for p in ("it", "itops", "a_b", "aXb", "hq")]
    with CaptureQueriesContext(conn) as five:
        interface.department_subtree_ids(roots)
    assert len(one) == len(five) == 2


# ── managed_department_ids ───────────────────────────────────────────────

def test_managed_two_departments(org):
    assert interface.managed_department_ids(9001) == _ids(org, "it", "itops")


def test_managed_inactive_employee_none(org):
    assert interface.managed_department_ids(9002) == []


def test_managed_deleted_employee_none(org):
    assert interface.managed_department_ids(9003) == []


def test_managed_inactive_department_excluded(org):
    assert interface.managed_department_ids(9005) == []


def test_managed_unknown_user_empty(org):
    assert interface.managed_department_ids(424242) == []


# ── department_manager_user_ids ──────────────────────────────────────────

def test_manager_user_ids_of_active_heads(org):
    ids = [org[p].id for p in ("it", "itops", "it.dev")]
    assert interface.department_manager_user_ids(ids) == {
        org["it"].id: 9001, org["itops"].id: 9001}


def test_manager_user_ids_same_filter_as_managed(org):
    """Уволенный, удалённый, без учётки, в неактивном отделе — ни там, ни там:
    получатель уведомления о переносе обязан сам видеть свой отдел (S1-17)."""
    every = [dep.id for dep in org.values()]
    by_department = interface.department_manager_user_ids(every)
    for user_id in (9001, 9002, 9003, 9005):
        assert sorted(d for d, u in by_department.items() if u == user_id) == \
            interface.managed_department_ids(user_id)
    assert org["aXb.c"].id not in by_department


def test_manager_user_ids_empty_input(org):
    assert interface.department_manager_user_ids([]) == {}


# ── выключенный hr и индекс ──────────────────────────────────────────────

@pytest.mark.parametrize("call", [
    lambda: interface.department_subtree_ids([1]),
    lambda: interface.managed_department_ids(1),
    lambda: interface.department_manager_user_ids([1]),
])
def test_hr_disabled_raises(monkeypatch, call):
    from apps.core import services as core_services

    monkeypatch.setattr(core_services, "service_status",
                        lambda name: (False, "выключено для проверки"))
    with pytest.raises(ServiceDisabled):
        call()


def test_path_has_like_index():
    """``path LIKE 'P.%'`` идёт по индексу ``varchar_pattern_ops``: Django
    заводит его сам для ``unique`` ``CharField`` — отдельная миграция не нужна."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT indexdef FROM pg_indexes WHERE tablename = 'hr_department' "
            "AND indexname LIKE %s", ["%path%like%"])
        rows = [row[0] for row in cursor.fetchall()]
    assert rows and "varchar_pattern_ops" in rows[0]

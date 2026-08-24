"""Контракт /api/hr/v1/org/employee-relations/* — не порт, ручная правка
руководителей/подчинённых на уровне СОТРУДНИКОВ (в дополнение к
позиционной ``ReportingRelation``, см. test_org_api.py).

Персональный слой ``EmployeeReportingOverride``: сотрудник X подчиняется
сотруднику Y независимо от связей их должностей. Приоритет разрешения
руководителя в ``get_org_tree`` (``mode=employees``): override -> позиционная
ReportingRelation -> явный Department.manager -> старый fallback-edge
"employment" от отдела/должности (см. докстринг ``org_service.get_org_tree``).

Авторизация — как и у ``/org/relations`` после смены гейта: ``hr.org.edit``
(HR senior/lead), elevated-токены (``is_staff``) проходят через wildcard.

Зафиксированные ловушки:
  * add_employee_relation: 422 self-reference, 404 неизвестный/мягко
    удалённый сотрудник, 422 неактивный сотрудник, 409 дубль
    (superior, subordinate, relation_type), 409 повторный direct-руководитель
    (частичный unique-констрейнт допускает ровно одного), 409 цикл —
    включая СМЕШАННЫЙ цикл (руководитель выведен из должностей, override
    замыкает кольцо в обратную сторону);
  * remove_employee_relation: 404 "Связь подчинения не найдена";
  * GET employee-relations фильтрует по employee_id/department_id (любая
    из сторон связи).

План: docs/plans/2026-07-20-hr-domain.md
"""
from __future__ import annotations

import datetime

import pytest
from django.db import connection
from django.db.utils import IntegrityError
from django.test import Client

from apps.hr.models import Department, Employee, EmployeeReportingOverride, Position, ReportingRelation
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/hr/v1/org"


@pytest.fixture
def dep(db):
    return Department.objects.create(name="ИТ", path="it")


@pytest.fixture
def hr_dep(db):
    return Department.objects.create(name="HR", path="hr-dept")


def _pos(title, dep, weight, **kw):
    return Position.objects.create(title=title, department=dep, weight=weight, **kw)


def _emp(dep, pos, email, **kw):
    return Employee.objects.create(
        first_name="И", last_name="И", email=email, department=dep, position=pos,
        hire_date=datetime.date(2024, 1, 9), **kw,
    )


@pytest.fixture
def auth(db):
    user = User.objects.create(
        username="orgemp-user", email="orgemp-user@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    user.set_password("S3cret!")
    user.save()
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def admin_auth(db):
    user = User.objects.create(
        username="orgemp-admin", email="orgemp-admin@htq.test", password="x", status=UserStatus.ACTIVE,
        is_staff=True,
    )
    user.set_password("Adm1n!Pass")
    user.save()
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def middle_auth(db, hr_dep):
    pos = _pos("HR Manager", hr_dep, weight=930)
    user = User.objects.create(
        username="orgemp-middle", email="orgemp-middle@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    user.set_password("S3cret!Pass1")
    user.save()
    Employee.objects.create(
        first_name="И", last_name="И", email="orgemp-middle@htq.test",
        department=hr_dep, position=pos, hire_date=datetime.date(2024, 1, 9), user_id=user.id,
    )
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def senior_auth(db, hr_dep):
    pos = _pos("Senior HR Manager", hr_dep, weight=931)
    user = User.objects.create(
        username="orgemp-senior", email="orgemp-senior@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    user.set_password("S3cret!Pass1")
    user.save()
    Employee.objects.create(
        first_name="И", last_name="И", email="orgemp-senior@htq.test",
        department=hr_dep, position=pos, hire_date=datetime.date(2024, 1, 9), user_id=user.id,
    )
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


def _has_edge(edges: list[dict], **expected) -> bool:
    return any(all(edge.get(k) == v for k, v in expected.items()) for edge in edges)


# ── модель — констрейнты ─────────────────────────────────────────────────

@pytest.mark.django_db
def test_model_columns_and_two_fk_indexes(dep):
    def _indexed_columns(table: str) -> set[str]:
        with connection.cursor() as cur:
            cur.execute("SELECT indexdef FROM pg_indexes WHERE tablename = %s", [table])
            defs = [r[0] for r in cur.fetchall()]
        cols: set[str] = set()
        for d in defs:
            inner = d[d.rfind("(") + 1: d.rfind(")")]
            for part in inner.split(","):
                token = part.strip().strip('"').split()[0]
                cols.add(token.strip('"'))
        return cols

    assert {"superior_id", "subordinate_id"} <= _indexed_columns("hr_employeereportingoverride")


@pytest.mark.django_db
def test_model_unique_constraint(dep):
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    b = _emp(dep, p, "b@htq.test")
    EmployeeReportingOverride.objects.create(superior=a, subordinate=b, relation_type="direct")
    with pytest.raises(IntegrityError):
        EmployeeReportingOverride.objects.create(superior=a, subordinate=b, relation_type="direct")


@pytest.mark.django_db
def test_model_self_reference_check_constraint(dep):
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    with pytest.raises(IntegrityError):
        EmployeeReportingOverride.objects.create(superior=a, subordinate=a, relation_type="direct")


@pytest.mark.django_db
def test_model_one_direct_superior_partial_unique_constraint(dep):
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    b = _emp(dep, p, "b@htq.test")
    c = _emp(dep, p, "c@htq.test")
    EmployeeReportingOverride.objects.create(superior=a, subordinate=c, relation_type="direct")
    with pytest.raises(IntegrityError):
        EmployeeReportingOverride.objects.create(superior=b, subordinate=c, relation_type="direct")


@pytest.mark.django_db
def test_model_allows_multiple_non_direct_superiors(dep):
    """Частичный unique бьёт только relation_type="direct" — functional/
    project не ограничены (матричная структура)."""
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    b = _emp(dep, p, "b@htq.test")
    c = _emp(dep, p, "c@htq.test")
    EmployeeReportingOverride.objects.create(superior=a, subordinate=c, relation_type="functional")
    EmployeeReportingOverride.objects.create(superior=b, subordinate=c, relation_type="functional")
    assert EmployeeReportingOverride.objects.filter(subordinate=c).count() == 2


# ── auth ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_list_requires_jwt():
    assert Client().get(f"{BASE}/employee-relations").status_code == 401


@pytest.mark.django_db
def test_create_requires_jwt():
    resp = Client().post(f"{BASE}/employee-relations", data={}, content_type="application/json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_create_forbidden_without_hr_access(auth, dep):
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    b = _emp(dep, p, "b@htq.test")
    resp = Client().post(
        f"{BASE}/employee-relations",
        data={"superior_employee_id": a.id, "subordinate_employee_id": b.id},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing permission: hr.org.edit"


@pytest.mark.django_db
def test_create_forbidden_for_middle_hr(middle_auth, dep):
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    b = _emp(dep, p, "b@htq.test")
    resp = Client().post(
        f"{BASE}/employee-relations",
        data={"superior_employee_id": a.id, "subordinate_employee_id": b.id},
        content_type="application/json", **middle_auth,
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_create_allowed_for_senior_hr(senior_auth, dep):
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    b = _emp(dep, p, "b@htq.test")
    resp = Client().post(
        f"{BASE}/employee-relations",
        data={"superior_employee_id": a.id, "subordinate_employee_id": b.id},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 201


@pytest.mark.django_db
def test_create_allowed_for_admin(admin_auth, dep):
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    b = _emp(dep, p, "b@htq.test")
    resp = Client().post(
        f"{BASE}/employee-relations",
        data={"superior_employee_id": a.id, "subordinate_employee_id": b.id},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 201


@pytest.mark.django_db
def test_delete_forbidden_without_hr_access(auth, dep):
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    b = _emp(dep, p, "b@htq.test")
    rel = EmployeeReportingOverride.objects.create(superior=a, subordinate=b)
    resp = Client().delete(f"{BASE}/employee-relations/{rel.id}", **auth)
    assert resp.status_code == 403


# ── /org/employee-relations — CRUD ───────────────────────────────────────────

@pytest.mark.django_db
def test_create_success_returns_201_relation_out(senior_auth, dep):
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "boss@htq.test")
    b = _emp(dep, p, "report@htq.test")
    resp = Client().post(
        f"{BASE}/employee-relations",
        data={
            "superior_employee_id": a.id, "subordinate_employee_id": b.id,
            "relation_type": "functional", "note": "испытательный срок",
        },
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["superior_employee_id"] == a.id
    assert body["subordinate_employee_id"] == b.id
    assert body["relation_type"] == "functional"
    assert body["note"] == "испытательный срок"
    assert body["superior_name"] and body["subordinate_name"]
    assert EmployeeReportingOverride.objects.filter(id=body["id"]).exists()


@pytest.mark.django_db
def test_create_self_reference_422(senior_auth, dep):
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    resp = Client().post(
        f"{BASE}/employee-relations",
        data={"superior_employee_id": a.id, "subordinate_employee_id": a.id},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Сотрудник не может подчиняться сам себе"


@pytest.mark.django_db
def test_create_unknown_employee_404(senior_auth, dep):
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    resp = Client().post(
        f"{BASE}/employee-relations",
        data={"superior_employee_id": a.id, "subordinate_employee_id": 999999},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_create_soft_deleted_employee_404(senior_auth, dep):
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    b = _emp(dep, p, "b@htq.test", is_deleted=True)
    resp = Client().post(
        f"{BASE}/employee-relations",
        data={"superior_employee_id": a.id, "subordinate_employee_id": b.id},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_create_inactive_employee_422(senior_auth, dep):
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    b = _emp(dep, p, "b@htq.test", status="suspended")
    resp = Client().post(
        f"{BASE}/employee-relations",
        data={"superior_employee_id": a.id, "subordinate_employee_id": b.id},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_create_duplicate_409(senior_auth, dep):
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    b = _emp(dep, p, "b@htq.test")
    EmployeeReportingOverride.objects.create(superior=a, subordinate=b, relation_type="direct")
    resp = Client().post(
        f"{BASE}/employee-relations",
        data={"superior_employee_id": a.id, "subordinate_employee_id": b.id, "relation_type": "direct"},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Такая связь подчинения уже существует"


@pytest.mark.django_db
def test_create_second_direct_superior_409(senior_auth, dep):
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    b = _emp(dep, p, "b@htq.test")
    c = _emp(dep, p, "c@htq.test")
    EmployeeReportingOverride.objects.create(superior=a, subordinate=c, relation_type="direct")
    resp = Client().post(
        f"{BASE}/employee-relations",
        data={"superior_employee_id": b.id, "subordinate_employee_id": c.id, "relation_type": "direct"},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 409
    assert "прямой руководитель" in resp.json()["detail"]


@pytest.mark.django_db
def test_create_direct_cycle_409(senior_auth, dep):
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    b = _emp(dep, p, "b@htq.test")
    EmployeeReportingOverride.objects.create(superior=a, subordinate=b, relation_type="direct")
    resp = Client().post(
        f"{BASE}/employee-relations",
        data={"superior_employee_id": b.id, "subordinate_employee_id": a.id, "relation_type": "direct"},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Эта связь замкнёт цепочку подчинения в кольцо"


@pytest.mark.django_db
def test_create_mixed_cycle_via_position_relation_409(senior_auth, dep):
    """A выведен из должностей как начальник B (позиционная
    ReportingRelation): держатель вышестоящей должности. Пользователь
    пытается добавить персональный override B -> A — это замыкает
    СМЕШАННЫЙ цикл (позиция + override), и его обязана поймать
    _build_effective_employee_superiors, а не только явные override-строки."""
    boss_pos = _pos("Начальник", dep, weight=10)
    report_pos = _pos("Подчинённый", dep, weight=20)
    ReportingRelation.objects.create(
        superior_position=boss_pos, subordinate_position=report_pos,
        relation_type="direct", effective_from=datetime.date(2024, 1, 1),
    )
    a = _emp(dep, boss_pos, "a@htq.test")
    b = _emp(dep, report_pos, "b@htq.test")

    resp = Client().post(
        f"{BASE}/employee-relations",
        data={"superior_employee_id": b.id, "subordinate_employee_id": a.id, "relation_type": "direct"},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Эта связь замкнёт цепочку подчинения в кольцо"


@pytest.mark.django_db
def test_delete_204(senior_auth, dep):
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    b = _emp(dep, p, "b@htq.test")
    rel = EmployeeReportingOverride.objects.create(superior=a, subordinate=b)
    resp = Client().delete(f"{BASE}/employee-relations/{rel.id}", **senior_auth)
    assert resp.status_code == 204
    assert not EmployeeReportingOverride.objects.filter(id=rel.id).exists()


@pytest.mark.django_db
def test_delete_404(senior_auth):
    resp = Client().delete(f"{BASE}/employee-relations/999999", **senior_auth)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Связь подчинения не найдена"


@pytest.mark.django_db
def test_list_filters_by_employee_id(senior_auth, dep):
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    b = _emp(dep, p, "b@htq.test")
    c = _emp(dep, p, "c@htq.test")
    EmployeeReportingOverride.objects.create(superior=a, subordinate=b, relation_type="direct")
    EmployeeReportingOverride.objects.create(superior=c, subordinate=a, relation_type="functional")

    resp = Client().get(f"{BASE}/employee-relations?employee_id={a.id}", **senior_auth)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2


@pytest.mark.django_db
def test_list_filters_by_department_id(senior_auth, dep):
    other = Department.objects.create(name="Другой", path="other")
    p_dep = _pos("P1", dep, weight=10)
    p_other = _pos("P2", other, weight=20)
    a = _emp(dep, p_dep, "a@htq.test")
    b = _emp(other, p_other, "b@htq.test")
    EmployeeReportingOverride.objects.create(superior=a, subordinate=b, relation_type="direct")

    resp = Client().get(f"{BASE}/employee-relations?department_id={dep.id}", **senior_auth)
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp2 = Client().get(f"{BASE}/employee-relations?department_id={999999}", **senior_auth)
    assert resp2.json() == []


# ── org/tree mode=employees — резолв через override/position/department ────

@pytest.mark.django_db
def test_tree_employees_mode_uses_explicit_override_edge(auth, dep):
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    b = _emp(dep, p, "b@htq.test")
    rel = EmployeeReportingOverride.objects.create(superior=a, subordinate=b, relation_type="direct")

    body = Client().get(f"{BASE}/tree?mode=employees", **auth).json()
    assert _has_edge(
        body["edges"], source=f"emp_{a.id}", target=f"emp_{b.id}",
        relation_type="direct", origin="employee", relation_id=rel.id,
    )


@pytest.mark.django_db
def test_tree_employees_mode_falls_back_to_position_relation(auth, dep):
    """Без override, но с позиционной ReportingRelation — держатель
    вышестоящей должности становится руководителем в mode=employees."""
    boss_pos = _pos("Начальник", dep, weight=10)
    report_pos = _pos("Подчинённый", dep, weight=20)
    ReportingRelation.objects.create(
        superior_position=boss_pos, subordinate_position=report_pos,
        relation_type="direct", effective_from=datetime.date(2024, 1, 1),
    )
    a = _emp(dep, boss_pos, "a@htq.test")
    b = _emp(dep, report_pos, "b@htq.test")

    body = Client().get(f"{BASE}/tree?mode=employees", **auth).json()
    assert _has_edge(
        body["edges"], source=f"emp_{a.id}", target=f"emp_{b.id}",
        origin="position", relation_id=None,
    )


@pytest.mark.django_db
def test_tree_employees_mode_falls_back_to_department_manager(auth, dep):
    p = _pos("P", dep, weight=10)
    manager = _emp(dep, p, "manager@htq.test")
    report_pos = _pos("Подчинённый", dep, weight=20)
    report = _emp(dep, report_pos, "report@htq.test")
    dep.manager = manager
    dep.save(update_fields=["manager"])

    body = Client().get(f"{BASE}/tree?mode=employees", **auth).json()
    assert _has_edge(
        body["edges"], source=f"emp_{manager.id}", target=f"emp_{report.id}",
        origin="department", relation_id=None,
    )


@pytest.mark.django_db
def test_tree_employees_mode_falls_back_to_employment_edge_when_nothing_resolves(auth, dep):
    """Ни override, ни позиционной связи, ни явного Department.manager —
    старое поведение сохранено: ребро от отдела с relation_type=employment."""
    p = _pos("Инженер", dep, weight=10)
    emp = _emp(dep, p, "e@htq.test")

    body = Client().get(f"{BASE}/tree?mode=employees", **auth).json()
    assert _has_edge(
        body["edges"], source=f"dept_{dep.id}", target=f"emp_{emp.id}",
        relation_type="employment", origin="employment", relation_id=None,
    )


@pytest.mark.django_db
def test_tree_employees_mode_override_takes_priority_over_position_relation(auth, dep):
    boss_pos = _pos("Начальник", dep, weight=10)
    report_pos = _pos("Подчинённый", dep, weight=20)
    other_pos = _pos("Другой", dep, weight=30)
    ReportingRelation.objects.create(
        superior_position=boss_pos, subordinate_position=report_pos,
        relation_type="direct", effective_from=datetime.date(2024, 1, 1),
    )
    a = _emp(dep, boss_pos, "a@htq.test")
    b = _emp(dep, report_pos, "b@htq.test")
    other = _emp(dep, other_pos, "other@htq.test")
    EmployeeReportingOverride.objects.create(superior=other, subordinate=b, relation_type="direct")

    body = Client().get(f"{BASE}/tree?mode=employees", **auth).json()
    assert _has_edge(
        body["edges"], source=f"emp_{other.id}", target=f"emp_{b.id}", origin="employee",
    )
    assert not _has_edge(body["edges"], source=f"emp_{a.id}", target=f"emp_{b.id}")


# ── PUT /org/employee-relations/superior — атомарная замена ──────────────────
#
# Для relation_type="direct" другого способа нет в принципе: частичный unique
# ux_employee_override_one_direct_superior допускает ровно одного прямого
# руководителя, поэтому "создать новую, потом удалить старую" невозможно —
# только снять и поставить, и только в одной транзакции.

@pytest.mark.django_db
def test_set_employee_superior_assigns(senior_auth, dep):
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    b = _emp(dep, p, "b@htq.test")

    resp = Client().put(
        f"{BASE}/employee-relations/superior",
        data={"subordinate_id": b.id, "superior_id": a.id},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 200
    assert resp.json()["superior_employee_id"] == a.id
    assert EmployeeReportingOverride.objects.filter(
        subordinate=b, relation_type="direct").count() == 1


@pytest.mark.django_db
def test_set_employee_superior_replaces_without_violating_partial_unique(senior_auth, dep):
    """Прямой руководитель ровно один: замена обязана пройти, хотя наивное
    "создать вторую, потом удалить первую" упёрлось бы в констрейнт."""
    p = _pos("P", dep, weight=10)
    old = _emp(dep, p, "old@htq.test")
    new = _emp(dep, p, "new@htq.test")
    sub = _emp(dep, p, "sub@htq.test")
    EmployeeReportingOverride.objects.create(superior=old, subordinate=sub, relation_type="direct")

    resp = Client().put(
        f"{BASE}/employee-relations/superior",
        data={"subordinate_id": sub.id, "superior_id": new.id},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 200
    rels = EmployeeReportingOverride.objects.filter(subordinate=sub, relation_type="direct")
    assert rels.count() == 1
    assert rels.first().superior_id == new.id


@pytest.mark.django_db
def test_set_employee_superior_null_clears(senior_auth, dep):
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    b = _emp(dep, p, "b@htq.test")
    EmployeeReportingOverride.objects.create(superior=a, subordinate=b, relation_type="direct")

    resp = Client().put(
        f"{BASE}/employee-relations/superior",
        data={"subordinate_id": b.id, "superior_id": None},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 200
    assert not EmployeeReportingOverride.objects.filter(subordinate=b).exists()


@pytest.mark.django_db
def test_set_employee_superior_cycle_409_and_rolls_back(senior_auth, dep):
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    b = _emp(dep, p, "b@htq.test")
    EmployeeReportingOverride.objects.create(superior=a, subordinate=b, relation_type="direct")

    resp = Client().put(
        f"{BASE}/employee-relations/superior",
        data={"subordinate_id": a.id, "superior_id": b.id},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 409
    # Существующая связь уцелела — транзакция откатилась целиком.
    assert EmployeeReportingOverride.objects.filter(superior=a, subordinate=b).exists()


@pytest.mark.django_db
def test_set_employee_superior_forbidden_without_permission(auth, dep):
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    b = _emp(dep, p, "b@htq.test")
    resp = Client().put(
        f"{BASE}/employee-relations/superior",
        data={"subordinate_id": b.id, "superior_id": a.id},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 403


# ── PATCH /org/employee-relations/{id} — смена типа ──────────────────────────

@pytest.mark.django_db
def test_change_employee_relation_type(senior_auth, dep):
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    b = _emp(dep, p, "b@htq.test")
    rel = EmployeeReportingOverride.objects.create(
        superior=a, subordinate=b, relation_type="functional")

    resp = Client().patch(
        f"{BASE}/employee-relations/{rel.id}",
        data={"relation_type": "project"},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 200
    rel.refresh_from_db()
    assert rel.relation_type == "project"


@pytest.mark.django_db
def test_change_employee_relation_type_to_direct_blocked_by_existing_direct(senior_auth, dep):
    """Перевод в direct обязан упереться в частичный unique: у подчинённого
    уже есть прямой руководитель."""
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    other = _emp(dep, p, "other@htq.test")
    sub = _emp(dep, p, "sub@htq.test")
    EmployeeReportingOverride.objects.create(superior=other, subordinate=sub, relation_type="direct")
    rel = EmployeeReportingOverride.objects.create(
        superior=a, subordinate=sub, relation_type="functional")

    resp = Client().patch(
        f"{BASE}/employee-relations/{rel.id}",
        data={"relation_type": "direct"},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 409
    assert "прямой руководитель" in resp.json()["detail"]


@pytest.mark.django_db
def test_change_employee_relation_type_to_direct_cycle_409(senior_auth, dep):
    """В отличие от должностей, здесь смена типа МЕНЯЕТ граф: эффективное
    дерево учитывает только direct. Перевод functional -> direct может
    замкнуть кольцо, и это обязано отлавливаться."""
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    b = _emp(dep, p, "b@htq.test")
    # a -> b прямая; обратная b -> a пока лишь функциональная (в дерево не входит)
    EmployeeReportingOverride.objects.create(superior=a, subordinate=b, relation_type="direct")
    rel = EmployeeReportingOverride.objects.create(
        superior=b, subordinate=a, relation_type="functional")

    resp = Client().patch(
        f"{BASE}/employee-relations/{rel.id}",
        data={"relation_type": "direct"},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 409


@pytest.mark.django_db
def test_change_employee_relation_type_404(senior_auth):
    resp = Client().patch(
        f"{BASE}/employee-relations/999999",
        data={"relation_type": "direct"},
        content_type="application/json", **senior_auth,
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_employee_relation_detail_rejects_other_methods(senior_auth, dep):
    p = _pos("P", dep, weight=10)
    a = _emp(dep, p, "a@htq.test")
    b = _emp(dep, p, "b@htq.test")
    rel = EmployeeReportingOverride.objects.create(superior=a, subordinate=b)
    resp = Client().get(f"{BASE}/employee-relations/{rel.id}", **senior_auth)
    assert resp.status_code == 405

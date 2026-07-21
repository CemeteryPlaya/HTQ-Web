"""Контракт /api/hr/v1/org/* — паритет с services/hr/app/api/v1/org.py.

Провенанс: app/services/org_service.py (get_org_tree/get_subordination_matrix/
add_relation/remove_relation/get_deletion_strategy/set_deletion_strategy) +
app/services/translation_service.py (build_translated_org_tree — переносится
как выключенный no-op seam, без сети). ``org_service.delete_department``
исходника НЕ переносится — мёртвый код (departments-роутер ходит в
``apps.hr.services.department_service``, не в org).

Авторизация (docs/plans/2026-07-20-hr-domain.md, под-модуль org): reads —
обычный jwt; writes (``POST /relations``, ``DELETE /relations/{id}``,
``PUT /settings/deletion-strategy``) — ``admin=True`` (require_hr_write
исходника = is_elevated), ровно как у positions/*.

Зафиксированные ловушки паритета:
  * add_relation: 422 self-reference, 409 duplicate (superior, subordinate,
    relation_type);
  * remove_relation: 404 detail == "Relation not found";
  * settings PUT возвращает {"deletion_strategy": <val>}, дефолт GET — "block";
  * матрица — форма {superiors, subordinates, cells}, пустая при отсутствии связей;
  * дерево (mode=positions) без явной связи фолбэкается на голову отдела/родителя;
  * lang="en" без настроенного провайдера — no-op (исходное ru-дерево, без сети).

План: docs/plans/2026-07-20-hr-domain.md
"""
from __future__ import annotations

import datetime

import pytest
from django.db import connection
from django.db.utils import IntegrityError
from django.test import Client

from apps.hr.models import Department, Employee, Position, ReportingRelation
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/hr/v1/org"


@pytest.fixture
def dep(db):
    return Department.objects.create(name="ИТ", path="it")


@pytest.fixture
def auth(db):
    """Обычный вошедший пользователь — годится для reads, НЕ годится для writes."""
    user = User.objects.create(
        username="org-user", email="org-user@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    user.set_password("S3cret!")
    user.save()
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def admin_auth(db):
    """is_staff=True — elevated, требуется для writes (require_hr_write)."""
    user = User.objects.create(
        username="org-admin", email="org-admin@htq.test", password="x", status=UserStatus.ACTIVE,
        is_staff=True,
    )
    user.set_password("Adm1n!Pass")
    user.save()
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


def _pos(title, dep, weight, **kw):
    return Position.objects.create(title=title, department=dep, weight=weight, **kw)


def _emp(dep, pos, email, **kw):
    return Employee.objects.create(
        first_name="И", last_name="И", email=email, department=dep, position=pos,
        hire_date=datetime.date(2024, 1, 9), **kw,
    )


def _rel(superior, subordinate, relation_type="direct", **kw):
    return ReportingRelation.objects.create(
        superior_position=superior, subordinate_position=subordinate,
        relation_type=relation_type, effective_from=datetime.date(2024, 1, 1), **kw,
    )


# ── модель ReportingRelation — сверка индексов/констрейнтов ────────────────

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


@pytest.mark.django_db
def test_reporting_relation_columns_and_two_fk_indexes(dep):
    # Исходник: Index("ix_reporting_superior") + Index("ix_reporting_subordinate")
    # — SQLAlchemy FK индекс не создаёт сам по себе, поэтому там оба заведены
    # явно. Django FK индексирует свою колонку по умолчанию — воспроизводит
    # РОВНО те же два индекса без db_index=False.
    cols = {
        r[0]: {"nullable": r[1] == "YES", "default": r[2]}
        for r in connection.cursor().execute(
            "SELECT column_name, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_name = 'hr_reportingrelation'"
        ).fetchall()
    }
    assert not cols["superior_position_id"]["nullable"]
    assert not cols["subordinate_position_id"]["nullable"]
    assert not cols["effective_from"]["nullable"]
    assert cols["effective_to"]["nullable"]
    assert cols["relation_type"]["default"] is not None
    assert cols["created_at"]["default"] is not None
    assert {"superior_position_id", "subordinate_position_id"} <= _indexed_columns("hr_reportingrelation")


@pytest.mark.django_db
def test_reporting_relation_unique_constraint(dep):
    a = _pos("A", dep, weight=10)
    b = _pos("B", dep, weight=20)
    _rel(a, b, "direct")
    with pytest.raises(IntegrityError):
        ReportingRelation.objects.create(
            superior_position=a, subordinate_position=b, relation_type="direct",
            effective_from=datetime.date(2024, 1, 1),
        )


@pytest.mark.django_db
def test_reporting_relation_self_reference_check_constraint(dep):
    a = _pos("A", dep, weight=10)
    with pytest.raises(IntegrityError):
        ReportingRelation.objects.create(
            superior_position=a, subordinate_position=a, relation_type="direct",
            effective_from=datetime.date(2024, 1, 1),
        )


# ── auth ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_tree_requires_jwt():
    assert Client().get(f"{BASE}/tree").status_code == 401


@pytest.mark.django_db
def test_matrix_requires_jwt():
    assert Client().get(f"{BASE}/subordination-matrix").status_code == 401


@pytest.mark.django_db
def test_deletion_strategy_get_requires_jwt():
    assert Client().get(f"{BASE}/settings/deletion-strategy").status_code == 401


@pytest.mark.django_db
def test_add_relation_requires_jwt_at_all():
    resp = Client().post(f"{BASE}/relations", data={}, content_type="application/json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_add_relation_forbidden_for_non_admin_jwt_user(auth, dep):
    a = _pos("A", dep, weight=10)
    b = _pos("B", dep, weight=20)
    resp = Client().post(
        f"{BASE}/relations",
        data={"superior_position_id": a.id, "subordinate_position_id": b.id},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_remove_relation_forbidden_for_non_admin(auth, dep):
    a = _pos("A", dep, weight=10)
    b = _pos("B", dep, weight=20)
    rel = _rel(a, b)
    resp = Client().delete(f"{BASE}/relations/{rel.id}", **auth)
    assert resp.status_code == 403


@pytest.mark.django_db
def test_deletion_strategy_put_forbidden_for_non_admin(auth):
    resp = Client().put(
        f"{BASE}/settings/deletion-strategy", data={"deletion_strategy": "cascade"},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 403


# ── /org/relations — CRUD ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_add_relation_success_returns_201_relation_out(admin_auth, dep):
    a = _pos("Начальник", dep, weight=10)
    b = _pos("Подчинённый", dep, weight=20)

    resp = Client().post(
        f"{BASE}/relations",
        data={
            "superior_position_id": a.id, "subordinate_position_id": b.id,
            "relation_type": "functional", "effective_from": "2024-03-01",
        },
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["superior_position_id"] == a.id
    assert body["subordinate_position_id"] == b.id
    assert body["relation_type"] == "functional"
    assert body["effective_from"] == "2024-03-01"
    assert body["effective_to"] is None
    assert ReportingRelation.objects.filter(id=body["id"]).exists()


@pytest.mark.django_db
def test_add_relation_defaults_relation_type_direct_and_effective_from_today(admin_auth, dep):
    a = _pos("A", dep, weight=10)
    b = _pos("B", dep, weight=20)
    resp = Client().post(
        f"{BASE}/relations",
        data={"superior_position_id": a.id, "subordinate_position_id": b.id},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["relation_type"] == "direct"
    assert body["effective_from"] == datetime.date.today().isoformat()


@pytest.mark.django_db
def test_add_relation_self_reference_422(admin_auth, dep):
    a = _pos("A", dep, weight=10)
    resp = Client().post(
        f"{BASE}/relations",
        data={"superior_position_id": a.id, "subordinate_position_id": a.id},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "A position cannot be subordinate to itself"


@pytest.mark.django_db
def test_add_relation_duplicate_409(admin_auth, dep):
    a = _pos("A", dep, weight=10)
    b = _pos("B", dep, weight=20)
    _rel(a, b, "direct")

    resp = Client().post(
        f"{BASE}/relations",
        data={"superior_position_id": a.id, "subordinate_position_id": b.id, "relation_type": "direct"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "This reporting relation already exists"


@pytest.mark.django_db
def test_add_relation_same_positions_different_type_allowed(admin_auth, dep):
    a = _pos("A", dep, weight=10)
    b = _pos("B", dep, weight=20)
    _rel(a, b, "direct")

    resp = Client().post(
        f"{BASE}/relations",
        data={"superior_position_id": a.id, "subordinate_position_id": b.id, "relation_type": "project"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 201


@pytest.mark.django_db
def test_remove_relation_204(admin_auth, dep):
    a = _pos("A", dep, weight=10)
    b = _pos("B", dep, weight=20)
    rel = _rel(a, b)

    resp = Client().delete(f"{BASE}/relations/{rel.id}", **admin_auth)
    assert resp.status_code == 204
    assert not ReportingRelation.objects.filter(id=rel.id).exists()


@pytest.mark.django_db
def test_remove_relation_404(admin_auth):
    resp = Client().delete(f"{BASE}/relations/999999", **admin_auth)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Relation not found"


# ── /org/subordination-matrix ────────────────────────────────────────────────

@pytest.mark.django_db
def test_matrix_empty_shape(auth):
    resp = Client().get(f"{BASE}/subordination-matrix", **auth)
    assert resp.status_code == 200
    assert resp.json() == {"superiors": [], "subordinates": [], "cells": []}


@pytest.mark.django_db
def test_matrix_returns_superiors_subordinates_and_cells(auth, dep):
    a = _pos("Начальник", dep, weight=10)
    b = _pos("Подчинённый", dep, weight=20)
    rel = _rel(a, b, "direct")

    resp = Client().get(f"{BASE}/subordination-matrix", **auth)
    body = resp.json()
    assert [s["id"] for s in body["superiors"]] == [a.id]
    assert [s["id"] for s in body["subordinates"]] == [b.id]
    assert body["cells"] == [{
        "superior_position_id": a.id, "subordinate_position_id": b.id,
        "relation_type": "direct",
        "effective_from": rel.effective_from.isoformat(), "effective_to": None,
    }]
    assert set(body["superiors"][0]) == {"id", "title", "weight", "level"}


@pytest.mark.django_db
def test_matrix_filters_by_unit_id(auth):
    dep_a = Department.objects.create(name="A", path="a")
    dep_b = Department.objects.create(name="B", path="b")
    a1 = _pos("A1", dep_a, weight=10)
    a2 = _pos("A2", dep_a, weight=11)
    b1 = _pos("B1", dep_b, weight=20)
    b2 = _pos("B2", dep_b, weight=21)
    _rel(a1, a2)
    _rel(b1, b2)

    resp = Client().get(f"{BASE}/subordination-matrix?unit_id={dep_a.id}", **auth)
    body = resp.json()
    assert [s["id"] for s in body["superiors"]] == [a1.id]
    assert [s["id"] for s in body["subordinates"]] == [a2.id]


# ── /org/settings/deletion-strategy ────────────────────────────────────────────

@pytest.mark.django_db
def test_deletion_strategy_defaults_to_block(auth):
    resp = Client().get(f"{BASE}/settings/deletion-strategy", **auth)
    assert resp.status_code == 200
    assert resp.json() == {"deletion_strategy": "block"}


@pytest.mark.django_db
def test_deletion_strategy_put_then_get_roundtrips(admin_auth, auth):
    put_resp = Client().put(
        f"{BASE}/settings/deletion-strategy", data={"deletion_strategy": "cascade"},
        content_type="application/json", **admin_auth,
    )
    assert put_resp.status_code == 200
    assert put_resp.json() == {"deletion_strategy": "cascade"}

    get_resp = Client().get(f"{BASE}/settings/deletion-strategy", **auth)
    assert get_resp.json() == {"deletion_strategy": "cascade"}


@pytest.mark.django_db
def test_deletion_strategy_put_invalid_value_422(admin_auth):
    resp = Client().put(
        f"{BASE}/settings/deletion-strategy", data={"deletion_strategy": "explode"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 422


# ── /org/tree ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_tree_positions_mode_uses_explicit_relation_as_edge(auth, dep):
    boss = _pos("Начальник", dep, weight=10)
    report = _pos("Подчинённый", dep, weight=20)
    _emp(dep, boss, "boss@htq.test")
    _emp(dep, report, "report@htq.test")
    _rel(boss, report, "direct")

    resp = Client().get(f"{BASE}/tree", **auth)
    assert resp.status_code == 200
    body = resp.json()
    node_ids = {n["id"] for n in body["nodes"]}
    assert f"pos_{boss.id}" in node_ids
    assert f"pos_{report.id}" in node_ids
    # dept-узлов быть не должно — режим по умолчанию "positions"
    assert not any(n["type"] == "department" for n in body["nodes"])
    assert {
        "source": f"pos_{boss.id}", "target": f"pos_{report.id}", "relation_type": "direct",
    } in body["edges"]


@pytest.mark.django_db
def test_tree_positions_mode_falls_back_to_dept_head_without_explicit_relation(auth, dep):
    """Без явной ReportingRelation узел должности подчинённого падает на
    голову отдела (fallback_parent_pos_id), а не остаётся без родителя."""
    head = _pos("Руководитель", dep, weight=10)
    member = _pos("Инженер", dep, weight=50)
    _emp(dep, head, "head@htq.test")
    _emp(dep, member, "member@htq.test")

    body = Client().get(f"{BASE}/tree", **auth).json()
    assert {
        "source": f"pos_{head.id}", "target": f"pos_{member.id}", "relation_type": "direct",
    } in body["edges"]


@pytest.mark.django_db
def test_tree_employees_mode_returns_employee_nodes(auth, dep):
    pos = _pos("Инженер", dep, weight=10)
    emp = _emp(dep, pos, "e@htq.test")

    body = Client().get(f"{BASE}/tree?mode=employees", **auth).json()
    emp_nodes = [n for n in body["nodes"] if n["type"] == "employee"]
    assert len(emp_nodes) == 1
    assert emp_nodes[0]["id"] == f"emp_{emp.id}"
    assert {
        "source": f"dept_{dep.id}", "target": f"emp_{emp.id}", "relation_type": "employment",
    } in body["edges"]


@pytest.mark.django_db
def test_tree_both_mode_includes_department_and_position_nodes(auth, dep):
    pos = _pos("Инженер", dep, weight=10)
    _emp(dep, pos, "e@htq.test")

    body = Client().get(f"{BASE}/tree?mode=both", **auth).json()
    assert any(n["type"] == "department" and n["id"] == f"dept_{dep.id}" for n in body["nodes"])


@pytest.mark.django_db
def test_tree_root_id_filters_to_subtree(auth):
    it = Department.objects.create(name="ИТ", path="it")
    dev = Department.objects.create(name="Разработка", path="it.dev")
    fin = Department.objects.create(name="Финансы", path="fin")
    p_it = _pos("ИТ-должность", it, weight=10)
    p_dev = _pos("Дев-должность", dev, weight=20)
    p_fin = _pos("Фин-должность", fin, weight=30)

    body = Client().get(f"{BASE}/tree?root_id={it.id}&mode=both", **auth).json()
    dept_ids = {n["meta"]["id"] for n in body["nodes"] if n["type"] == "department"}
    assert dept_ids == {it.id, dev.id}
    pos_ids = {n["meta"]["department_id"] for n in body["nodes"] if n["type"] == "position"}
    assert fin.id not in pos_ids


@pytest.mark.django_db
def test_tree_root_id_not_found_404(auth):
    resp = Client().get(f"{BASE}/tree?root_id=999999", **auth)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Root unit not found"


@pytest.mark.django_db
def test_tree_invalid_mode_422(auth):
    resp = Client().get(f"{BASE}/tree?mode=bogus", **auth)
    assert resp.status_code == 422


@pytest.mark.django_db
def test_tree_invalid_depth_422(auth):
    resp = Client().get(f"{BASE}/tree?depth=0", **auth)
    assert resp.status_code == 422
    resp2 = Client().get(f"{BASE}/tree?depth=11", **auth)
    assert resp2.status_code == 422


# ── перевод (D9) — lang=en без настроенного провайдера = no-op, без сети ────

@pytest.mark.django_db
def test_tree_lang_en_is_noop_without_configured_provider(auth, dep, monkeypatch):
    """GOOGLE_TRANSLATE_API_KEY/LIBRE_TRANSLATE_API_URL не заданы нигде в
    htqweb/settings (граница задачи не трогает settings-модули) — поэтому
    build_translated_org_tree ВСЕГДА no-op. Подменяем httpx.Client, чтобы
    любая попытка сети роняла тест — доказательство, что сеть не используется."""
    import httpx

    def _boom(*args, **kwargs):
        raise AssertionError("networked httpx.Client() must not be constructed when no provider is configured")

    monkeypatch.setattr(httpx, "Client", _boom)

    pos = _pos("Инженер", dep, weight=10)
    _emp(dep, pos, "e@htq.test")

    ru_body = Client().get(f"{BASE}/tree", **auth).json()
    en_body = Client().get(f"{BASE}/tree?lang=en", **auth).json()
    assert en_body == ru_body


@pytest.mark.django_db
def test_tree_lang_invalid_422(auth):
    resp = Client().get(f"{BASE}/tree?lang=fr", **auth)
    assert resp.status_code == 422

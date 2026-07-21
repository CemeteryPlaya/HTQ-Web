"""Контракт /api/hr/v1/departments/* — паритет с services/hr/app/api/v1/departments.py.

Провенанс формы ответов: app/schemas/department.py (DepartmentOut,
DepartmentTree, DepartmentWithPositions), поведение — app/services/
department_service.py + app/repositories/department_repo.py.

Зафиксированные ловушки паритета (проверяются тестами ниже):
  * список и дерево отдают ТОЛЬКО активные отделы, порядок — по path;
  * /{id}/children из-за LIKE 'parent.%' отдаёт ВЕСЬ поддерев, а не прямых
    детей (докстринг исходника врёт), порядок — по name, только активные;
  * /{id}/employees отдаёт сотрудников ВКЛЮЧАЯ мягко удалённых (в связи
    исходника фильтра нет);
  * DELETE при наличии зависимостей и cascade=false — 409 со СТРУКТУРНЫМ
    detail (объект, не строка);
  * POST без path генерирует его транслитерацией имени, с учётом parent_id.

План: docs/plans/2026-07-20-hr-domain.md
"""
import datetime

import pytest
from django.test import Client

from apps.hr.models import Department, Employee, Position, ReportingRelation
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/hr/v1/departments"


@pytest.fixture
def auth(db):
    user = User.objects.create(
        username="hr-user", email="hr@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    user.set_password("S3cret!")
    user.save()
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


def _dep(name, path, **kw):
    return Department.objects.create(name=name, path=path, **kw)


def _pos(title, dep, weight, **kw):
    return Position.objects.create(title=title, department=dep, weight=weight, **kw)


def _emp(dep, pos, email, **kw):
    return Employee.objects.create(
        first_name="И", last_name="И", email=email, department=dep, position=pos,
        hire_date=datetime.date(2024, 1, 9), **kw,
    )


# ── auth ────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_requires_jwt():
    assert Client().get(f"{BASE}/").status_code == 401


# ── GET / (list) ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_list_returns_only_active_ordered_by_path_with_positions(auth):
    it = _dep("ИТ", "it")
    _dep("Архив", "arc", is_active=False)
    dev = _dep("Разработка", "it.dev")
    _pos("Ведущий", it, weight=10)
    _pos("Инженер", it, weight=50)

    resp = Client().get(f"{BASE}/", **auth)
    assert resp.status_code == 200
    body = resp.json()

    assert [d["path"] for d in body] == ["it", "it.dev"]  # активные, по path
    assert {"id", "name", "path", "description", "manager_id", "is_active",
            "created_at", "updated_at", "positions"} <= set(body[0])
    # positions вложены и отсортированы по weight (order_by в связи исходника)
    assert [p["title"] for p in body[0]["positions"]] == ["Ведущий", "Инженер"]
    assert {"id", "title", "department_id", "grade", "weight", "level",
            "is_system"} == set(body[0]["positions"][0])
    assert body[1]["id"] == dev.id


# ── GET /tree ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_tree_nests_by_path_prefix(auth):
    _dep("ИТ", "it")
    _dep("Разработка", "it.dev")
    _dep("Бэкенд", "it.dev.backend")
    _dep("Финансы", "fin")

    body = Client().get(f"{BASE}/tree", **auth).json()

    assert [r["path"] for r in body] == ["fin", "it"] or [r["path"] for r in body] == ["it", "fin"]
    it = next(r for r in body if r["path"] == "it")
    assert [c["path"] for c in it["children"]] == ["it.dev"]
    assert [c["path"] for c in it["children"][0]["children"]] == ["it.dev.backend"]


# ── POST / ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_create_autogenerates_path_by_transliteration(auth):
    resp = Client().post(f"{BASE}/", data={"name": "Отдел Кадров"},
                         content_type="application/json", **auth)
    assert resp.status_code == 201
    assert resp.json()["path"] == "otdel_kadrov"


@pytest.mark.django_db
def test_create_nests_path_under_parent(auth):
    parent = _dep("ИТ", "it")
    resp = Client().post(f"{BASE}/", data={"name": "Разработка", "parent_id": parent.id},
                         content_type="application/json", **auth)
    assert resp.status_code == 201
    assert resp.json()["path"] == "it.razrabotka"


@pytest.mark.django_db
def test_create_honours_explicit_path(auth):
    resp = Client().post(f"{BASE}/", data={"name": "ИТ", "path": "custom.path"},
                         content_type="application/json", **auth)
    assert resp.status_code == 201
    assert resp.json()["path"] == "custom.path"


@pytest.mark.django_db
def test_create_deduplicates_colliding_path(auth):
    _dep("Старый", "otdel")
    resp = Client().post(f"{BASE}/", data={"name": "Отдел"},
                         content_type="application/json", **auth)
    assert resp.status_code == 201
    # исходник добавляет суффикс времени, лишь бы не совпало
    assert resp.json()["path"].startswith("otdel_")


# ── GET /{id}/ ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_detail_and_404(auth):
    dep = _dep("ИТ", "it")
    assert Client().get(f"{BASE}/{dep.id}/", **auth).json()["name"] == "ИТ"
    missing = Client().get(f"{BASE}/999999/", **auth)
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Department not found"


# ── PUT + PATCH /{id}/ ──────────────────────────────────────────────────────

@pytest.mark.django_db
@pytest.mark.parametrize("method", ["put", "patch"])
def test_update_accepts_both_put_and_patch(auth, method):
    """PUT — задокументированный контракт исходника; PATCH — то, что реально
    шлёт фронт (frontend/src/api/hr.ts::updateDepartment), из-за чего сейчас
    получает 405. Регистрируем оба: строго аддитивно."""
    dep = _dep("ИТ", "it")
    resp = getattr(Client(), method)(
        f"{BASE}/{dep.id}/", data={"name": "ИТ и связь"},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "ИТ и связь"
    dep.refresh_from_db()
    assert dep.name == "ИТ и связь"


@pytest.mark.django_db
def test_update_ignores_none_fields(auth):
    dep = _dep("ИТ", "it", description="исходное")
    Client().patch(f"{BASE}/{dep.id}/", data={"name": "ИТ-2", "description": None},
                   content_type="application/json", **auth)
    dep.refresh_from_db()
    assert dep.name == "ИТ-2"
    assert dep.description == "исходное"  # exclude_none в исходнике


# ── DELETE /{id}/ ───────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_delete_clean_department_returns_204(auth):
    dep = _dep("Пустой", "empty")
    assert Client().delete(f"{BASE}/{dep.id}/", **auth).status_code == 204
    assert not Department.objects.filter(id=dep.id).exists()


@pytest.mark.django_db
def test_delete_with_dependents_returns_409_structured_detail(auth):
    dep = _dep("ИТ", "it")
    _dep("Разработка", "it.dev")
    pos = _pos("Инженер", dep, weight=50)
    _emp(dep, pos, "a@htq.test")

    resp = Client().delete(f"{BASE}/{dep.id}/", **auth)
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "department_has_dependents"
    assert detail["department"] == {"id": dep.id, "name": "ИТ"}
    assert detail["blockers"] == {"sub_departments": 1, "positions": 1, "employees": 1}
    assert Department.objects.filter(id=dep.id).exists()


@pytest.mark.django_db
def test_delete_soft_deleted_employees_not_counted_as_blockers(auth):
    dep = _dep("ИТ", "it")
    pos = _pos("Инженер", dep, weight=50)
    _emp(dep, pos, "a@htq.test", is_deleted=True)

    resp = Client().delete(f"{BASE}/{dep.id}/", **auth)
    assert resp.json()["detail"]["blockers"]["employees"] == 0


@pytest.mark.django_db
def test_delete_cascade_removes_subtree(auth):
    dep = _dep("ИТ", "it")
    child = _dep("Разработка", "it.dev")
    pos = _pos("Инженер", dep, weight=50)
    emp = _emp(dep, pos, "a@htq.test")

    resp = Client().delete(f"{BASE}/{dep.id}/?cascade=true", **auth)
    assert resp.status_code == 204
    assert not Department.objects.filter(id__in=[dep.id, child.id]).exists()
    assert not Position.objects.filter(id=pos.id).exists()
    assert not Employee.objects.filter(id=emp.id).exists()


@pytest.mark.django_db
def test_delete_cascade_clears_manager_pointing_at_deleted_employee(auth):
    dep = _dep("ИТ", "it")
    other = _dep("Финансы", "fin")
    pos = _pos("Инженер", dep, weight=50)
    emp = _emp(dep, pos, "a@htq.test")
    other.manager = emp
    other.save(update_fields=["manager"])

    assert Client().delete(f"{BASE}/{dep.id}/?cascade=true", **auth).status_code == 204
    other.refresh_from_db()
    assert other.manager_id is None


@pytest.mark.django_db
def test_delete_cascade_drops_reporting_relations_touching_subtree_positions(auth):
    """Закрывает TODO исходника (department_service.py, шаг «1. Drop reporting
    relations»): каскадное удаление отдела должно чистить ReportingRelation, где
    ЛЮБАЯ сторона (superior ИЛИ subordinate) указывает на позицию из удаляемого
    поддерева — даже если другая сторона связи торчит в отделе, который НЕ
    удаляется (здесь: "fin" остаётся, связь всё равно должна быть выметена)."""
    dep = _dep("ИТ", "it")
    other = _dep("Финансы", "fin")
    boss = _pos("Начальник", dep, weight=10)
    outsider = _pos("Финансист", other, weight=20)
    rel = ReportingRelation.objects.create(
        superior_position=boss, subordinate_position=outsider,
        effective_from=datetime.date(2024, 1, 1),
    )

    resp = Client().delete(f"{BASE}/{dep.id}/?cascade=true", **auth)
    assert resp.status_code == 204
    assert not ReportingRelation.objects.filter(id=rel.id).exists()
    # "fin" и её позиция вне поддерева — не должны быть тронуты.
    assert Department.objects.filter(id=other.id).exists()
    assert Position.objects.filter(id=outsider.id).exists()


# ── GET /{id}/children и /{id}/employees ────────────────────────────────────

@pytest.mark.django_db
def test_children_returns_whole_subtree_active_ordered_by_name(auth):
    dep = _dep("ИТ", "it")
    _dep("Разработка", "it.dev")
    _dep("Бэкенд", "it.dev.backend")
    _dep("Архив", "it.arc", is_active=False)

    body = Client().get(f"{BASE}/{dep.id}/children", **auth).json()
    # LIKE 'it.%' -> весь поддерев (не только прямые дети), только активные,
    # порядок по name
    assert [d["name"] for d in body] == ["Бэкенд", "Разработка"]


@pytest.mark.django_db
def test_employees_includes_soft_deleted(auth):
    dep = _dep("ИТ", "it")
    pos = _pos("Инженер", dep, weight=50)
    _emp(dep, pos, "a@htq.test")
    _emp(dep, pos, "b@htq.test", is_deleted=True)

    body = Client().get(f"{BASE}/{dep.id}/employees", **auth).json()
    assert {e["email"] for e in body} == {"a@htq.test", "b@htq.test"}


@pytest.mark.django_db
def test_employees_404_for_missing_department(auth):
    assert Client().get(f"{BASE}/999999/employees", **auth).status_code == 404


# ── cascade: PMOMember (под-модуль pmo) ─────────────────────────────────────

@pytest.mark.django_db
def test_delete_cascade_drops_pmo_memberships_of_subtree_employees(auth):
    """Закрывает TODO исходника (department_service.py, шаг «2. Drop PMO
    memberships»): каскадное удаление отдела должно чистить PMOMember по
    СОТРУДНИКАМ удаляемого поддерева ПЕРЕД удалением самих сотрудников — даже
    если PMO, в котором состоит сотрудник, никак не относится к отделу
    (здесь: членство в "PMO-1" переживает удаление сотрудника, только
    строка PMOMember должна исчезнуть — не сам PMO)."""
    from apps.hr.models import PMO, PMOMember

    dep = _dep("ИТ", "it")
    pos = _pos("Инженер", dep, weight=50)
    emp = _emp(dep, pos, "a@htq.test")
    pmo = PMO.objects.create(name="PMO-1", code="PMO-1")
    member = PMOMember.objects.create(
        pmo=pmo, employee=emp, from_date=datetime.date(2024, 1, 1),
    )

    resp = Client().delete(f"{BASE}/{dep.id}/?cascade=true", **auth)
    assert resp.status_code == 204
    assert not PMOMember.objects.filter(id=member.id).exists()
    assert not Employee.objects.filter(id=emp.id).exists()
    # PMO сам по себе — вне удаляемого поддерева, не должен быть тронут.
    assert PMO.objects.filter(id=pmo.id).exists()

"""Контракт /api/hr/v1/positions/* — паритет с services/hr/app/api/v1/positions.py.

Провенанс формы ответов: app/schemas/position.py (PositionOut, LevelThresholdOut,
PermissionCatalog), app/schemas/common.py (PaginatedResponse), поведение —
app/services/position_service.py.

Авторизация (docs/plans/2026-07-20-hr-domain.md): reads = jwt (get_current_user
исходника), writes = jwt + admin (require_hr_write исходника = is_elevated).

Зафиксированные ловушки паритета (проверяются тестами ниже):
  * список — конверт PaginatedResponse {items,total,page,pages,limit}, порядок
    по weight;
  * PUT + PATCH оба работают на /{id}/ (PATCH — то, что реально шлёт фронт);
  * weight глобально уникален — 409 при коллизии на create/update/weight;
  * level всегда пересчитывается из hr_levelthreshold при смене weight;
  * системные должности (is_system) — нельзя менять title/department_id/
    is_active (409) и нельзя удалить (409), но вес/грейд/permissions можно;
  * update_threshold/create_threshold/delete_threshold пересчитывают level
    ВСЕХ должностей (не только затронутый диапазон — это буквальное
    поведение исходника: `_recompute_levels_in_range` определён, но НИКОГДА
    не вызывается ни одним эндпойнтом — мёртвый код, не переносим);
  * move — либо точечная перестановка веса, либо fallback на полный
    ребаланс уровня (при конфликте/выходе за диапазон порога);
  * permissions-catalog — статические данные + LEVEL_PRESETS.

План: docs/plans/2026-07-20-hr-domain.md
"""
from __future__ import annotations

import pytest
from django.test import Client

from apps.hr.models import LevelThreshold, Position, PositionWeightAudit
from apps.hr.models import Department
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/hr/v1/positions"


@pytest.fixture
def dep(db):
    return Department.objects.create(name="ИТ", path="it")


@pytest.fixture
def auth(db):
    """Обычный вошедший пользователь — годится для reads, НЕ годится для writes."""
    user = User.objects.create(
        username="hr-user", email="hr-user@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    user.set_password("S3cret!")
    user.save()
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def admin_auth(db):
    """is_staff=True — elevated, требуется для writes (require_hr_write)."""
    user = User.objects.create(
        username="hr-admin", email="hr-admin@htq.test", password="x", status=UserStatus.ACTIVE,
        is_staff=True,
    )
    user.set_password("Adm1n!Pass")
    user.save()
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


def _pos(title, dep, weight, **kw):
    return Position.objects.create(title=title, department=dep, weight=weight, **kw)


def _threshold(level_number, weight_from, weight_to, **kw):
    return LevelThreshold.objects.create(
        level_number=level_number, weight_from=weight_from, weight_to=weight_to, **kw,
    )


# ── auth ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_requires_jwt_on_list():
    assert Client().get(f"{BASE}/").status_code == 401


@pytest.mark.django_db
def test_read_allowed_for_plain_jwt_user(auth, dep):
    _pos("Инженер", dep, weight=100)
    resp = Client().get(f"{BASE}/", **auth)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_create_forbidden_for_non_admin_jwt_user(auth, dep):
    resp = Client().post(
        f"{BASE}/", data={"title": "Инженер", "department_id": dep.id, "weight": 100},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_create_requires_jwt_at_all():
    resp = Client().post(f"{BASE}/", data={}, content_type="application/json")
    assert resp.status_code == 401


# ── GET / (list, paginated envelope) ─────────────────────────────────────

@pytest.mark.django_db
def test_list_returns_paginated_envelope_ordered_by_weight(admin_auth, dep):
    _pos("Второй", dep, weight=200)
    _pos("Первый", dep, weight=50)

    resp = Client().get(f"{BASE}/", **admin_auth)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"items", "total", "page", "pages", "limit"}
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["limit"] == 20
    assert body["pages"] == 1
    assert [p["title"] for p in body["items"]] == ["Первый", "Второй"]
    assert {"id", "title", "department_id", "grade", "description", "requirements",
            "is_active", "weight", "permissions", "level", "is_system",
            "created_at", "updated_at"} == set(body["items"][0])


@pytest.mark.django_db
def test_list_pagination_page_and_limit(admin_auth, dep):
    for i in range(5):
        _pos(f"P{i}", dep, weight=100 + i)

    resp = Client().get(f"{BASE}/?page=2&limit=2", **admin_auth)
    body = resp.json()
    assert body["page"] == 2
    assert body["limit"] == 2
    assert body["total"] == 5
    assert body["pages"] == 3
    assert len(body["items"]) == 2


@pytest.mark.django_db
def test_list_invalid_query_params_422(admin_auth):
    resp = Client().get(f"{BASE}/?page=0", **admin_auth)
    assert resp.status_code == 422
    resp2 = Client().get(f"{BASE}/?limit=500", **admin_auth)
    assert resp2.status_code == 422


# ── POST / (create) ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_create_computes_level_from_thresholds(admin_auth, dep):
    _threshold(1, 0, 99)
    _threshold(2, 100, 999)

    resp = Client().post(
        f"{BASE}/", data={"title": "Тимлид", "department_id": dep.id, "weight": 50},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["level"] == 1
    assert body["is_system"] is False
    assert body["weight"] == 50


@pytest.mark.django_db
def test_create_defaults_to_fallback_level_when_no_threshold_matches(admin_auth, dep):
    resp = Client().post(
        f"{BASE}/", data={"title": "Безуровневый", "department_id": dep.id, "weight": 9999},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 201
    assert resp.json()["level"] == 5  # _DEFAULT_LEVEL


@pytest.mark.django_db
def test_create_conflicting_weight_409(admin_auth, dep):
    _pos("Существующий", dep, weight=100)
    resp = Client().post(
        f"{BASE}/", data={"title": "Новый", "department_id": dep.id, "weight": 100},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 409
    assert "100" in resp.json()["detail"]


@pytest.mark.django_db
def test_create_roundtrips_permissions_matrix(admin_auth, dep):
    resp = Client().post(
        f"{BASE}/",
        data={
            "title": "Сеньор", "department_id": dep.id, "weight": 30,
            "permissions": {"hr_level": "senior", "permissions": ["hr.employees.view"]},
        },
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 201
    assert resp.json()["permissions"] == {"hr_level": "senior", "permissions": ["hr.employees.view"]}


@pytest.mark.django_db
def test_create_without_permissions_is_null(admin_auth, dep):
    resp = Client().post(
        f"{BASE}/", data={"title": "Junior", "department_id": dep.id, "weight": 10},
        content_type="application/json", **admin_auth,
    )
    assert resp.json()["permissions"] is None


# ── GET /{id}/ ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_detail_and_404(admin_auth, dep):
    pos = _pos("Инженер", dep, weight=100)
    resp = Client().get(f"{BASE}/{pos.id}/", **admin_auth)
    assert resp.status_code == 200
    assert resp.json()["title"] == "Инженер"

    missing = Client().get(f"{BASE}/999999/", **admin_auth)
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Position not found"


# ── PUT + PATCH /{id}/ ────────────────────────────────────────────────────

@pytest.mark.django_db
@pytest.mark.parametrize("method", ["put", "patch"])
def test_update_accepts_both_put_and_patch(admin_auth, dep, method):
    """PUT — задокументированный контракт исходника; PATCH — то, что реально
    шлёт фронт (frontend/src/api/hr.ts::updatePosition)."""
    pos = _pos("Инженер", dep, weight=100)
    resp = getattr(Client(), method)(
        f"{BASE}/{pos.id}/", data={"title": "Ст. инженер"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Ст. инженер"
    pos.refresh_from_db()
    assert pos.title == "Ст. инженер"


@pytest.mark.django_db
def test_update_forbidden_for_non_admin(auth, dep):
    pos = _pos("Инженер", dep, weight=100)
    resp = Client().put(
        f"{BASE}/{pos.id}/", data={"title": "X"}, content_type="application/json", **auth,
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_update_ignores_none_fields(admin_auth, dep):
    pos = _pos("Инженер", dep, weight=100, description="исходное")
    Client().patch(
        f"{BASE}/{pos.id}/", data={"title": "Инженер-2", "description": None},
        content_type="application/json", **admin_auth,
    )
    pos.refresh_from_db()
    assert pos.title == "Инженер-2"
    assert pos.description == "исходное"


@pytest.mark.django_db
def test_update_weight_field_recomputes_level_and_records_audit(admin_auth, dep):
    _threshold(1, 0, 99)
    _threshold(2, 100, 999)
    pos = _pos("Инженер", dep, weight=500, level=2)

    resp = Client().patch(
        f"{BASE}/{pos.id}/", data={"weight": 10},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["weight"] == 10
    assert body["level"] == 1
    audit = PositionWeightAudit.objects.get(position_id=pos.id)
    assert audit.old_weight == 500
    assert audit.new_weight == 10
    assert audit.old_level == 2
    assert audit.new_level == 1
    assert audit.reason == "manual"


@pytest.mark.django_db
def test_update_weight_conflict_409(admin_auth, dep):
    _pos("Занято", dep, weight=100)
    pos = _pos("Инженер", dep, weight=200)
    resp = Client().patch(
        f"{BASE}/{pos.id}/", data={"weight": 100},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 409


@pytest.mark.django_db
def test_update_system_position_blocks_title_department_active(admin_auth, dep):
    other_dep = Department.objects.create(name="Финансы", path="fin")
    pos = _pos("Системная", dep, weight=100, is_system=True)

    resp = Client().patch(
        f"{BASE}/{pos.id}/", data={"title": "Новое имя"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 409
    assert "title" in resp.json()["detail"]

    resp2 = Client().patch(
        f"{BASE}/{pos.id}/", data={"department_id": other_dep.id},
        content_type="application/json", **admin_auth,
    )
    assert resp2.status_code == 409

    resp3 = Client().patch(
        f"{BASE}/{pos.id}/", data={"is_active": False},
        content_type="application/json", **admin_auth,
    )
    assert resp3.status_code == 409


@pytest.mark.django_db
def test_update_system_position_allows_weight_grade_permissions(admin_auth, dep):
    pos = _pos("Системная", dep, weight=100, is_system=True, grade=1)

    resp = Client().patch(
        f"{BASE}/{pos.id}/",
        data={"grade": 5, "weight": 150, "permissions": {"hr_level": "lead", "permissions": []}},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["grade"] == 5
    assert body["weight"] == 150
    assert body["permissions"]["hr_level"] == "lead"


# ── DELETE /{id}/ ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_delete_returns_204(admin_auth, dep):
    pos = _pos("Удаляемая", dep, weight=100)
    resp = Client().delete(f"{BASE}/{pos.id}/", **admin_auth)
    assert resp.status_code == 204
    assert not Position.objects.filter(id=pos.id).exists()


@pytest.mark.django_db
def test_delete_system_position_409(admin_auth, dep):
    pos = _pos("Системная", dep, weight=100, is_system=True)
    resp = Client().delete(f"{BASE}/{pos.id}/", **admin_auth)
    assert resp.status_code == 409
    assert Position.objects.filter(id=pos.id).exists()


@pytest.mark.django_db
def test_delete_forbidden_for_non_admin(auth, dep):
    pos = _pos("X", dep, weight=100)
    resp = Client().delete(f"{BASE}/{pos.id}/", **auth)
    assert resp.status_code == 403


# ── PATCH /{id}/weight ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_weight_endpoint_updates_weight_and_level(admin_auth, dep):
    _threshold(1, 0, 99)
    _threshold(2, 100, 999)
    pos = _pos("Инженер", dep, weight=500)

    resp = Client().patch(
        f"{BASE}/{pos.id}/weight", data={"weight": 5},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200
    assert resp.json()["weight"] == 5
    assert resp.json()["level"] == 1


@pytest.mark.django_db
def test_weight_endpoint_negative_weight_rejected_by_schema_422(admin_auth, dep):
    pos = _pos("Инженер", dep, weight=100)
    resp = Client().patch(
        f"{BASE}/{pos.id}/weight", data={"weight": -1},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_weight_endpoint_conflict_409(admin_auth, dep):
    _pos("Занято", dep, weight=42)
    pos = _pos("Инженер", dep, weight=100)
    resp = Client().patch(
        f"{BASE}/{pos.id}/weight", data={"weight": 42},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 409


@pytest.mark.django_db
def test_weight_endpoint_no_change_skips_audit(admin_auth, dep):
    pos = _pos("Инженер", dep, weight=100, level=5)
    resp = Client().patch(
        f"{BASE}/{pos.id}/weight", data={"weight": 100},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200
    assert not PositionWeightAudit.objects.filter(position_id=pos.id).exists()


# ── PATCH /{id}/move ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_move_between_before_and_after_picks_midpoint(admin_auth, dep):
    a = _pos("A", dep, weight=100)
    b = _pos("B", dep, weight=200)
    moved = _pos("C", dep, weight=500)

    resp = Client().patch(
        f"{BASE}/{moved.id}/move",
        data={"before_position_id": a.id, "after_position_id": b.id},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200
    assert resp.json()["weight"] == 150


@pytest.mark.django_db
def test_move_before_only_adds_100(admin_auth, dep):
    a = _pos("A", dep, weight=100)
    moved = _pos("C", dep, weight=500)

    resp = Client().patch(
        f"{BASE}/{moved.id}/move", data={"before_position_id": a.id},
        content_type="application/json", **admin_auth,
    )
    assert resp.json()["weight"] == 200


@pytest.mark.django_db
def test_move_after_only_subtracts_100(admin_auth, dep):
    a = _pos("A", dep, weight=300)
    moved = _pos("C", dep, weight=500)

    resp = Client().patch(
        f"{BASE}/{moved.id}/move", data={"after_position_id": a.id},
        content_type="application/json", **admin_auth,
    )
    assert resp.json()["weight"] == 200


@pytest.mark.django_db
def test_move_too_tight_gap_triggers_level_rebalance(admin_auth, dep):
    _threshold(2, 0, 999)
    a = _pos("A", dep, weight=100, level=2)
    b = _pos("B", dep, weight=101, level=2)  # gap < 2 -> no midpoint
    moved = _pos("C", dep, weight=500, level=2)

    resp = Client().patch(
        f"{BASE}/{moved.id}/move",
        data={"before_position_id": a.id, "after_position_id": b.id},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200
    # rebalance даёт уникальные веса всем трём должностям уровня 2
    weights = set(Position.objects.filter(id__in=[a.id, b.id, moved.id]).values_list("weight", flat=True))
    assert len(weights) == 3


@pytest.mark.django_db
def test_move_before_equals_after_422(admin_auth, dep):
    a = _pos("A", dep, weight=100)
    moved = _pos("C", dep, weight=500)
    resp = Client().patch(
        f"{BASE}/{moved.id}/move",
        data={"before_position_id": a.id, "after_position_id": a.id},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_move_self_reference_422(admin_auth, dep):
    moved = _pos("C", dep, weight=500)
    resp = Client().patch(
        f"{BASE}/{moved.id}/move", data={"before_position_id": moved.id},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_move_target_level_not_found_404(admin_auth, dep):
    moved = _pos("C", dep, weight=500)
    resp = Client().patch(
        f"{BASE}/{moved.id}/move", data={"target_level": 99},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Target level not found"


@pytest.mark.django_db
def test_move_missing_before_position_404(admin_auth, dep):
    moved = _pos("C", dep, weight=500)
    resp = Client().patch(
        f"{BASE}/{moved.id}/move", data={"before_position_id": 999999},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Position 999999 not found"


# ── POST /rebalance ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_rebalance_single_level(admin_auth, dep):
    _threshold(2, 0, 999)
    for i in range(3):
        _pos(f"P{i}", dep, weight=100 + i, level=2)

    resp = Client().post(
        f"{BASE}/rebalance", data={"level": 2}, content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["levels"] == {"2": 3}
    assert body["total"] == 3


@pytest.mark.django_db
def test_rebalance_level_not_found_404(admin_auth):
    resp = Client().post(
        f"{BASE}/rebalance", data={"level": 77}, content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Level threshold not found"


@pytest.mark.django_db
def test_rebalance_all_returns_counts_per_level(admin_auth, dep):
    _pos("A", dep, weight=10, level=1)
    _pos("B", dep, weight=20, level=1)
    _pos("C", dep, weight=30, level=2)

    resp = Client().post(f"{BASE}/rebalance", data={}, content_type="application/json", **admin_auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["levels"] == {"1": 2, "2": 1}
    assert body["total"] == 3


@pytest.mark.django_db
def test_rebalance_forbidden_for_non_admin(auth):
    resp = Client().post(f"{BASE}/rebalance", data={}, content_type="application/json", **auth)
    assert resp.status_code == 403


# ── /positions/levels/ — пороги уровней ──────────────────────────────────

@pytest.mark.django_db
def test_list_thresholds_ordered_by_level_number(admin_auth):
    _threshold(2, 100, 199)
    _threshold(1, 0, 99)

    resp = Client().get(f"{BASE}/levels/", **admin_auth)
    assert resp.status_code == 200
    body = resp.json()
    assert [t["level_number"] for t in body] == [1, 2]
    assert {"id", "level_number", "weight_from", "weight_to", "label", "color",
            "created_at", "updated_at"} == set(body[0])


@pytest.mark.django_db
def test_create_threshold_recomputes_affected_positions(admin_auth, dep):
    pos = _pos("Инженер", dep, weight=50, level=5)  # изначально дефолтный level

    resp = Client().post(
        f"{BASE}/levels/", data={"level_number": 1, "weight_from": 0, "weight_to": 99},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 201
    pos.refresh_from_db()
    assert pos.level == 1
    audit = PositionWeightAudit.objects.get(position_id=pos.id)
    assert audit.reason == "threshold_change"
    assert audit.old_level == 5
    assert audit.new_level == 1


@pytest.mark.django_db
def test_create_threshold_duplicate_level_409(admin_auth):
    _threshold(1, 0, 99)
    resp = Client().post(
        f"{BASE}/levels/", data={"level_number": 1, "weight_from": 200, "weight_to": 299},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 409


@pytest.mark.django_db
def test_create_threshold_overlapping_range_409(admin_auth):
    _threshold(1, 0, 99)
    resp = Client().post(
        f"{BASE}/levels/", data={"level_number": 2, "weight_from": 50, "weight_to": 150},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 409


@pytest.mark.django_db
def test_create_threshold_invalid_range_422(admin_auth):
    resp = Client().post(
        f"{BASE}/levels/", data={"level_number": 1, "weight_from": 100, "weight_to": 10},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_update_threshold_recomputes_positions(admin_auth, dep):
    _threshold(1, 0, 99)
    pos = _pos("Инженер", dep, weight=150, level=5)

    resp = Client().put(
        f"{BASE}/levels/1", data={"weight_to": 200},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200
    pos.refresh_from_db()
    assert pos.level == 1


@pytest.mark.django_db
def test_update_threshold_not_found_404(admin_auth):
    resp = Client().put(
        f"{BASE}/levels/999", data={"weight_to": 200},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_update_threshold_overlap_409(admin_auth):
    _threshold(1, 0, 99)
    _threshold(2, 100, 199)
    resp = Client().put(
        f"{BASE}/levels/1", data={"weight_to": 150},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 409


@pytest.mark.django_db
def test_delete_threshold_recomputes_positions_to_fallback(admin_auth, dep):
    _threshold(1, 0, 99)
    pos = _pos("Инженер", dep, weight=50, level=1)

    resp = Client().delete(f"{BASE}/levels/1", **admin_auth)
    assert resp.status_code == 204
    pos.refresh_from_db()
    assert pos.level == 5  # _DEFAULT_LEVEL, порога больше нет


@pytest.mark.django_db
def test_delete_threshold_not_found_404(admin_auth):
    resp = Client().delete(f"{BASE}/levels/999", **admin_auth)
    assert resp.status_code == 404


@pytest.mark.django_db
def test_levels_forbidden_for_non_admin_write(auth):
    resp = Client().post(
        f"{BASE}/levels/", data={"level_number": 1, "weight_from": 0, "weight_to": 99},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_levels_read_allowed_for_plain_jwt(auth):
    resp = Client().get(f"{BASE}/levels/", **auth)
    assert resp.status_code == 200


# ── GET /permissions-catalog/ ─────────────────────────────────────────────

@pytest.mark.django_db
def test_permissions_catalog_shape(auth):
    resp = Client().get(f"{BASE}/permissions-catalog/", **auth)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"hr_levels", "permissions", "level_presets"}
    assert {lvl["value"] for lvl in body["hr_levels"]} == {"junior", "middle", "senior", "lead"}
    assert set(body["level_presets"]) == {"junior", "middle", "senior", "lead"}
    assert "hr.employees.view" in body["level_presets"]["junior"]
    # junior ⊆ middle ⊆ senior ⊆ lead — свойство пресетов исходника
    junior = set(body["level_presets"]["junior"])
    lead = set(body["level_presets"]["lead"])
    assert junior <= lead
    keys = {item["key"] for item in body["permissions"]}
    assert "hr.positions.edit" in keys


@pytest.mark.django_db
def test_permissions_catalog_requires_jwt():
    assert Client().get(f"{BASE}/permissions-catalog/").status_code == 401

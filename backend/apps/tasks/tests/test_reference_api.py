"""Contract tests for the reference-data routes.

Mirrors ``services/task/app/api/v1/{labels,task_types,equipment}.py`` and
``sequences.py``: paths, status codes and field names are asserted against
the FastAPI original, not against what felt natural to implement.
"""

import pytest
from django.test import Client

from apps.tasks.models import (Equipment, EquipmentCategory, Label,
                               TaskSequence, TaskType)
from apps.tasks.services import reference_service as ref_svc

from .helpers import BASE, auth, admin_token, patch_json, post_json, token


# ── auth ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
@pytest.mark.parametrize("path", ["labels/", "task-types/", "equipment/"])
def test_reference_routes_require_authentication(path):
    resp = Client().get(f"{BASE}/{path}")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Not authenticated"}


# ── labels ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_list_labels():
    Label.objects.create(name="urgent", color="#ff0000")
    Label.objects.create(name="ops", color="#00ff00")
    resp = Client().get(f"{BASE}/labels/", **auth())
    assert resp.status_code == 200
    body = resp.json()
    assert [row["name"] for row in body] == ["urgent", "ops"]
    # Response shape is exactly LabelResponse — no extra columns leak.
    assert set(body[0]) == {"id", "name", "color"}


# Labels are a shared, company-wide dictionary: reads stay open, writes are
# admin-only, so every mutating case below carries an admin token. The
# regular-caller 403 is asserted in test_permissions.py.

@pytest.mark.django_db
def test_create_label_returns_201():
    resp = post_json(Client(), f"{BASE}/labels/",
                     {"name": "blocked", "color": "#123abc"},
                     **auth(admin_token()))
    assert resp.status_code == 201
    assert resp.json()["name"] == "blocked"
    assert Label.objects.filter(name="blocked").exists()


@pytest.mark.django_db
def test_create_label_defaults_color():
    resp = post_json(Client(), f"{BASE}/labels/", {"name": "plain"},
                     **auth(admin_token()))
    assert resp.status_code == 201
    assert resp.json()["color"] == "#808080"


@pytest.mark.django_db
def test_create_label_rejects_bad_color():
    """``LabelCreate.color`` carries a hex pattern — a bad value is a 422
    envelope, not a 500."""
    resp = post_json(Client(), f"{BASE}/labels/",
                     {"name": "x", "color": "red"}, **auth(admin_token()))
    assert resp.status_code == 422
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_update_and_delete_label():
    label = Label.objects.create(name="old", color="#111111")
    resp = patch_json(Client(), f"{BASE}/labels/{label.id}/",
                      {"name": "new"}, **auth(admin_token()))
    assert resp.status_code == 200
    assert resp.json()["name"] == "new"
    # colour untouched by a partial update
    assert resp.json()["color"] == "#111111"

    resp = Client().delete(f"{BASE}/labels/{label.id}/", **auth(admin_token()))
    assert resp.status_code == 204
    assert not Label.objects.filter(pk=label.id).exists()


@pytest.mark.django_db
def test_label_detail_404_for_unknown_id():
    assert patch_json(Client(), f"{BASE}/labels/999/", {"name": "x"},
                      **auth(admin_token())).status_code == 404
    assert Client().delete(f"{BASE}/labels/999/",
                           **auth(admin_token())).status_code == 404


@pytest.mark.django_db
def test_label_detail_accepts_both_slash_spellings():
    """APPEND_SLASH=False: both spellings must resolve, never 404/redirect."""
    label = Label.objects.create(name="dual", color="#222222")
    for path in (f"{BASE}/labels/{label.id}", f"{BASE}/labels/{label.id}/"):
        assert patch_json(Client(), path, {"color": "#333333"},
                          **auth(admin_token())).status_code == 200


# ── task types ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_list_task_types_includes_seeded_system_rows():
    resp = Client().get(f"{BASE}/task-types/", **auth())
    assert resp.status_code == 200
    by_slug = {row["slug"]: row for row in resp.json()}
    assert {"task", "bug", "story", "epic", "subtask"} <= set(by_slug)
    assert by_slug["bug"]["is_system"] is True
    assert by_slug["bug"]["name"] == "Баг"


@pytest.mark.django_db
def test_create_task_type_autogenerates_slug_from_cyrillic_name():
    resp = post_json(Client(), f"{BASE}/task-types/",
                     {"name": "Обслуживание"}, **auth())
    assert resp.status_code == 201
    body = resp.json()
    assert body["slug"] == "obsluzhivanie"
    assert body["is_system"] is False


@pytest.mark.django_db
def test_create_task_type_deduplicates_generated_slug():
    TaskType.objects.create(slug="remont", name="Ремонт")
    resp = post_json(Client(), f"{BASE}/task-types/", {"name": "Ремонт"},
                     **auth())
    assert resp.status_code == 201
    assert resp.json()["slug"] == "remont-2"


@pytest.mark.django_db
def test_create_task_type_conflicting_explicit_slug_is_409():
    resp = post_json(Client(), f"{BASE}/task-types/",
                     {"name": "Другая задача", "slug": "task"}, **auth())
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]


@pytest.mark.django_db
def test_create_task_type_rejects_malformed_slug():
    resp = post_json(Client(), f"{BASE}/task-types/",
                     {"name": "X", "slug": "Not A Slug"}, **auth())
    assert resp.status_code == 422


@pytest.mark.django_db
def test_system_task_type_cannot_be_deleted():
    system = TaskType.objects.get(slug="task")
    resp = Client().delete(f"{BASE}/task-types/{system.id}/", **auth())
    assert resp.status_code == 403
    assert TaskType.objects.filter(pk=system.id).exists()


@pytest.mark.django_db
def test_custom_task_type_can_be_updated_and_deleted():
    row = TaskType.objects.create(slug="custom", name="Custom")
    resp = patch_json(Client(), f"{BASE}/task-types/{row.id}/",
                      {"name": "Renamed", "color": "#abcdef"}, **auth())
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"
    # slug is not in TaskTypeUpdate, so it cannot be changed through the API
    assert resp.json()["slug"] == "custom"

    assert Client().delete(f"{BASE}/task-types/{row.id}/",
                           **auth()).status_code == 204


@pytest.mark.django_db
def test_update_task_type_ignores_slug_in_body():
    """Extra keys are dropped by the schema — a client cannot smuggle a
    slug change through the update endpoint."""
    row = TaskType.objects.create(slug="stable", name="Stable")
    patch_json(Client(), f"{BASE}/task-types/{row.id}/",
               {"slug": "hijacked", "name": "N"}, **auth())
    row.refresh_from_db()
    assert row.slug == "stable"


# ── equipment ───────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_list_equipment_hides_inactive_by_default():
    Equipment.objects.create(name="Кран")
    Equipment.objects.create(name="Списанный", is_active=False)
    resp = Client().get(f"{BASE}/equipment/", **auth())
    assert [row["name"] for row in resp.json()] == ["Кран"]

    resp = Client().get(f"{BASE}/equipment/?active_only=false", **auth())
    assert {row["name"] for row in resp.json()} == {"Кран", "Списанный"}


# Same split as labels: the equipment list is open, writes are admin-only.

@pytest.mark.django_db
def test_create_equipment_returns_201():
    resp = post_json(Client(), f"{BASE}/equipment/",
                     {"name": "Экскаватор", "inventory_no": "INV-1",
                      "category": "Спецтехника"}, **auth(admin_token()))
    assert resp.status_code == 201
    assert resp.json()["is_active"] is True


@pytest.mark.django_db
def test_delete_equipment_soft_disables_it():
    """Historical ResourceAllocation rows reference equipment — the original
    flips ``is_active`` instead of deleting, and so does this."""
    eq = Equipment.objects.create(name="Погрузчик")
    resp = Client().delete(f"{BASE}/equipment/{eq.id}", **auth(admin_token()))
    assert resp.status_code == 204
    eq.refresh_from_db()
    assert eq.is_active is False


@pytest.mark.django_db
def test_equipment_detail_accepts_both_slash_spellings():
    """FastAPI declared ``equipment/{id}`` but the frontend calls it with a
    trailing slash — both must work (no 307 that drops the auth header)."""
    eq = Equipment.objects.create(name="Дрель")
    assert patch_json(Client(), f"{BASE}/equipment/{eq.id}", {"name": "A"},
                      **auth(admin_token())).status_code == 200
    assert patch_json(Client(), f"{BASE}/equipment/{eq.id}/", {"name": "B"},
                      **auth(admin_token())).status_code == 200
    eq.refresh_from_db()
    assert eq.name == "B"


@pytest.mark.django_db
def test_equipment_404_for_unknown_id():
    assert Client().delete(f"{BASE}/equipment/999",
                           **auth(admin_token())).status_code == 404


# ── категория техники: справочник за строковым полем ────────────────────
#
# ``category`` в контракте остался строкой, но за ней теперь таблица. Эти
# тесты стерегут ровно стык: снаружи форма прежняя, внутри — FK.

@pytest.mark.django_db
def test_creating_equipment_by_category_name_fills_the_reference():
    resp = post_json(Client(), f"{BASE}/equipment/",
                     {"name": "Экскаватор", "category": "Спецтехника"},
                     **auth(admin_token()))
    assert resp.status_code == 201
    body = resp.json()
    assert body["category"] == "Спецтехника"
    row = EquipmentCategory.objects.get(name="Спецтехника")
    assert body["category_id"] == row.id
    assert row.slug == "spetstehnika"


@pytest.mark.django_db
def test_equipment_category_name_is_matched_case_insensitively():
    """Второй ввод того же названия в другом регистре не должен плодить
    вторую строку справочника — иначе «2 кары» становятся неисчислимы."""
    client = Client()
    post_json(client, f"{BASE}/equipment/",
              {"name": "Кара 1", "category": "Вилопогрузчик"},
              **auth(admin_token()))
    post_json(client, f"{BASE}/equipment/",
              {"name": "Кара 2", "category": "вилопогрузчик "},
              **auth(admin_token()))
    assert EquipmentCategory.objects.filter(name__iexact="вилопогрузчик").count() == 1


@pytest.mark.django_db
def test_equipment_accepts_category_id_and_it_wins_over_the_name():
    picked = EquipmentCategory.objects.create(slug="kran", name="Кран")
    resp = post_json(Client(), f"{BASE}/equipment/",
                     {"name": "КС-45", "category": "Мимо", "category_id": picked.id},
                     **auth(admin_token()))
    assert resp.json()["category"] == "Кран"
    assert not EquipmentCategory.objects.filter(name="Мимо").exists()


@pytest.mark.django_db
def test_equipment_category_can_be_cleared():
    eq = Equipment.objects.create(
        name="Дрель",
        category=EquipmentCategory.objects.create(slug="ruchnoy", name="Ручной"))
    resp = patch_json(Client(), f"{BASE}/equipment/{eq.id}", {"category": ""},
                      **auth(admin_token()))
    assert resp.status_code == 200
    assert resp.json()["category"] is None
    eq.refresh_from_db()
    assert eq.category_id is None


@pytest.mark.django_db
def test_equipment_can_be_filtered_by_category():
    kran = EquipmentCategory.objects.create(slug="kran", name="Кран")
    Equipment.objects.create(name="КС-45", category=kran)
    Equipment.objects.create(name="Дрель")
    resp = Client().get(f"{BASE}/equipment/?category_id={kran.id}", **auth())
    assert [row["name"] for row in resp.json()] == ["КС-45"]


# ── плоские справочники: типы техники, роли, виды объёмов ───────────────

_FLAT = ["equipment-categories", "work-roles", "volume-types"]


@pytest.mark.django_db
@pytest.mark.parametrize("path", _FLAT)
def test_flat_reference_routes_require_authentication(path):
    assert Client().get(f"{BASE}/{path}/").status_code == 401


@pytest.mark.django_db
@pytest.mark.parametrize("path", _FLAT)
def test_flat_reference_writes_are_admin_only(path):
    resp = post_json(Client(), f"{BASE}/{path}/", {"name": "Что-то"},
                     **auth(token()))
    assert resp.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("path", _FLAT)
def test_flat_reference_create_generates_a_slug(path):
    resp = post_json(Client(), f"{BASE}/{path}/", {"name": "Вилопогрузчик"},
                     **auth(admin_token()))
    assert resp.status_code == 201
    body = resp.json()
    assert body["slug"] == "vilopogruzchik"
    assert body["is_active"] is True


@pytest.mark.django_db
@pytest.mark.parametrize("path", _FLAT)
def test_flat_reference_duplicate_name_is_409(path):
    hdr = auth(admin_token())
    post_json(Client(), f"{BASE}/{path}/", {"name": "Кран"}, **hdr)
    resp = post_json(Client(), f"{BASE}/{path}/", {"name": "кран"}, **hdr)
    assert resp.status_code == 409


@pytest.mark.django_db
@pytest.mark.parametrize("path", _FLAT)
def test_flat_reference_delete_soft_disables_and_hides_the_row(path):
    """PROTECT на FK означает, что настоящее удаление упёрлось бы в базу —
    ручка гасит ``is_active``, как и у техники."""
    hdr = auth(admin_token())
    row_id = post_json(Client(), f"{BASE}/{path}/", {"name": "Устарело"},
                       **hdr).json()["id"]
    assert Client().delete(f"{BASE}/{path}/{row_id}", **hdr).status_code == 204
    assert Client().get(f"{BASE}/{path}/", **auth()).json() == []
    shown = Client().get(f"{BASE}/{path}/?active_only=false", **auth()).json()
    assert [r["is_active"] for r in shown] == [False]


@pytest.mark.django_db
@pytest.mark.parametrize("path", _FLAT)
def test_flat_reference_detail_accepts_both_slash_spellings(path):
    hdr = auth(admin_token())
    row_id = post_json(Client(), f"{BASE}/{path}/", {"name": "Первое"},
                       **hdr).json()["id"]
    assert patch_json(Client(), f"{BASE}/{path}/{row_id}", {"name": "A"},
                      **hdr).status_code == 200
    assert patch_json(Client(), f"{BASE}/{path}/{row_id}/", {"name": "B"},
                      **hdr).json()["name"] == "B"


@pytest.mark.django_db
def test_volume_type_carries_a_unit_and_defaults_to_pieces():
    hdr = auth(admin_token())
    default = post_json(Client(), f"{BASE}/volume-types/", {"name": "Валы"},
                        **hdr).json()
    assert default["unit"] == "piece"
    tons = post_json(Client(), f"{BASE}/volume-types/",
                     {"name": "Металл", "unit": "ton"}, **hdr).json()
    assert tons["unit"] == "ton"


@pytest.mark.django_db
def test_flat_reference_slugs_are_unique_only_within_their_own_table():
    """«Кран» законно существует и как тип техники, и как вид работ —
    уникальность слага в пределах своей таблицы, а не всех сразу."""
    hdr = auth(admin_token())
    a = post_json(Client(), f"{BASE}/equipment-categories/", {"name": "Кран"},
                  **hdr).json()
    b = post_json(Client(), f"{BASE}/work-roles/", {"name": "Кран"},
                  **hdr).json()
    assert a["slug"] == b["slug"] == "kran"


# ── sequences (admin-only) ──────────────────────────────────────────────

@pytest.mark.django_db
def test_next_task_key_is_admin_only():
    resp = Client().post(f"{BASE}/sequences/TASK/next", **auth(token()))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_next_task_key_increments():
    client = Client()
    hdr = auth(admin_token())
    first = client.post(f"{BASE}/sequences/TASK/next", **hdr)
    assert first.status_code == 200
    assert first.json() == {"key": "TASK-1"}
    second = client.post(f"{BASE}/sequences/TASK/next", **hdr)
    assert second.json() == {"key": "TASK-2"}
    assert TaskSequence.objects.get(name="TASK").current_value == 2


@pytest.mark.django_db
def test_sequences_are_independent_per_prefix():
    hdr = auth(admin_token())
    Client().post(f"{BASE}/sequences/TASK/next", **hdr)
    resp = Client().post(f"{BASE}/sequences/OPS/next", **hdr)
    assert resp.json() == {"key": "OPS-1"}


# ── slug helper (unit) ──────────────────────────────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("Обслуживание", "obsluzhivanie"),
    ("Bug Fix", "bug-fix"),
    ("  Спец  Задача  ", "spets-zadacha"),
    ("!!!", "type"),          # nothing slug-able -> documented fallback
    ("Қазақша", "kazaksha"),  # Kazakh-specific letters are mapped
])
def test_slugify_name(name, expected):
    assert ref_svc.slugify_name(name) == expected

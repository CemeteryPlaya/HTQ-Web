"""Contract tests for ``/api/requests/v1/templates/*`` (the form builder).

Sources: ``services/requests/app/api/v1/forms.py`` +
``services/requests/tests/{test_forms_api,test_template_lifecycle,
test_template_data_table}.py``. Follows the auth/response-shape contract
byte-for-byte; the data-table side effects (``ensure_source_for_template`` /
``sync_columns_for_template``) are asserted at the model level since the
``reference-sources/*`` HTTP surface is out of this task's scope (a
different, not-yet-wired sub-domain).
"""

import pytest
from django.test import Client

from apps.approvals.models import (
    RequestFormTemplate, RequestFormTemplateVersion, RequestProject,
    RequestProjectMember, RequestReferenceSource,
)

from .helpers import BASE, admin_token, auth, patch_json, post_json, token

_SCHEMA = {"fields": [
    {"type": "money", "key": "amount", "label": "Сумма", "contributes_to_total": True},
    {"type": "text", "key": "reason", "label": "Обоснование"},
]}
_WF = {
    "nodes": [
        {"id": "n_start", "type": "start"},
        {"id": "n_app", "type": "approval", "assignee": {"kind": "user", "id": 9}, "mode": "any"},
        {"id": "n_ok", "type": "end_approved"},
        {"id": "n_no", "type": "end_rejected"},
    ],
    "edges": [
        {"from": "n_start", "to": "n_app"},
        {"from": "n_app", "to": "n_ok", "on": "approve"},
        {"from": "n_app", "to": "n_no", "on": "reject"},
    ],
}


# ── list / create ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_templates_require_auth():
    assert Client().get(f"{BASE}/templates/").status_code == 401


@pytest.mark.django_db
def test_global_template_requires_elevated():
    resp = post_json(Client(), f"{BASE}/templates/", {"name": "Expense"}, **auth())
    assert resp.status_code == 403

    resp = post_json(Client(), f"{BASE}/templates/", {"name": "Expense"},
                     **auth(admin_token()))
    assert resp.status_code == 201
    body = resp.json()
    assert body["slug"] == "expense"
    assert body["project_id"] is None


@pytest.mark.django_db
def test_project_admin_may_create_scoped_template():
    project = RequestProject.objects.create(name="P1")
    RequestProjectMember.objects.create(project=project, user_id=7, role="admin")
    resp = post_json(Client(), f"{BASE}/templates/",
                     {"name": "Scoped", "project_id": project.id}, **auth())
    assert resp.status_code == 201
    assert resp.json()["project_id"] == project.id


@pytest.mark.django_db
def test_non_admin_project_member_cannot_create_template():
    project = RequestProject.objects.create(name="P2")
    RequestProjectMember.objects.create(project=project, user_id=7, role="member")
    resp = post_json(Client(), f"{BASE}/templates/",
                     {"name": "Scoped", "project_id": project.id}, **auth())
    assert resp.status_code == 403


@pytest.mark.django_db
def test_duplicate_slug_conflicts():
    post_json(Client(), f"{BASE}/templates/", {"name": "Trip"}, **auth(admin_token()))
    resp = post_json(Client(), f"{BASE}/templates/", {"name": "Trip"}, **auth(admin_token()))
    assert resp.status_code == 409


@pytest.mark.django_db
def test_create_template_creates_its_data_table():
    resp = post_json(Client(), f"{BASE}/templates/", {"name": "Счёт"}, **auth(admin_token()))
    tid = resp.json()["id"]
    src = RequestReferenceSource.objects.get(template_id=tid)
    assert src.columns_json == [
        "Номер запроса", "Статус", "Отправлено", "Завершено",
        "Инициатор", "Текущий согласующий",
    ]


@pytest.mark.django_db
def test_list_templates_filters_by_project_and_hides_deleted():
    project = RequestProject.objects.create(name="P3")
    global_tpl = post_json(Client(), f"{BASE}/templates/", {"name": "Global"},
                           **auth(admin_token())).json()
    scoped_tpl = post_json(Client(), f"{BASE}/templates/",
                           {"name": "Scoped2", "project_id": project.id},
                           **auth(admin_token())).json()

    resp = Client().get(f"{BASE}/templates/", **auth(admin_token()))
    ids = [t["id"] for t in resp.json()]
    assert global_tpl["id"] in ids
    assert scoped_tpl["id"] not in ids

    resp = Client().get(f"{BASE}/templates/?project_id={project.id}",
                        **auth(admin_token()))
    ids = [t["id"] for t in resp.json()]
    assert scoped_tpl["id"] in ids
    assert global_tpl["id"] not in ids


@pytest.mark.django_db
def test_get_template_404():
    assert Client().get(f"{BASE}/templates/999/", **auth()).status_code == 404


# ── update ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_update_template_requires_manage_permission():
    tpl = RequestFormTemplate.objects.create(name="X", slug="x")
    resp = patch_json(Client(), f"{BASE}/templates/{tpl.id}/", {"name": "Y"}, **auth())
    assert resp.status_code == 403

    resp = patch_json(Client(), f"{BASE}/templates/{tpl.id}/", {"name": "Y"},
                      **auth(admin_token()))
    assert resp.status_code == 200
    assert resp.json()["name"] == "Y"


# ── publish / fetch versions ────────────────────────────────────────────

@pytest.mark.django_db
def test_publish_version_and_fetch():
    tid = post_json(Client(), f"{BASE}/templates/", {"name": "PO"},
                    **auth(admin_token())).json()["id"]
    resp = post_json(Client(), f"{BASE}/templates/{tid}/versions/",
                     {"schema_json": _SCHEMA, "workflow_json": _WF},
                     **auth(admin_token()))
    assert resp.status_code == 201
    vid = resp.json()["id"]
    assert resp.json()["version"] == 1

    resp = Client().get(f"{BASE}/templates/{tid}/", **auth(admin_token()))
    assert resp.json()["current_version_id"] == vid

    resp = post_json(Client(), f"{BASE}/templates/{tid}/versions/",
                     {"schema_json": _SCHEMA, "workflow_json": _WF},
                     **auth(admin_token()))
    assert resp.json()["version"] == 2

    resp = Client().get(f"{BASE}/templates/{tid}/versions/{vid}/", **auth())
    assert resp.status_code == 200
    assert resp.json()["schema_json"]["fields"][0]["key"] == "amount"


@pytest.mark.django_db
def test_publish_updates_data_table_columns():
    tid = post_json(Client(), f"{BASE}/templates/", {"name": "Счёт2"},
                    **auth(admin_token())).json()["id"]
    post_json(Client(), f"{BASE}/templates/{tid}/versions/",
             {"schema_json": _SCHEMA, "workflow_json": _WF}, **auth(admin_token()))
    src = RequestReferenceSource.objects.get(template_id=tid)
    assert "Сумма" in src.columns_json
    assert "Обоснование" in src.columns_json


@pytest.mark.django_db
def test_publish_invalid_workflow_422():
    tid = post_json(Client(), f"{BASE}/templates/", {"name": "Bad"},
                    **auth(admin_token())).json()["id"]
    bad_wf = {"nodes": [{"id": "n_start", "type": "start"}],
             "edges": [{"from": "n_start", "to": "ghost"}]}
    resp = post_json(Client(), f"{BASE}/templates/{tid}/versions/",
                     {"schema_json": _SCHEMA, "workflow_json": bad_wf},
                     **auth(admin_token()))
    assert resp.status_code == 422


@pytest.mark.django_db
def test_publish_version_requires_manage_permission():
    tpl = RequestFormTemplate.objects.create(name="Z", slug="z")
    resp = post_json(Client(), f"{BASE}/templates/{tpl.id}/versions/",
                     {"schema_json": _SCHEMA, "workflow_json": _WF}, **auth())
    assert resp.status_code == 403


@pytest.mark.django_db
def test_get_version_404_wrong_template():
    tid1 = post_json(Client(), f"{BASE}/templates/", {"name": "A1"},
                     **auth(admin_token())).json()["id"]
    tid2 = post_json(Client(), f"{BASE}/templates/", {"name": "A2"},
                     **auth(admin_token())).json()["id"]
    vid = post_json(Client(), f"{BASE}/templates/{tid1}/versions/",
                    {"schema_json": _SCHEMA, "workflow_json": _WF},
                    **auth(admin_token())).json()["id"]
    resp = Client().get(f"{BASE}/templates/{tid2}/versions/{vid}/", **auth())
    assert resp.status_code == 404


# ── preview ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_preview_validates_without_persisting():
    resp = post_json(Client(), f"{BASE}/templates/preview/",
                     {"schema_json": _SCHEMA, "workflow_json": _WF}, **auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["field_keys"] == ["amount", "reason"]
    assert body["node_count"] == 4
    assert not RequestFormTemplate.objects.exists()


@pytest.mark.django_db
def test_preview_invalid_is_422():
    bad_wf = {"nodes": [{"id": "n_start", "type": "start"}],
             "edges": [{"from": "n_start", "to": "ghost"}]}
    resp = post_json(Client(), f"{BASE}/templates/preview/",
                     {"schema_json": _SCHEMA, "workflow_json": bad_wf}, **auth())
    assert resp.status_code == 422


@pytest.mark.django_db
def test_preview_requires_auth():
    resp = post_json(Client(), f"{BASE}/templates/preview/",
                     {"schema_json": _SCHEMA, "workflow_json": _WF})
    assert resp.status_code == 401


# ── lifecycle: deactivate / activate / delete ───────────────────────────

def _published(client):
    tid = post_json(client, f"{BASE}/templates/", {"name": "Life"},
                    **auth(admin_token())).json()["id"]
    post_json(client, f"{BASE}/templates/{tid}/versions/",
             {"schema_json": _SCHEMA, "workflow_json": _WF}, **auth(admin_token()))
    return tid


@pytest.mark.django_db
def test_deactivate_then_activate_roundtrip():
    client = Client()
    tid = _published(client)

    resp = post_json(client, f"{BASE}/templates/{tid}/deactivate/", {}, **auth(admin_token()))
    assert resp.status_code == 200
    assert resp.json()["status"] == "inactive"
    assert resp.json()["is_active"] is False

    # still listed
    resp = client.get(f"{BASE}/templates/", **auth(admin_token()))
    assert any(t["id"] == tid for t in resp.json())

    resp = post_json(client, f"{BASE}/templates/{tid}/activate/", {}, **auth(admin_token()))
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"
    assert resp.json()["is_active"] is True


@pytest.mark.django_db
def test_deactivate_requires_manage_permission():
    client = Client()
    tid = _published(client)
    resp = post_json(client, f"{BASE}/templates/{tid}/deactivate/", {}, **auth())
    assert resp.status_code == 403


@pytest.mark.django_db
def test_activate_404_for_deleted_template():
    client = Client()
    tid = _published(client)
    client.delete(f"{BASE}/templates/{tid}/", **auth(admin_token()))
    resp = post_json(client, f"{BASE}/templates/{tid}/activate/", {}, **auth(admin_token()))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_delete_hides_template_and_preserves_data_table_access():
    client = Client()
    tid = _published(client)
    src = RequestReferenceSource.objects.get(template_id=tid)

    resp = client.delete(f"{BASE}/templates/{tid}/", **auth(admin_token()))
    assert resp.status_code == 204

    resp = client.get(f"{BASE}/templates/", **auth(admin_token()))
    assert all(t["id"] != tid for t in resp.json())

    tpl = RequestFormTemplate.objects.get(pk=tid)
    assert tpl.status == "deleted"
    assert tpl.is_active is False

    src.refresh_from_db()
    # the creator (admin_token's user_id) retains access to the orphaned table
    assert tpl.created_by in src.access_ids


@pytest.mark.django_db
def test_delete_requires_manage_permission():
    client = Client()
    tid = _published(client)
    resp = client.delete(f"{BASE}/templates/{tid}/", **auth())
    assert resp.status_code == 403


@pytest.mark.django_db
def test_delete_404_unknown_template():
    resp = Client().delete(f"{BASE}/templates/999/", **auth(admin_token()))
    assert resp.status_code == 404

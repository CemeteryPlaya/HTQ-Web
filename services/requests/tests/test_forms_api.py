from tests.factories import auth

_SCHEMA = {"fields": [
    {"type": "money", "key": "amount", "label": "Сумма", "contributes_to_total": True},
    {"type": "text", "key": "reason", "label": "Обоснование"},
]}
_WF = {
    "nodes": [
        {"id": "n_start", "type": "start"},
        {"id": "n_app", "type": "approval", "assignee": {"kind": "project_admins"}, "mode": "any"},
        {"id": "n_ok", "type": "end_approved"},
        {"id": "n_no", "type": "end_rejected"},
    ],
    "edges": [
        {"from": "n_start", "to": "n_app"},
        {"from": "n_app", "to": "n_ok", "on": "approve"},
        {"from": "n_app", "to": "n_no", "on": "reject"},
    ],
}


async def test_global_template_requires_elevated(client):
    r = await client.post("/api/requests/v1/templates/", json={"name": "Expense"}, headers=auth(1))
    assert r.status_code == 403
    r = await client.post("/api/requests/v1/templates/", json={"name": "Expense"}, headers=auth(1, is_staff=True))
    assert r.status_code == 201
    assert r.json()["slug"] == "expense"
    assert r.json()["project_id"] is None


async def test_duplicate_slug_conflicts(client):
    await client.post("/api/requests/v1/templates/", json={"name": "Trip"}, headers=auth(1, is_staff=True))
    r = await client.post("/api/requests/v1/templates/", json={"name": "Trip"}, headers=auth(1, is_staff=True))
    assert r.status_code == 409


async def test_publish_version_and_fetch(client):
    r = await client.post("/api/requests/v1/templates/", json={"name": "PO"}, headers=auth(1, is_staff=True))
    tid = r.json()["id"]
    r = await client.post(
        f"/api/requests/v1/templates/{tid}/versions/",
        json={"schema_json": _SCHEMA, "workflow_json": _WF},
        headers=auth(1, is_staff=True),
    )
    assert r.status_code == 201
    vid = r.json()["id"]
    assert r.json()["version"] == 1
    r = await client.get(f"/api/requests/v1/templates/{tid}/", headers=auth(1, is_staff=True))
    assert r.json()["current_version_id"] == vid
    r = await client.post(
        f"/api/requests/v1/templates/{tid}/versions/",
        json={"schema_json": _SCHEMA, "workflow_json": _WF},
        headers=auth(1, is_staff=True),
    )
    assert r.json()["version"] == 2
    r = await client.get(f"/api/requests/v1/templates/{tid}/versions/{vid}/", headers=auth(2))
    assert r.status_code == 200
    assert r.json()["schema_json"]["fields"][0]["key"] == "amount"


async def test_publish_invalid_workflow_422(client):
    r = await client.post("/api/requests/v1/templates/", json={"name": "Bad"}, headers=auth(1, is_staff=True))
    tid = r.json()["id"]
    bad_wf = {"nodes": [{"id": "n_start", "type": "start"}], "edges": [{"from": "n_start", "to": "ghost"}]}
    r = await client.post(
        f"/api/requests/v1/templates/{tid}/versions/",
        json={"schema_json": _SCHEMA, "workflow_json": bad_wf},
        headers=auth(1, is_staff=True),
    )
    assert r.status_code == 422


async def test_preview_validates_without_persisting(client):
    r = await client.post(
        "/api/requests/v1/templates/preview/",
        json={"schema_json": _SCHEMA, "workflow_json": _WF},
        headers=auth(2),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert body["field_keys"] == ["amount", "reason"]
    assert body["node_count"] == 4

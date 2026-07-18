from tests.factories import auth

_SCHEMA = {"fields": [{"type": "text", "key": "x", "label": "X"}]}
_WF = {
    "nodes": [
        {"id": "s", "type": "start"},
        {"id": "a", "type": "approval", "assignee": {"kind": "user", "id": 9}, "mode": "any"},
        {"id": "ok", "type": "end_approved"}, {"id": "no", "type": "end_rejected"},
    ],
    "edges": [
        {"from": "s", "to": "a"}, {"from": "a", "to": "ok", "on": "approve"},
        {"from": "a", "to": "no", "on": "reject"},
    ],
}


async def _published(client):
    r = await client.post("/api/requests/v1/templates/", json={"name": "Life"}, headers=auth(1, is_staff=True))
    tid = r.json()["id"]
    await client.post(f"/api/requests/v1/templates/{tid}/versions/",
                      json={"schema_json": _SCHEMA, "workflow_json": _WF}, headers=auth(1, is_staff=True))
    return tid


async def test_deactivate_blocks_submit_but_stays_visible(client):
    tid = await _published(client)
    r = await client.post(f"/api/requests/v1/templates/{tid}/deactivate/", headers=auth(1, is_staff=True))
    assert r.status_code == 200 and r.json()["status"] == "inactive"

    r = await client.post("/api/requests/v1/instances/", json={"template_id": tid, "form_values": {}}, headers=auth(1))
    assert r.status_code == 409 and "заблокирована" in r.json()["detail"]

    # still listed for admins
    r = await client.get("/api/requests/v1/templates/", headers=auth(1, is_staff=True))
    assert any(t["id"] == tid for t in r.json())

    r = await client.post(f"/api/requests/v1/templates/{tid}/activate/", headers=auth(1, is_staff=True))
    assert r.json()["status"] == "active"
    r = await client.post("/api/requests/v1/instances/", json={"template_id": tid, "form_values": {}}, headers=auth(1))
    assert r.status_code == 201


async def test_delete_hides_keeps_data_and_blocks_form(client):
    tid = await _published(client)
    sid = next(
        s["id"] for s in
        (await client.get("/api/requests/v1/reference-sources/my-data-tables", headers=auth(1, is_staff=True))).json()
        if s["template_id"] == tid
    )

    r = await client.delete(f"/api/requests/v1/templates/{tid}/", headers=auth(1, is_staff=True))
    assert r.status_code == 204

    # gone from the templates list
    r = await client.get("/api/requests/v1/templates/", headers=auth(1, is_staff=True))
    assert all(t["id"] != tid for t in r.json())

    # form blocked
    r = await client.post("/api/requests/v1/instances/", json={"template_id": tid, "form_values": {}}, headers=auth(1))
    assert r.status_code == 409 and "заблокирована" in r.json()["detail"]

    # data table preserved and still readable
    r = await client.get(f"/api/requests/v1/reference-sources/{sid}/rows/", headers=auth(1, is_staff=True))
    assert r.status_code == 200

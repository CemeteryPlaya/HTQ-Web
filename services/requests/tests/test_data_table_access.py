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


async def _make_table(client):
    r = await client.post("/api/requests/v1/templates/", json={"name": "AccT"}, headers=auth(1, is_staff=True))
    tid = r.json()["id"]
    await client.post(f"/api/requests/v1/templates/{tid}/versions/",
                      json={"schema_json": _SCHEMA, "workflow_json": _WF}, headers=auth(1, is_staff=True))
    r = await client.get("/api/requests/v1/reference-sources/my-data-tables", headers=auth(1, is_staff=True))
    sid = next(s["id"] for s in r.json() if s["template_id"] == tid)
    return tid, sid


async def test_stranger_cannot_see_or_read(client):
    _, sid = await _make_table(client)
    r = await client.get("/api/requests/v1/reference-sources/my-data-tables", headers=auth(7))
    assert all(s["id"] != sid for s in r.json())
    r = await client.get(f"/api/requests/v1/reference-sources/{sid}/rows/", headers=auth(7))
    assert r.status_code == 403


async def test_grant_access_lets_viewer_read(client):
    _, sid = await _make_table(client)
    r = await client.patch(f"/api/requests/v1/reference-sources/{sid}/access",
                           json={"viewer_ids": [5]}, headers=auth(1, is_staff=True))
    assert r.status_code == 200
    r = await client.get("/api/requests/v1/reference-sources/my-data-tables", headers=auth(5))
    t = next((s for s in r.json() if s["id"] == sid), None)
    assert t is not None and t["can_manage"] is False
    r = await client.get(f"/api/requests/v1/reference-sources/{sid}/rows/", headers=auth(5))
    assert r.status_code == 200


async def test_viewer_cannot_manage_access(client):
    _, sid = await _make_table(client)
    await client.patch(f"/api/requests/v1/reference-sources/{sid}/access",
                       json={"viewer_ids": [5]}, headers=auth(1, is_staff=True))
    r = await client.patch(f"/api/requests/v1/reference-sources/{sid}/access",
                           json={"viewer_ids": [5, 6]}, headers=auth(5))
    assert r.status_code == 403

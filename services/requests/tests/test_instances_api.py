from tests.factories import auth

_SCHEMA = {"fields": [
    {"type": "money", "key": "amount", "label": "Amount", "required": True, "contributes_to_total": True},
]}
_WF = {"nodes": [
        {"id": "s", "type": "start"},
        {"id": "a", "type": "approval", "assignee": {"kind": "project_admins"}, "mode": "any"},
        {"id": "ok", "type": "end_approved"},
        {"id": "no", "type": "end_rejected"}],
       "edges": [{"from": "s", "to": "a"},
                 {"from": "a", "to": "ok", "on": "approve"},
                 {"from": "a", "to": "no", "on": "reject"}]}


async def _setup_template(client):
    p = await client.post("/api/requests/v1/projects/", json={"name": "Proj"}, headers=auth(1, is_staff=True))
    pid = p.json()["id"]
    await client.post(f"/api/requests/v1/projects/{pid}/members/",
                      json={"user_id": 10, "role": "admin"}, headers=auth(1, is_staff=True))
    t = await client.post("/api/requests/v1/templates/",
                          json={"name": "Expense", "project_id": pid}, headers=auth(1, is_staff=True))
    tid = t.json()["id"]
    await client.post(f"/api/requests/v1/templates/{tid}/versions/",
                      json={"schema_json": _SCHEMA, "workflow_json": _WF},
                      headers=auth(1, is_staff=True))
    return pid, tid


async def test_full_happy_path(client):
    pid, tid = await _setup_template(client)
    r = await client.post("/api/requests/v1/instances/",
                          json={"template_id": tid, "title": "Trip", "form_values": {"amount": 500}},
                          headers=auth(2))
    assert r.status_code == 201
    iid = r.json()["id"]
    assert r.json()["status"] == "draft"
    r = await client.post(f"/api/requests/v1/instances/{iid}/submit/", headers=auth(2))
    assert r.status_code == 200
    assert r.json()["status"] == "pending"
    assert r.json()["current_node_id"] == "a"
    r = await client.get("/api/requests/v1/instances/?box=inbox", headers=auth(10))
    assert any(i["id"] == iid for i in r.json())
    r = await client.post(f"/api/requests/v1/instances/{iid}/approve/", json={}, headers=auth(10))
    assert r.status_code == 200
    assert r.json()["status"] == "approved"


async def test_required_field_blocks_submit(client):
    pid, tid = await _setup_template(client)
    r = await client.post("/api/requests/v1/instances/",
                          json={"template_id": tid, "title": "No amount", "form_values": {}},
                          headers=auth(2))
    iid = r.json()["id"]
    r = await client.post(f"/api/requests/v1/instances/{iid}/submit/", headers=auth(2))
    assert r.status_code == 422


async def test_non_approver_cannot_approve(client):
    pid, tid = await _setup_template(client)
    r = await client.post("/api/requests/v1/instances/",
                          json={"template_id": tid, "form_values": {"amount": 1}}, headers=auth(2))
    iid = r.json()["id"]
    await client.post(f"/api/requests/v1/instances/{iid}/submit/", headers=auth(2))
    r = await client.post(f"/api/requests/v1/instances/{iid}/approve/", json={}, headers=auth(3))
    assert r.status_code == 403


def _wf_branch():
    return {"nodes": [
        {"id": "s", "type": "start"},
        {"id": "c", "type": "condition", "expr": {">": [{"var": "amount"}, 100]}},
        {"id": "small", "type": "end_approved"},
        {"id": "big", "type": "approval", "assignee": {"kind": "project_admins"}, "mode": "any"},
        {"id": "ok", "type": "end_approved"},
        {"id": "no", "type": "end_rejected"}],
        "edges": [
            {"from": "s", "to": "c"},
            {"from": "c", "to": "small", "when": "false"},
            {"from": "c", "to": "big", "when": "true"},
            {"from": "big", "to": "ok", "on": "approve"},
            {"from": "big", "to": "no", "on": "reject"}]}


async def _setup_branch_template(client, name_suffix: str):
    p = await client.post("/api/requests/v1/projects/", json={"name": f"PCond-{name_suffix}"}, headers=auth(1, is_staff=True))
    pid = p.json()["id"]
    await client.post(f"/api/requests/v1/projects/{pid}/members/",
                      json={"user_id": 10, "role": "admin"}, headers=auth(1, is_staff=True))
    t = await client.post("/api/requests/v1/templates/",
                          json={"name": f"Cond-{name_suffix}", "project_id": pid}, headers=auth(1, is_staff=True))
    tid = t.json()["id"]
    await client.post(f"/api/requests/v1/templates/{tid}/versions/",
                      json={"schema_json": _SCHEMA, "workflow_json": _wf_branch()},
                      headers=auth(1, is_staff=True))
    return tid


async def test_condition_false_auto_approves(client):
    tid = await _setup_branch_template(client, "false")
    r = await client.post("/api/requests/v1/instances/",
                          json={"template_id": tid, "form_values": {"amount": 50}},
                          headers=auth(2))
    iid = r.json()["id"]
    r = await client.post(f"/api/requests/v1/instances/{iid}/submit/", headers=auth(2))
    # amount < 100 → false branch → end_approved auto-finalize
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    assert r.json()["current_node_id"] is None


async def test_condition_true_routes_to_approval(client):
    tid = await _setup_branch_template(client, "true")
    r = await client.post("/api/requests/v1/instances/",
                          json={"template_id": tid, "form_values": {"amount": 500}},
                          headers=auth(2))
    iid = r.json()["id"]
    r = await client.post(f"/api/requests/v1/instances/{iid}/submit/", headers=auth(2))
    assert r.json()["status"] == "pending"
    assert r.json()["current_node_id"] == "big"


async def test_reject_and_request_changes(client):
    pid, tid = await _setup_template(client)
    r = await client.post("/api/requests/v1/instances/",
                          json={"template_id": tid, "form_values": {"amount": 1}}, headers=auth(2))
    iid = r.json()["id"]
    await client.post(f"/api/requests/v1/instances/{iid}/submit/", headers=auth(2))
    r = await client.post(f"/api/requests/v1/instances/{iid}/request-changes/",
                          json={"comment": "fix"}, headers=auth(10))
    assert r.json()["status"] == "returned"
    await client.patch(f"/api/requests/v1/instances/{iid}/",
                       json={"form_values": {"amount": 2}}, headers=auth(2))
    r = await client.post(f"/api/requests/v1/instances/{iid}/resubmit/", headers=auth(2))
    assert r.json()["status"] == "pending"
    r = await client.post(f"/api/requests/v1/instances/{iid}/reject/",
                          json={"comment": "no"}, headers=auth(10))
    assert r.json()["status"] == "rejected"

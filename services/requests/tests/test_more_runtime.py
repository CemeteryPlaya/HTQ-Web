"""Runtime enforcement of the builder's step-4 "Прочее" (More) settings.

Shared helpers (`_published_template`, `_submit`) are reused across the
settings-runtime tasks — keep them generic at module top.
"""

from tests.factories import auth


async def _published_template(client, settings=None):
    r = await client.post(
        "/api/requests/v1/templates/",
        json={"name": f"T{settings}", "config_json": {"settings": settings or {}}},
        headers=auth(1, is_staff=True),
    )
    tid = r.json()["id"]
    schema = {"fields": [{"type": "text", "key": "x", "label": "X"}]}
    wf = {
        "nodes": [
            {"id": "s", "type": "start"},
            {"id": "a", "type": "approval", "assignee": {"kind": "user", "id": 9}, "mode": "any"},
            {"id": "ok", "type": "end_approved"},
            {"id": "no", "type": "end_rejected"},
        ],
        "edges": [
            {"from": "s", "to": "a"},
            {"from": "a", "to": "ok", "on": "approve"},
            {"from": "a", "to": "no", "on": "reject"},
        ],
    }
    await client.post(
        f"/api/requests/v1/templates/{tid}/versions/",
        json={"schema_json": schema, "workflow_json": wf},
        headers=auth(1, is_staff=True),
    )
    return tid


async def _submit(client, tid, initiator=1):
    r = await client.post(
        "/api/requests/v1/instances/",
        json={"template_id": tid, "form_values": {"x": "1"}},
        headers=auth(initiator),
    )
    iid = r.json()["id"]
    await client.post(f"/api/requests/v1/instances/{iid}/submit/", headers=auth(initiator))
    return iid


async def test_cancel_pending_allowed_by_default(client):
    tid = await _published_template(client)
    iid = await _submit(client, tid)
    r = await client.post(f"/api/requests/v1/instances/{iid}/cancel/", json={"comment": ""}, headers=auth(1))
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


async def test_cancel_pending_blocked_after_first_step_when_disabled(client):
    tid = await _published_template(client, {"allow_revoke_pending": False})
    iid = await _submit(client, tid)
    await client.post(f"/api/requests/v1/instances/{iid}/approve/", json={"comment": ""}, headers=auth(9))
    # single-approver workflow finalizes on approve → now APPROVED, cancel blocked
    r = await client.post(f"/api/requests/v1/instances/{iid}/cancel/", json={"comment": ""}, headers=auth(1))
    assert r.status_code == 409


async def test_modify_approved_blocked_by_default(client):
    tid = await _published_template(client)
    iid = await _submit(client, tid)
    await client.post(f"/api/requests/v1/instances/{iid}/approve/", json={"comment": ""}, headers=auth(9))
    r = await client.patch(f"/api/requests/v1/instances/{iid}/", json={"title": "edited"}, headers=auth(1))
    assert r.status_code == 409


async def test_modify_approved_allowed_within_window(client):
    tid = await _published_template(client, {"allow_modify_approved": True, "modify_within_days": 30})
    iid = await _submit(client, tid)
    await client.post(f"/api/requests/v1/instances/{iid}/approve/", json={"comment": ""}, headers=auth(9))
    r = await client.patch(f"/api/requests/v1/instances/{iid}/", json={"title": "edited"}, headers=auth(1))
    assert r.status_code == 200
    assert r.json()["title"] == "edited"


async def _two_step_template(client, settings):
    r = await client.post(
        "/api/requests/v1/templates/",
        json={"name": "dedup", "config_json": {"settings": settings}},
        headers=auth(1, is_staff=True),
    )
    tid = r.json()["id"]
    schema = {"fields": [{"type": "text", "key": "x", "label": "X"}]}
    wf = {
        "nodes": [
            {"id": "s", "type": "start"},
            {"id": "a1", "type": "approval", "assignee": {"kind": "user", "id": 9}, "mode": "any"},
            {"id": "a2", "type": "approval", "assignee": {"kind": "user", "id": 9}, "mode": "any"},
            {"id": "ok", "type": "end_approved"},
            {"id": "no", "type": "end_rejected"},
        ],
        "edges": [
            {"from": "s", "to": "a1"},
            {"from": "a1", "to": "a2", "on": "approve"},
            {"from": "a1", "to": "no", "on": "reject"},
            {"from": "a2", "to": "ok", "on": "approve"},
            {"from": "a2", "to": "no", "on": "reject"},
        ],
    }
    await client.post(
        f"/api/requests/v1/templates/{tid}/versions/",
        json={"schema_json": schema, "workflow_json": wf},
        headers=auth(1, is_staff=True),
    )
    return tid


async def test_dedup_once_auto(client):
    tid = await _two_step_template(client, {"dedup": "once_auto"})
    iid = await _submit(client, tid)
    r = await client.post(f"/api/requests/v1/instances/{iid}/approve/", json={"comment": ""}, headers=auth(9))
    assert r.json()["status"] == "approved"  # a2 auto-approved


async def test_dedup_none_needs_both(client):
    tid = await _two_step_template(client, {"dedup": "none"})
    iid = await _submit(client, tid)
    r = await client.post(f"/api/requests/v1/instances/{iid}/approve/", json={"comment": ""}, headers=auth(9))
    assert r.json()["status"] == "pending"  # still waiting on a2


async def test_batch_approve_gated_on(client):
    tid = await _published_template(client, {"allow_batch": True})
    iid1 = await _submit(client, tid)
    iid2 = await _submit(client, tid)
    r = await client.post(
        "/api/requests/v1/instances/batch-approve",
        json={"ids": [iid1, iid2], "comment": ""},
        headers=auth(9),
    )
    assert r.status_code == 200
    results = r.json()["results"]
    assert all(res["ok"] is True for res in results), results
    for iid in (iid1, iid2):
        g = await client.get(f"/api/requests/v1/instances/{iid}/", headers=auth(9))
        assert g.json()["status"] == "approved"


async def test_batch_approve_disabled_by_default(client):
    tid = await _published_template(client)
    iid = await _submit(client, tid)
    r = await client.post(
        "/api/requests/v1/instances/batch-approve",
        json={"ids": [iid], "comment": ""},
        headers=auth(9),
    )
    assert r.status_code == 200
    res = r.json()["results"][0]
    assert res["ok"] is False
    assert "batch" in res["error"]


async def test_recall_returns_to_pending(client):
    tid = await _two_step_template(client, {"allow_recall_decision": True})
    iid = await _submit(client, tid)
    # Approve a1 (mode any) -> advances to a2, still pending.
    r = await client.post(f"/api/requests/v1/instances/{iid}/approve/", json={"comment": ""}, headers=auth(9))
    assert r.json()["status"] == "pending"
    # Recall the a1 approval -> back to pending, awaiting user 9 at a1 again.
    rec = await client.post(f"/api/requests/v1/instances/{iid}/recall/", json={"comment": ""}, headers=auth(9))
    assert rec.status_code == 200
    body = rec.json()
    assert body["status"] == "pending"
    assert body["current_node_id"] == "a1"
    # A live action exists for user 9 -> the request is back in their inbox.
    inbox = await client.get("/api/requests/v1/instances/?box=inbox", headers=auth(9))
    assert iid in [i["id"] for i in inbox.json()]


async def test_recall_disabled_by_default(client):
    tid = await _two_step_template(client, {})
    iid = await _submit(client, tid)
    await client.post(f"/api/requests/v1/instances/{iid}/approve/", json={"comment": ""}, headers=auth(9))
    rec = await client.post(f"/api/requests/v1/instances/{iid}/recall/", json={"comment": ""}, headers=auth(9))
    assert rec.status_code == 403


async def test_delegated_submission_allowed_for_elevated(client):
    tid = await _published_template(client, {"allow_delegate_submission": True})
    r = await client.post(
        "/api/requests/v1/instances/",
        json={"template_id": tid, "form_values": {"x": "1"}, "on_behalf_of": 5},
        headers=auth(1, is_staff=True),
    )
    assert r.status_code == 201
    assert r.json()["initiator_id"] == 5


async def test_delegated_submission_blocked_without_flag(client):
    tid = await _published_template(client)
    r = await client.post(
        "/api/requests/v1/instances/",
        json={"template_id": tid, "form_values": {"x": "1"}, "on_behalf_of": 5},
        headers=auth(1, is_staff=True),
    )
    assert r.status_code == 403

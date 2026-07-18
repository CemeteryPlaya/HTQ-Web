"""API-level tests for the stats endpoints. Drives instances through the full
runtime (project → template → submit → approve/reject) so finalize-time
UPSERTs into request_stats_daily run for real, then checks the JSON shapes."""

from tests.factories import auth

_SCHEMA = {"fields": [
    {"type": "money", "key": "amount", "label": "Amount", "required": True, "contributes_to_total": True},
]}
_WF_AUTO_APPROVE = {  # routes straight to end_approved
    "nodes": [
        {"id": "s", "type": "start"},
        {"id": "ok", "type": "end_approved"}],
    "edges": [{"from": "s", "to": "ok"}],
}


async def _setup(client, project_name: str):
    p = await client.post("/api/requests/v1/projects/",
                          json={"name": project_name, "budget_limit": "10000"},
                          headers=auth(1, is_staff=True))
    pid = p.json()["id"]
    t = await client.post("/api/requests/v1/templates/",
                          json={"name": f"Tpl-{project_name}", "project_id": pid},
                          headers=auth(1, is_staff=True))
    tid = t.json()["id"]
    await client.post(f"/api/requests/v1/templates/{tid}/versions/",
                      json={"schema_json": _SCHEMA, "workflow_json": _WF_AUTO_APPROVE},
                      headers=auth(1, is_staff=True))
    return pid, tid


async def _submit_approved(client, tid: int, amount: float):
    r = await client.post("/api/requests/v1/instances/",
                          json={"template_id": tid, "form_values": {"amount": amount}},
                          headers=auth(2))
    iid = r.json()["id"]
    r = await client.post(f"/api/requests/v1/instances/{iid}/submit/", headers=auth(2))
    assert r.json()["status"] == "approved"


async def test_overview_counts_finalized(client):
    pid, tid = await _setup(client, "Stat-Ov")
    await _submit_approved(client, tid, 100)
    await _submit_approved(client, tid, 200)
    r = await client.get("/api/requests/v1/stats/overview", headers=auth(1, is_staff=True))
    assert r.status_code == 200
    body = r.json()
    assert body["by_status"]["approved"]["count"] >= 2


async def test_by_project_plan_vs_fact(client):
    pid, tid = await _setup(client, "Stat-BP")
    await _submit_approved(client, tid, 100)
    await _submit_approved(client, tid, 250)
    r = await client.get(f"/api/requests/v1/stats/by-project?project_id={pid}",
                         headers=auth(1, is_staff=True))
    assert r.status_code == 200
    body = r.json()
    assert body["project"]["id"] == pid
    assert body["project"]["budget_limit"] == 10000.0
    assert body["sum_approved"] == 350.0
    assert body["remaining"] == 9650.0
    assert 3 < body["percent_used"] < 4


async def test_by_template(client):
    pid, tid = await _setup(client, "Stat-BT")
    await _submit_approved(client, tid, 100)
    await _submit_approved(client, tid, 200)
    r = await client.get(f"/api/requests/v1/stats/by-template?project_id={pid}",
                         headers=auth(1, is_staff=True))
    assert r.status_code == 200
    body = r.json()
    row = next((x for x in body if x["template_id"] == tid), None)
    assert row is not None
    assert row["count"] == 2
    assert row["approved"] == 2
    assert row["approval_rate"] == 1.0
    assert row["avg_amount"] == 150.0


async def test_by_actor_initiator(client):
    pid, tid = await _setup(client, "Stat-BA")
    await _submit_approved(client, tid, 100)
    r = await client.get("/api/requests/v1/stats/by-actor?role=initiator",
                         headers=auth(1, is_staff=True))
    assert r.status_code == 200
    body = r.json()
    assert any(row["user_id"] == 2 and row["count"] >= 1 for row in body)


async def test_heatmap_returns_per_day_rows(client):
    pid, tid = await _setup(client, "Stat-HM")
    await _submit_approved(client, tid, 100)
    r = await client.get("/api/requests/v1/stats/heatmap", headers=auth(1, is_staff=True))
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert any(row["approved"] >= 1 for row in body)

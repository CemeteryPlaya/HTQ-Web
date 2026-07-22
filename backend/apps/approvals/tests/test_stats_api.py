"""Contract tests for ``/api/requests/v1/stats/*``.

Source: ``services/requests/app/api/v1/stats.py`` +
``services/requests/tests/test_stats_api.py``. Drives instances through the
real runtime (project -> template -> submit -> auto-approve) so
``stats_rollup.upsert_finalization`` runs for real on finalization, then
checks the JSON shapes match the original's aggregation cuts.
"""

import pytest
from django.test import Client

from .helpers import BASE, admin_token, auth, post_json, simple_workflow, token

_SCHEMA = {"fields": [
    {"type": "money", "key": "amount", "label": "Amount", "required": True,
     "contributes_to_total": True},
]}
_WF_AUTO_APPROVE = {  # routes straight to end_approved -- no approval node
    "nodes": [{"id": "s", "type": "start"}, {"id": "ok", "type": "end_approved"}],
    "edges": [{"from": "s", "to": "ok"}],
}


def _setup(client: Client, project_name: str):
    pid = post_json(client, f"{BASE}/projects/",
                    {"name": project_name, "budget_limit": "10000"},
                    **auth(admin_token())).json()["id"]
    tid = post_json(client, f"{BASE}/templates/",
                    {"name": f"Tpl-{project_name}", "project_id": pid},
                    **auth(admin_token())).json()["id"]
    post_json(client, f"{BASE}/templates/{tid}/versions/",
             {"schema_json": _SCHEMA, "workflow_json": _WF_AUTO_APPROVE},
             **auth(admin_token()))
    return pid, tid


def _submit_approved(client: Client, tid: int, amount: float):
    r = post_json(client, f"{BASE}/instances/",
                  {"template_id": tid, "form_values": {"amount": amount}}, **auth())
    iid = r.json()["id"]
    r = post_json(client, f"{BASE}/instances/{iid}/submit/", {}, **auth())
    assert r.json()["status"] == "approved"


# ── auth ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_stats_require_auth():
    assert Client().get(f"{BASE}/stats/overview").status_code == 401


# ── overview ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_overview_counts_finalized():
    client = Client()
    _pid, tid = _setup(client, "Stat-Ov")
    _submit_approved(client, tid, 100)
    _submit_approved(client, tid, 200)

    resp = client.get(f"{BASE}/stats/overview", **auth(admin_token()))
    assert resp.status_code == 200
    body = resp.json()
    assert body["by_status"]["approved"]["count"] >= 2
    assert "from" in body and "to" in body


@pytest.mark.django_db
def test_overview_invalid_date_is_422():
    resp = Client().get(f"{BASE}/stats/overview?from=not-a-date", **auth())
    assert resp.status_code == 422


# ── by-project ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_by_project_plan_vs_fact():
    client = Client()
    pid, tid = _setup(client, "Stat-BP")
    _submit_approved(client, tid, 100)
    _submit_approved(client, tid, 250)

    resp = client.get(f"{BASE}/stats/by-project?project_id={pid}", **auth(admin_token()))
    assert resp.status_code == 200
    body = resp.json()
    assert body["project"]["id"] == pid
    assert body["project"]["budget_limit"] == 10000.0
    assert body["sum_approved"] == 350.0
    assert body["remaining"] == 9650.0
    assert 3 < body["percent_used"] < 4


@pytest.mark.django_db
def test_by_project_unknown_returns_null_project():
    resp = Client().get(f"{BASE}/stats/by-project?project_id=999999", **auth())
    assert resp.status_code == 200
    assert resp.json() == {"project": None}


@pytest.mark.django_db
def test_by_project_missing_param_is_422():
    resp = Client().get(f"{BASE}/stats/by-project", **auth())
    assert resp.status_code == 422


# ── by-template ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_by_template():
    client = Client()
    pid, tid = _setup(client, "Stat-BT")
    _submit_approved(client, tid, 100)
    _submit_approved(client, tid, 200)

    resp = client.get(f"{BASE}/stats/by-template?project_id={pid}", **auth(admin_token()))
    assert resp.status_code == 200
    body = resp.json()
    row = next((x for x in body if x["template_id"] == tid), None)
    assert row is not None
    assert row["count"] == 2
    assert row["approved"] == 2
    assert row["approval_rate"] == 1.0
    assert row["avg_amount"] == 150.0


# ── by-actor ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_by_actor_initiator_default_role():
    client = Client()
    _pid, tid = _setup(client, "Stat-BA")
    _submit_approved(client, tid, 100)

    resp = client.get(f"{BASE}/stats/by-actor", **auth(admin_token()))
    assert resp.status_code == 200
    body = resp.json()
    assert any(row["user_id"] == 7 and row["count"] >= 1 for row in body)


@pytest.mark.django_db
def test_by_actor_approver_role():
    client = Client()
    tid = post_json(client, f"{BASE}/templates/", {"name": "ApproverFlow"},
                    **auth(admin_token())).json()["id"]
    schema = {"fields": [{"key": "amount", "type": "number", "label": "Сумма"}]}
    wf = simple_workflow(approver_id=11)
    post_json(client, f"{BASE}/templates/{tid}/versions/",
             {"schema_json": schema, "workflow_json": wf}, **auth(admin_token()))

    iid = post_json(client, f"{BASE}/instances/",
                    {"template_id": tid, "form_values": {"amount": 5}},
                    **auth()).json()["id"]
    post_json(client, f"{BASE}/instances/{iid}/submit/", {}, **auth())
    resp = post_json(client, f"{BASE}/instances/{iid}/approve/", {"comment": ""},
                     **auth(token(user_id=11, sub="11")))
    assert resp.json()["status"] == "approved"

    resp = client.get(f"{BASE}/stats/by-actor?role=approver", **auth(admin_token()))
    assert resp.status_code == 200
    assert any(row["user_id"] == 11 for row in resp.json())


@pytest.mark.django_db
def test_by_actor_invalid_role_is_422():
    resp = Client().get(f"{BASE}/stats/by-actor?role=bogus", **auth())
    assert resp.status_code == 422


# ── heatmap ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_heatmap_returns_per_day_rows():
    client = Client()
    _pid, tid = _setup(client, "Stat-HM")
    _submit_approved(client, tid, 100)

    resp = client.get(f"{BASE}/stats/heatmap", **auth(admin_token()))
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert any(row["approved"] >= 1 for row in body)

"""Contract tests for ``/api/requests/v1/instances/*`` and the approver
actions.

Sources: ``services/requests/app/api/v1/{instances,actions}.py`` plus
``services/request_runtime.py``. The state machine is the thing most likely
to drift in a port, so the lifecycle (draft → pending → approved/rejected/
returned) gets end-to-end coverage rather than unit stubs.
"""

import pytest
from django.test import Client

from apps.approvals.models import (
    ApprovalAction, RequestActivity, RequestInstance, RequestStatus,
    RequestWatcher,
)

from .helpers import (
    BASE, admin_token, auth, make_instance, make_template, patch_json,
    post_json, simple_workflow, token,
)

USER = 7
APPROVER = 11
OTHER = 42


# ── creation ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_instances_require_auth():
    assert Client().get(f"{BASE}/instances/").status_code == 401


@pytest.mark.django_db
def test_create_instance_starts_as_draft():
    template = make_template()
    resp = post_json(Client(), f"{BASE}/instances/",
                     {"template_id": template.id, "title": "Отпуск в мае",
                      "form_values": {"amount": 5}}, **auth())
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == RequestStatus.DRAFT
    assert body["initiator_id"] == USER
    assert body["template_version_id"] == template.current_version_id
    assert body["code"].startswith("REQ-otpusk-")
    assert RequestActivity.objects.filter(event_type="created").exists()


@pytest.mark.django_db
def test_create_instance_generates_sequential_codes():
    template = make_template()
    client = Client()
    first = post_json(client, f"{BASE}/instances/",
                      {"template_id": template.id}, **auth()).json()
    second = post_json(client, f"{BASE}/instances/",
                       {"template_id": template.id}, **auth()).json()
    assert first["code"].endswith("-0001")
    assert second["code"].endswith("-0002")


@pytest.mark.django_db
def test_create_instance_unknown_template_is_404():
    resp = post_json(Client(), f"{BASE}/instances/", {"template_id": 999},
                     **auth())
    assert resp.status_code == 404


@pytest.mark.django_db
def test_create_instance_on_an_unpublished_template_is_409():
    template = make_template(publish=False)
    resp = post_json(Client(), f"{BASE}/instances/",
                     {"template_id": template.id}, **auth())
    assert resp.status_code == 409
    assert "no published version" in resp.json()["detail"]


@pytest.mark.django_db
def test_create_instance_on_a_blocked_template_is_409():
    template = make_template()
    template.status = "inactive"
    template.save(update_fields=["status"])
    resp = post_json(Client(), f"{BASE}/instances/",
                     {"template_id": template.id}, **auth())
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Форма заблокирована"


@pytest.mark.django_db
def test_delegated_submission_needs_both_the_setting_and_elevation():
    plain = make_template(slug="plain")
    # setting off -> even an admin is refused
    resp = post_json(Client(), f"{BASE}/instances/",
                     {"template_id": plain.id, "on_behalf_of": OTHER},
                     **auth(admin_token()))
    assert resp.status_code == 403

    allowed = make_template(
        slug="allowed", config={"settings": {"allow_delegate_submission": True}})
    # setting on, but caller not elevated -> still refused
    assert post_json(Client(), f"{BASE}/instances/",
                     {"template_id": allowed.id, "on_behalf_of": OTHER},
                     **auth()).status_code == 403
    # both -> allowed, and the initiator is the person acted for
    resp = post_json(Client(), f"{BASE}/instances/",
                     {"template_id": allowed.id, "on_behalf_of": OTHER},
                     **auth(admin_token()))
    assert resp.status_code == 201
    assert resp.json()["initiator_id"] == OTHER
    assert RequestActivity.objects.filter(
        event_type="created_on_behalf").exists()


# ── mailboxes ───────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_sent_box_lists_own_requests():
    template = make_template()
    mine = make_instance(template, initiator_id=USER)
    make_instance(template, initiator_id=OTHER)
    resp = Client().get(f"{BASE}/instances/?box=sent", **auth())
    assert [row["id"] for row in resp.json()] == [mine.id]


@pytest.mark.django_db
def test_inbox_lists_requests_awaiting_my_action():
    template = make_template()
    waiting = make_instance(template, status=RequestStatus.PENDING)
    ApprovalAction.objects.create(request=waiting, node_id="a1",
                                  approver_id=USER)
    acted_on = make_instance(template, status=RequestStatus.PENDING)
    ApprovalAction.objects.create(request=acted_on, node_id="a1",
                                  approver_id=USER, action="approve",
                                  acted_at="2026-01-01T00:00:00Z")

    inbox = Client().get(f"{BASE}/instances/?box=inbox", **auth()).json()
    assert [row["id"] for row in inbox] == [waiting.id]

    done = Client().get(f"{BASE}/instances/?box=done", **auth()).json()
    assert [row["id"] for row in done] == [acted_on.id]


@pytest.mark.django_db
def test_cc_box_lists_watched_requests():
    template = make_template()
    watched = make_instance(template, initiator_id=OTHER)
    RequestWatcher.objects.create(request=watched, user_id=USER)
    resp = Client().get(f"{BASE}/instances/?box=cc", **auth())
    assert [row["id"] for row in resp.json()] == [watched.id]


@pytest.mark.django_db
def test_unknown_box_falls_back_to_inbox():
    """The box name comes from a UI tab — the original tolerated anything."""
    assert Client().get(f"{BASE}/instances/?box=weird",
                        **auth()).status_code == 200


# ── draft editing ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_only_the_initiator_can_edit_a_draft():
    template = make_template()
    instance = make_instance(template, initiator_id=OTHER)
    assert patch_json(Client(), f"{BASE}/instances/{instance.id}/",
                      {"title": "чужое"}, **auth()).status_code == 403


@pytest.mark.django_db
def test_edit_draft_updates_title_and_values():
    template = make_template()
    instance = make_instance(template)
    resp = patch_json(Client(), f"{BASE}/instances/{instance.id}/",
                      {"title": "Новое", "form_values": {"amount": 42}},
                      **auth())
    assert resp.status_code == 200
    assert resp.json()["title"] == "Новое"
    assert resp.json()["form_values_json"] == {"amount": 42}


@pytest.mark.django_db
def test_pending_request_is_not_editable():
    template = make_template()
    instance = make_instance(template, status=RequestStatus.PENDING)
    resp = patch_json(Client(), f"{BASE}/instances/{instance.id}/",
                      {"title": "нельзя"}, **auth())
    assert resp.status_code == 409


# ── the lifecycle ───────────────────────────────────────────────────────

def _submit(client, instance_id, tok=None):
    return client.post(f"{BASE}/instances/{instance_id}/submit/",
                       **auth(tok))


@pytest.mark.django_db
def test_submit_moves_to_pending_and_assigns_the_approver():
    template = make_template()
    instance = make_instance(template)
    resp = _submit(Client(), instance.id)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == RequestStatus.PENDING
    assert body["current_node_id"] == "a1"
    assert body["submitted_at"] is not None

    action = ApprovalAction.objects.get(request_id=instance.id)
    assert action.approver_id == APPROVER
    assert action.acted_at is None


@pytest.mark.django_db
def test_only_the_initiator_can_submit():
    template = make_template()
    instance = make_instance(template, initiator_id=OTHER)
    assert _submit(Client(), instance.id).status_code == 403


@pytest.mark.django_db
def test_submitting_twice_is_409():
    template = make_template()
    instance = make_instance(template)
    client = Client()
    _submit(client, instance.id)
    assert _submit(client, instance.id).status_code == 409


@pytest.mark.django_db
def test_approve_finalizes_a_single_step_workflow():
    template = make_template()
    instance = make_instance(template)
    _submit(Client(), instance.id)

    resp = post_json(Client(), f"{BASE}/instances/{instance.id}/approve/",
                     {"comment": "ок"}, **auth(token(user_id=APPROVER,
                                                     sub=str(APPROVER))))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == RequestStatus.APPROVED
    assert body["current_node_id"] is None
    assert body["finalized_at"] is not None


@pytest.mark.django_db
def test_reject_finalizes_as_rejected():
    template = make_template()
    instance = make_instance(template)
    _submit(Client(), instance.id)
    resp = post_json(Client(), f"{BASE}/instances/{instance.id}/reject/",
                     {"comment": "нет"},
                     **auth(token(user_id=APPROVER, sub=str(APPROVER))))
    assert resp.json()["status"] == RequestStatus.REJECTED


@pytest.mark.django_db
def test_a_non_approver_cannot_act():
    template = make_template()
    instance = make_instance(template)
    _submit(Client(), instance.id)
    resp = post_json(Client(), f"{BASE}/instances/{instance.id}/approve/",
                     {}, **auth(token(user_id=OTHER, sub=str(OTHER))))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_request_changes_returns_the_request_to_its_author():
    template = make_template()
    instance = make_instance(template)
    _submit(Client(), instance.id)
    resp = post_json(Client(),
                     f"{BASE}/instances/{instance.id}/request-changes/",
                     {"comment": "поправьте сумму"},
                     **auth(token(user_id=APPROVER, sub=str(APPROVER))))
    assert resp.status_code == 200
    assert resp.json()["status"] == RequestStatus.RETURNED
    assert resp.json()["current_node_id"] is None


@pytest.mark.django_db
def test_returned_request_is_editable_and_resubmittable():
    template = make_template()
    instance = make_instance(template)
    client = Client()
    _submit(client, instance.id)
    post_json(client, f"{BASE}/instances/{instance.id}/request-changes/", {},
              **auth(token(user_id=APPROVER, sub=str(APPROVER))))

    assert patch_json(client, f"{BASE}/instances/{instance.id}/",
                      {"form_values": {"amount": 1}}, **auth()).status_code == 200
    resp = client.post(f"{BASE}/instances/{instance.id}/resubmit/", **auth())
    assert resp.status_code == 200
    assert resp.json()["status"] == RequestStatus.PENDING


@pytest.mark.django_db
def test_resubmitting_a_draft_is_409():
    template = make_template()
    instance = make_instance(template)
    resp = Client().post(f"{BASE}/instances/{instance.id}/resubmit/", **auth())
    assert resp.status_code == 409


@pytest.mark.django_db
def test_all_mode_needs_every_approver():
    template = make_template(
        workflow={
            "nodes": [
                {"id": "start", "type": "start"},
                {"id": "a1", "type": "approval", "mode": "all",
                 "assignee": {"kind": "users", "ids": [11, 12]}},
                {"id": "ok", "type": "end_approved"},
                {"id": "no", "type": "end_rejected"},
            ],
            "edges": [
                {"from": "start", "to": "a1"},
                {"from": "a1", "to": "ok", "on": "approve"},
                {"from": "a1", "to": "no", "on": "reject"},
            ],
        })
    instance = make_instance(template)
    _submit(Client(), instance.id)

    first = post_json(Client(), f"{BASE}/instances/{instance.id}/approve/", {},
                      **auth(token(user_id=11, sub="11")))
    assert first.json()["status"] == RequestStatus.PENDING   # still waiting

    second = post_json(Client(), f"{BASE}/instances/{instance.id}/approve/", {},
                       **auth(token(user_id=12, sub="12")))
    assert second.json()["status"] == RequestStatus.APPROVED


# ── cancel ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_initiator_can_cancel_a_pending_request():
    template = make_template()
    instance = make_instance(template)
    _submit(Client(), instance.id)
    resp = post_json(Client(), f"{BASE}/instances/{instance.id}/cancel/", {},
                     **auth())
    assert resp.status_code == 200
    assert resp.json()["status"] == RequestStatus.CANCELLED


@pytest.mark.django_db
def test_a_stranger_cannot_cancel():
    template = make_template()
    instance = make_instance(template)
    _submit(Client(), instance.id)
    resp = post_json(Client(), f"{BASE}/instances/{instance.id}/cancel/", {},
                     **auth(token(user_id=OTHER, sub=str(OTHER))))
    assert resp.status_code == 403


# ── batch approve ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_batch_approve_reports_per_item_results():
    """Not all-or-nothing: the UI needs to know which ones went through."""
    allowed = make_template(slug="batch",
                            config={"settings": {"allow_batch": True}})
    plain = make_template(slug="nobatch")
    ok_instance = make_instance(allowed)
    blocked = make_instance(plain)
    client = Client()
    _submit(client, ok_instance.id)
    _submit(client, blocked.id)

    resp = post_json(client, f"{BASE}/instances/batch-approve",
                     {"ids": [ok_instance.id, blocked.id, 999]},
                     **auth(token(user_id=APPROVER, sub=str(APPROVER))))
    assert resp.status_code == 200
    results = {row["id"]: row for row in resp.json()["results"]}
    assert results[ok_instance.id]["ok"] is True
    assert results[blocked.id]["error"] == "batch disabled"
    assert results[999]["error"] == "not found"


# ── detail ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_get_instance_and_unknown_id():
    template = make_template()
    instance = make_instance(template)
    assert Client().get(f"{BASE}/instances/{instance.id}/",
                        **auth()).status_code == 200
    assert Client().get(f"{BASE}/instances/999/", **auth()).status_code == 404


@pytest.mark.django_db
def test_instance_detail_accepts_both_slash_spellings():
    template = make_template()
    instance = make_instance(template)
    for path in (f"{BASE}/instances/{instance.id}",
                 f"{BASE}/instances/{instance.id}/"):
        assert Client().get(path, **auth()).status_code == 200

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
    RequestActivity, RequestInstance, RequestStatus,
    RequestWatcher,
)

from .helpers import (
    APPROVER, BASE, admin_token, auth, decide, make_instance, make_template,
    patch_json, pending_task, post_json, token,
)

USER = 7
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


def _submit(client, instance_id, tok=None):
    return client.post(f"{BASE}/instances/{instance_id}/submit/",
                       **auth(tok))


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
    """«Список дел» и «Готово» отвечает движок signoff: кто должен решить и
    кто уже решал — вопросы к нему, а не к таблицам заявок."""
    template = make_template(approvers=(USER,))
    client = Client()
    waiting = make_instance(template)
    acted_on = make_instance(template)
    _submit(client, waiting.id)
    _submit(client, acted_on.id)
    decide(client, acted_on, USER)

    inbox = client.get(f"{BASE}/instances/?box=inbox", **auth()).json()
    assert [row["id"] for row in inbox] == [waiting.id]

    done = client.get(f"{BASE}/instances/?box=done", **auth()).json()
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


# ── the lifecycle ───────────────────────────────────────────────────────


@pytest.mark.django_db
def test_submit_moves_to_pending_and_opens_a_signoff_process():
    template = make_template()
    instance = make_instance(template)
    resp = _submit(Client(), instance.id)
    # Отдаётся карточка ПРОЦЕССА — как у submit в contracts.
    assert resp.status_code == 201, resp.content
    card = resp.json()
    assert card["state"] == "pending"
    assert card["scope"] == f"template:{template.id}"
    assert card["stages"][0]["tasks"][0]["user_id"] == APPROVER
    assert card["subject_title"].startswith(instance.code)

    body = Client().get(f"{BASE}/instances/{instance.id}/", **auth()).json()
    assert body["status"] == RequestStatus.PENDING
    assert body["approval_state"] == "pending"
    assert body["submitted_at"] is not None
    assert body["current_node_id"] is None  # наследие старого движка


@pytest.mark.django_db
def test_submit_without_a_route_is_409_with_the_engines_reason():
    template = make_template(route=False)
    instance = make_instance(template)
    resp = _submit(Client(), instance.id)
    assert resp.status_code == 409
    assert "не настроен маршрут" in resp.json()["detail"]
    instance.refresh_from_db()
    assert instance.status == RequestStatus.DRAFT


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
def test_approve_finalizes_a_single_stage_route():
    template = make_template()
    instance = make_instance(template)
    client = Client()
    _submit(client, instance.id)

    resp = decide(client, instance, APPROVER, comment="ок")
    assert resp.status_code == 200, resp.content
    assert resp.json()["state"] == "approved"

    body = client.get(f"{BASE}/instances/{instance.id}/", **auth()).json()
    assert body["status"] == RequestStatus.APPROVED
    assert body["approval_state"] == "approved"
    assert body["finalized_at"] is not None
    assert RequestActivity.objects.filter(request=instance, event_type="finalized").exists()


@pytest.mark.django_db
def test_reject_finalizes_as_rejected():
    template = make_template()
    instance = make_instance(template)
    client = Client()
    _submit(client, instance.id)
    decide(client, instance, APPROVER, decision="reject", comment="нет")
    body = client.get(f"{BASE}/instances/{instance.id}/", **auth()).json()
    assert body["status"] == RequestStatus.REJECTED
    assert body["approval_state"] == "rejected"


@pytest.mark.django_db
def test_a_non_approver_cannot_act():
    """Чужой запрос: движок отвечает 409 «адресован другому» — состояние
    данных, а не нехватка прав (см. signoff.engine.act)."""
    template = make_template()
    instance = make_instance(template)
    client = Client()
    _submit(client, instance.id)
    task = pending_task(instance, APPROVER)
    resp = post_json(client, f"/api/signoff/v1/tasks/{task.pk}/decision",
                     {"decision": "approve"},
                     **auth(token(user_id=OTHER, sub=str(OTHER))))
    assert resp.status_code == 409


@pytest.mark.django_db
def test_rework_returns_the_request_to_its_author():
    template = make_template()
    instance = make_instance(template)
    client = Client()
    _submit(client, instance.id)
    resp = decide(client, instance, APPROVER, decision="rework", comment="поправьте сумму")
    assert resp.status_code == 200, resp.content
    body = client.get(f"{BASE}/instances/{instance.id}/", **auth()).json()
    assert body["status"] == RequestStatus.RETURNED
    assert body["approval_state"] == "rework"
    assert RequestActivity.objects.filter(request=instance,
                                          event_type="request_changes").exists()


@pytest.mark.django_db
def test_returned_request_is_editable_and_resubmittable():
    template = make_template()
    instance = make_instance(template)
    client = Client()
    _submit(client, instance.id)
    decide(client, instance, APPROVER, decision="rework")

    assert patch_json(client, f"{BASE}/instances/{instance.id}/",
                      {"form_values": {"amount": 1}}, **auth()).status_code == 200
    resp = client.post(f"{BASE}/instances/{instance.id}/resubmit/", **auth())
    assert resp.status_code == 201, resp.content
    assert resp.json()["state"] == "pending"
    assert client.get(f"{BASE}/instances/{instance.id}/",
                      **auth()).json()["status"] == RequestStatus.PENDING
    # Новый круг — новый процесс, старый остался историей.
    processes = client.get(
        f"/api/signoff/v1/processes?subject_type=approvals.request&subject_id={instance.id}",
        **auth(admin_token())).json()
    assert sorted(row["state"] for row in processes) == ["pending", "rework"]


@pytest.mark.django_db
def test_pending_request_is_locked_by_signoff_with_the_engines_reason():
    template = make_template()
    instance = make_instance(template)
    client = Client()
    _submit(client, instance.id)
    resp = patch_json(client, f"{BASE}/instances/{instance.id}/",
                      {"title": "нельзя"}, **auth())
    assert resp.status_code == 409
    assert "на согласовании" in resp.json()["detail"]


@pytest.mark.django_db
def test_resubmitting_a_draft_is_409():
    template = make_template()
    instance = make_instance(template)
    resp = Client().post(f"{BASE}/instances/{instance.id}/resubmit/", **auth())
    assert resp.status_code == 409


@pytest.mark.django_db
def test_all_quorum_needs_every_approver():
    template = make_template(approvers=(11, 12))
    instance = make_instance(template)
    client = Client()
    _submit(client, instance.id)

    first = decide(client, instance, 11)
    assert first.json()["state"] == "pending"   # still waiting
    assert client.get(f"{BASE}/instances/{instance.id}/", **auth()).json()["status"] == RequestStatus.PENDING

    second = decide(client, instance, 12)
    assert second.json()["state"] == "approved"
    assert client.get(f"{BASE}/instances/{instance.id}/", **auth()).json()["status"] == RequestStatus.APPROVED


# ── cancel (через signoff) ──────────────────────────────────────────────

def _process_id(client, instance) -> int:
    rows = client.get(
        f"/api/signoff/v1/processes?subject_type=approvals.request&subject_id={instance.id}&state=pending",
        **auth(admin_token())).json()
    return rows[0]["id"]


@pytest.mark.django_db
def test_initiator_can_cancel_a_pending_request():
    template = make_template()
    instance = make_instance(template)
    client = Client()
    _submit(client, instance.id)
    resp = client.post(f"/api/signoff/v1/processes/{_process_id(client, instance)}/cancel",
                       **auth())
    assert resp.status_code == 200, resp.content
    body = client.get(f"{BASE}/instances/{instance.id}/", **auth()).json()
    assert body["status"] == RequestStatus.CANCELLED
    assert body["approval_state"] == "draft"


@pytest.mark.django_db
def test_a_stranger_cannot_cancel():
    template = make_template()
    instance = make_instance(template)
    client = Client()
    _submit(client, instance.id)
    process_id = _process_id(client, instance)
    resp = client.post(f"/api/signoff/v1/processes/{process_id}/cancel",
                       **auth(token(user_id=OTHER, sub=str(OTHER))))
    assert resp.status_code in (403, 404)


# ── batch (через signoff) ───────────────────────────────────────────────

@pytest.mark.django_db
def test_batch_decision_reports_per_item_results():
    """Not all-or-nothing: the UI needs to know which ones went through."""
    template = make_template()
    first, second = make_instance(template), make_instance(template)
    client = Client()
    _submit(client, first.id)
    _submit(client, second.id)
    tasks = [pending_task(first, APPROVER).pk, pending_task(second, APPROVER).pk]

    resp = post_json(client, "/api/signoff/v1/tasks/batch-decision",
                     {"task_ids": [*tasks, 999999], "decision": "approve"},
                     **auth(token(user_id=APPROVER, sub=str(APPROVER))))
    assert resp.status_code == 200, resp.content
    results = {row["task_id"]: row for row in resp.json()}
    assert all(results[t]["ok"] for t in tasks)
    assert results[999999]["ok"] is False
    assert RequestInstance.objects.filter(status=RequestStatus.APPROVED).count() == 2


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

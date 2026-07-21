"""Contract tests for ``/api/tasks/v1/tasks/*``.

Mirrors ``services/task/app/api/v1/tasks.py``. The permission matrix and the
FSM are the two things most likely to drift during a port, so they get the
most coverage here.

``apps.users.interface`` / ``apps.hr.interface`` are patched where a test
cares about hydrated names; otherwise they degrade to ``None``/``{}`` on
their own (hr is still the prep stub — see ``services/hydration.py``), which
is itself the behaviour PLAN.md §7 requires and is asserted directly in
``test_hydration.py``.
"""

import pytest
from django.test import Client

from apps.tasks.models import (
    AssigneeRole, Label, Notification, Priority, Project, Status, Task,
    TaskActivity, TaskAssignee, TaskDelegate, TaskType, TaskWatcher,
)

from .helpers import BASE, admin_token, auth, patch_json, post_json, token

USER = 7          # the id baked into helpers.token()
OTHER = 42


def _mk_task(**over) -> Task:
    fields = {"key": f"TASK-{Task.objects.count() + 1}", "summary": "S",
              "reporter_id": USER}
    fields.update(over)
    return Task.objects.create(**fields)


# ── list / filters / visibility ─────────────────────────────────────────

@pytest.mark.django_db
def test_list_requires_auth():
    assert Client().get(f"{BASE}/tasks/").status_code == 401


@pytest.mark.django_db
def test_list_returns_list_shape():
    _mk_task(summary="First")
    resp = Client().get(f"{BASE}/tasks/", **auth())
    assert resp.status_code == 200
    row = resp.json()[0]
    assert row["summary"] == "First"
    # The back-compat slug fallback for an unclassified task.
    assert row["task_type"] == "task"
    assert row["subtask_count"] == 0
    assert row["labels"] == []


@pytest.mark.django_db
def test_list_hides_soft_deleted_tasks():
    _mk_task(summary="visible")
    _mk_task(summary="gone", is_deleted=True)
    resp = Client().get(f"{BASE}/tasks/", **auth())
    assert [r["summary"] for r in resp.json()] == ["visible"]


@pytest.mark.django_db
def test_non_elevated_user_sees_only_their_own_tasks():
    mine = _mk_task(summary="mine", reporter_id=USER)
    _mk_task(summary="theirs", reporter_id=OTHER)
    resp = Client().get(f"{BASE}/tasks/", **auth())
    assert [r["id"] for r in resp.json()] == [mine.id]


@pytest.mark.django_db
def test_elevated_user_sees_everything():
    _mk_task(summary="mine", reporter_id=USER)
    _mk_task(summary="theirs", reporter_id=OTHER)
    resp = Client().get(f"{BASE}/tasks/", **auth(admin_token()))
    assert len(resp.json()) == 2


@pytest.mark.django_db
def test_task_visible_through_any_participant_role_appears_once():
    """The visibility filter ORs across several to-many joins; without
    ``distinct()`` a task reachable by two roles would be listed twice."""
    task = _mk_task(summary="multi", reporter_id=OTHER, supervisor_id=USER)
    TaskAssignee.objects.create(task=task, user_id=USER)
    TaskWatcher.objects.create(task=task, user_id=USER)
    resp = Client().get(f"{BASE}/tasks/", **auth())
    assert [r["id"] for r in resp.json()] == [task.id]


@pytest.mark.django_db
def test_list_filters():
    a = _mk_task(summary="alpha", status=Status.DONE, priority=Priority.HIGH)
    _mk_task(summary="beta", status=Status.TODO, priority=Priority.LOW)
    client, hdr = Client(), auth(admin_token())

    assert [r["id"] for r in client.get(
        f"{BASE}/tasks/?status=done", **hdr).json()] == [a.id]
    assert [r["id"] for r in client.get(
        f"{BASE}/tasks/?priority=high", **hdr).json()] == [a.id]
    assert [r["id"] for r in client.get(
        f"{BASE}/tasks/?search=alph", **hdr).json()] == [a.id]


@pytest.mark.django_db
def test_list_search_matches_key_and_description():
    task = _mk_task(summary="nothing", description="needle here")
    hdr = auth(admin_token())
    assert [r["id"] for r in Client().get(
        f"{BASE}/tasks/?search=needle", **hdr).json()] == [task.id]
    assert [r["id"] for r in Client().get(
        f"{BASE}/tasks/?search={task.key}", **hdr).json()] == [task.id]


@pytest.mark.django_db
def test_list_standalone_filter():
    project = Project.objects.create(name="P")
    _mk_task(summary="in-project", project=project)
    solo = _mk_task(summary="solo")
    resp = Client().get(f"{BASE}/tasks/?standalone=true", **auth(admin_token()))
    assert [r["id"] for r in resp.json()] == [solo.id]


@pytest.mark.django_db
def test_list_label_filter():
    label = Label.objects.create(name="ops")
    tagged = _mk_task(summary="tagged")
    tagged.labels.add(label)
    _mk_task(summary="plain")
    resp = Client().get(f"{BASE}/tasks/?label_id={label.id}",
                        **auth(admin_token()))
    assert [r["id"] for r in resp.json()] == [tagged.id]


@pytest.mark.django_db
def test_list_pagination():
    for i in range(3):
        _mk_task(summary=f"t{i}")
    hdr = auth(admin_token())
    assert len(Client().get(f"{BASE}/tasks/?limit=2", **hdr).json()) == 2
    assert len(Client().get(f"{BASE}/tasks/?limit=2&offset=2", **hdr).json()) == 1


@pytest.mark.django_db
def test_bad_query_param_is_422_not_500():
    resp = Client().get(f"{BASE}/tasks/?limit=abc", **auth())
    assert resp.status_code == 422
    resp = Client().get(f"{BASE}/tasks/?limit=999", **auth())
    assert resp.status_code == 422


# ── create ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_create_task_assigns_sequential_key_and_defaults():
    resp = post_json(Client(), f"{BASE}/tasks/", {"summary": "New"}, **auth())
    assert resp.status_code == 201
    body = resp.json()
    assert body["key"] == "TASK-1"
    assert body["status"] == Status.TODO
    assert body["priority"] == Priority.MEDIUM
    assert body["reporter_id"] == USER      # defaults to the caller
    assert body["task_type"] == "task"      # seeded default type


@pytest.mark.django_db
def test_create_task_rejects_blank_summary():
    resp = post_json(Client(), f"{BASE}/tasks/", {"summary": "   "}, **auth())
    assert resp.status_code == 422


@pytest.mark.django_db
def test_create_task_resolves_type_by_slug():
    resp = post_json(Client(), f"{BASE}/tasks/",
                     {"summary": "Bug!", "task_type": "bug"}, **auth())
    assert resp.json()["task_type"] == "bug"
    assert resp.json()["task_type_name"] == "Баг"


@pytest.mark.django_db
def test_create_task_builds_crew_from_legacy_and_explicit_fields():
    resp = post_json(Client(), f"{BASE}/tasks/", {
        "summary": "Crew",
        "assignee_id": 11,
        "assignees": [{"user_id": 12, "role": "collaborator"}],
    }, **auth())
    body = resp.json()
    assert body["assignee_id"] == 11
    crew = {row["user_id"]: row["role"] for row in body["assignees"]}
    assert crew == {11: AssigneeRole.PRIMARY, 12: AssigneeRole.COLLABORATOR}


@pytest.mark.django_db
def test_create_task_explicit_primary_demotes_the_legacy_one():
    resp = post_json(Client(), f"{BASE}/tasks/", {
        "summary": "Crew",
        "assignee_id": 11,
        "assignees": [{"user_id": 12, "role": "primary"}],
    }, **auth())
    crew = {row["user_id"]: row["role"] for row in resp.json()["assignees"]}
    assert crew == {11: AssigneeRole.COLLABORATOR, 12: AssigneeRole.PRIMARY}


@pytest.mark.django_db
def test_create_task_notifies_the_crew():
    post_json(Client(), f"{BASE}/tasks/",
              {"summary": "N", "assignee_id": 11}, **auth())
    note = Notification.objects.get(recipient_id=11)
    assert note.verb.startswith("task_assigned:")
    assert note.target_type == "task"


@pytest.mark.django_db
def test_create_task_stores_multi_department_set():
    resp = post_json(Client(), f"{BASE}/tasks/",
                     {"summary": "D", "department_ids": [3, 5]}, **auth())
    body = resp.json()
    assert body["department_id"] == 3           # first becomes primary
    assert sorted(body["department_ids"]) == [3, 5]


@pytest.mark.django_db
def test_create_task_ignores_unknown_label_ids():
    label = Label.objects.create(name="real")
    resp = post_json(Client(), f"{BASE}/tasks/",
                     {"summary": "L", "label_ids": [label.id, 999]}, **auth())
    assert [row["id"] for row in resp.json()["labels"]] == [label.id]


# ── detail ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_get_task_detail_shape():
    task = _mk_task(summary="Detail", description="body")
    resp = Client().get(f"{BASE}/tasks/{task.id}/", **auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["description"] == "body"
    for key in ("comments", "attachments", "activities", "subtasks",
                "delegates", "watchers", "outgoing_links", "incoming_links"):
        assert body[key] == [], key


@pytest.mark.django_db
def test_get_task_out_of_scope_is_404_not_403():
    """A task the caller cannot see must be indistinguishable from one that
    does not exist, so the endpoint never confirms its existence."""
    task = _mk_task(summary="secret", reporter_id=OTHER)
    assert Client().get(f"{BASE}/tasks/{task.id}/", **auth()).status_code == 404


@pytest.mark.django_db
def test_task_detail_accepts_both_slash_spellings():
    task = _mk_task()
    for path in (f"{BASE}/tasks/{task.id}", f"{BASE}/tasks/{task.id}/"):
        assert Client().get(path, **auth()).status_code == 200


# ── update / FSM ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_update_summary_requires_full_edit():
    task = _mk_task(reporter_id=OTHER, supervisor_id=OTHER)
    TaskAssignee.objects.create(task=task, user_id=USER)   # assignee only
    resp = patch_json(Client(), f"{BASE}/tasks/{task.id}/",
                      {"summary": "hijack"}, **auth())
    assert resp.status_code == 403


@pytest.mark.django_db
def test_assignee_may_change_status_only():
    task = _mk_task(reporter_id=OTHER, supervisor_id=OTHER)
    TaskAssignee.objects.create(task=task, user_id=USER)
    resp = patch_json(Client(), f"{BASE}/tasks/{task.id}/",
                      {"status": "in_progress"}, **auth())
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"


@pytest.mark.django_db
def test_delegate_gets_full_edit():
    task = _mk_task(reporter_id=OTHER, supervisor_id=OTHER)
    TaskDelegate.objects.create(task=task, user_id=USER)
    resp = patch_json(Client(), f"{BASE}/tasks/{task.id}/",
                      {"summary": "allowed"}, **auth())
    assert resp.status_code == 200


@pytest.mark.django_db
def test_invalid_transition_is_400():
    task = _mk_task(status=Status.BACKLOG)
    # backlog -> done is not in TRANSITIONS
    resp = patch_json(Client(), f"{BASE}/tasks/{task.id}/",
                      {"status": "done"}, **auth())
    assert resp.status_code == 400
    assert "Cannot transition" in resp.json()["detail"]


@pytest.mark.django_db
def test_done_transition_stamps_completion_and_progress():
    task = _mk_task(status=Status.IN_PROGRESS)
    resp = patch_json(Client(), f"{BASE}/tasks/{task.id}/",
                      {"status": "done"}, **auth())
    body = resp.json()
    assert body["progress_percent"] == 100
    assert body["completed_at"] is not None


@pytest.mark.django_db
def test_reopening_clears_the_completion_stamp():
    task = _mk_task(status=Status.IN_PROGRESS)
    patch_json(Client(), f"{BASE}/tasks/{task.id}/", {"status": "done"}, **auth())
    resp = patch_json(Client(), f"{BASE}/tasks/{task.id}/",
                      {"status": "in_progress"}, **auth())
    assert resp.json()["completed_at"] is None


@pytest.mark.django_db
def test_update_writes_activity_log_entries():
    task = _mk_task(summary="before")
    patch_json(Client(), f"{BASE}/tasks/{task.id}/",
               {"summary": "after"}, **auth())
    entry = TaskActivity.objects.get(task=task, field_name="summary")
    assert (entry.old_value, entry.new_value) == ("before", "after")
    assert entry.actor_id == USER


@pytest.mark.django_db
def test_changing_assignee_syncs_the_crew_table():
    task = _mk_task()
    TaskAssignee.objects.create(task=task, user_id=11, role=AssigneeRole.PRIMARY)
    patch_json(Client(), f"{BASE}/tasks/{task.id}/",
               {"assignee_id": 12}, **auth())
    roles = dict(TaskAssignee.objects.filter(task=task)
                 .values_list("user_id", "role"))
    assert roles == {11: AssigneeRole.COLLABORATOR, 12: AssigneeRole.PRIMARY}


@pytest.mark.django_db
def test_transitions_endpoint_lists_reachable_states():
    task = _mk_task(status=Status.BLOCKED)
    resp = Client().get(f"{BASE}/tasks/{task.id}/transitions/", **auth())
    assert resp.status_code == 200
    assert {row["status"] for row in resp.json()} == {
        "in_progress", "todo", "cancelled"}


# ── delete ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_delete_is_soft():
    task = _mk_task()
    assert Client().delete(f"{BASE}/tasks/{task.id}/",
                           **auth()).status_code == 204
    task.refresh_from_db()
    assert task.is_deleted is True


@pytest.mark.django_db
def test_delete_requires_full_edit():
    task = _mk_task(reporter_id=OTHER, supervisor_id=OTHER)
    TaskAssignee.objects.create(task=task, user_id=USER)
    assert Client().delete(f"{BASE}/tasks/{task.id}/",
                           **auth()).status_code == 403


# ── participants ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_replace_assignees_removes_absent_members():
    task = _mk_task()
    TaskAssignee.objects.create(task=task, user_id=11, role=AssigneeRole.PRIMARY)
    TaskAssignee.objects.create(task=task, user_id=12)
    resp = patch_json(Client(), f"{BASE}/tasks/{task.id}/assignees/", {
        "assignees": [{"user_id": 12, "role": "primary"}],
    }, **auth())
    assert resp.status_code == 200
    assert resp.json()["assignee_id"] == 12
    assert list(TaskAssignee.objects.filter(task=task)
                .values_list("user_id", flat=True)) == [12]


@pytest.mark.django_db
def test_replace_assignees_rejects_two_primaries():
    task = _mk_task()
    resp = patch_json(Client(), f"{BASE}/tasks/{task.id}/assignees/", {
        "assignees": [{"user_id": 1, "role": "primary"},
                      {"user_id": 2, "role": "primary"}],
    }, **auth())
    assert resp.status_code == 422


@pytest.mark.django_db
def test_set_supervisor_logs_and_notifies():
    task = _mk_task()
    resp = patch_json(Client(), f"{BASE}/tasks/{task.id}/supervisor/",
                      {"user_id": 21}, **auth())
    assert resp.json()["supervisor_id"] == 21
    assert TaskActivity.objects.filter(task=task,
                                       field_name="supervisor_id").exists()
    assert Notification.objects.filter(recipient_id=21).exists()


@pytest.mark.django_db
def test_only_supervisor_or_admin_may_add_a_delegate():
    task = _mk_task(reporter_id=USER, supervisor_id=OTHER)
    # caller is the reporter but not the supervisor
    resp = post_json(Client(), f"{BASE}/tasks/{task.id}/delegates/",
                     {"user_id": 33}, **auth())
    assert resp.status_code == 403


@pytest.mark.django_db
def test_supervisor_adds_delegate_idempotently():
    task = _mk_task(supervisor_id=USER)
    url = f"{BASE}/tasks/{task.id}/delegates/"
    assert post_json(Client(), url, {"user_id": 33}, **auth()).status_code == 201
    post_json(Client(), url, {"user_id": 33}, **auth())
    assert TaskDelegate.objects.filter(task=task, user_id=33).count() == 1


@pytest.mark.django_db
def test_delegate_may_give_up_their_own_seat():
    task = _mk_task(reporter_id=OTHER, supervisor_id=OTHER)
    TaskDelegate.objects.create(task=task, user_id=USER)
    resp = Client().delete(f"{BASE}/tasks/{task.id}/delegates/{USER}/", **auth())
    assert resp.status_code == 200
    assert not TaskDelegate.objects.filter(task=task, user_id=USER).exists()


@pytest.mark.django_db
def test_delegate_cannot_revoke_someone_else():
    task = _mk_task(reporter_id=OTHER, supervisor_id=OTHER)
    TaskDelegate.objects.create(task=task, user_id=USER)
    TaskDelegate.objects.create(task=task, user_id=99)
    resp = Client().delete(f"{BASE}/tasks/{task.id}/delegates/99/", **auth())
    assert resp.status_code == 403


@pytest.mark.django_db
def test_watch_and_unwatch_are_self_only():
    task = _mk_task()
    assert Client().post(f"{BASE}/tasks/{task.id}/watch/",
                         **auth()).status_code == 201
    assert TaskWatcher.objects.filter(task=task, user_id=USER).exists()
    # repeat is a no-op, not a duplicate-key error
    Client().post(f"{BASE}/tasks/{task.id}/watch/", **auth())
    assert TaskWatcher.objects.filter(task=task, user_id=USER).count() == 1

    assert Client().delete(f"{BASE}/tasks/{task.id}/watch/",
                           **auth()).status_code == 200
    assert not TaskWatcher.objects.filter(task=task, user_id=USER).exists()


@pytest.mark.django_db
def test_progress_update_is_clamped_and_logged():
    task = _mk_task()
    resp = patch_json(Client(), f"{BASE}/tasks/{task.id}/progress/",
                      {"percent": 60}, **auth())
    assert resp.json()["progress_percent"] == 60
    assert TaskActivity.objects.filter(task=task,
                                       field_name="progress_percent").exists()


@pytest.mark.django_db
def test_progress_out_of_range_is_422():
    task = _mk_task()
    resp = patch_json(Client(), f"{BASE}/tasks/{task.id}/progress/",
                      {"percent": 140}, **auth())
    assert resp.status_code == 422


# ── stats ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_stats_shape_and_counts():
    _mk_task(status=Status.TODO, priority=Priority.HIGH)
    _mk_task(status=Status.TODO, priority=Priority.LOW)
    _mk_task(status=Status.BACKLOG, priority=Priority.LOW)
    resp = Client().get(f"{BASE}/tasks/stats/", **auth(admin_token()))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert body["by_status"] == {"todo": 2, "backlog": 1}
    assert body["by_priority"] == {"high": 1, "low": 2}
    assert body["by_type"] == {"unknown": 3}
    for key in ("by_department", "by_assignee", "created_per_day",
                "resolved_per_day"):
        assert isinstance(body[key], list), key


@pytest.mark.django_db
def test_stats_counts_each_task_once_despite_role_joins():
    """Regression guard for the GROUP BY: a task the caller reaches through
    several roles must not be counted several times.

    ``/tasks/stats/`` runs in the "reports" scope for a non-elevated caller,
    which only admits terminal tasks the caller works on — hence ``done``
    here. The task matches the scope twice over (denormalised
    ``assignee_id`` AND a ``TaskAssignee`` row), which is exactly the
    row-multiplying join the DISTINCT count has to absorb.
    """
    task = _mk_task(status=Status.DONE, assignee_id=USER)
    TaskAssignee.objects.create(task=task, user_id=USER)
    resp = Client().get(f"{BASE}/tasks/stats/", **auth())
    body = resp.json()
    assert body["total"] == 1
    assert body["by_status"] == {"done": 1}
    assert body["by_assignee"][0]["count"] == 1


@pytest.mark.django_db
def test_stats_by_department_labels_missing_department():
    _mk_task(department_id=None)
    resp = Client().get(f"{BASE}/tasks/stats/", **auth(admin_token()))
    assert resp.json()["by_department"][0]["department__name"] == "Без отдела"


@pytest.mark.django_db
def test_stats_by_type_uses_slugs():
    bug = TaskType.objects.get(slug="bug")
    _mk_task(task_type=bug)
    resp = Client().get(f"{BASE}/tasks/stats/", **auth(admin_token()))
    assert resp.json()["by_type"] == {"bug": 1}

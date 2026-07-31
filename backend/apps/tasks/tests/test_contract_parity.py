"""Contract-parity tests for the tasks domain (DoD §6.6 п.1).

PROVENANCE — read ``fixtures/contracts.json``'s ``source`` keys before
touching anything here. The FastAPI task-service is not running in this
environment, so none of these shapes were captured from a live response;
each was derived by reading the Pydantic response model in
``services/task/app/schemas/``. Whoever spins up the original stack should
replace the field maps with captured responses — the helpers below can stay.

The point is DRIFT DETECTION, not characterisation of whatever Django
returns today: the assertions check the field NAMES and TYPES taken from the
FastAPI schemas, so renaming, dropping or retyping a field the React
frontend reads fails here even when the new output looks reasonable on its
own. Nested objects are checked too — a list-of-objects field like
``assignees`` is only useful if the objects inside it kept their shape.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from django.test import Client
from django.utils import timezone

from apps.tasks.models import (
    AssigneeRole, CalendarEvent, Equipment, Label, Notification, Project,
    Task, TaskActivity, TaskAssignee, ResourceAllocation, TaskAttachment,
    TaskComment, TaskDelegate, TaskType, TaskWatcher,
)

from .helpers import BASE, admin_token, auth, post_json

CONTRACTS = json.loads(
    (Path(__file__).parent / "fixtures" / "contracts.json")
    .read_text(encoding="utf-8")
)["contracts"]


def _check_type(value, expected: str) -> bool:
    """``expected`` is a ``|``-joined list of: int, float, str, bool, list,
    dict, null."""
    for opt in expected.split("|"):
        if opt == "null" and value is None:
            return True
        if opt == "bool" and isinstance(value, bool):
            return True
        if opt == "int" and isinstance(value, int) and not isinstance(value, bool):
            return True
        # JSON has one number type: an integral float serialises as `0`, so a
        # float-typed field legitimately arrives as int.
        if opt == "float" and isinstance(value, (int, float)) \
                and not isinstance(value, bool):
            return True
        if opt == "str" and isinstance(value, str):
            return True
        if opt == "list" and isinstance(value, list):
            return True
        if opt == "dict" and isinstance(value, dict):
            return True
    return False


def assert_shape(body: dict, contract_name: str) -> None:
    contract = CONTRACTS[contract_name]
    fields = contract["fields"]
    assert set(body) == set(fields), (
        f"top-level keys drifted from {contract['source']}: "
        f"got {sorted(body)}, expected {sorted(fields)}"
    )
    for key, expected in fields.items():
        assert _check_type(body[key], expected), (
            f"{contract_name}.{key!r} = {body[key]!r} does not match "
            f"{expected!r} from {contract['source']}"
        )


def assert_each(items: list, contract_name: str) -> None:
    assert items, f"fixture set up no rows to check {contract_name} against"
    for item in items:
        assert_shape(item, contract_name)


# ── a task exercising every nested block at once ────────────────────────

@pytest.fixture
def rich_task(db):
    """One task carrying every optional relation, so the detail contract is
    checked with its nested lists populated rather than empty."""
    project = Project.objects.create(name="Парити", owner_id=11,
                                     department_id=3)
    label = Label.objects.create(name="ops")
    parent = Task.objects.create(key="TASK-100", summary="Родитель")
    task = Task.objects.create(
        key="TASK-101", summary="Задача", description="Описание",
        task_type=TaskType.objects.get(slug="bug"), project=project,
        parent=parent, reporter_id=7, assignee_id=11, supervisor_id=12,
        department_id=3, start_date=dt.date(2026, 3, 2),
        due_date=dt.date(2026, 3, 6), estimated_working_days=5,
    )
    task.labels.add(label)
    TaskAssignee.objects.create(task=task, user_id=11,
                                role=AssigneeRole.PRIMARY)
    TaskDelegate.objects.create(task=task, user_id=13, granted_by_id=12)
    TaskWatcher.objects.create(task=task, user_id=14)
    TaskComment.objects.create(task=task, author_id=11, body="комментарий")
    TaskAttachment.objects.create(task=task, file_path="k", filename="f.pdf",
                                  uploaded_by_id=11)
    TaskActivity.objects.create(task=task, actor_id=11, field_name="summary",
                                old_value="a", new_value="b")
    Task.objects.create(key="TASK-102", summary="Подзадача", parent=task)
    return task


@pytest.mark.django_db
def test_task_detail_matches_the_fastapi_schema(rich_task):
    resp = Client().get(f"{BASE}/tasks/{rich_task.id}/", **auth(admin_token()))
    assert resp.status_code == 200
    body = resp.json()
    assert_shape(body, "TaskDetailResponse")
    assert_each(body["assignees"], "AssigneeResponse")
    assert_each(body["delegates"], "DelegateResponse")
    assert_each(body["watchers"], "WatcherResponse")
    assert_each(body["labels"], "LabelResponse")
    assert_each(body["comments"], "CommentResponse")
    assert_each(body["attachments"], "AttachmentResponse")
    assert_each(body["activities"], "ActivityResponse")
    assert_each(body["subtasks"], "TaskListResponse")


@pytest.mark.django_db
def test_task_list_matches_the_fastapi_schema(rich_task):
    resp = Client().get(f"{BASE}/tasks/", **auth(admin_token()))
    assert_each(resp.json(), "TaskListResponse")


@pytest.mark.django_db
def test_task_create_response_uses_the_detail_schema():
    """POST /tasks/ declares the same ``response_model`` as GET /tasks/{id}
    in the original — assert it against the same contract, not a bespoke one."""
    resp = post_json(Client(), f"{BASE}/tasks/", {"summary": "Новая"}, **auth())
    assert resp.status_code == 201
    assert_shape(resp.json(), "TaskDetailResponse")


@pytest.mark.django_db
def test_task_stats_matches_the_fastapi_schema(rich_task):
    resp = Client().get(f"{BASE}/tasks/stats/", **auth(admin_token()))
    assert_shape(resp.json(), "TaskStats")


@pytest.mark.django_db
def test_link_response_matches_the_fastapi_schema():
    a = Task.objects.create(key="TASK-1", summary="A")
    b = Task.objects.create(key="TASK-2", summary="B")
    # admin_token: linking now requires full-edit rights on the source task,
    # and these fixtures have no reporter/assignee for a regular caller to be.
    resp = post_json(Client(), f"{BASE}/task-links/",
                     {"source_id": a.id, "target_id": b.id,
                      "link_type": "blocks"}, **auth(admin_token()))
    assert_shape(resp.json(), "LinkResponse")


# ── reference data ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_reference_responses_match_the_fastapi_schemas():
    Label.objects.create(name="ops")
    Equipment.objects.create(name="Кран")
    client = Client()
    assert_each(client.get(f"{BASE}/labels/", **auth()).json(),
                "LabelResponse")
    assert_each(client.get(f"{BASE}/task-types/", **auth()).json(),
                "TaskTypeResponse")
    assert_each(client.get(f"{BASE}/equipment/", **auth()).json(),
                "EquipmentResponse")


@pytest.mark.django_db
def test_assignment_response_matches_the_fastapi_schema():
    task = Task.objects.create(key="TASK-1", summary="A")
    ResourceAllocation.objects.create(task=task, employee_id=11, role="сварщик")
    # admin_token: listing a task's resources now requires visibility of the
    # task itself, and this fixture has no participants.
    assert_each(Client().get(f"{BASE}/assignments/?task_id={task.id}",
                             **auth(admin_token())).json(),
                "AssignmentResponse")


# ── projects ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_project_responses_match_the_fastapi_schema():
    project = Project.objects.create(name="Проект", owner_id=11)
    client = Client()
    assert_each(client.get(f"{BASE}/projects/", **auth(admin_token())).json(),
                "ProjectResponse")
    assert_shape(client.get(f"{BASE}/projects/{project.id}/",
                            **auth(admin_token())).json(), "ProjectResponse")


# ── notifications ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_notification_responses_match_the_fastapi_schemas():
    task = Task.objects.create(key="TASK-1", summary="A")
    Notification.objects.create(recipient_id=7, actor_id=11, task=task,
                                verb="task_assigned:TASK-1",
                                target_type="task", target_id=task.id)
    client = Client()
    assert_each(client.get(f"{BASE}/notifications/", **auth()).json(),
                "NotificationResponse")

    page = client.get(f"{BASE}/notifications/history/", **auth()).json()
    assert_shape(page, "NotificationsPage")
    assert_each(page["items"], "NotificationResponse")


# ── calendar ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_calendar_responses_match_the_fastapi_schemas():
    start = timezone.now() + dt.timedelta(days=1)
    resp = post_json(Client(), f"{BASE}/calendar/", {
        "title": "Планёрка", "start_at": start.isoformat(),
        "end_at": (start + dt.timedelta(hours=1)).isoformat(),
        "participant_user_ids": [11],
    }, **auth())
    assert resp.status_code == 201
    body = resp.json()
    assert_shape(body, "CalendarEventResponse")
    assert_each(body["participants"], "CalendarEventParticipantInfo")

    event_id = body["id"]
    exc = post_json(Client(), f"{BASE}/calendar/{event_id}/exceptions/",
                    {"exception_date": "2026-04-01"}, **auth())
    assert_shape(exc.json(), "EventExceptionResponse")

    listing = Client().get(f"{BASE}/calendar/", **auth()).json()
    assert_each(listing, "CalendarEventResponse")
    assert_each(listing[0]["exceptions"], "EventExceptionResponse")


@pytest.mark.django_db
def test_production_day_response_matches_the_fastapi_schema():
    resp = Client().get(
        f"{BASE}/production-calendar/?date__gte=2026-01-01&date__lte=2026-01-05",
        **auth())
    assert_each(resp.json(), "ProductionDayResponse")


# ── gantt ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_gantt_responses_match_the_fastapi_schemas():
    task = Task.objects.create(key="TASK-1", summary="A",
                               start_date=dt.date(2026, 3, 2),
                               due_date=dt.date(2026, 3, 6), assignee_id=11)
    ResourceAllocation.objects.create(
        task=task, equipment=Equipment.objects.create(name="Кран"))

    flat = Client().get(f"{BASE}/reports/gantt", **auth()).json()
    assert_shape(flat, "ReportsGanttResponse")
    assert_each(flat["tasks"], "GanttTask")

    resource = Client().get(
        f"{BASE}/reports/resource-gantt?from=2026-03-01&to=2026-03-31",
        **auth()).json()
    assert_shape(resource, "ResourceGanttResponse")
    assert_each(resource["resources"], "ResourceRow")
    for row in resource["resources"]:
        assert_each(row["allocated_tasks"], "AllocatedTask")


# ── error envelope ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_errors_always_use_the_detail_envelope():
    """FastAPI's ``HTTPException`` renders ``{"detail": ...}``; every failure
    mode here must match, including the ones Django would otherwise render
    as HTML."""
    client = Client()
    for resp in (
        client.get(f"{BASE}/tasks/"),                              # 401
        client.get(f"{BASE}/tasks/999999/", **auth()),             # 404
        client.post(f"{BASE}/sequences/TASK/next", **auth()),      # 403
        client.get(f"{BASE}/tasks/?limit=abc", **auth()),          # 422
    ):
        assert resp.status_code in (401, 403, 404, 422)
        assert set(resp.json()) == {"detail"}, resp.content

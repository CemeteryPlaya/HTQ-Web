"""Contract tests for task links, comments, attachments, activity and
resource assignments.

Sources: ``services/task/app/api/v1/{links,comments,attachments,activity,
assignments}.py`` plus the comment/attachment endpoints on the tasks router
and ``services/link_service.py``.
"""

from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.tasks.models import (
    Equipment, LinkType, Task, TaskActivity, ResourceAllocation, TaskAttachment,
    TaskComment, TaskLink,
)

from .helpers import BASE, admin_token, auth, post_json

USER = 7


def _mk_task(**over) -> Task:
    fields = {"key": f"TASK-{Task.objects.count() + 1}", "summary": "S",
              "reporter_id": USER}
    fields.update(over)
    return Task.objects.create(**fields)


# ── links ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_create_link_writes_the_mirror_row():
    a, b = _mk_task(), _mk_task()
    resp = post_json(Client(), f"{BASE}/task-links/",
                     {"source_id": a.id, "target_id": b.id,
                      "link_type": "blocks"}, **auth())
    assert resp.status_code == 201
    body = resp.json()
    assert body["source_key"] == a.key and body["target_key"] == b.key
    # ``created_at`` is typed str in the original schema, so it is stringified
    assert isinstance(body["created_at"], str)
    assert TaskLink.objects.filter(source=b, target=a,
                                   link_type=LinkType.IS_BLOCKED_BY).exists()


@pytest.mark.django_db
def test_relates_to_link_has_no_mirror():
    a, b = _mk_task(), _mk_task()
    post_json(Client(), f"{BASE}/task-links/",
              {"source_id": a.id, "target_id": b.id,
               "link_type": "relates_to"}, **auth())
    assert TaskLink.objects.count() == 1


@pytest.mark.django_db
def test_self_link_is_rejected_by_the_schema():
    a = _mk_task()
    resp = post_json(Client(), f"{BASE}/task-links/",
                     {"source_id": a.id, "target_id": a.id,
                      "link_type": "relates_to"}, **auth())
    assert resp.status_code == 422


@pytest.mark.django_db
def test_link_to_missing_task_is_404():
    """Contract change from the FastAPI original, which answered 400.

    Both endpoints of a link are now visibility-checked, and a task the
    caller cannot see must be indistinguishable from one that does not
    exist — otherwise the status code alone tells an outsider which task
    ids are real. 404 for both is the answer that leaks nothing.
    """
    a = _mk_task()
    resp = post_json(Client(), f"{BASE}/task-links/",
                     {"source_id": a.id, "target_id": 9999,
                      "link_type": "blocks"}, **auth())
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.django_db
def test_blocking_cycle_is_rejected():
    a, b, c = _mk_task(), _mk_task(), _mk_task()
    client = Client()
    post_json(client, f"{BASE}/task-links/",
              {"source_id": a.id, "target_id": b.id, "link_type": "blocks"},
              **auth())
    post_json(client, f"{BASE}/task-links/",
              {"source_id": b.id, "target_id": c.id, "link_type": "blocks"},
              **auth())
    # c blocks a would close the chain a -> b -> c -> a
    resp = post_json(client, f"{BASE}/task-links/",
                     {"source_id": c.id, "target_id": a.id,
                      "link_type": "blocks"}, **auth())
    assert resp.status_code == 400
    assert "cycle" in resp.json()["detail"]


@pytest.mark.django_db
def test_delete_link_removes_the_mirror_too():
    a, b = _mk_task(), _mk_task()
    resp = post_json(Client(), f"{BASE}/task-links/",
                     {"source_id": a.id, "target_id": b.id,
                      "link_type": "blocks"}, **auth())
    link_id = resp.json()["id"]
    assert Client().delete(f"{BASE}/task-links/{link_id}/",
                           **auth()).status_code == 204
    assert TaskLink.objects.count() == 0


@pytest.mark.django_db
def test_delete_missing_link_is_404():
    assert Client().delete(f"{BASE}/task-links/999/", **auth()).status_code == 404


@pytest.mark.django_db
def test_links_appear_on_the_task_detail_from_both_sides():
    a, b = _mk_task(), _mk_task()
    post_json(Client(), f"{BASE}/task-links/",
              {"source_id": a.id, "target_id": b.id, "link_type": "blocks"},
              **auth())
    detail_a = Client().get(f"{BASE}/tasks/{a.id}/", **auth()).json()
    detail_b = Client().get(f"{BASE}/tasks/{b.id}/", **auth()).json()
    assert detail_a["outgoing_links"][0]["link_type"] == "blocks"
    assert detail_b["outgoing_links"][0]["link_type"] == "is_blocked_by"
    # source/target are absolute, not relative to the task being rendered
    assert detail_b["incoming_links"][0]["source_key"] == a.key
    assert detail_b["incoming_links"][0]["target_key"] == b.key


# ── comments ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_add_and_list_comments():
    task = _mk_task()
    resp = post_json(Client(), f"{BASE}/tasks/{task.id}/comments/",
                     {"body": "первый"}, **auth())
    assert resp.status_code == 201
    assert resp.json()["body"] == "первый"
    assert resp.json()["author_id"] == USER

    listing = Client().get(f"{BASE}/tasks/{task.id}/comments", **auth())
    assert listing.status_code == 200
    assert [c["body"] for c in listing.json()] == ["первый"]


@pytest.mark.django_db
def test_blank_comment_is_rejected():
    task = _mk_task()
    resp = post_json(Client(), f"{BASE}/tasks/{task.id}/comments/",
                     {"body": "   "}, **auth())
    assert resp.status_code == 422


@pytest.mark.django_db
def test_comment_on_missing_task_is_404():
    resp = post_json(Client(), f"{BASE}/tasks/999/comments/",
                     {"body": "x"}, **auth())
    assert resp.status_code == 404


@pytest.mark.django_db
def test_comment_author_name_hydrates():
    task = _mk_task()
    TaskComment.objects.create(task=task, author_id=11, body="hi")
    with patch("apps.tasks.services.hydration.users_interface.get_users_brief",
               return_value=[{"id": 11, "username": "a", "email": "a@x",
                              "is_active": True, "full_name": "Анна А"}]):
        resp = Client().get(f"{BASE}/tasks/{task.id}/comments/", **auth())
    assert resp.json()[0]["author_name"] == "Анна А"


# ── attachments ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_upload_attachment_goes_through_media_interface():
    """Р3: bytes are stored by media, not written to a local uploads dir."""
    task = _mk_task()
    upload = SimpleUploadedFile("plan.pdf", b"%PDF-1.4 data",
                                content_type="application/pdf")
    with patch("apps.media_files.interface.store_file",
               return_value={"id": "abc", "url": "/api/media/v1/files/abc"}) as store:
        resp = Client().post(f"{BASE}/tasks/{task.id}/attachments/",
                             {"file": upload}, **auth())
    assert resp.status_code == 201
    assert resp.json()["filename"] == "plan.pdf"
    kwargs = store.call_args.kwargs
    assert kwargs["scope"] == "task_attachment"
    # The restricted scope requires the calling domain to vouch, and it only
    # does so after its own soft-edit check passed.
    assert kwargs["internal_authorized"] is True
    assert kwargs["owner_id"] == USER


@pytest.mark.django_db
def test_upload_attachment_requires_soft_edit():
    task = _mk_task(reporter_id=99, supervisor_id=99)
    # Not a participant at all -> the task is not even visible -> 404.
    upload = SimpleUploadedFile("x.txt", b"x", content_type="text/plain")
    resp = Client().post(f"{BASE}/tasks/{task.id}/attachments/",
                         {"file": upload}, **auth())
    assert resp.status_code == 404


@pytest.mark.django_db
def test_upload_without_a_file_is_422():
    task = _mk_task()
    resp = Client().post(f"{BASE}/tasks/{task.id}/attachments/", {}, **auth())
    assert resp.status_code == 422


@pytest.mark.django_db
def test_list_attachments():
    task = _mk_task()
    TaskAttachment.objects.create(task=task, file_path="k", filename="a.txt",
                                  uploaded_by_id=USER)
    resp = Client().get(f"{BASE}/tasks/{task.id}/attachments", **auth())
    assert [a["filename"] for a in resp.json()] == ["a.txt"]


# ── activity ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_activity_is_newest_first():
    task = _mk_task()
    TaskActivity.objects.create(task=task, field_name="summary",
                                old_value="a", new_value="b")
    TaskActivity.objects.create(task=task, field_name="status",
                                old_value="todo", new_value="done")
    resp = Client().get(f"{BASE}/tasks/{task.id}/activity", **auth())
    assert resp.status_code == 200
    assert [row["field_name"] for row in resp.json()] == ["status", "summary"]


# ── resource assignments ────────────────────────────────────────────────

@pytest.mark.django_db
def test_create_assignment_for_an_employee():
    task = _mk_task()
    resp = post_json(Client(), f"{BASE}/assignments/",
                     {"task_id": task.id, "employee_id": 11, "role": "сварщик"},
                     **auth())
    assert resp.status_code == 201
    assert resp.json()["allocation"] == 100


@pytest.mark.django_db
def test_create_assignment_for_equipment():
    task = _mk_task()
    eq = Equipment.objects.create(name="Кран")
    resp = post_json(Client(), f"{BASE}/assignments/",
                     {"task_id": task.id, "equipment_id": eq.id}, **auth())
    assert resp.status_code == 201
    assert resp.json()["equipment_id"] == eq.id


@pytest.mark.django_db
@pytest.mark.parametrize("body", [
    {"employee_id": 11, "equipment_id": 1},   # both
    {},                                        # neither
])
def test_assignment_requires_exactly_one_resource(body):
    task = _mk_task()
    resp = post_json(Client(), f"{BASE}/assignments/",
                     {"task_id": task.id, **body}, **auth())
    assert resp.status_code == 422
    assert "exactly one" in resp.json()["detail"]


@pytest.mark.django_db
def test_list_assignments_requires_task_id():
    resp = Client().get(f"{BASE}/assignments/", **auth())
    assert resp.status_code == 422


@pytest.mark.django_db
def test_list_and_delete_assignments():
    task = _mk_task()
    row = ResourceAllocation.objects.create(task=task, employee_id=11)
    resp = Client().get(f"{BASE}/assignments/?task_id={task.id}", **auth())
    assert [a["id"] for a in resp.json()] == [row.id]

    assert Client().delete(f"{BASE}/assignments/{row.id}",
                           **auth()).status_code == 204
    assert not ResourceAllocation.objects.filter(pk=row.id).exists()


@pytest.mark.django_db
def test_assignment_for_missing_task_is_404():
    resp = post_json(Client(), f"{BASE}/assignments/",
                     {"task_id": 999, "employee_id": 11}, **auth())
    assert resp.status_code == 404

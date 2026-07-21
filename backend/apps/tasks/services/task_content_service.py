"""Comments, attachments, activity and resource assignments.

Ported from ``services/task/app/api/v1/{comments,attachments,activity,
assignments}.py`` plus the comment/attachment endpoints that live on the
main tasks router.

A note on the original's duplicates: ``comments.py`` and ``attachments.py``
each registered a second, slash-less pair of routes on the same ``/tasks``
prefix, and both were broken — ``comments.py``'s POST wrote
``TaskComment(content=...)`` against a model whose column is ``body``, and
``attachments.py``'s POST took the file id as a query parameter. The working
implementations are the ones on the tasks router, and those are what this
module ports. The **list** halves of those duplicate routers did work, so
their paths are still registered (see ``urls.py``) and answer from here.
"""

from __future__ import annotations

from django.http import Http404

from .. import schemas
from ..models import Equipment, Task, TaskActivity, TaskAssignment, TaskAttachment, TaskComment
from . import hydration


def _require_task(task_id: int) -> Task:
    task = Task.objects.filter(pk=task_id, is_deleted=False).first()
    if task is None:
        raise Http404("Task not found")
    return task


# ── comments ────────────────────────────────────────────────────────────

def list_comments(task_id: int) -> list[schemas.CommentResponse]:
    rows = list(TaskComment.objects.filter(task_id=task_id).order_by("id"))
    users = hydration.user_briefs([row.author_id for row in rows])
    return [schemas.CommentResponse.model_validate({
        "id": row.id, "task_id": row.task_id, "author_id": row.author_id,
        "author_name": hydration.user_name(users, row.author_id),
        "body": row.body, "created_at": row.created_at,
        "updated_at": row.updated_at,
    }) for row in rows]


def create_comment(task_id: int, body: str,
                   author_id: int | None) -> schemas.CommentResponse:
    _require_task(task_id)
    row = TaskComment.objects.create(task_id=task_id, author_id=author_id,
                                     body=body)
    users = hydration.user_briefs([author_id])
    return schemas.CommentResponse.model_validate({
        "id": row.id, "task_id": row.task_id, "author_id": row.author_id,
        "author_name": hydration.user_name(users, author_id),
        "body": row.body, "created_at": row.created_at,
        "updated_at": row.updated_at,
    })


# ── attachments ─────────────────────────────────────────────────────────

def list_attachments(task_id: int) -> list[schemas.AttachmentResponse]:
    rows = list(TaskAttachment.objects.filter(task_id=task_id).order_by("id"))
    users = hydration.user_briefs([row.uploaded_by_id for row in rows])
    return [schemas.AttachmentResponse.model_validate({
        "id": row.id, "task_id": row.task_id, "file_path": row.file_path,
        "filename": row.filename, "uploaded_by_id": row.uploaded_by_id,
        "uploaded_by_name": hydration.user_name(users, row.uploaded_by_id),
        "created_at": row.created_at,
    }) for row in rows]


def create_attachment(task_id: int, *, file_path: str, filename: str,
                      uploaded_by_id: int | None) -> schemas.AttachmentResponse:
    """Record an already-stored file against a task.

    The bytes are written by ``apps.media_files.interface.store_file``
    (decision Р3 — no S2S upload, no local ``uploads/`` directory like the
    original's); this only persists the resulting storage key. The view owns
    the storage call so this stays a pure DB operation.
    """
    _require_task(task_id)
    row = TaskAttachment.objects.create(task_id=task_id, file_path=file_path,
                                        filename=filename,
                                        uploaded_by_id=uploaded_by_id)
    users = hydration.user_briefs([uploaded_by_id])
    return schemas.AttachmentResponse.model_validate({
        "id": row.id, "task_id": row.task_id, "file_path": row.file_path,
        "filename": row.filename, "uploaded_by_id": row.uploaded_by_id,
        "uploaded_by_name": hydration.user_name(users, uploaded_by_id),
        "created_at": row.created_at,
    })


# ── activity ────────────────────────────────────────────────────────────

def list_activity(task_id: int) -> list[schemas.ActivityResponse]:
    rows = list(TaskActivity.objects.filter(task_id=task_id)
                .order_by("-created_at"))
    users = hydration.user_briefs([row.actor_id for row in rows])
    return [schemas.ActivityResponse.model_validate({
        "id": row.id, "task_id": row.task_id, "actor_id": row.actor_id,
        "actor_name": hydration.user_name(users, row.actor_id),
        "field_name": row.field_name, "old_value": row.old_value,
        "new_value": row.new_value, "created_at": row.created_at,
    }) for row in rows]


# ── resource assignments ────────────────────────────────────────────────

def list_assignments(task_id: int) -> list[schemas.AssignmentResponse]:
    return [_assignment_payload(row) for row in
            TaskAssignment.objects.filter(task_id=task_id).order_by("id")]


def _assignment_payload(row: TaskAssignment) -> schemas.AssignmentResponse:
    return schemas.AssignmentResponse.model_validate({
        "id": row.id, "task_id": row.task_id, "employee_id": row.employee_id,
        "equipment_id": row.equipment_id, "role": row.role,
        "allocation": row.allocation,
    })


def create_assignment(data: schemas.AssignmentCreate) -> schemas.AssignmentResponse:
    """Exactly one of employee/equipment, enforced here AND by a DB CHECK.

    The application check exists to produce the original's 422 with a useful
    message; the constraint exists so no other write path can violate it.
    """
    has_employee = data.employee_id is not None
    has_equipment = data.equipment_id is not None
    if has_employee == has_equipment:
        raise ValueError("Provide exactly one of employee_id or equipment_id")
    _require_task(data.task_id)
    if has_equipment and not Equipment.objects.filter(
            pk=data.equipment_id).exists():
        raise Http404("Equipment not found")
    row = TaskAssignment.objects.create(**data.model_dump())
    return _assignment_payload(row)


def delete_assignment(assignment_id: int) -> None:
    row = TaskAssignment.objects.filter(pk=assignment_id).first()
    if row is None:
        raise Http404("Assignment not found")
    row.delete()

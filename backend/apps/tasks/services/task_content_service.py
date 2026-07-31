"""Comments, attachments, activity and per-task work volumes.

Ported from ``services/task/app/api/v1/{comments,attachments,activity,
assignments}.py`` plus the comment/attachment endpoints that live on the
main tasks router. Назначения ресурсов, которые сюда тоже попали при
переносе, с появлением плана уехали в ``resource_service``.

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

from django.db import transaction
from django.http import Http404

from .. import schemas
from ..models import (Task, TaskActivity, TaskAttachment, TaskComment,
                      TaskVolume)
from . import block_service
from . import daily_report_service
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


# ── объёмы работ по задаче ──────────────────────────────────────────────

def list_task_volumes(task_id: int) -> list[dict]:
    """Плановые объёмы задачи вместе с фактом, посчитанным из отчётов.

    Факт приезжает свёрткой ``DailyReport``, а не колонкой рядом с планом:
    у отчёта есть дата выполнения и автор, и хранить его копию значило бы
    завести второй источник правды (см. докстринг ``TaskVolume``).
    """
    rows = list(TaskVolume.objects.filter(task_id=task_id)
                .select_related("volume_type").order_by("volume_type__name"))
    done = daily_report_service.completed_by_volume_type(task_ids=[task_id])
    return [build_task_volume(row,
                              completed=done.get((task_id, row.volume_type_id)))
            for row in rows]


def build_task_volume(row: TaskVolume, *, completed=None) -> dict:
    return {
        "id": row.id,
        "task_id": row.task_id,
        "volume_type_id": row.volume_type_id,
        "volume_type_name": row.volume_type.name,
        "unit": str(row.volume_type.unit),
        "planned_quantity": float(row.planned_quantity),
        "completed_quantity": float(completed or 0),
    }


@transaction.atomic
def set_task_volumes(task_id: int, volumes: list[dict]) -> list[dict]:
    """Заменить набор объёмов задачи целиком.

    Тот же контракт «полный список», что у ``block_service.set_block_volumes``
    и ``site_service.set_project_sites``: форма присылает всё, сервер не
    заставляет её вычислять разницу.

    Здесь ТОЛЬКО план. Факт правится ежедневными отчётами
    (``daily_report_service``) и в это тело не приходит: у него есть дата
    выполнения и автор, которых у строки объёма быть не может.
    """
    _require_task(task_id)
    wanted = {v["volume_type_id"]: v for v in volumes}
    # ValueError -> 422. Явно, а не через FK: нарушение внешнего ключа
    # поднимается на коммите, уже за пределами вьюхи (см. докстринг
    # ``block_service.require_volume_types``).
    block_service.require_volume_types(wanted)

    TaskVolume.objects.filter(task_id=task_id).exclude(
        volume_type_id__in=wanted).delete()
    for type_id, payload in wanted.items():
        TaskVolume.objects.update_or_create(
            task_id=task_id, volume_type_id=type_id,
            defaults={"planned_quantity": payload["planned_quantity"]},
        )
    return list_task_volumes(task_id)


# Назначения ресурсов переехали в ``resource_service``: вместе с планом
# (``ResourceRequirement``) это самостоятельный сюжет, а здесь они лежали за
# компанию с комментариями и вложениями.

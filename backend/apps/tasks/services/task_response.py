"""Response builders for task payloads.

The FastAPI original got its denormalised fields for free: pydantic's
``from_attributes`` read ``@property`` accessors on the SQLAlchemy model
(``assignee_name``, ``department_name``, ``task_type``…) which walked
eager-loaded relationships into the replica tables. With the replicas gone
(Р2) those names come from a neighbouring app, so they cannot be model
properties without an N+1 across an app boundary — they are assembled here
instead, after ONE batched hydration pass over the whole result set.

The invariant to preserve when editing: collect every user id and department
id in the batch **first**, hydrate once, then build. A ``hydration.*`` call
inside a per-task loop is the bug this module exists to prevent.
"""

from __future__ import annotations

from .. import schemas
from ..models import Task
from . import contractor_service
from . import hydration
from . import task_content_service


def _iter_user_ids(tasks: list[Task]):
    for task in tasks:
        yield task.reporter_id
        yield task.assignee_id
        yield task.supervisor_id
        for row in task.assignees.all():
            yield row.user_id
        # delegates/watchers are only prefetched for detail responses; a
        # list response never touches them, so this stays cheap.
        for row in task.delegates.all():
            yield row.user_id
            yield row.granted_by_id
        for row in task.watchers.all():
            yield row.user_id
        for row in task.comments.all():
            yield row.author_id
        for row in task.attachments.all():
            yield row.uploaded_by_id
        for row in task.activities.all():
            yield row.actor_id


def _iter_department_ids(tasks: list[Task]):
    for task in tasks:
        yield task.department_id
        for link in task.department_links.all():
            yield link.department_id


class _Ctx:
    """Hydration maps for one batch of tasks."""

    __slots__ = ("users", "departments", "contractors")

    def __init__(self, tasks: list[Task], *, deep: bool):
        self.users = hydration.user_briefs(
            _iter_user_ids(tasks) if deep else _iter_list_user_ids(tasks)
        )
        self.departments = hydration.department_briefs(_iter_department_ids(tasks))
        # Эффективный партнёр — тоже батч и тоже здесь, по тому же
        # инварианту модуля: одна волна на весь список, а не запрос на
        # задачу. Подъём по дереву (задача → роудмап → площадка → проект)
        # живёт в contractor_service, ему тут не место.
        self.contractors = contractor_service.effective_contractors(tasks)

    def name(self, user_id):
        return hydration.user_name(self.users, user_id)

    def avatar(self, user_id):
        return hydration.user_avatar(self.users, user_id)

    def dept(self, department_id):
        return hydration.department_name(self.departments, department_id)

    def effective_contractor(self, task_id):
        return self.contractors.get(task_id)


def _iter_list_user_ids(tasks: list[Task]):
    """Narrower id sweep for list responses — no comments/activities/etc.

    A list payload has no nested comment or activity blocks, so touching
    those relations would issue queries for data that is never rendered.
    """
    for task in tasks:
        yield task.reporter_id
        yield task.assignee_id
        yield task.supervisor_id
        for row in task.assignees.all():
            yield row.user_id


def _common_fields(task: Task, ctx: _Ctx) -> dict:
    """Fields shared by the list and detail shapes."""
    type_row = task.task_type
    dept_ids = [link.department_id for link in task.department_links.all()]
    return {
        "id": task.id,
        "key": task.key,
        "summary": task.summary,
        "task_type_id": task.task_type_id,
        # Back-compat: the slug, with the original's "task" fallback for an
        # unclassified row.
        "task_type": type_row.slug if type_row else "task",
        "task_type_name": type_row.name if type_row else None,
        "task_type_color": type_row.color if type_row else None,
        "priority": task.priority,
        "status": task.status,
        "progress_percent": task.progress_percent,
        "reporter_id": task.reporter_id,
        "reporter_name": ctx.name(task.reporter_id),
        "assignee_id": task.assignee_id,
        "assignee_name": ctx.name(task.assignee_id),
        "supervisor_id": task.supervisor_id,
        "supervisor_name": ctx.name(task.supervisor_id),
        "department_id": task.department_id,
        "department_name": ctx.dept(task.department_id),
        "department_ids": dept_ids,
        "departments": [
            {"id": did, "name": ctx.dept(did)}
            for did in dept_ids if ctx.dept(did) is not None
        ],
        "project_id": task.project_id,
        "project_name": task.project.name if task.project else None,
        "project_color": task.project.color if task.project else None,
        # Роудмап — джойн, как проект: модель этого же аппа.
        "roadmap_id": task.roadmap_id,
        "roadmap_name": task.roadmap.name if task.roadmap else None,
        "roadmap_color": task.roadmap.color if task.roadmap else None,
        # Объект резолвится джойном (``select_related("site")`` в
        # task_service), а не через hydration: Site — модель этого же аппа.
        "site_id": task.site_id,
        "site_name": task.site.name if task.site else None,
        "site_color": task.site.color if task.site else None,
        # Блок — тоже джойн (``select_related("site_block")``). Цвета у него
        # нет: чип блока рисуется цветом своего объекта, иначе на одной
        # карточке оказались бы два несвязанных цветовых кода.
        "site_block_id": task.site_block_id,
        "site_block_name": (task.site_block.name if task.site_block else None),
        # Партнёр — модель этого же аппа, поэтому джойн, а не hydration.
        "contractor_id": task.contractor_id,
        "contractor_name": task.contractor.name if task.contractor else None,
        # Кто РЕАЛЬНО выполняет: своё значение или унаследованное с
        # роудмапа/площадки/проекта. Оба поля рядом намеренно — «унаследован»
        # и «назначен лично» это разные факты, и UI их различает.
        "effective_contractor": ctx.effective_contractor(task.id),
        "contractor_worker_id": task.contractor_worker_id,
        "contractor_worker_name": (task.contractor_worker.full_name
                                   if task.contractor_worker else None),
        "parent_id": task.parent_id,
        "parent_key": task.parent.key if task.parent else None,
        "assignees": [
            {"user_id": row.user_id, "role": row.role,
             "name": ctx.name(row.user_id), "avatar_url": ctx.avatar(row.user_id)}
            for row in task.assignees.all()
        ],
        "labels": [{"id": lbl.id, "name": lbl.name, "color": lbl.color}
                   for lbl in task.labels.all()],
        "due_date": task.due_date,
        "start_date": task.start_date,
        # The original computed effective_* / date_warnings nowhere — the
        # fields exist on the schema and always defaulted. Kept identical
        # rather than inventing semantics the frontend has never seen.
        "effective_start_date": task.start_date,
        "effective_due_date": task.due_date,
        "date_warnings": [],
        "completed_at": task.completed_at,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def _list_payload(task: Task, ctx: _Ctx) -> dict:
    payload = _common_fields(task, ctx)
    # ``len(prefetched)`` rather than ``.count()``: a COUNT query per task
    # would be an N+1, and this counts the same set the original did
    # (``len(self.subtasks)`` over an unfiltered relationship — soft-deleted
    # subtasks included).
    payload["subtask_count"] = len(task.subtasks.all())
    return payload


def build_list(tasks: list[Task]) -> list[schemas.TaskListResponse]:
    ctx = _Ctx(tasks, deep=False)
    return [schemas.TaskListResponse.model_validate(_list_payload(t, ctx))
            for t in tasks]


def _link_payload(link) -> dict:
    """``source_*``/``target_*`` are absolute, not relative to the task being
    rendered — an incoming link reports the same source and target as the
    outgoing row on the other task. Both sides are prefetched by
    ``task_service.get_task`` so neither attribute access queries."""
    return {
        "id": link.id,
        "source_id": link.source_id,
        "target_id": link.target_id,
        "link_type": link.link_type,
        "created_by_id": link.created_by_id,
        "source_key": link.source.key,
        "source_summary": link.source.summary,
        "target_key": link.target.key,
        "target_summary": link.target.summary,
        # ``str``, not isoformat — the original's schema types this as ``str``
        # so pydantic stringified the datetime. See schemas.LinkResponse.
        "created_at": str(link.created_at),
    }


def build_detail(task: Task) -> schemas.TaskDetailResponse:
    ctx = _Ctx([task], deep=True)
    payload = _common_fields(task, ctx)
    payload.update({
        "description": task.description,
        "delegates": [
            {"user_id": row.user_id, "name": ctx.name(row.user_id),
             "avatar_url": ctx.avatar(row.user_id),
             "granted_by_id": row.granted_by_id,
             "granted_by_name": ctx.name(row.granted_by_id),
             "granted_at": row.granted_at}
            for row in task.delegates.all()
        ],
        "watchers": [
            {"user_id": row.user_id, "name": ctx.name(row.user_id),
             "avatar_url": ctx.avatar(row.user_id)}
            for row in task.watchers.all()
        ],
        "label_ids": [lbl.id for lbl in task.labels.all()],
        "comments": [
            {"id": row.id, "task_id": row.task_id, "author_id": row.author_id,
             "author_name": ctx.name(row.author_id), "body": row.body,
             "created_at": row.created_at, "updated_at": row.updated_at}
            for row in task.comments.all()
        ],
        "attachments": [
            {"id": row.id, "task_id": row.task_id, "file_path": row.file_path,
             "filename": row.filename, "uploaded_by_id": row.uploaded_by_id,
             "uploaded_by_name": ctx.name(row.uploaded_by_id),
             "created_at": row.created_at}
            for row in task.attachments.all()
        ],
        "activities": [
            {"id": row.id, "task_id": row.task_id, "actor_id": row.actor_id,
             "actor_name": ctx.name(row.actor_id), "field_name": row.field_name,
             "old_value": row.old_value, "new_value": row.new_value,
             "created_at": row.created_at}
            for row in task.activities.all()
        ],
        "outgoing_links": [_link_payload(link)
                           for link in task.outgoing_links.all()],
        "incoming_links": [_link_payload(link)
                           for link in task.incoming_links.all()],
        # Факт по каждому виду работ — свёртка отчётов задачи; в самой
        # строке объёма его нет (см. докстринг TaskVolume).
        "volumes": task_content_service.list_task_volumes(task.id),
        "subtasks": [],
    })
    subtasks = list(task.subtasks.filter(is_deleted=False)
                    # ``site``/``site_block`` тоже: ``_common_fields`` печатает
                    # их имена, и без джойна каждая подзадача стоила бы двух
                    # лишних запросов.
                    .select_related("task_type", "project", "roadmap", "site",
                                    "site_block", "parent")
                    .prefetch_related("labels", "assignees", "department_links",
                                      "subtasks"))
    payload["subtasks"] = [s.model_dump() for s in build_list(subtasks)]
    return schemas.TaskDetailResponse.model_validate(payload)

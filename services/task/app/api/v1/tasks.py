"""Task API endpoints — Jira + SharePoint shape.

Role-based permissions (see TaskService.can_user_edit / can_user_progress):

- Full edit (any field)               : elevated / reporter / supervisor / delegate
- Soft edit (status, progress, comments): + any assignee (primary or collaborator)
- Read                                 : visibility filter in repository
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.auth.dependencies import TokenPayload, get_current_user
from app.models.task import Task as TaskModel
from app.services.task_service import TaskService
from app.schemas.task import (
    AssigneesUpdate,
    DelegateCreate,
    ProgressUpdate,
    SupervisorUpdate,
    TaskCreate,
    TaskUpdate,
    TaskListResponse,
    TaskDetailResponse,
    TaskStats,
    Status,
)
from app.schemas.comment import CommentCreate, CommentResponse
from app.schemas.attachment import AttachmentResponse
from app.repositories.task_repo import TaskRepository

router = APIRouter(prefix="/tasks", tags=["tasks"])


async def _employee_scope(repo: TaskRepository, current_user: TokenPayload) -> tuple[str, int | None]:
    if current_user.is_elevated:
        return "all", None
    return "employee", await repo.get_user_department_id(current_user.user_id)


async def _report_scope(repo: TaskRepository, current_user: TokenPayload) -> tuple[str, int | None]:
    if current_user.is_elevated:
        return "all", None
    return "reports", await repo.get_user_department_id(current_user.user_id)


async def _load_task_for_action(
    service: TaskService,
    task_id: int,
    current_user: TokenPayload,
) -> TaskModel:
    """Load a task and enforce visibility (404 otherwise).

    Does NOT enforce write permission — caller decides whether the user
    needs full edit, soft edit, or just visibility.
    """
    if current_user.is_elevated:
        task = await service.task_repo.get_with_relations(task_id)
    else:
        department_id = await service.task_repo.get_user_department_id(
            current_user.user_id
        )
        task = await service.task_repo.get_with_relations(
            task_id,
            visibility="employee",
            visibility_user_id=current_user.user_id,
            visibility_department_id=department_id,
        )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def _require_full_edit(
    service: TaskService, task: TaskModel, current_user: TokenPayload
) -> None:
    if not service.can_user_edit(task, current_user.user_id, current_user.is_elevated):
        raise HTTPException(
            status_code=403,
            detail="Only supervisor, delegate, reporter or admin can edit this task",
        )


def _require_soft_edit(
    service: TaskService, task: TaskModel, current_user: TokenPayload
) -> None:
    if not service.can_user_progress(
        task, current_user.user_id, current_user.is_elevated
    ):
        raise HTTPException(
            status_code=403,
            detail="Only assignees, supervisor, delegate, reporter or admin can change status/progress",
        )


@router.get("/", response_model=list[TaskListResponse])
async def list_tasks(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: Status | None = None,
    priority: str | None = None,
    task_type: str | None = None,
    task_type_id: int | None = None,
    assignee_id: int | None = None,
    reporter_id: int | None = None,
    supervisor_id: int | None = None,
    department_id: int | None = None,
    project_id: int | None = None,
    standalone: bool = Query(
        False,
        description="If true, return only tasks without a project (project_id IS NULL).",
    ),
    parent_id: int | None = None,
    label_id: int | None = None,
    search: str | None = None,
):
    """List tasks with filtering and pagination."""
    repo = TaskRepository(db)
    visibility, visibility_department_id = await _employee_scope(repo, current_user)

    tasks = await repo.get_list(
        offset=offset,
        limit=limit,
        status=status,
        priority=priority,
        task_type=task_type,
        task_type_id=task_type_id,
        assignee_id=assignee_id,
        reporter_id=reporter_id,
        supervisor_id=supervisor_id,
        department_id=department_id,
        project_id=project_id,
        project_unset=standalone,
        parent_id=parent_id,
        label_id=label_id,
        search=search,
        visibility=visibility,
        visibility_user_id=current_user.user_id,
        visibility_department_id=visibility_department_id,
    )
    return tasks


@router.get("/stats/", response_model=TaskStats)
async def get_task_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
    department_id: int | None = None,
    project_id: int | None = None,
):
    """Get task statistics."""
    repo = TaskRepository(db)
    visibility, visibility_department_id = await _report_scope(repo, current_user)
    stats = await repo.get_stats(
        department_id=department_id,
        project_id=project_id,
        visibility=visibility,
        visibility_user_id=current_user.user_id,
        visibility_department_id=visibility_department_id,
    )
    return stats


@router.get("/{task_id}/", response_model=TaskDetailResponse)
async def get_task(
    task_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """Get task details with all relations."""
    service = TaskService(db)
    return await _load_task_for_action(service, task_id, current_user)


@router.post("/", response_model=TaskDetailResponse, status_code=201)
async def create_task(
    data: TaskCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """Create a new task."""
    service = TaskService(db)
    try:
        task = await service.create_task(data, user_id=current_user.user_id)
        await db.commit()
        return await service.task_repo.get_with_relations(task.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{task_id}/", response_model=TaskDetailResponse)
async def update_task(
    task_id: int,
    data: TaskUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """Update task.

    Permission rules:
    - Status / progress alone → soft-edit role (assignee allowed).
    - Any other field → full-edit role.
    """
    service = TaskService(db)
    task = await _load_task_for_action(service, task_id, current_user)

    fields = set(data.model_dump(exclude_unset=True).keys())
    soft_only = fields.issubset({"status", "progress_percent"})
    if soft_only:
        _require_soft_edit(service, task, current_user)
    else:
        _require_full_edit(service, task, current_user)

    try:
        prev_status = task.status
        prev_assignee_id = task.assignee_id

        await service.update_task(task_id, data, user_id=current_user.user_id)
        await db.commit()
        full = await service.task_repo.get_with_relations(task_id)

        # Publish status-change event so the messenger "Задачи" bot can
        # DM the primary assignee. Skip when no status change or no
        # recipient.
        new_status = full.status if full else None
        if new_status and prev_status and new_status != prev_status:
            recipient = full.assignee_id or prev_assignee_id
            if recipient:
                try:
                    import json as _json
                    import redis.asyncio as _aioredis

                    from app.core.settings import settings as _settings
                    from app.models.user_replica import User as _UserReplica

                    actor_name = ""
                    actor_row = await db.execute(
                        select(_UserReplica).where(_UserReplica.id == current_user.user_id)
                    )
                    actor = actor_row.scalar_one_or_none()
                    if actor:
                        actor_name = (
                            f"{actor.first_name} {actor.last_name}".strip()
                            or actor.username
                        )
                    client = _aioredis.Redis.from_url(_settings.redis_url)
                    try:
                        await client.publish(
                            "notify.task_status_changed",
                            _json.dumps(
                                {
                                    "user_id": int(recipient),
                                    "task_id": full.id,
                                    "task_key": full.key,
                                    "summary": full.summary,
                                    "from_status": str(prev_status),
                                    "to_status": str(new_status),
                                    "actor_name": actor_name,
                                },
                                default=str,
                            ),
                        )
                    finally:
                        await client.aclose()
                except Exception:  # noqa: BLE001
                    pass
        return full
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{task_id}/", status_code=204)
async def delete_task(
    task_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """Soft delete a task."""
    service = TaskService(db)
    task = await _load_task_for_action(service, task_id, current_user)
    _require_full_edit(service, task, current_user)
    try:
        await service.delete_task(task_id)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{task_id}/transitions/")
async def get_task_transitions(
    task_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """Get available status transitions for a task."""
    service = TaskService(db)
    try:
        transitions = await service.get_available_transitions(task_id)
        return [{"status": s.value} for s in transitions]
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# -------------------------------------------------------------------- #
# Multi-assignee, supervisor, delegates, watchers, progress             #
# -------------------------------------------------------------------- #


@router.patch("/{task_id}/assignees/", response_model=TaskDetailResponse)
async def update_assignees(
    task_id: int,
    data: AssigneesUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """Replace the task's assignee crew (primary + collaborators)."""
    service = TaskService(db)
    task = await _load_task_for_action(service, task_id, current_user)
    _require_full_edit(service, task, current_user)
    try:
        await service.replace_assignees(
            task_id, data.assignees, actor_id=current_user.user_id
        )
        await db.commit()
        return await service.task_repo.get_with_relations(task_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{task_id}/supervisor/", response_model=TaskDetailResponse)
async def update_supervisor(
    task_id: int,
    data: SupervisorUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """Set or clear the task supervisor.

    The current supervisor or reporter can transfer ownership. After
    they do, the new supervisor inherits the edit privileges.
    """
    service = TaskService(db)
    task = await _load_task_for_action(service, task_id, current_user)
    _require_full_edit(service, task, current_user)
    try:
        await service.set_supervisor(
            task_id, data.user_id, actor_id=current_user.user_id
        )
        await db.commit()
        return await service.task_repo.get_with_relations(task_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{task_id}/delegates/", response_model=TaskDetailResponse, status_code=201)
async def add_delegate(
    task_id: int,
    data: DelegateCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """Grant a user delegate (deputy) rights on a task.

    Only the supervisor (or elevated admin) may delegate. Reporters and
    existing delegates cannot — that would let delegates self-propagate
    rights.
    """
    service = TaskService(db)
    task = await _load_task_for_action(service, task_id, current_user)

    if not current_user.is_elevated and task.supervisor_id != current_user.user_id:
        raise HTTPException(
            status_code=403,
            detail="Only the supervisor (or admin) can add delegates",
        )

    try:
        await service.add_delegate(
            task_id, data.user_id, granted_by=current_user.user_id
        )
        await db.commit()
        return await service.task_repo.get_with_relations(task_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{task_id}/delegates/{user_id}/", response_model=TaskDetailResponse)
async def remove_delegate(
    task_id: int,
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """Revoke a delegate.

    The supervisor can revoke any delegate. A delegate may also remove
    themself (give up the deputy seat).
    """
    service = TaskService(db)
    task = await _load_task_for_action(service, task_id, current_user)

    is_self = user_id == current_user.user_id
    is_supervisor = task.supervisor_id == current_user.user_id
    if not (current_user.is_elevated or is_supervisor or is_self):
        raise HTTPException(
            status_code=403, detail="Cannot revoke another user's delegate seat"
        )

    try:
        await service.remove_delegate(
            task_id, user_id, actor_id=current_user.user_id
        )
        await db.commit()
        return await service.task_repo.get_with_relations(task_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{task_id}/watch/", response_model=TaskDetailResponse, status_code=201)
async def watch_task(
    task_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """Subscribe the current user to a task (self-only)."""
    service = TaskService(db)
    await _load_task_for_action(service, task_id, current_user)
    await service.add_watcher(task_id, current_user.user_id)
    await db.commit()
    return await service.task_repo.get_with_relations(task_id)


@router.delete("/{task_id}/watch/", response_model=TaskDetailResponse)
async def unwatch_task(
    task_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """Unsubscribe the current user from a task."""
    service = TaskService(db)
    await _load_task_for_action(service, task_id, current_user)
    await service.remove_watcher(task_id, current_user.user_id)
    await db.commit()
    return await service.task_repo.get_with_relations(task_id)


@router.patch("/{task_id}/progress/", response_model=TaskDetailResponse)
async def update_progress(
    task_id: int,
    data: ProgressUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """Update progress percent (0..100).

    Any assignee, supervisor, delegate, reporter or admin can change it.
    """
    service = TaskService(db)
    task = await _load_task_for_action(service, task_id, current_user)
    _require_soft_edit(service, task, current_user)
    try:
        await service.set_progress(
            task_id, data.percent, actor_id=current_user.user_id
        )
        await db.commit()
        return await service.task_repo.get_with_relations(task_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# -------------------------------------------------------------------- #
# Comments / attachments                                                #
# -------------------------------------------------------------------- #


@router.post("/{task_id}/comments/", response_model=CommentResponse, status_code=201)
async def add_comment(
    task_id: int,
    data: CommentCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """Add a comment to a task."""
    from app.repositories import CommentRepository

    task = await TaskRepository(db).get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    repo = CommentRepository(db)
    comment = await repo.create(
        task_id=task_id,
        author_id=current_user.user_id,
        body=data.body,
    )
    await db.commit()
    return comment


@router.post("/{task_id}/attachments/", response_model=AttachmentResponse, status_code=201)
async def add_attachment(
    task_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
    file: UploadFile = File(...),
):
    """Add an attachment to a task."""
    from app.repositories import AttachmentRepository
    from pathlib import Path

    task = await TaskRepository(db).get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    upload_dir = Path("uploads/task_attachments")
    upload_dir.mkdir(parents=True, exist_ok=True)

    filename = file.filename or "unnamed"
    file_path = upload_dir / f"{task_id}_{filename}"

    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    repo = AttachmentRepository(db)
    attachment = await repo.create(
        task_id=task_id,
        file_path=str(file_path),
        filename=filename,
        uploaded_by_id=current_user.user_id,
    )
    await db.commit()
    return attachment

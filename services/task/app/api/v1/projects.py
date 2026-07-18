"""Project API endpoints — Roadmap-level grouping of tasks."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.auth.dependencies import TokenPayload, get_current_user
from app.repositories import ProjectRepository
from app.repositories.task_repo import TaskRepository
from app.schemas.project import (
    ProjectCreate,
    ProjectUpdate,
    ProjectResponse,
)

router = APIRouter(prefix="/projects", tags=["projects"])


async def _project_scope(
    repo: ProjectRepository,
    current_user: TokenPayload,
) -> tuple[bool, int | None]:
    if current_user.is_elevated:
        return False, None
    return True, await repo.get_user_department_id(current_user.user_id)


@router.get("/", response_model=list[ProjectResponse])
async def list_projects(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """List visible projects."""
    repo = ProjectRepository(db)
    employee_scope, department_id = await _project_scope(repo, current_user)
    projects = await repo.get_visible_projects(
        employee_scope=employee_scope,
        employee_department_id=department_id,
    )
    return projects


@router.get("/{project_id}/", response_model=ProjectResponse)
async def get_project(
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """Get project details."""
    repo = ProjectRepository(db)
    employee_scope, department_id = await _project_scope(repo, current_user)
    project = await repo.get_visible_by_id(
        project_id,
        employee_scope=employee_scope,
        employee_department_id=department_id,
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("/", response_model=ProjectResponse, status_code=201)
async def create_project(
    data: ProjectCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """Create a new project."""
    repo = ProjectRepository(db)
    payload = data.model_dump()
    # Default owner to creator if not specified.
    if payload.get("owner_id") is None:
        payload["owner_id"] = current_user.user_id
    project = await repo.create(**payload)
    await db.commit()
    return project


@router.patch("/{project_id}/", response_model=ProjectResponse)
async def update_project(
    project_id: int,
    data: ProjectUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """Update a project."""
    repo = ProjectRepository(db)
    project = await repo.get_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    await repo.update(project, **data.model_dump(exclude_unset=True))
    await db.commit()
    return project


@router.delete("/{project_id}/", status_code=204)
async def delete_project(
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """Delete a project. Tasks lose their project link (FK ON DELETE SET NULL)."""
    repo = ProjectRepository(db)
    project = await repo.get_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    await repo.delete(project)
    await db.commit()


@router.get("/{project_id}/tasks/")
async def get_project_tasks(
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """Get all tasks under a project (flat list — UI builds the tree)."""
    project_repo = ProjectRepository(db)
    employee_scope, department_id = await _project_scope(project_repo, current_user)
    project = await project_repo.get_visible_by_id(
        project_id,
        employee_scope=employee_scope,
        employee_department_id=department_id,
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    repo = TaskRepository(db)
    tasks = await repo.get_list(
        project_id=project_id,
        department_id=department_id if employee_scope else None,
        limit=1000,
    )
    return tasks

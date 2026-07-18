"""Project + membership endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TokenPayload, get_current_user, require_admin
from app.auth.permissions import ensure_can_manage_project
from app.db import get_db_session
from app.repositories.project_repo import ProjectRepository
from app.schemas.member import MemberAdd, MemberResponse
from app.schemas.project import ProjectCreate, ProjectResponse, ProjectUpdate
from app.services.user_replica import ensure_user_replica

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/", response_model=list[ProjectResponse])
async def list_projects(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
):
    return await ProjectRepository(db).list_ordered()


@router.post("/", response_model=ProjectResponse, status_code=201)
async def create_project(
    data: ProjectCreate,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[TokenPayload, Depends(require_admin)],
):
    repo = ProjectRepository(db)
    payload = data.model_dump()
    if payload.get("owner_id") is None:
        payload["owner_id"] = current_user.user_id
    # The owner_id FK points at the request_users replica, which may not yet
    # hold the acting user (bootstrap not run, or upsert event not propagated).
    # Self-heal from the token so the insert can't hit a FK violation.
    if payload.get("owner_id") == current_user.user_id:
        await ensure_user_replica(db, current_user)
    return await repo.create(**payload)


@router.get("/{project_id}/", response_model=ProjectResponse)
async def get_project(
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
):
    project = await ProjectRepository(db).get_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.patch("/{project_id}/", response_model=ProjectResponse)
async def update_project(
    project_id: int,
    data: ProjectUpdate,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
):
    repo = ProjectRepository(db)
    project = await repo.get_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await ensure_can_manage_project(repo, project_id, current_user)
    await repo.update(project, **data.model_dump(exclude_unset=True))
    # updated_at uses onupdate=now(); refresh so the server value is loaded
    # inside the async context (avoids a lazy IO during response serialization).
    await db.refresh(project)
    return project


@router.delete("/{project_id}/", status_code=204)
async def delete_project(
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[TokenPayload, Depends(require_admin)],
):
    repo = ProjectRepository(db)
    project = await repo.get_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await repo.delete(project)


@router.get("/{project_id}/members/", response_model=list[MemberResponse])
async def list_members(
    project_id: int,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
):
    return await ProjectRepository(db).list_members(project_id)


@router.post("/{project_id}/members/", response_model=MemberResponse, status_code=201)
async def add_member(
    project_id: int,
    data: MemberAdd,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
):
    repo = ProjectRepository(db)
    project = await repo.get_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await ensure_can_manage_project(repo, project_id, current_user)
    return await repo.add_member(project_id, data.user_id, data.role, granted_by=current_user.user_id)


@router.delete("/{project_id}/members/{user_id}/", status_code=204)
async def remove_member(
    project_id: int,
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
):
    repo = ProjectRepository(db)
    await ensure_can_manage_project(repo, project_id, current_user)
    member = await repo.get_member(project_id, user_id)
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    await repo.remove_member(member)

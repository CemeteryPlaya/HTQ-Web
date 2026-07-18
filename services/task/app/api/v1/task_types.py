"""Task type registry endpoints.

Allows users to add custom task types beyond the five seeded system
rows. Slug uniqueness is enforced by the DB.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.auth.dependencies import TokenPayload, get_current_user
from app.repositories import TaskTypeRepository
from app.schemas.task_type import (
    TaskTypeCreate,
    TaskTypeUpdate,
    TaskTypeResponse,
)

router = APIRouter(prefix="/task-types", tags=["task-types"])


@router.get("/", response_model=list[TaskTypeResponse])
async def list_task_types(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """List all task types (system + user-defined)."""
    repo = TaskTypeRepository(db)
    return await repo.list_all()


@router.post("/", response_model=TaskTypeResponse, status_code=201)
async def create_task_type(
    data: TaskTypeCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """Create a new task type.

    The slug identifier is auto-generated from the name (transliterating
    Cyrillic) when not supplied, and de-duplicated automatically.
    """
    repo = TaskTypeRepository(db)
    slug = data.slug or await repo.generate_unique_slug(data.name)
    existing = await repo.get_by_slug(slug)
    if existing:
        raise HTTPException(
            status_code=409, detail=f"Task type with slug '{slug}' already exists"
        )
    try:
        row = await repo.create(
            slug=slug,
            name=data.name,
            color=data.color,
            icon=data.icon,
            is_system=False,
        )
        await db.commit()
        return row
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{type_id}/", response_model=TaskTypeResponse)
async def update_task_type(
    type_id: int,
    data: TaskTypeUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """Update a task type. System rows can have name/color/icon changed
    but their slug is immutable (enforced by the schema not allowing it)."""
    repo = TaskTypeRepository(db)
    row = await repo.get_by_id(type_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task type not found")
    await repo.update(row, **data.model_dump(exclude_unset=True))
    await db.commit()
    return row


@router.delete("/{type_id}/", status_code=204)
async def delete_task_type(
    type_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    """Delete a user-defined task type. System rows are protected."""
    repo = TaskTypeRepository(db)
    row = await repo.get_by_id(type_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task type not found")
    if row.is_system:
        raise HTTPException(
            status_code=403,
            detail="System task types cannot be deleted",
        )
    await repo.delete(row)
    await db.commit()

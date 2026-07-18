"""Label API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.auth.dependencies import get_current_user
from app.repositories import LabelRepository
from app.schemas.label import LabelCreate, LabelUpdate, LabelResponse

router = APIRouter(prefix="/labels", tags=["labels"])


@router.get("/", response_model=list[LabelResponse])
async def list_labels(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: dict = Depends(get_current_user),
):
    """List all labels."""
    repo = LabelRepository(db)
    labels = await repo.get_all()
    return labels


@router.post("/", response_model=LabelResponse, status_code=201)
async def create_label(
    data: LabelCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: dict = Depends(get_current_user),
):
    """Create a new label."""
    repo = LabelRepository(db)
    label = await repo.create(**data.model_dump())
    await db.commit()
    return label


@router.patch("/{label_id}/", response_model=LabelResponse)
async def update_label(
    label_id: int,
    data: LabelUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: dict = Depends(get_current_user),
):
    """Update a label."""
    repo = LabelRepository(db)
    label = await repo.get_by_id(label_id)
    if not label:
        raise HTTPException(status_code=404, detail="Label not found")
    
    await repo.update(label, **data.model_dump(exclude_unset=True))
    await db.commit()
    return label


@router.delete("/{label_id}/", status_code=204)
async def delete_label(
    label_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: dict = Depends(get_current_user),
):
    """Delete a label."""
    repo = LabelRepository(db)
    label = await repo.get_by_id(label_id)
    if not label:
        raise HTTPException(status_code=404, detail="Label not found")
    
    await repo.delete(label)
    await db.commit()

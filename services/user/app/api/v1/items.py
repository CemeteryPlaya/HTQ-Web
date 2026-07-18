"""User-owned items — personal notes/drafts.

Mirrors backend/mainView/views.py:ItemViewSet. Each user only sees their own.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TokenPayload, get_current_user
from app.db import get_db_session
from app.models.item import Item


router = APIRouter(prefix="/api/users/v1/items", tags=["items"])


class ItemResponse(BaseModel):
    id: int
    title: str
    description: str
    owner_id: int
    created_at: str


class ItemCreateRequest(BaseModel):
    title: str
    description: str = ""


class ItemUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None


def _to_response(item: Item) -> ItemResponse:
    return ItemResponse(
        id=item.id,
        title=item.title,
        description=item.description,
        owner_id=item.owner_id,
        created_at=item.created_at.isoformat(),
    )


@router.get("/", response_model=list[ItemResponse])
async def list_items(
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    result = await db.execute(
        select(Item)
        .where(Item.owner_id == current_user.user_id)
        .order_by(Item.created_at.desc())
    )
    return [_to_response(i) for i in result.scalars().all()]


@router.post("/", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(
    request: ItemCreateRequest,
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    item = Item(
        title=request.title,
        description=request.description,
        owner_id=current_user.user_id,
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return _to_response(item)


@router.get("/{item_id}/", response_model=ItemResponse)
async def get_item(
    item_id: int,
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    result = await db.execute(
        select(Item).where(Item.id == item_id, Item.owner_id == current_user.user_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return _to_response(item)


@router.patch("/{item_id}/", response_model=ItemResponse)
async def update_item(
    item_id: int,
    request: ItemUpdateRequest,
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    result = await db.execute(
        select(Item).where(Item.id == item_id, Item.owner_id == current_user.user_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    update_data = request.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(item, field, value)

    await db.commit()
    await db.refresh(item)
    return _to_response(item)


@router.delete("/{item_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: int,
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    result = await db.execute(
        select(Item).where(Item.id == item_id, Item.owner_id == current_user.user_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    await db.delete(item)
    await db.commit()

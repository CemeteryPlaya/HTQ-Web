"""Task link API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.auth.dependencies import get_current_user
from app.services.link_service import LinkService
from app.schemas.link import LinkCreate, LinkResponse

router = APIRouter(prefix="/task-links", tags=["task-links"])


@router.post("/", response_model=LinkResponse, status_code=201)
async def create_link(
    data: LinkCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: dict = Depends(get_current_user),
):
    """Create a task link."""
    service = LinkService(db)
    try:
        link = await service.create_link(
            source_id=data.source_id,
            target_id=data.target_id,
            link_type=data.link_type,
            user_id=current_user.user_id,
        )
        await db.commit()
        return link
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{link_id}/", status_code=204)
async def delete_link(
    link_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: dict = Depends(get_current_user),
):
    """Delete a task link."""
    service = LinkService(db)
    try:
        await service.delete_link(link_id)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

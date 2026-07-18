from typing import Annotated
import uuid
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db_session
from app.auth.dependencies import TokenPayload, get_current_user
from app.models import TaskAttachment

router = APIRouter(prefix="/tasks", tags=["attachments"])

@router.get("/{task_id}/attachments")
async def list_attachments(
    task_id: int,
    session: Annotated[AsyncSession, Depends(get_db_session)],
):
    result = await session.execute(select(TaskAttachment).where(TaskAttachment.task_id == task_id))
    return result.scalars().all()

@router.post("/{task_id}/attachments")
async def upload_attachment(
    task_id: int,
    file_metadata_id: uuid.UUID,
    filename: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
):
    attachment = TaskAttachment(
        task_id=task_id, 
        uploaded_by_id=user.user_id,
        file_path=str(file_metadata_id),
        filename=filename
    )
    session.add(attachment)
    await session.commit()
    return attachment

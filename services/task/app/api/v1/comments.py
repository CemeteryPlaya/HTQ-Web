from typing import Annotated
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db_session
from app.auth.dependencies import TokenPayload, get_current_user
from app.models import TaskComment

router = APIRouter(prefix="/tasks", tags=["comments"])

@router.get("/{task_id}/comments")
async def list_comments(
    task_id: int,
    session: Annotated[AsyncSession, Depends(get_db_session)],
):
    result = await session.execute(select(TaskComment).where(TaskComment.task_id == task_id))
    return result.scalars().all()

@router.post("/{task_id}/comments")
async def create_comment(
    task_id: int,
    content: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
):
    comment = TaskComment(task_id=task_id, author_id=user.user_id, content=content)
    session.add(comment)
    await session.commit()
    return comment

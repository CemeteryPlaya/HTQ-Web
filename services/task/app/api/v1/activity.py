from typing import Annotated
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db_session
from app.models import TaskActivity

router = APIRouter(prefix="/tasks", tags=["activity"])

@router.get("/{task_id}/activity")
async def get_activity(
    task_id: int,
    session: Annotated[AsyncSession, Depends(get_db_session)],
):
    result = await session.execute(select(TaskActivity).where(TaskActivity.task_id == task_id).order_by(TaskActivity.created_at.desc()))
    return result.scalars().all()

from typing import Annotated
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db_session
from app.auth.dependencies import TokenPayload, require_admin
from app.services.sequences import next_task_key

router = APIRouter(prefix="/sequences", tags=["sequences"])

@router.post("/{project_prefix}/next")
async def get_next_key(
    project_prefix: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _admin: Annotated[TokenPayload, Depends(require_admin)],
):
    key = await next_task_key(session, project_prefix)
    return {"key": key}

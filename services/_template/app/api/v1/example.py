"""
Example router — JWT-protected, demonstrates DB session + actor enqueue.
Replace with your actual service endpoints under /api/<service>/v1/...
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TokenPayload, get_current_user
from app.db import get_db_session


router = APIRouter(tags=["__service_name__"])


class ExampleResponse(BaseModel):
    id: int
    name: str
    owner_id: int


@router.get("/items", response_model=list[ExampleResponse])
async def list_items(
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    return []


@router.post("/items", response_model=ExampleResponse, status_code=201)
async def create_item(
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    # from app.workers.actors import example_task
    # example_task.send({"item_id": 1})
    return ExampleResponse(id=1, name="example", owner_id=current_user.user_id)

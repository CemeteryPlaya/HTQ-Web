"""Equipment CRUD — manage physical resources used in resource planning."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TokenPayload, get_current_user
from app.db import get_db
from app.models.equipment import Equipment
from app.schemas.gantt import EquipmentCreate, EquipmentResponse, EquipmentUpdate

router = APIRouter(prefix="/equipment", tags=["equipment"])


@router.get("/", response_model=list[EquipmentResponse])
async def list_equipment(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
    active_only: bool = Query(True),
):
    stmt = select(Equipment)
    if active_only:
        stmt = stmt.where(Equipment.is_active.is_(True))
    stmt = stmt.order_by(Equipment.name)
    return (await db.execute(stmt)).scalars().all()


@router.post("/", response_model=EquipmentResponse, status_code=201)
async def create_equipment(
    payload: EquipmentCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    obj = Equipment(**payload.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


@router.patch("/{equipment_id}", response_model=EquipmentResponse)
async def update_equipment(
    equipment_id: int,
    payload: EquipmentUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    obj = await db.get(Equipment, equipment_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Equipment not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
    await db.flush()
    await db.refresh(obj)
    return obj


@router.delete("/{equipment_id}", status_code=204)
async def delete_equipment(
    equipment_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: TokenPayload = Depends(get_current_user),
):
    obj = await db.get(Equipment, equipment_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Equipment not found")
    # Soft-disable rather than hard delete to preserve historical assignments.
    obj.is_active = False
    await db.flush()

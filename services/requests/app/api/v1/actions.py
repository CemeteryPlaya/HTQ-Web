"""Approver actions on a pending request."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TokenPayload, get_current_user
from app.db import get_db_session
from app.models.request_instance import RequestInstance
from app.schemas.instance import ActionRequest, BatchActionRequest, InstanceResponse
from app.services import request_runtime as rr
from app.services.template_settings import settings_for_instance

router = APIRouter(prefix="/instances", tags=["actions"])


async def _get_or_404(db: AsyncSession, instance_id: int) -> RequestInstance:
    inst = await db.get(RequestInstance, instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail="Request not found")
    return inst


@router.post("/batch-approve")
async def batch_approve(
    data: BatchActionRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
):
    results = []
    for iid in data.ids:
        inst = await db.get(RequestInstance, iid)
        if not inst:
            results.append({"id": iid, "ok": False, "error": "not found"})
            continue
        if not (await settings_for_instance(db, inst))["allow_batch"]:
            results.append({"id": iid, "ok": False, "error": "batch disabled"})
            continue
        try:
            await rr.act(db, inst, approver_id=user.user_id, action="approve", comment=data.comment)
            results.append({"id": iid, "ok": True})
        except HTTPException as e:
            results.append({"id": iid, "ok": False, "error": e.detail})
    return {"results": results}


@router.post("/{instance_id}/approve/", response_model=InstanceResponse)
async def approve(
    instance_id: int, data: ActionRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
):
    inst = await _get_or_404(db, instance_id)
    await rr.act(db, inst, approver_id=user.user_id, action="approve", comment=data.comment)
    await db.refresh(inst)
    return inst


@router.post("/{instance_id}/reject/", response_model=InstanceResponse)
async def reject(
    instance_id: int, data: ActionRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
):
    inst = await _get_or_404(db, instance_id)
    await rr.act(db, inst, approver_id=user.user_id, action="reject", comment=data.comment)
    await db.refresh(inst)
    return inst


@router.post("/{instance_id}/request-changes/", response_model=InstanceResponse)
async def request_changes(
    instance_id: int, data: ActionRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
):
    inst = await _get_or_404(db, instance_id)
    await rr.act(db, inst, approver_id=user.user_id, action="request_changes", comment=data.comment)
    await db.refresh(inst)
    return inst


@router.post("/{instance_id}/cancel/", response_model=InstanceResponse)
async def cancel(
    instance_id: int, data: ActionRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
):
    inst = await _get_or_404(db, instance_id)
    await rr.cancel(db, inst, actor_id=user.user_id, is_elevated=user.is_elevated)
    await db.refresh(inst)
    return inst


@router.post("/{instance_id}/recall/", response_model=InstanceResponse)
async def recall(
    instance_id: int, data: ActionRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
):
    inst = await _get_or_404(db, instance_id)
    await rr.recall(db, inst, approver_id=user.user_id)
    await db.refresh(inst)
    return inst

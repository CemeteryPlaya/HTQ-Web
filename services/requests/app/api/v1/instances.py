"""Request instance lifecycle endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TokenPayload, get_current_user
from app.db import get_db_session
from app.models.form_template import RequestFormTemplate
from app.models.request_instance import RequestInstance, RequestStatus
from app.repositories.instance_repo import InstanceRepository
from app.schemas.instance import InstanceCreate, InstanceResponse, InstanceUpdate
from app.services import request_runtime as rr

router = APIRouter(prefix="/instances", tags=["instances"])


async def _get_or_404(db: AsyncSession, instance_id: int) -> RequestInstance:
    inst = await db.get(RequestInstance, instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail="Request not found")
    return inst


@router.post("/", response_model=InstanceResponse, status_code=201)
async def create_instance(
    data: InstanceCreate,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
):
    tpl = await db.get(RequestFormTemplate, data.template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    if tpl.status != "active":
        raise HTTPException(status_code=409, detail="Форма заблокирована")
    if tpl.current_version_id is None:
        raise HTTPException(status_code=409, detail="template has no published version")
    initiator = user.user_id
    delegated = data.on_behalf_of is not None and data.on_behalf_of != user.user_id
    if delegated:
        from app.services.template_settings import settings_for_template

        st = await settings_for_template(db, tpl.id)
        if not st["allow_delegate_submission"] or not user.is_elevated:
            raise HTTPException(status_code=403, detail="delegated submission is not allowed")
        initiator = data.on_behalf_of
    repo = InstanceRepository(db)
    code = await repo.next_code(tpl.id, tpl.slug)
    inst = await repo.create(
        code=code, template_id=tpl.id, template_version_id=tpl.current_version_id,
        project_id=data.project_id if data.project_id is not None else tpl.project_id,
        initiator_id=initiator, title=data.title, form_values_json=data.form_values,
        status=RequestStatus.DRAFT.value,
    )
    if delegated:
        repo.log(inst.id, "created_on_behalf", user.user_id, {"for": initiator})
    else:
        repo.log(inst.id, "created", user.user_id, None)
    from app.services.template_data_table import sync_row_for_instance
    await sync_row_for_instance(db, inst)
    await db.refresh(inst)
    return inst


@router.get("/", response_model=list[InstanceResponse])
async def list_instances(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
    box: str = "inbox",
):
    return await InstanceRepository(db).list_for_user(user.user_id, role=box)


@router.get("/{instance_id}/", response_model=InstanceResponse)
async def get_instance(
    instance_id: int,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
):
    return await _get_or_404(db, instance_id)


@router.patch("/{instance_id}/", response_model=InstanceResponse)
async def update_draft(
    instance_id: int,
    data: InstanceUpdate,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
):
    inst = await _get_or_404(db, instance_id)
    if inst.initiator_id != user.user_id:
        raise HTTPException(status_code=403, detail="only the initiator can edit")
    editable = inst.status in (RequestStatus.DRAFT.value, RequestStatus.RETURNED.value)
    if not editable and inst.status == RequestStatus.APPROVED.value:
        from datetime import datetime, timezone

        from app.services.template_settings import settings_for_instance

        st = await settings_for_instance(db, inst)
        within = inst.finalized_at is not None and (
            datetime.now(timezone.utc)
            - (
                inst.finalized_at
                if inst.finalized_at.tzinfo
                else inst.finalized_at.replace(tzinfo=timezone.utc)
            )
        ).days <= int(st["modify_within_days"] or 0)
        editable = bool(st["allow_modify_approved"]) and within
    if not editable:
        raise HTTPException(status_code=409, detail="request is not editable in its current state")
    if data.title is not None:
        inst.title = data.title
    if data.form_values is not None:
        inst.form_values_json = data.form_values
    await db.flush()
    from app.services.template_data_table import sync_row_for_instance
    await sync_row_for_instance(db, inst)
    await db.refresh(inst)
    return inst


@router.post("/{instance_id}/submit/", response_model=InstanceResponse)
async def submit_instance(
    instance_id: int,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
):
    inst = await _get_or_404(db, instance_id)
    if inst.initiator_id != user.user_id:
        raise HTTPException(status_code=403, detail="only the initiator can submit")
    await rr.submit(db, inst, actor_id=user.user_id)
    await db.refresh(inst)
    return inst


@router.post("/{instance_id}/resubmit/", response_model=InstanceResponse)
async def resubmit_instance(
    instance_id: int,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
):
    inst = await _get_or_404(db, instance_id)
    if inst.initiator_id != user.user_id:
        raise HTTPException(status_code=403, detail="only the initiator can resubmit")
    if inst.status != RequestStatus.RETURNED.value:
        raise HTTPException(status_code=409, detail="only a returned request can be resubmitted")
    await rr.submit(db, inst, actor_id=user.user_id)
    await db.refresh(inst)
    return inst

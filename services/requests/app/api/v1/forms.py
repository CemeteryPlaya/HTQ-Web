"""Form template + version endpoints (the form builder)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TokenPayload, get_current_user
from app.auth.permissions import ensure_can_manage_template
from app.db import get_db_session
from app.repositories.project_repo import ProjectRepository
from app.repositories.template_repo import TemplateRepository
from app.schemas.template import (
    PreviewRequest,
    PreviewResponse,
    TemplateCreate,
    TemplateResponse,
    TemplateUpdate,
    VersionPublish,
    VersionResponse,
)
from app.services.template_validation import validate_template_version
from app.util.slug import slugify

router = APIRouter(tags=["forms"])


def _validate_or_422(schema_json: dict, workflow_json: dict):
    try:
        return validate_template_version(schema_json, workflow_json)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid template version: {exc}")


@router.get("/templates/", response_model=list[TemplateResponse])
async def list_templates(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
    project_id: int | None = None,
):
    return await TemplateRepository(db).list_for_project(project_id)


@router.post("/templates/", response_model=TemplateResponse, status_code=201)
async def create_template(
    data: TemplateCreate,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
):
    proj_repo = ProjectRepository(db)
    await ensure_can_manage_template(proj_repo, data.project_id, current_user)
    repo = TemplateRepository(db)
    slug = slugify(data.name)
    if await repo.slug_exists(data.project_id, slug):
        raise HTTPException(status_code=409, detail=f"Template slug '{slug}' already exists in this scope")
    tpl = await repo.create(
        project_id=data.project_id, name=data.name, slug=slug,
        description=data.description, icon=data.icon, color=data.color,
        config_json=data.config_json, created_by=current_user.user_id,
    )
    from app.services.template_data_table import ensure_source_for_template
    await ensure_source_for_template(db, tpl)
    return tpl


@router.get("/templates/{template_id}/", response_model=TemplateResponse)
async def get_template(
    template_id: int,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
):
    tpl = await TemplateRepository(db).get_by_id(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    return tpl


@router.patch("/templates/{template_id}/", response_model=TemplateResponse)
async def update_template(
    template_id: int,
    data: TemplateUpdate,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
):
    repo = TemplateRepository(db)
    tpl = await repo.get_by_id(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    await ensure_can_manage_template(ProjectRepository(db), tpl.project_id, current_user)
    await repo.update(tpl, **data.model_dump(exclude_unset=True))
    await db.refresh(tpl)
    return tpl


@router.post("/templates/{template_id}/deactivate/", response_model=TemplateResponse)
async def deactivate_template(
    template_id: int,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
):
    repo = TemplateRepository(db)
    tpl = await repo.get_by_id(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    await ensure_can_manage_template(ProjectRepository(db), tpl.project_id, current_user)
    tpl.status = "inactive"
    tpl.is_active = False
    await db.flush()
    await db.refresh(tpl)
    return tpl


@router.post("/templates/{template_id}/activate/", response_model=TemplateResponse)
async def activate_template(
    template_id: int,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
):
    repo = TemplateRepository(db)
    tpl = await repo.get_by_id(template_id)
    if not tpl or tpl.status == "deleted":
        raise HTTPException(status_code=404, detail="Template not found")
    await ensure_can_manage_template(ProjectRepository(db), tpl.project_id, current_user)
    tpl.status = "active"
    tpl.is_active = True
    await db.flush()
    await db.refresh(tpl)
    return tpl


@router.delete("/templates/{template_id}/", status_code=204)
async def delete_template(
    template_id: int,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
):
    """Soft-delete: the template is hidden and the form is blocked, but its data
    table / reference data is kept. Owner + process admins retain access to it."""
    from sqlalchemy import select
    from app.models.reference_source import RequestReferenceSource

    repo = TemplateRepository(db)
    tpl = await repo.get_by_id(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    await ensure_can_manage_template(ProjectRepository(db), tpl.project_id, current_user)

    # Preserve access to the (now-orphaned) data table for its owner + admins.
    src = (await db.execute(
        select(RequestReferenceSource).where(RequestReferenceSource.template_id == tpl.id)
    )).scalar_one_or_none()
    if src is not None:
        keep = {int(x) for x in (src.access_ids or []) if isinstance(x, int)}
        if tpl.created_by:
            keep.add(int(tpl.created_by))
        for a in (tpl.config_json or {}).get("process_admin_ids") or []:
            if isinstance(a, int):
                keep.add(a)
        src.access_ids = sorted(keep)

    tpl.status = "deleted"
    tpl.is_active = False
    await db.flush()


@router.post("/templates/{template_id}/versions/", response_model=VersionResponse, status_code=201)
async def publish_version(
    template_id: int,
    data: VersionPublish,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
):
    repo = TemplateRepository(db)
    tpl = await repo.get_by_id(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    await ensure_can_manage_template(ProjectRepository(db), tpl.project_id, current_user)
    _validate_or_422(data.schema_json, data.workflow_json)
    version = await repo.add_version(tpl, data.schema_json, data.workflow_json, published_by=current_user.user_id)
    from app.services.template_data_table import sync_columns_for_template
    await sync_columns_for_template(db, tpl, data.schema_json)
    return version


@router.get("/templates/{template_id}/versions/{version_id}/", response_model=VersionResponse)
async def get_version(
    template_id: int,
    version_id: int,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
):
    version = await TemplateRepository(db).get_version(version_id)
    if not version or version.template_id != template_id:
        raise HTTPException(status_code=404, detail="Version not found")
    return version


@router.post("/templates/preview/", response_model=PreviewResponse)
async def preview_template(
    data: PreviewRequest,
    current_user: Annotated[TokenPayload, Depends(get_current_user)],
):
    schema, graph = _validate_or_422(data.schema_json, data.workflow_json)
    return PreviewResponse(valid=True, field_keys=sorted(schema.keys), node_count=len(graph.nodes))

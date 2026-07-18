"""Org API — subordination matrix, org tree, reporting relations, settings."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.auth.dependencies import get_current_user, require_hr_write, TokenPayload
from app.services.org_service import OrgService

router = APIRouter(prefix="/org", tags=["org"])


def _svc(db: AsyncSession = Depends(get_db_session)) -> OrgService:
    return OrgService(db)


# ── Schemas (inline — small, no separate file needed) ─────────────────

class RelationCreate(BaseModel):
    superior_position_id: int
    subordinate_position_id: int
    relation_type: Literal["direct", "functional", "project"] = "direct"
    effective_from: date | None = None
    effective_to: date | None = None


class RelationOut(BaseModel):
    id: int
    superior_position_id: int
    subordinate_position_id: int
    relation_type: str
    effective_from: date | None
    effective_to: date | None

    model_config = {"from_attributes": True}


class OrgSettingUpdate(BaseModel):
    deletion_strategy: Literal["block", "reassign_to_parent", "cascade"]


# ── Org tree (Фича 3 endpoint lives here too) ──────────────────────────

@router.get("/tree")
async def get_org_tree(
    root_id: int | None = Query(default=None),
    depth: int = Query(default=5, ge=1, le=10),
    mode: Literal["positions", "employees", "both"] = Query(default="positions"),
    lang: Literal["ru", "en"] = Query(default="ru"),
    svc: OrgService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    """Return nodes + edges for React Flow org-chart rendering."""
    return await svc.get_org_tree(root_id=root_id, depth=depth, mode=mode, lang=lang)


# ── Subordination matrix ───────────────────────────────────────────────

@router.get("/subordination-matrix")
async def get_subordination_matrix(
    unit_id: int | None = Query(default=None),
    svc: OrgService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    """NxM matrix of reporting relations for a unit (or all if unit_id omitted)."""
    return await svc.get_subordination_matrix(unit_id=unit_id)


# ── Reporting relations CRUD ───────────────────────────────────────────

@router.post("/relations", response_model=RelationOut, status_code=status.HTTP_201_CREATED)
async def add_relation(
    body: RelationCreate,
    svc: OrgService = Depends(_svc),
    _: TokenPayload = Depends(require_hr_write),
):
    return await svc.add_relation(
        superior_id=body.superior_position_id,
        subordinate_id=body.subordinate_position_id,
        relation_type=body.relation_type,
        effective_from=body.effective_from,
        effective_to=body.effective_to,
    )


@router.delete("/relations/{relation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_relation(
    relation_id: int,
    svc: OrgService = Depends(_svc),
    _: TokenPayload = Depends(require_hr_write),
):
    await svc.remove_relation(relation_id)


# ── Org settings ──────────────────────────────────────────────────────

@router.get("/settings/deletion-strategy")
async def get_deletion_strategy(
    svc: OrgService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return {"deletion_strategy": await svc.get_deletion_strategy()}


@router.put("/settings/deletion-strategy")
async def set_deletion_strategy(
    body: OrgSettingUpdate,
    svc: OrgService = Depends(_svc),
    _: TokenPayload = Depends(require_hr_write),
):
    await svc.set_deletion_strategy(body.deletion_strategy)
    return {"deletion_strategy": body.deletion_strategy}

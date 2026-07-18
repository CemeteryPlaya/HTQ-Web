"""PMO API — CRUD + members + org-chart."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.auth.dependencies import get_current_user, require_hr_write, TokenPayload
from app.services.pmo_service import PMOService

router = APIRouter(prefix="/pmo", tags=["pmo"])


def _svc(db: AsyncSession = Depends(get_db_session)) -> PMOService:
    return PMOService(db)


# ── Schemas ────────────────────────────────────────────────────────────

class PMOCreate(BaseModel):
    name: str = Field(..., max_length=200)
    code: str = Field(..., max_length=50)
    description: str | None = None
    head_employee_id: int | None = None
    status: Literal["active", "suspended", "closed"] = "active"


class PMOUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    head_employee_id: int | None = None
    status: Literal["active", "suspended", "closed"] | None = None


class PMOOut(BaseModel):
    id: int
    name: str
    code: str
    description: str | None
    head_employee_id: int | None
    status: str

    model_config = {"from_attributes": True}


class MemberAdd(BaseModel):
    employee_id: int
    membership_type: Literal["permanent", "assigned", "consulting"] = "permanent"
    position_in_pmo: str | None = Field(default=None, max_length=200)
    allocation_percent: int = Field(default=100, ge=0, le=100)
    is_primary: bool = False
    from_date: date | None = None
    to_date: date | None = None

    @model_validator(mode="after")
    def _check_dates(self):
        if self.from_date and self.to_date and self.to_date < self.from_date:
            raise ValueError("to_date must be >= from_date")
        return self


class MemberUpdate(BaseModel):
    employee_id: int | None = None
    membership_type: Literal["permanent", "assigned", "consulting"] | None = None
    position_in_pmo: str | None = Field(default=None, max_length=200)
    allocation_percent: int | None = Field(default=None, ge=0, le=100)
    is_primary: bool | None = None
    from_date: date | None = None
    to_date: date | None = None

    @model_validator(mode="after")
    def _check_dates(self):
        if self.from_date and self.to_date and self.to_date < self.from_date:
            raise ValueError("to_date must be >= from_date")
        return self


class MemberOut(BaseModel):
    id: int
    pmo_id: int
    employee_id: int
    employee_name: str
    employee_email: str
    primary_position: str | None
    position_in_pmo: str | None
    membership_type: str
    allocation_percent: int
    is_primary: bool
    from_date: str | None
    to_date: str | None


class MemberCreatedOut(BaseModel):
    id: int
    pmo_id: int
    employee_id: int
    membership_type: str
    position_in_pmo: str | None
    allocation_percent: int
    is_primary: bool
    from_date: date
    to_date: date | None

    model_config = {"from_attributes": True}


# ── CRUD ──────────────────────────────────────────────────────────────

@router.get("/", response_model=list[PMOOut])
async def list_pmos(
    status_filter: str | None = Query(default=None, alias="status"),
    svc: PMOService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.list_pmos(status_filter=status_filter)


@router.post("/", response_model=PMOOut, status_code=status.HTTP_201_CREATED)
async def create_pmo(
    body: PMOCreate,
    svc: PMOService = Depends(_svc),
    _: TokenPayload = Depends(require_hr_write),
):
    return await svc.create_pmo(body.model_dump())


@router.get("/{id}", response_model=PMOOut)
async def get_pmo(
    id: int,
    svc: PMOService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.get_pmo(id)


@router.patch("/{id}", response_model=PMOOut)
async def update_pmo(
    id: int,
    body: PMOUpdate,
    svc: PMOService = Depends(_svc),
    _: TokenPayload = Depends(require_hr_write),
):
    return await svc.update_pmo(id, body.model_dump(exclude_none=True))


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pmo(
    id: int,
    svc: PMOService = Depends(_svc),
    _: TokenPayload = Depends(require_hr_write),
):
    await svc.delete_pmo(id)


# ── Members ────────────────────────────────────────────────────────────

@router.get("/{id}/members", response_model=list[MemberOut])
async def list_pmo_members(
    id: int,
    svc: PMOService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.list_members(id)


@router.post("/{id}/members", response_model=MemberCreatedOut, status_code=status.HTTP_201_CREATED)
async def add_pmo_member(
    id: int,
    body: MemberAdd,
    response: Response,
    svc: PMOService = Depends(_svc),
    current_user: TokenPayload = Depends(require_hr_write),
):
    member, warning_total = await svc.add_member(
        id,
        body.model_dump(),
        actor_user_id=current_user.user_id,
    )
    if warning_total > 100:
        response.headers["X-Allocation-Warning"] = str(warning_total)
    return member


@router.patch("/{id}/members/{member_id}", response_model=MemberCreatedOut)
async def update_pmo_member(
    id: int,
    member_id: int,
    body: MemberUpdate,
    response: Response,
    svc: PMOService = Depends(_svc),
    current_user: TokenPayload = Depends(require_hr_write),
):
    member, warning_total = await svc.update_member(
        id,
        member_id,
        body.model_dump(exclude_unset=True),
        actor_user_id=current_user.user_id,
    )
    if warning_total > 100:
        response.headers["X-Allocation-Warning"] = str(warning_total)
    return member


@router.delete("/{id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_pmo_member(
    id: int,
    member_id: int,
    svc: PMOService = Depends(_svc),
    _: TokenPayload = Depends(require_hr_write),
):
    await svc.remove_member(id, member_id)


# ── Org-chart ──────────────────────────────────────────────────────────

@router.get("/{id}/org-chart")
async def pmo_org_chart(
    id: int,
    svc: PMOService = Depends(_svc),
    _: TokenPayload = Depends(get_current_user),
):
    return await svc.get_pmo_org_chart(id)

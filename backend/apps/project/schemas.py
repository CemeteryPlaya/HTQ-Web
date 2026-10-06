from __future__ import annotations

from datetime import date
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ProjectIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=255)
    kind: str = Field("project", pattern="^(project|company_overhead)$")
    country_code: str = Field(..., min_length=2, max_length=2)
    manager_user_id: Optional[int] = None
    customer_name: str = Field("", max_length=255)
    customer_counterparty_id: str = Field("", max_length=64)
    date_start: Optional[date] = None
    date_end: Optional[date] = None
    ext_1c_ref: str = Field("", max_length=64)


class ProjectPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    status: Optional[str] = Field(None, pattern="^(active|closed|archived)$")
    manager_user_id: Optional[int] = None
    customer_name: Optional[str] = Field(None, max_length=255)
    customer_counterparty_id: Optional[str] = Field(None, max_length=64)
    date_start: Optional[date] = None
    date_end: Optional[date] = None
    ext_1c_ref: Optional[str] = Field(None, max_length=64)


class MemberIn(BaseModel):
    user_id: int


# ── Проектная структура (docs/plans/2026-10-06-project-structure-spec.md §4) ──

_PART = "^(office|site)$"
_INT4 = 2**31 - 1


class RoleIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    level: int = Field(..., ge=1, le=4)
    default_part: str = Field("office", pattern=_PART)
    sort_order: int = Field(0, ge=-_INT4, le=_INT4)


class RolePatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    level: Optional[int] = Field(None, ge=1, le=4)
    default_part: Optional[str] = Field(None, pattern=_PART)
    sort_order: Optional[int] = Field(None, ge=-_INT4, le=_INT4)
    is_active: Optional[bool] = None


class SlotIn(BaseModel):
    role_id: int = Field(..., ge=1, le=_INT4)
    parent_id: Optional[UUID] = None
    part: Optional[str] = Field(None, pattern=_PART)
    title: str = Field("", max_length=255)
    planned_headcount: int = Field(1, ge=1, le=999)


class SlotPatch(BaseModel):
    """Присланный ``parent_id: null`` — «без руководителя»; не присланный —
    подчинение не меняется (``model_dump(exclude_unset=True)``)."""

    parent_id: Optional[UUID] = None
    part: Optional[str] = Field(None, pattern=_PART)
    title: Optional[str] = Field(None, max_length=255)
    planned_headcount: Optional[int] = Field(None, ge=1, le=999)
    closed_on: Optional[date] = None


class AssignmentIn(BaseModel):
    employee_id: int = Field(..., ge=1, le=_INT4)
    date_from: date
    date_to: Optional[date] = None


class AssignmentPatch(BaseModel):
    """Присланный ``date_to: null`` — «бессрочно»."""

    date_from: Optional[date] = None
    date_to: Optional[date] = None

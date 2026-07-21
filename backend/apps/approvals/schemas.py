"""Pydantic schemas for the approvals domain.

Ported from ``services/requests/app/schemas/*.py``. They ARE the response
contract, so they come across as-is; where the original imported a
SQLAlchemy enum this imports the equivalent ``TextChoices``, which serialises
to the same strings.

``Decimal`` fields (``total_amount``, ``budget_limit``,
``sum_approved_amount``) stay ``Decimal`` rather than becoming ``float``:
these are money, and the original declared them that way. ``model_dump(
mode="json")`` — which ``htqweb.http.api_view`` uses — renders a ``Decimal``
as a JSON string, exactly as FastAPI did.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from .models import ProjectMemberRole, ProjectStatus


# ── projects ────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    status: ProjectStatus = ProjectStatus.ACTIVE
    color: str = Field(default="#3b82f6", max_length=20)
    budget_limit: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="KZT", min_length=3, max_length=3)
    start_date: date | None = None
    end_date: date | None = None
    owner_id: int | None = None
    department_id: int | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=5000)
    status: ProjectStatus | None = None
    color: str | None = Field(None, max_length=20)
    budget_limit: Decimal | None = Field(None, ge=0)
    currency: str | None = Field(None, min_length=3, max_length=3)
    start_date: date | None = None
    end_date: date | None = None
    owner_id: int | None = None
    department_id: int | None = None


class ProjectResponse(BaseModel):
    id: int
    name: str
    description: str
    status: ProjectStatus
    color: str
    budget_limit: Decimal | None = None
    currency: str
    start_date: date | None = None
    end_date: date | None = None
    owner_id: int | None = None
    department_id: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MemberAdd(BaseModel):
    user_id: int
    role: ProjectMemberRole = ProjectMemberRole.MEMBER


class MemberResponse(BaseModel):
    project_id: int
    user_id: int
    role: ProjectMemberRole
    granted_by: int | None = None
    granted_at: datetime

    model_config = {"from_attributes": True}


# ── templates and versions ──────────────────────────────────────────────

class TemplateCreate(BaseModel):
    project_id: int | None = None
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    icon: str = Field(default="", max_length=50)
    color: str = Field(default="#3b82f6", max_length=20)
    config_json: dict = Field(default_factory=dict)


class TemplateUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=5000)
    icon: str | None = Field(None, max_length=50)
    color: str | None = Field(None, max_length=20)
    config_json: dict | None = None
    is_active: bool | None = None


class TemplateResponse(BaseModel):
    id: int
    project_id: int | None = None
    name: str
    slug: str
    description: str
    icon: str
    color: str
    config_json: dict = Field(default_factory=dict)
    is_active: bool
    status: str = "active"
    created_by: int | None = None
    current_version_id: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class VersionPublish(BaseModel):
    schema_json: dict
    workflow_json: dict


class VersionResponse(BaseModel):
    id: int
    template_id: int
    version: int
    schema_json: dict
    workflow_json: dict
    published_at: datetime
    published_by: int | None = None

    model_config = {"from_attributes": True}


class PreviewRequest(BaseModel):
    schema_json: dict
    workflow_json: dict


class PreviewResponse(BaseModel):
    valid: bool
    field_keys: list[str]
    node_count: int


# ── instances and actions ───────────────────────────────────────────────

class InstanceCreate(BaseModel):
    template_id: int
    title: str = Field("", max_length=300)
    project_id: int | None = None
    form_values: dict = Field(default_factory=dict)
    on_behalf_of: int | None = None


class InstanceUpdate(BaseModel):
    title: str | None = Field(None, max_length=300)
    form_values: dict | None = None


class ActionRequest(BaseModel):
    comment: str = Field("", max_length=4000)


class BatchActionRequest(BaseModel):
    ids: list[int]
    comment: str = ""


class InstanceResponse(BaseModel):
    id: int
    code: str
    template_id: int
    template_version_id: int
    project_id: int | None = None
    initiator_id: int
    title: str
    status: str
    current_node_id: str | None = None
    form_values_json: dict
    total_amount: Decimal | None = None
    currency: str | None = None
    submitted_at: datetime | None = None
    finalized_at: datetime | None = None
    requires_admin_attention: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── reference sources ───────────────────────────────────────────────────

class ReferenceSourceCreate(BaseModel):
    slug: str | None = Field(None, max_length=64)
    name: str = Field(..., min_length=1, max_length=200)
    columns: list[str] = Field(default_factory=list)


class ReferenceSourceUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    columns: list[str] | None = None


class ReferenceSourceResponse(BaseModel):
    id: int
    slug: str
    name: str
    columns: list[str]
    template_id: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReferenceRowCreate(BaseModel):
    data: dict


class ReferenceRowResponse(BaseModel):
    id: int
    source_id: int
    data: dict

    model_config = {"from_attributes": True}


class DataTableResponse(BaseModel):
    id: int
    slug: str
    name: str
    columns: list[str]
    template_id: int | None
    access_ids: list[int]
    can_manage: bool


class AccessUpdate(BaseModel):
    viewer_ids: list[int]

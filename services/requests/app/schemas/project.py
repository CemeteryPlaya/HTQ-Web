from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.project import ProjectStatus


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

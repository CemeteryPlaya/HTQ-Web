"""Project schemas (roadmap-level grouping of tasks)."""

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.project import ProjectStatus


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    status: ProjectStatus = Field(default=ProjectStatus.ACTIVE)
    color: str = Field(default="#3b82f6", max_length=20)
    start_date: date | None = None
    end_date: date | None = None
    owner_id: int | None = None
    department_id: int | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=5000)
    status: ProjectStatus | None = None
    color: str | None = Field(None, max_length=20)
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
    start_date: date | None
    end_date: date | None
    owner_id: int | None = None
    owner_name: str | None = None
    department_id: int | None = None
    department_name: str | None = None
    task_count: int = 0
    done_count: int = 0
    progress: float = 0.0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

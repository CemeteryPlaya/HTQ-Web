"""Vacancy schemas."""

from datetime import date, datetime
from pydantic import BaseModel, Field


class VacancyBase(BaseModel):
    title: str = Field(..., max_length=255)
    department_id: int
    position_id: int
    description: str = ""
    requirements: str = ""
    status: str = Field(default="open", pattern="^(open|closed|on_hold)$")
    assigned_recruiter_id: int | None = None


class VacancyCreate(VacancyBase):
    pass


class VacancyUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    department_id: int | None = None
    position_id: int | None = None
    description: str | None = None
    requirements: str | None = None
    status: str | None = Field(default=None, pattern="^(open|closed|on_hold)$")
    assigned_recruiter_id: int | None = None
    closed_at: date | None = None


class VacancyOut(VacancyBase):
    id: int
    opened_at: date
    closed_at: date | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

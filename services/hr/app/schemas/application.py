"""Application (candidate) schemas."""

from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


APPLICATION_STATUSES = "^(new|reviewed|interview|offer|rejected|hired)$"


class ApplicationBase(BaseModel):
    vacancy_id: int
    candidate_name: str = Field(..., max_length=255)
    candidate_email: EmailStr
    candidate_phone: str | None = Field(default=None, max_length=20)
    resume_url: str | None = Field(default=None, max_length=500)
    cover_letter: str | None = None
    notes: str | None = None


class ApplicationCreate(ApplicationBase):
    pass


class ApplicationUpdate(BaseModel):
    candidate_name: str | None = Field(default=None, max_length=255)
    candidate_email: EmailStr | None = None
    candidate_phone: str | None = None
    resume_url: str | None = None
    cover_letter: str | None = None
    notes: str | None = None
    status: str | None = Field(default=None, pattern=APPLICATION_STATUSES)


class ApplicationStatusChange(BaseModel):
    status: str = Field(..., pattern=APPLICATION_STATUSES)
    notes: str | None = None


class ApplicationOut(ApplicationBase):
    id: int
    status: str
    applied_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

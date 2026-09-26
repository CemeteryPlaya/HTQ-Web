from __future__ import annotations

from datetime import date
from typing import Optional

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


class ProjectPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    status: Optional[str] = Field(None, pattern="^(active|closed|archived)$")
    manager_user_id: Optional[int] = None
    customer_name: Optional[str] = Field(None, max_length=255)
    customer_counterparty_id: Optional[str] = Field(None, max_length=64)
    date_start: Optional[date] = None
    date_end: Optional[date] = None


class MemberIn(BaseModel):
    user_id: int

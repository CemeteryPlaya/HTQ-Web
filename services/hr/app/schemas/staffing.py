"""Staffing-table schemas. Numeric fields serialize as strings."""

from __future__ import annotations

from pydantic import BaseModel, Field


class StaffingLineIn(BaseModel):
    position_id: int
    department_id: int
    grade: int | None = None
    headcount: str = "1"
    salary: str = "0"
    note: str | None = None


class StaffingLineOut(BaseModel):
    id: int
    position_id: int
    department_id: int
    grade: int | None = None
    headcount: str
    salary: str
    fot: str
    note: str | None = None

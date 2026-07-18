"""TimeEntry schemas."""

from datetime import date, datetime, time
from typing import Optional
from pydantic import BaseModel, Field, model_validator


class TimeEntryBase(BaseModel):
    employee_id: int
    date: date
    start_time: time
    end_time: time
    break_minutes: int = Field(default=0, ge=0)
    description: str | None = None
    project: str | None = Field(default=None, max_length=255)
    task: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def end_after_start(self) -> "TimeEntryBase":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class TimeEntryCreate(TimeEntryBase):
    pass


class TimeEntryUpdate(BaseModel):
    date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    break_minutes: int | None = Field(default=None, ge=0)
    description: str | None = None
    project: str | None = None
    task: str | None = None


class TimeEntryOut(TimeEntryBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DailyReport(BaseModel):
    date: date
    employee_id: int
    total_minutes: int
    entries: list[TimeEntryOut]


class WeeklyReport(BaseModel):
    week_start: date
    week_end: date
    employee_id: int
    total_minutes: int
    daily: list[DailyReport]


class MonthlyReport(BaseModel):
    year: int
    month: int
    employee_id: int
    total_minutes: int
    weekly: list[WeeklyReport]

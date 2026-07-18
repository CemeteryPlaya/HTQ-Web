"""Schemas for calendar models."""

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator


EventType = Literal["personal", "department", "common", "conference"]
RsvpStatus = Literal["pending", "accepted", "declined"]


class EventExceptionBase(BaseModel):
    exception_date: date
    is_cancelled: bool = True


class EventExceptionResponse(EventExceptionBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_id: int


class CalendarEventBase(BaseModel):
    title: str
    description: Optional[str] = None
    # Precise timestamps. For all-day events the form sends midnight in the
    # user's local tz and ``is_all_day=True``; the UI then hides the time
    # component on display.
    start_at: datetime
    end_at: datetime
    is_all_day: bool = True
    event_type: EventType = "personal"
    conference_room_id: Optional[str] = None
    color: Optional[str] = None
    is_global: bool = False
    department_id: Optional[int] = None


class CalendarEventCreate(CalendarEventBase):
    # Optional list of user_ids to invite (besides the creator). When the
    # frontend creates "Общее совещание", the picker fills this with the
    # selected employees' user_ids; the event then appears on each of
    # their calendars without requiring is_global.
    participant_user_ids: list[int] = []

    @field_validator("end_at")
    @classmethod
    def end_after_start(cls, v: datetime, info):
        start = info.data.get("start_at")
        if start is not None and v < start:
            raise ValueError("end_at must be >= start_at")
        return v


class CalendarEventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    is_all_day: Optional[bool] = None
    event_type: Optional[EventType] = None
    conference_room_id: Optional[str] = None
    color: Optional[str] = None
    is_global: Optional[bool] = None
    department_id: Optional[int] = None
    # ``None`` means "do not touch participants"; an empty list clears them.
    participant_user_ids: Optional[list[int]] = None


class CalendarEventParticipantInfo(BaseModel):
    """Compact participant info; full_name is best-effort from task_users."""

    user_id: int
    full_name: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    rsvp_status: RsvpStatus = "pending"


class CalendarEventResponse(CalendarEventBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime
    creator_id: Optional[int] = None
    exceptions: list[EventExceptionResponse] = []
    participants: list[CalendarEventParticipantInfo] = []


class RsvpUpdate(BaseModel):
    status: RsvpStatus


class ProductionDayUpdate(BaseModel):
    day_type: Literal["working", "weekend", "holiday", "short"]
    note: Optional[str] = None


class ProductionDayResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    date: date
    day_type: Literal["working", "weekend", "holiday", "short"]
    working_days_since_epoch: int
    note: Optional[str] = None

"""Production-calendar schemas."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, field_validator

_DAY_TYPES = {"working", "weekend", "holiday", "short"}
_TMPL_TYPES = {"working", "weekend"}


class WeekDayConfig(BaseModel):
    type: str
    hours: float = Field(ge=0)

    @field_validator("type")
    @classmethod
    def _type_ok(cls, v: str) -> str:
        if v not in _TMPL_TYPES:
            raise ValueError(f"type must be one of {_TMPL_TYPES}")
        return v


class WeekTemplateIn(BaseModel):
    name: str = Field(max_length=100)
    days: dict[str, WeekDayConfig]

    @field_validator("days")
    @classmethod
    def _days_ok(cls, v: dict[str, WeekDayConfig]) -> dict[str, WeekDayConfig]:
        if set(v.keys()) != {str(i) for i in range(7)}:
            raise ValueError('days must have keys "0".."6"')
        return v


class WeekTemplateOut(BaseModel):
    id: int
    name: str
    is_default: bool
    days: dict

    model_config = {"from_attributes": True}


class CalendarDayIn(BaseModel):
    day_type: str
    norm_hours: float = Field(default=0, ge=0)
    note: str | None = None

    @field_validator("day_type")
    @classmethod
    def _type_ok(cls, v: str) -> str:
        if v not in _DAY_TYPES:
            raise ValueError(f"day_type must be one of {_DAY_TYPES}")
        return v


class CalendarImportItem(CalendarDayIn):
    day: date


class AssignTemplateIn(BaseModel):
    week_template_id: int | None = None


class ShiftSlot(BaseModel):
    type: str
    hours: float = Field(ge=0)

    @field_validator("type")
    @classmethod
    def _slot_type_ok(cls, v: str) -> str:
        if v not in {"work", "off"}:
            raise ValueError('slot type must be "work" or "off"')
        return v


class ShiftPatternIn(BaseModel):
    name: str = Field(max_length=100)
    slots: list[ShiftSlot] = Field(min_length=1)
    holidays_off: bool = False


class ShiftPatternOut(BaseModel):
    id: int
    name: str
    slots: list
    holidays_off: bool

    model_config = {"from_attributes": True}


class AssignShiftIn(BaseModel):
    shift_pattern_id: int
    anchor_date: date


class EmployeeDayOverrideIn(BaseModel):
    day_type: str
    norm_hours: float = Field(default=0, ge=0)
    note: str | None = None

    @field_validator("day_type")
    @classmethod
    def _ovr_type_ok(cls, v: str) -> str:
        if v not in _DAY_TYPES:
            raise ValueError(f"day_type must be one of {_DAY_TYPES}")
        return v

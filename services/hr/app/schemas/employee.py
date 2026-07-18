"""Employee schemas."""

from datetime import date, datetime
from pydantic import BaseModel, EmailStr, Field

from app.schemas.department import DepartmentShort
from app.schemas.position import PositionShort


class EmployeeBase(BaseModel):
    first_name: str = Field(..., max_length=100)
    last_name: str = Field(..., max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    email: str = Field(..., max_length=255)
    phone: str | None = Field(default=None, max_length=20)
    department_id: int
    position_id: int
    hire_date: date
    status: str = Field(default="active", pattern="^(active|inactive|terminated|suspended|pending|rejected)$")
    avatar_url: str | None = Field(default=None, max_length=500)
    bio: str | None = None


class EmployeeCreate(EmployeeBase):
    user_id: int | None = None


class EmployeeUpdate(BaseModel):
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    middle_name: str | None = None
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = None
    department_id: int | None = None
    position_id: int | None = None
    status: str | None = Field(default=None, pattern="^(active|inactive|terminated|suspended|pending|rejected)$")
    avatar_url: str | None = None
    bio: str | None = None
    termination_date: date | None = None


class EmployeeTransfer(BaseModel):
    department_id: int
    position_id: int | None = None
    effective_date: date | None = None


class EmployeeOut(EmployeeBase):
    id: int
    user_id: int | None = None
    termination_date: date | None = None
    department: DepartmentShort | None = None
    position: PositionShort | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

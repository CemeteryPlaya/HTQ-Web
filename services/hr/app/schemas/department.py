"""Department schemas."""

from datetime import datetime
from pydantic import BaseModel, Field

from app.schemas.position import PositionShort


class DepartmentBase(BaseModel):
    name: str = Field(..., max_length=255)
    path: str = Field(..., max_length=500, description="ltree path, e.g. 'company.dev.backend'")
    description: str | None = None
    manager_id: int | None = None
    is_active: bool = True


class DepartmentCreate(DepartmentBase):
    path: str | None = Field(default=None, max_length=500, description="ltree path, auto-generated if omitted")
    parent_id: int | None = None


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    path: str | None = Field(default=None, max_length=500)
    description: str | None = None
    manager_id: int | None = None
    is_active: bool | None = None


class DepartmentShort(BaseModel):
    id: int
    name: str
    path: str

    model_config = {"from_attributes": True}


class DepartmentOut(DepartmentBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DepartmentTree(DepartmentOut):
    children: list["DepartmentTree"] = []


class DepartmentWithPositions(DepartmentOut):
    """DepartmentOut + nested positions (joined-load).

    Used by GET /departments/ so the structure page can render positions inline
    without an N+1 fan-out from the frontend.
    """
    positions: list[PositionShort] = []

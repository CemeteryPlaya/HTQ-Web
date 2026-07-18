"""Position schemas."""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


HRLevelLiteral = Literal["junior", "middle", "senior", "lead"]


class PositionPermissions(BaseModel):
    """Permission matrix attached to a non-system position.

    ``permissions`` is the authoritative key-set enforced by
    ``app.auth.hr_access`` (``HRAccess.has`` / ``require_permission``).
    ``hr_level`` is a UI/migration preset: selecting a level fills
    ``permissions`` with the corresponding preset (see ``app.auth.permissions``).
    """

    hr_level: HRLevelLiteral | None = None
    permissions: list[str] = Field(default_factory=list)


class PositionBase(BaseModel):
    title: str = Field(..., max_length=255)
    department_id: int
    grade: int = Field(default=1, ge=1, le=10)
    description: str | None = None
    requirements: dict | None = None
    is_active: bool = True
    weight: int = Field(default=100, ge=0)
    permissions: PositionPermissions | None = None


class PositionCreate(PositionBase):
    pass


class PositionUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    department_id: int | None = None
    grade: int | None = Field(default=None, ge=1, le=10)
    description: str | None = None
    requirements: dict | None = None
    is_active: bool | None = None
    weight: int | None = Field(default=None, ge=0)
    permissions: PositionPermissions | None = None


class PositionWeightUpdate(BaseModel):
    weight: int = Field(..., ge=0)


class PositionShort(BaseModel):
    id: int
    title: str
    department_id: int
    grade: int
    weight: int
    level: int
    is_system: bool = False

    model_config = {"from_attributes": True}


class PositionOut(PositionBase):
    id: int
    level: int
    is_system: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PermissionCatalogItem(BaseModel):
    key: str
    label: str
    description: str | None = None
    group: str


class PermissionCatalog(BaseModel):
    hr_levels: list[dict] = Field(default_factory=list)
    permissions: list[PermissionCatalogItem] = Field(default_factory=list)
    level_presets: dict[str, list[str]] = Field(default_factory=dict)


class LevelThresholdOut(BaseModel):
    id: int
    level_number: int
    weight_from: int
    weight_to: int
    label: str | None
    color: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LevelThresholdCreate(BaseModel):
    level_number: int = Field(..., ge=1)
    weight_from: int = Field(..., ge=0)
    weight_to: int = Field(..., ge=0)
    label: str | None = Field(default=None, max_length=100)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")


class LevelThresholdUpdate(BaseModel):
    weight_from: int | None = Field(default=None, ge=0)
    weight_to: int | None = Field(default=None, ge=0)
    label: str | None = Field(default=None, max_length=100)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")


class PositionMoveRequest(BaseModel):
    before_position_id: int | None = None
    after_position_id: int | None = None
    target_level: int | None = Field(default=None, ge=1)


class PositionRebalanceRequest(BaseModel):
    level: int | None = Field(default=None, ge=1)

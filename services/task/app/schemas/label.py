"""Label schemas."""

from pydantic import BaseModel, Field


class LabelCreate(BaseModel):
    """Schema for creating a label."""

    name: str = Field(..., min_length=1, max_length=100)
    color: str = Field(default="#808080", pattern=r"^#[0-9A-Fa-f]{6}$")


class LabelUpdate(BaseModel):
    """Schema for updating a label."""

    name: str | None = Field(None, min_length=1, max_length=100)
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")


class LabelResponse(BaseModel):
    """Label response schema."""

    id: int
    name: str
    color: str

    model_config = {"from_attributes": True}

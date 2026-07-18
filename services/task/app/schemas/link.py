"""Task link schemas."""


from pydantic import BaseModel, model_validator

from app.models.link import LinkType


class LinkCreate(BaseModel):
    """Schema for creating a task link."""

    source_id: int
    target_id: int
    link_type: LinkType

    @model_validator(mode="after")
    def prevent_self_reference(self) -> "LinkCreate":
        if self.source_id == self.target_id:
            raise ValueError("Task cannot link to itself")
        return self


class LinkResponse(BaseModel):
    """Task link response schema."""

    id: int
    source_id: int
    target_id: int
    link_type: LinkType
    created_by_id: int | None = None

    source_key: str | None = None
    source_summary: str | None = None
    target_key: str | None = None
    target_summary: str | None = None

    created_at: str

    model_config = {"from_attributes": True}

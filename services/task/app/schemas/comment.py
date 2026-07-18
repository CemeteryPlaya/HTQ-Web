"""Comment schemas."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class CommentCreate(BaseModel):
    """Schema for creating a comment."""

    body: str = Field(..., min_length=1, max_length=10000)

    @field_validator("body")
    @classmethod
    def body_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Comment body cannot be blank")
        return v


class CommentUpdate(BaseModel):
    """Schema for updating a comment."""

    body: str = Field(..., min_length=1, max_length=10000)


class CommentResponse(BaseModel):
    """Comment response schema."""

    id: int
    task_id: int
    author_id: int | None = None
    author_name: str | None = None
    body: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

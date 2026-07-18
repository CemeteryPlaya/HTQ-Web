"""TaskType registry schemas."""

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


SLUG_RE = re.compile(r"^[a-z0-9_-]+$")


class TaskTypeCreate(BaseModel):
    # Slug is optional — when omitted, the service auto-generates it from
    # ``name`` (transliterating Cyrillic and de-duplicating). Callers may
    # still pass an explicit slug if they want a specific identifier.
    slug: str | None = Field(default=None, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    color: str = Field(default="#6b7280", max_length=20)
    icon: str | None = Field(default=None, max_length=50)

    @field_validator("slug")
    @classmethod
    def slug_format(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        if not v:
            return None
        if not SLUG_RE.match(v):
            raise ValueError("Slug must contain only lowercase letters, digits, _ and -")
        return v


class TaskTypeUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    color: str | None = Field(None, max_length=20)
    icon: str | None = Field(None, max_length=50)
    # slug is intentionally NOT editable — it's the stable identifier
    # other services and the historical UI rely on.


class TaskTypeResponse(BaseModel):
    id: int
    slug: str
    name: str
    color: str
    icon: str | None = None
    is_system: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

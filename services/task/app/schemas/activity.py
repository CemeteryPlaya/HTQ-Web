"""Activity schemas."""

from datetime import datetime

from pydantic import BaseModel


class ActivityResponse(BaseModel):
    """Task activity response schema."""

    id: int
    task_id: int
    actor_id: int | None = None
    actor_name: str | None = None
    field_name: str
    old_value: str | None = None
    new_value: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}

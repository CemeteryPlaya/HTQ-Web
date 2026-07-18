"""Attachment schemas."""

from datetime import datetime

from pydantic import BaseModel


class AttachmentResponse(BaseModel):
    """Attachment response schema."""

    id: int
    task_id: int
    file_path: str
    filename: str
    uploaded_by_id: int | None = None
    uploaded_by_name: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}

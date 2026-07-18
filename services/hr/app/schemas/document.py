"""Document schemas."""

from datetime import datetime
from pydantic import BaseModel, Field


class DocumentBase(BaseModel):
    employee_id: int
    title: str = Field(..., max_length=255)
    doc_type: str = Field(..., max_length=50)
    file_path: str = Field(..., max_length=500)
    file_size: int = Field(..., gt=0)
    mime_type: str = Field(default="application/octet-stream", max_length=100)
    metadata_: dict | None = Field(default=None, alias="metadata")

    model_config = {"populate_by_name": True}


class DocumentCreate(DocumentBase):
    uploaded_by: int


class DocumentOut(DocumentBase):
    id: int
    uploaded_by: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}

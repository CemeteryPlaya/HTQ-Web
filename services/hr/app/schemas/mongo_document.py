"""Pydantic schemas for MongoDB HR documents.

These documents represent bulky / unstructured HR files (contracts,
policies, memos, certificates, orders) that are stored in MongoDB
rather than the relational PostgreSQL database.

Each document holds ``sql_employee_id`` — a synthetic foreign key
that references ``hr_employees.id`` in PostgreSQL. The link is
maintained by convention, not by a database constraint.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class HRDocType(str, Enum):
    """Allowed HR document types in MongoDB."""
    CONTRACT = "contract"
    ORDER = "order"
    CERTIFICATE = "certificate"
    POLICY = "policy"
    MEMO = "memo"
    PERFORMANCE_REVIEW = "performance_review"
    DISCIPLINARY = "disciplinary"
    TRAINING = "training"
    OTHER = "other"


class HRDocumentCreate(BaseModel):
    """Schema for creating a new HR document in MongoDB."""
    sql_employee_id: int = Field(..., description="ID of the employee in PostgreSQL hr_employees table")
    title: str = Field(..., min_length=1, max_length=500)
    doc_type: HRDocType = Field(..., description="Type of the HR document")
    content: str = Field(default="", description="Text content or description")
    file_url: str | None = Field(default=None, description="URL to the attached file (media-service)")
    file_size_bytes: int | None = Field(default=None, ge=0)
    mime_type: str = Field(default="application/octet-stream")
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary key-value metadata")


class HRDocumentOut(BaseModel):
    """Schema for reading an HR document from MongoDB."""
    id: str = Field(..., alias="_id", description="MongoDB ObjectId as string")
    sql_employee_id: int
    title: str
    doc_type: str
    content: str = ""
    file_url: str | None = None
    file_size_bytes: int | None = None
    mime_type: str = "application/octet-stream"
    tags: list[str] = []
    metadata: dict[str, Any] = {}
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by_user_id: int | None = None

    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat() if v else None}


class HRDocumentUpdate(BaseModel):
    """Schema for updating an HR document in MongoDB."""
    title: str | None = None
    doc_type: HRDocType | None = None
    content: str | None = None
    file_url: str | None = None
    file_size_bytes: int | None = None
    mime_type: str | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None

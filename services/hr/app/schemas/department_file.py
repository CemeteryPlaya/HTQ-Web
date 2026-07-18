"""Schemas for department file manager endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DepartmentFolderOut(BaseModel):
    id: int
    department: int
    department_name: str
    files_count: int
    created_at: datetime


class DepartmentFileFolderCreate(BaseModel):
    department: int = Field(..., ge=1)
    name: str = Field(..., min_length=1, max_length=255)


class DepartmentFileFolderOut(BaseModel):
    id: int
    department: int
    name: str
    files_count: int
    created_by: int | None
    created_by_name: str | None
    created_at: datetime


class DepartmentFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    folder: int
    file_folder: int | None
    name: str
    file: str
    file_url: str
    file_size: int
    uploaded_by: int | None
    uploaded_by_name: str | None
    description: str
    created_at: datetime

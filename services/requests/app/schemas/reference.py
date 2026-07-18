from datetime import datetime

from pydantic import BaseModel, Field


class ReferenceSourceCreate(BaseModel):
    slug: str | None = Field(None, max_length=64)
    name: str = Field(..., min_length=1, max_length=200)
    columns: list[str] = Field(default_factory=list)


class ReferenceSourceUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    columns: list[str] | None = None


class ReferenceSourceResponse(BaseModel):
    id: int
    slug: str
    name: str
    columns: list[str]
    template_id: int | None = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class ReferenceRowCreate(BaseModel):
    data: dict


class ReferenceRowResponse(BaseModel):
    id: int
    source_id: int
    data: dict
    model_config = {"from_attributes": True}


class DataTableResponse(BaseModel):
    id: int
    slug: str
    name: str
    columns: list[str]
    template_id: int | None
    access_ids: list[int]
    can_manage: bool


class AccessUpdate(BaseModel):
    viewer_ids: list[int]

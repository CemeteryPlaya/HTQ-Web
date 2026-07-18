from datetime import datetime

from pydantic import BaseModel, Field


class TemplateCreate(BaseModel):
    project_id: int | None = None
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    icon: str = Field(default="", max_length=50)
    color: str = Field(default="#3b82f6", max_length=20)
    config_json: dict = Field(default_factory=dict)


class TemplateUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=5000)
    icon: str | None = Field(None, max_length=50)
    color: str | None = Field(None, max_length=20)
    config_json: dict | None = None
    is_active: bool | None = None


class TemplateResponse(BaseModel):
    id: int
    project_id: int | None = None
    name: str
    slug: str
    description: str
    icon: str
    color: str
    config_json: dict = Field(default_factory=dict)
    is_active: bool
    status: str = "active"
    created_by: int | None = None
    current_version_id: int | None = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class VersionPublish(BaseModel):
    schema_json: dict
    workflow_json: dict


class VersionResponse(BaseModel):
    id: int
    template_id: int
    version: int
    schema_json: dict
    workflow_json: dict
    published_at: datetime
    published_by: int | None = None
    model_config = {"from_attributes": True}


class PreviewRequest(BaseModel):
    schema_json: dict
    workflow_json: dict


class PreviewResponse(BaseModel):
    valid: bool
    field_keys: list[str]
    node_count: int

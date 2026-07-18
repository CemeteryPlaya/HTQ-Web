from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class InstanceCreate(BaseModel):
    template_id: int
    title: str = Field("", max_length=300)
    project_id: int | None = None
    form_values: dict = Field(default_factory=dict)
    on_behalf_of: int | None = None


class InstanceUpdate(BaseModel):
    title: str | None = Field(None, max_length=300)
    form_values: dict | None = None


class ActionRequest(BaseModel):
    comment: str = Field("", max_length=4000)


class BatchActionRequest(BaseModel):
    ids: list[int]
    comment: str = ""


class InstanceResponse(BaseModel):
    id: int
    code: str
    template_id: int
    template_version_id: int
    project_id: int | None = None
    initiator_id: int
    title: str
    status: str
    current_node_id: str | None = None
    form_values_json: dict
    total_amount: Decimal | None = None
    currency: str | None = None
    submitted_at: datetime | None = None
    finalized_at: datetime | None = None
    requires_admin_attention: bool
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

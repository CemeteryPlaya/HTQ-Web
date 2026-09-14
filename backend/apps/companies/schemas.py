"""Контракт ``/api/companies/v1`` — план блока A, раздел «Контракт API».

Изменение формы — только вслед за правкой плана: фронт (``src/types/companies.ts``)
собран по этой же таблице.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from apps.companies.models import CompanyKind


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    kind: str
    status: str
    country: str
    parent_slug: str | None
    archived_at: datetime | None


class CompanyTreeNode(BaseModel):
    slug: str
    name: str
    kind: str
    status: str
    country: str
    children: list[CompanyTreeNode] = Field(default_factory=list)


class MyCompany(BaseModel):
    slug: str
    name: str
    kind: str
    is_default: bool
    is_current: bool


class CompanyPatch(BaseModel):
    """Правка реестровых полей. Slug не правится: он — имя схемы и поддомен.

    ``parent_slug=None`` в теле — «без родителя»; отсутствие ключа — «не
    трогать». Разница читается через ``model_fields_set`` во вьюхе.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    kind: str | None = None
    country: str | None = Field(default=None, max_length=2)
    parent_slug: str | None = None

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str | None) -> str | None:
        if value is not None and value not in CompanyKind.values:
            raise ValueError(f"kind должен быть одним из {list(CompanyKind.values)}")
        return value


class ModuleRead(BaseModel):
    app_label: str
    enabled: bool
    message: str
    is_core: bool


class ModulePatch(BaseModel):
    enabled: bool
    message: str | None = Field(default=None, max_length=200)


class MembershipRead(BaseModel):
    user_id: int
    username: str
    full_name: str
    email: str
    is_active: bool
    is_default: bool


class MembershipCreate(BaseModel):
    user_id: int = Field(gt=0)
    is_default: bool = False

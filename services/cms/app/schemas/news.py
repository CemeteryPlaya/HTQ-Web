"""Pydantic schemas for News + taxonomy (categories, tags)."""

import uuid
from datetime import datetime
from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.models.news import NewsStatus


# --- Taxonomy --------------------------------------------------------------


class CategoryBase(BaseModel):
    slug: str = Field(..., max_length=120, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(..., max_length=160, min_length=1)
    description: str = Field("", max_length=500)


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    slug: Optional[str] = Field(None, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: Optional[str] = Field(None, max_length=160, min_length=1)
    description: Optional[str] = Field(None, max_length=500)


class CategoryRead(CategoryBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


class TagBase(BaseModel):
    slug: str = Field(..., max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(..., max_length=80, min_length=1)


class TagCreate(TagBase):
    pass


class TagUpdate(BaseModel):
    slug: Optional[str] = Field(None, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: Optional[str] = Field(None, max_length=80, min_length=1)


class TagRead(TagBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


# --- News ------------------------------------------------------------------


class NewsBase(BaseModel):
    title: str = Field(..., max_length=300, min_length=1)
    slug: str = Field(..., max_length=320, min_length=1)
    excerpt: str = Field("", max_length=500)
    content: str = ""
    image: Optional[str] = Field(None, max_length=500)
    category_id: Optional[int] = None
    author_id: Optional[int] = None
    status: NewsStatus = NewsStatus.DRAFT
    scheduled_at: Optional[datetime] = None


class NewsCreate(NewsBase):
    tag_ids: list[int] = Field(default_factory=list)


class NewsUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=300, min_length=1)
    slug: Optional[str] = Field(None, max_length=320, min_length=1)
    excerpt: Optional[str] = Field(None, max_length=500)
    content: Optional[str] = None
    image: Optional[str] = Field(None, max_length=500)
    category_id: Optional[int] = None
    author_id: Optional[int] = None
    status: Optional[NewsStatus] = None
    scheduled_at: Optional[datetime] = None
    tag_ids: Optional[list[int]] = None
    # Legacy compatibility — accepted but mapped onto `status`.
    published: Optional[bool] = None


class NewsRead(NewsBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    published: bool
    published_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    category: Optional[CategoryRead] = Field(default=None, validation_alias="category_ref")
    tags: list[TagRead] = Field(default_factory=list)
    # Legacy denormalized fields for transitional clients.
    summary: str = ""


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int
    has_next: bool


class NewsTranslateRequest(BaseModel):
    target: str = Field("en", min_length=2, max_length=10)


class NewsTranslateResponse(BaseModel):
    task_id: str
    news_id: int
    target: str
    status: str = "queued"


class NewsAttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    news_id: int
    role: str
    filename: str
    size: int
    content_type: str
    storage_path: str
    created_at: datetime

    @computed_field  # type: ignore[misc]
    @property
    def url(self) -> str:
        """Fresh signed redirect URL — works inside ``<img src>``."""
        from app.services.signed_url import signed_query

        return f"/api/cms/v1/news/attachments/{self.id}?{signed_query(str(self.id))}"

"""Common schemas."""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class DateWarning(BaseModel):
    """Date calculation warning."""

    code: str
    message: str


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated response wrapper."""

    count: int
    next: str | None = None
    previous: str | None = None
    results: list[T]

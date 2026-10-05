"""Тела запросов подотчёта (B4.1)."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class AccountableCreate(BaseModel):
    project_id: UUID
    article_id: UUID
    amount: Decimal = Field(max_digits=18, decimal_places=2)
    goal: str = Field(min_length=1, max_length=2000)


class AccountableUpdate(BaseModel):
    version: int | None = None
    project_id: UUID | None = None
    article_id: UUID | None = None
    amount: Decimal | None = Field(default=None, max_digits=18, decimal_places=2)
    goal: str | None = Field(default=None, max_length=2000)


class VersionOnly(BaseModel):
    version: int | None = None

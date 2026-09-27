"""Тела запросов бюджета (ТЗ §23: CreateBudget, UpdateBudget, корректировка).

Изменяющие операции несут ``version`` записи — оптимистическая блокировка
(E-CON-01, D-29); ``None`` — клиент версию не прислал, проверка пропускается.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class BudgetLineIn(BaseModel):
    article_id: UUID
    limit_amount: Decimal = Field(default=Decimal("0"), max_digits=18, decimal_places=2)
    comment: str = Field(default="", max_length=255)


class BudgetCreate(BaseModel):
    project_id: UUID
    currency: str = Field(default="KZT", min_length=3, max_length=3)
    date_from: date | None = None
    date_to: date | None = None
    lines: list[BudgetLineIn] = Field(default_factory=list)


class BudgetUpdate(BaseModel):
    version: int | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    date_from: date | None = None
    date_to: date | None = None
    lines: list[BudgetLineIn] | None = None


class VersionOnly(BaseModel):
    version: int | None = None


class CorrectionSave(BaseModel):
    version: int | None = None
    lines: list[BudgetLineIn]
    comment: str = Field(default="", max_length=1000)


class WithComment(BaseModel):
    version: int | None = None
    comment: str = Field(default="", max_length=1000)

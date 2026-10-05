"""Тела запросов альтернативных предложений (ТЗ §12, A5.1, задача 2).

Схема проверяет только типы. Диапазоны цен и сумм, длину обоснования, даты и
уникальность контрагента проверяет сервис (``services/alternatives/offers.py``):
отказ приходит кодом модуля на своём поле, а не общей ошибкой схемы, а
значение за пределами столбца — ``E-VAL-01``, а не ошибка БД.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

SourceType = Literal["invoice", "agreement"]


class OfferCreate(BaseModel):
    source_type: SourceType
    source_id: UUID


class OfferLineIn(BaseModel):
    source_line_id: UUID
    price: Decimal | None = None


class OfferUpdate(BaseModel):
    version: int | None = None
    counterparty_id: UUID | None = None
    currency_code: str | None = Field(default=None, max_length=8)
    delivery_date: date | None = None
    payment_terms: str | None = Field(default=None, max_length=16)
    payment_terms_note: str | None = None
    justification: str | None = None
    with_vat: bool | None = None
    vat_rate: Decimal | None = None
    lines: list[OfferLineIn] | None = None


class OfferVersion(BaseModel):
    version: int | None = None


class LimitBody(BaseModel):
    limit: int

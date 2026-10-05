"""Схемы ручек справочников. PATCH-схемы: поле ``None`` — «не пришло»."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field


class CountryIn(BaseModel):
    code: str = Field(..., min_length=2, max_length=2)
    name: str = Field(..., min_length=1, max_length=128)


class CountryPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    is_active: Optional[bool] = None


class CurrencyIn(BaseModel):
    code: str = Field(..., min_length=3, max_length=3)
    name: str = Field(..., min_length=1, max_length=64)
    symbol: str = Field("", max_length=8)


class CurrencyPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=64)
    symbol: Optional[str] = Field(None, max_length=8)
    is_active: Optional[bool] = None


class RateIn(BaseModel):
    currency_code: str = Field(..., min_length=3, max_length=3)
    on_date: date
    rate: Decimal = Field(..., gt=0, max_digits=18, decimal_places=6)


class VatIn(BaseModel):
    country_code: str = Field(..., min_length=2, max_length=2)
    rate: Decimal = Field(..., ge=0, le=100, max_digits=5, decimal_places=2)
    date_from: date
    date_to: Optional[date] = None


class MrpIn(BaseModel):
    date_from: date
    value: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2)


class UomIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=16)
    short_name: str = Field(..., min_length=1, max_length=16)
    name: str = Field(..., min_length=1, max_length=64)


class UomPatch(BaseModel):
    short_name: Optional[str] = Field(None, min_length=1, max_length=16)
    name: Optional[str] = Field(None, min_length=1, max_length=64)
    is_active: Optional[bool] = None


class ArticleGroupIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=128)
    node_key: str = Field(..., min_length=1, max_length=128)


class ArticleGroupPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    is_active: Optional[bool] = None


class ArticleIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=255)
    group_id: str
    parent_id: Optional[str] = None
    ext_1c_ref: str = Field("", max_length=64)


class ArticlePatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    is_active: Optional[bool] = None
    ext_1c_ref: Optional[str] = Field(None, max_length=64)


DayType = Literal["working", "weekend", "holiday", "short"]


class ProductionDayUpdate(BaseModel):
    day_type: DayType
    note: Optional[str] = Field(None, max_length=255)


class ProductionDayResponse(BaseModel):
    date: date
    day_type: DayType
    working_days_since_epoch: int
    note: Optional[str] = None
    # Может ли пользователь править день: узел + управляющая компания (для кнопки).
    can_edit: bool = False

    model_config = {"from_attributes": True}

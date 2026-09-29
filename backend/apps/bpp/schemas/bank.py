"""Тела запросов справочника «Счета организации и шаблоны выписок» (ТЗ §18,
задача A3.1).

Схема проверяет только типы и длины: правила (IBAN mod 97, обязательные
колонки шаблона, маска даты) — в ``services/bank/settings.py``, чтобы отказ
пришёл кодом модуля, а не общей ошибкой схемы.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    format: str = Field(min_length=1, max_length=8)
    encoding: str | None = Field(default=None, max_length=32)
    delimiter: str | None = Field(default=None, max_length=4)
    date_format: str | None = Field(default=None, max_length=32)
    columns: dict[str, str] = Field(default_factory=dict)
    amount_mode: str | None = Field(default=None, max_length=8)


class TemplateUpdate(BaseModel):
    version: int | None = None
    name: str | None = Field(default=None, max_length=255)
    format: str | None = Field(default=None, max_length=8)
    encoding: str | None = Field(default=None, max_length=32)
    delimiter: str | None = Field(default=None, max_length=4)
    date_format: str | None = Field(default=None, max_length=32)
    columns: dict[str, str] | None = None
    amount_mode: str | None = Field(default=None, max_length=8)
    is_active: bool | None = None


class AccountCreate(BaseModel):
    iban: str = Field(min_length=1, max_length=64)
    bank_name: str = Field(default="", max_length=255)
    bic: str = Field(min_length=1, max_length=32)
    currency: str = Field(default="KZT", min_length=3, max_length=3)
    template_id: str = Field(min_length=1, max_length=64)


class AccountUpdate(BaseModel):
    version: int | None = None
    iban: str | None = Field(default=None, min_length=1, max_length=64)
    bank_name: str | None = Field(default=None, max_length=255)
    bic: str | None = Field(default=None, min_length=1, max_length=32)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    template_id: str | None = Field(default=None, min_length=1, max_length=64)
    is_active: bool | None = None

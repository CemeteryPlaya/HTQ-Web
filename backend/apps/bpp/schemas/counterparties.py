"""Тела запросов справочника «Контрагенты» (ТЗ §18, §23).

Реквизиты (БИН/ИИН, IBAN, БИК) здесь проверяются только по длине строки:
правило и текст ошибки — в ``services/counterparties/validation.py``, чтобы
отказ пришёл кодом ТЗ (E-CTR-03/04), а не общей ошибкой схемы.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Kind = Literal["legal", "ip", "individual", "nonresident"]


class CounterpartyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    short_name: str = Field(default="", max_length=255)
    kind: Kind
    country_code: str = Field(min_length=2, max_length=2)
    reg_number: str = Field(min_length=1, max_length=64)  # до нормализации
    is_vat_payer: bool = False
    vat_cert_series: str = Field(default="", max_length=32)
    vat_cert_number: str = Field(default="", max_length=32)
    legal_address: str = Field(default="", max_length=1000)
    contact_person: str = Field(default="", max_length=255)
    phone: str = Field(default="", max_length=64)
    email: str = Field(default="", max_length=254)
    ext_1c_ref: str = Field(default="", max_length=64)


class CounterpartyUpdate(BaseModel):
    version: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=500)
    short_name: str | None = Field(default=None, max_length=255)
    kind: Kind | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    reg_number: str | None = Field(default=None, min_length=1, max_length=64)
    is_vat_payer: bool | None = None
    vat_cert_series: str | None = Field(default=None, max_length=32)
    vat_cert_number: str | None = Field(default=None, max_length=32)
    legal_address: str | None = Field(default=None, max_length=1000)
    contact_person: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=254)
    ext_1c_ref: str | None = Field(default=None, max_length=64)


class VersionOnly(BaseModel):
    version: int | None = None


class BlockIn(BaseModel):
    version: int | None = None
    reason: str = Field(default="", max_length=1000)


class VerifiedIn(BaseModel):
    """``verified``: ``true``/``false`` — решение ФД поверх порога, ``null`` —
    вернуть метку порогу. Поле обязательно: пустое тело не должно молча
    снимать ручное решение."""

    version: int | None = None
    verified: bool | None


class BankAccountCreate(BaseModel):
    iban: str = Field(min_length=1, max_length=64)
    bank_name: str = Field(default="", max_length=255)
    bic: str = Field(min_length=1, max_length=32)
    currency: str = Field(default="KZT", min_length=3, max_length=3)
    is_primary: bool = False


class BankAccountUpdate(BaseModel):
    iban: str | None = Field(default=None, min_length=1, max_length=64)
    bank_name: str | None = Field(default=None, max_length=255)
    bic: str | None = Field(default=None, min_length=1, max_length=32)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    is_primary: bool | None = None
    is_active: bool | None = None

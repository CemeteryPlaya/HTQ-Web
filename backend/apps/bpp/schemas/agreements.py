"""Тела запросов договора (ТЗ §09, §23: CreateAgreement, SubmitAgreement).

Изменяющие операции несут ``version`` записи — оптимистическая блокировка
(E-CON-01, D-29); ``None`` — клиент версию не прислал, проверка пропускается.
Черновик сохраняется без обязательных полей: полноту проверяет «Отправить».
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

Role = Literal["sn", "pm"]
Kind = Literal["goods", "works", ""]


class AgreementFromPlan(BaseModel):
    item_ids: list[UUID] = Field(min_length=1)
    role: Role | None = None


class AgreementItemIn(BaseModel):
    id: UUID | None = None
    request_item_id: UUID | None = None
    qty: Decimal = Field(max_digits=15, decimal_places=3)
    amount: Decimal | None = Field(default=None, max_digits=18, decimal_places=2)


class AgreementUpdate(BaseModel):
    version: int | None = None
    counterparty_id: UUID | None = None
    name: str | None = Field(default=None, max_length=500)
    ext_number: str | None = Field(default=None, max_length=50)
    ext_date: date | None = None
    agreement_type: Kind | None = None
    is_open: bool | None = None
    amount: Decimal | None = Field(default=None, max_digits=18, decimal_places=2)
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    with_vat: bool | None = None
    # Ручная ставка НДС (D-14); ``null`` — вернуть ставку справочника.
    vat_rate: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5,
                                     decimal_places=2)
    valid_to: date | None = None
    items: list[AgreementItemIn] | None = None


class AgreementSubmit(BaseModel):
    version: int | None = None
    counterparty_confirmed: bool = False


class VersionOnly(BaseModel):
    version: int | None = None


class WithComment(BaseModel):
    version: int | None = None
    comment: str = Field(default="", max_length=1000)

"""Тела запросов счёта (ТЗ §10, §23: CreateInvoice, SubmitInvoice,
DecideInvoice, MarkInvoicePaid).

Изменяющие операции несут ``version`` записи (E-CON-01, D-29); ``None`` —
клиент версию не прислал. Черновик сохраняется без обязательных полей.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

Role = Literal["sn", "pm"]


class InvoiceCreate(BaseModel):
    """Из плана (``item_ids``) или из договора (``agreement_id`` и, по желанию,
    ``item_ids`` — позиции договора)."""
    item_ids: list[UUID] = Field(default_factory=list)
    agreement_id: UUID | None = None
    role: Role | None = None


class InvoiceLineIn(BaseModel):
    id: UUID | None = None
    request_item_id: UUID | None = None
    qty: Decimal = Field(max_digits=15, decimal_places=3)
    amount: Decimal = Field(max_digits=18, decimal_places=2)


class InvoiceUpdate(BaseModel):
    version: int | None = None
    basis: Literal["no_contract"] | None = None
    counterparty_id: UUID | None = None
    ext_number: str | None = Field(default=None, max_length=50)
    ext_date: date | None = None
    amount: Decimal | None = Field(default=None, max_digits=18, decimal_places=2)
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    rate: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=6)
    with_vat: bool | None = None
    vat_rate: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5,
                                     decimal_places=2)
    purchase_type: Literal["goods", "works"] | None = None
    is_advance: bool | None = None
    due_date: date | None = None
    author_comment: str | None = Field(default=None, max_length=1000)
    lines: list[InvoiceLineIn] | None = None


class InvoiceSubmit(BaseModel):
    version: int | None = None
    counterparty_confirmed: bool = False


class Decision(BaseModel):
    decision: Literal["pay", "not_payable", "return"]
    planned_pay_date: date | None = None
    comment: str = Field(default="", max_length=1000)


class BatchDecision(BaseModel):
    invoice_ids: list[UUID] = Field(min_length=1, max_length=200)
    decision: Literal["pay", "not_payable"]
    planned_pay_date: date | None = None
    comment: str = Field(default="", max_length=1000)


class Payment(BaseModel):
    pay_date: date
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    pp_number: str = Field(default="", max_length=50)
    rate: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=6)


class DocsRequest(BaseModel):
    avr: bool = False
    waybill: bool = False
    vat_invoice: bool = False
    comment: str = Field(default="", max_length=1000)


class VersionOnly(BaseModel):
    version: int | None = None


class WithComment(BaseModel):
    version: int | None = None
    comment: str = Field(default="", max_length=1000)


class SelectAlternative(BaseModel):
    """SelectAlternativeOffer (ТЗ §26): АП, комментарий, версия исходного счёта."""
    offer_id: UUID
    version: int | None = None
    comment: str = Field(default="", max_length=1000)

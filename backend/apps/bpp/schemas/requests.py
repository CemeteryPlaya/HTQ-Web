"""Тела запросов заявки и плана закупок (ТЗ §23).

Черновик сохраняется без обязательных полей шапки, кроме проекта (ТЗ §7.7):
полноту проверяет «Отправить» (E-REQ-01).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

Role = Literal["sn", "pm"]
Kind = Literal["goods", "works", ""]


class ItemIn(BaseModel):
    name: str = Field(default="", max_length=500)
    specs: str = Field(default="", max_length=2000)
    uom_id: UUID | None = None
    qty: Decimal = Field(default=Decimal("0"), max_digits=15, decimal_places=3)
    price: Decimal = Field(default=Decimal("0"), max_digits=18, decimal_places=2)
    need_date: date | None = None


class RequestCreate(BaseModel):
    initiator_role: Role | None = None
    project_id: UUID | None = None
    article_id: UUID | None = None
    purchase_type: Kind = ""
    need_date: date | None = None
    justification: str = Field(default="", max_length=2000)
    items: list[ItemIn] = Field(default_factory=list)


class RequestUpdate(BaseModel):
    version: int | None = None
    initiator_role: Role | None = None
    project_id: UUID | None = None
    article_id: UUID | None = None
    purchase_type: Kind | None = None
    need_date: date | None = None
    justification: str | None = Field(default=None, max_length=2000)
    items: list[ItemIn] | None = None


class VersionOnly(BaseModel):
    version: int | None = None


class WithComment(BaseModel):
    version: int | None = None
    comment: str = Field(default="", max_length=1000)


class PlanValidate(BaseModel):
    item_ids: list[UUID]
    target: Literal["contract", "invoice"]
    role: Role | None = None


class PlanReassign(BaseModel):
    item_ids: list[UUID] = Field(min_length=1)
    to_user_id: int

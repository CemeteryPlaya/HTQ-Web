"""Схемы стыка с тендерным модулем — пакет B-1 (T1.2, пошаговый план
2026-10-07 §2, мастер-план tender §3.4).

``apps.tender`` импортирует только ``apps.bpp.interface`` (сторож изоляции),
поэтому эти классы реэкспортируются оттуда: ``bpp.interface.TenderRequestSubmit``
и т. д. Деньги — ``Decimal(18,2)``, количества — ``Decimal(15,3)``, как у
заявки БЗО.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "BudgetArticle", "BudgetFigures", "RequestRef", "RequestStatusOut", "TenderActor",
    "TenderItemIn", "TenderPartIn", "TenderRequestSubmit",
]


class TenderActor(BaseModel):
    """От чьего имени действует tender: права и группы статей — его
    собственные в БЗО (T-20)."""
    user_id: int
    is_superuser: bool = False


class TenderItemIn(BaseModel):
    name: str = Field(max_length=500)
    specs: str = Field(default="", max_length=2000)
    uom_id: str
    qty: Decimal = Field(max_digits=15, decimal_places=3)
    price: Decimal = Field(max_digits=18, decimal_places=2)
    need_date: date


class TenderPartIn(BaseModel):
    #: Ключ части у tender (UUID ``TenderRequestPart`` строкой) — им
    #: помечается ошибка части (``DomainError.details["part"]``).
    key: str
    #: ``None`` — завести ЗЗ; иначе — пересобрать эту (только «Черновик» и
    #: «На доработке»).
    bpp_request_id: str | None = None
    article_id: str
    purchase_type: Literal["goods", "works"]
    items: list[TenderItemIn] = Field(min_length=1)


class TenderRequestSubmit(BaseModel):
    actor: TenderActor
    initiator_role: Literal["sn", "pm"]
    project_id: str
    tender_number: str = Field(min_length=1, max_length=32)
    justification: str = Field(max_length=2000)
    need_date: date
    parts: list[TenderPartIn] = Field(min_length=1)


class RequestRef(BaseModel):
    key: str
    bpp_request_id: str
    number: str
    status: str
    #: id позиций ЗЗ — в порядке ``items`` части.
    items: list[str]


class RequestStatusOut(BaseModel):
    bpp_request_id: str
    number: str
    status: str
    status_comment: str = ""
    rework_comment: str = ""


class BudgetFigures(BaseModel):
    limit: Decimal
    committed: Decimal
    available: Decimal
    currency_code: str


class BudgetArticle(BaseModel):
    id: str
    code: str
    name: str
    group_code: str
    available: Decimal

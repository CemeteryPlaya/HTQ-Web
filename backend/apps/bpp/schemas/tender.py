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
    "BudgetArticle", "BudgetFigures", "ClosingFileIn", "CounterpartyRef", "DocumentRef",
    "DocumentStatusOut", "HandoverDocIn", "HandoverLineIn", "ProspectIn", "RequestRef",
    "RequestStatusOut", "ReplacedBy", "TenderActor", "TenderHandover", "TenderItemIn",
    "TenderPartIn", "TenderRequestSubmit",
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


# ── этап 5 тендера (T5.4, зона A) ─────────────────────────────────────────

class ProspectIn(BaseModel):
    """Реквизиты потенциального поставщика из портала — для карточки контрагента."""
    name: str = Field(min_length=2, max_length=500)
    country_code: str = Field(default="KZ", max_length=2)
    reg_number: str = Field(default="", max_length=30)
    is_vat_payer: bool = False
    contact_name: str = Field(default="", max_length=255)
    phone: str = Field(default="", max_length=64)
    email: str = Field(default="", max_length=254)
    tender_number: str = Field(default="", max_length=32)


class CounterpartyRef(BaseModel):
    """Карточка контрагента: ``created`` — заведена сейчас, иначе найдена."""
    id: str
    created: bool
    status: str


# ── пакет B-2: документы из тендера (T5.3) ────────────────────────────────

class HandoverLineIn(BaseModel):
    """Строка документа: позиция ЗЗ, количество и сумма к оплате (с НДС, если
    поставщик плательщик) в валюте документа. Позиция не указана — единственная
    позиция ЗЗ (доставка и СМР — ЗЗ из одной позиции)."""
    bpp_request_item_id: str | None = None
    qty: Decimal = Field(gt=0, max_digits=15, decimal_places=3)
    amount: Decimal = Field(ge=0, max_digits=18, decimal_places=2)


class HandoverDocIn(BaseModel):
    """Документ «поставщик × ЗЗ»: ``key`` — ключ идемпотентности передачи."""
    key: str = Field(min_length=1, max_length=80)
    bpp_request_id: str
    counterparty_id: str
    currency_code: str = Field(min_length=3, max_length=3)
    with_vat: bool
    vat_rate: Decimal | None = None
    kind: Literal["agreement", "invoice"]
    payment: Literal["prepay", "advance", "postpay"]
    postpay_days: int | None = Field(default=None, ge=1, le=365)
    lines: list[HandoverLineIn] = Field(min_length=1)
    #: Файлы КП победителя (``media_file_id``) — в документ файлом КП.
    offer_media_file_ids: list[str] = []


class TenderHandover(BaseModel):
    actor: TenderActor
    tender_number: str = Field(min_length=1, max_length=32)
    docs: list[HandoverDocIn] = Field(min_length=1)


class DocumentRef(BaseModel):
    key: str
    doc_type: Literal["agreement", "invoice"]
    doc_id: str
    number: str
    status: str


class ReplacedBy(BaseModel):
    """Документ заменён альтернативой БЗО (T-18): новый документ."""
    doc_type: str | None
    doc_id: str | None
    number: str | None
    offer_number: str


class DocumentStatusOut(BaseModel):
    """Документ ЗЗ для стадий поставки тендера."""
    request_id: str
    doc_type: Literal["agreement", "invoice"]
    doc_id: str
    number: str
    status: str
    amount: Decimal | None
    currency_code: str
    counterparty_id: str | None
    agreement_id: str | None = None
    paid_amount: Decimal = Decimal("0")
    is_advance: bool = False
    pay_after_receipt: bool = False
    due_date: date | None = None
    docs_required: dict = {}
    received_at: date | None = None
    tender_key: str = ""
    replaced_by: ReplacedBy | None = None


class ClosingFileIn(BaseModel):
    """Скан закрывающего документа, уже лежащий в хранилище (``media_file_id``)."""
    media_file_id: str
    file_type: Literal["waybill", "act", "vat_invoice"]
    name: str = ""

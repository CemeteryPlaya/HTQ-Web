"""Тела запросов тендерного модуля.

Схемы держат только ТИПЫ (ключ, дата, число): значения — длину наименования,
«больше нуля», существование статьи — проверяет сервис и отвечает конвертом
``{detail, code, fields: [{field, message}]}`` с именами полей тела
(``items[0].qty``), который читает форма. Черновик сохраняется без
обязательных полей шапки, кроме проекта: полноту проверяет отправка (T1.3).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

Role = Literal["sn", "pm"]
Kind = Literal["goods", "works"]


class RequestItemIn(BaseModel):
    #: Ключ существующей позиции — правка на месте; пусто — новая позиция.
    id: UUID | None = None
    name: str = ""
    specs: str = ""
    uom_id: UUID | None = None
    qty: Decimal | None = None
    plan_price: Decimal | None = None
    need_date: date | None = None
    article_id: UUID | None = None


class RequestCreate(BaseModel):
    initiator_role: Role | None = None
    project_id: UUID | None = None
    article_id: UUID | None = None
    purchase_type: Kind = "goods"
    need_date: date | None = None
    delivery_address: str = ""
    justification: str = ""
    needs_delivery: bool = False
    delivery_article_id: UUID | None = None
    delivery_plan_amount: Decimal | None = None
    needs_works: bool = False
    works_scope: str = ""
    works_article_id: UUID | None = None
    works_plan_amount: Decimal | None = None
    allow_analogs: bool = False
    allow_partial: bool = True
    items: list[RequestItemIn] = Field(default_factory=list)


class RequestUpdate(BaseModel):
    """Правка черновика: меняются только переданные поля (``exclude_unset``)."""

    version: int | None = None
    initiator_role: Role | None = None
    project_id: UUID | None = None
    article_id: UUID | None = None
    purchase_type: Kind | None = None
    need_date: date | None = None
    delivery_address: str | None = None
    justification: str | None = None
    needs_delivery: bool | None = None
    delivery_article_id: UUID | None = None
    delivery_plan_amount: Decimal | None = None
    needs_works: bool | None = None
    works_scope: str | None = None
    works_article_id: UUID | None = None
    works_plan_amount: Decimal | None = None
    allow_analogs: bool | None = None
    allow_partial: bool | None = None
    items: list[RequestItemIn] | None = None


class RequestAction(BaseModel):
    """Отправка, отзыв, исключение части (T1.3): версия карточки."""

    version: int | None = None


class RequestCancel(RequestAction):
    """Отмена (T1.3): причина ≥ 10 символов проверяется сервисом."""

    comment: str = ""


# ════════════════════════════════════════════════════════════════════════════
# Тендеры и участники (T2.1, T2.2; план этапов 0–2, §4.3). Блок ведёт
# исполнитель тендеров — заявочные схемы выше сюда не переносить.
# ════════════════════════════════════════════════════════════════════════════

from datetime import datetime  # noqa: E402  (блок дописан к файлу, импорт — его)


class TenderCreate(BaseModel):
    request_id: UUID
    deadline_at: datetime | None = None
    currency_code: str = "KZT"
    delivery_terms: str = ""
    quality_reviewer_user_id: int | None = None


class TenderUpdate(BaseModel):
    """Правка черновика (и проверяющего — до утверждения выбора): меняются
    только переданные поля (``exclude_unset``)."""

    version: int | None = None
    deadline_at: datetime | None = None
    currency_code: str | None = None
    delivery_terms: str | None = None
    quality_reviewer_user_id: int | None = None


class PaymentSchemeIn(BaseModel):
    """Без ``version`` (контракт фронта T2.3). ``kind`` строкой: неизвестную
    схему отвергает сервис полем ``kind``, а не общей ошибкой типа."""

    kind: str
    advance_pct: Decimal | None = None
    postpay_days: int | None = None


class TenderVersion(BaseModel):
    version: int | None = None


class TenderExtend(BaseModel):
    version: int | None = None
    deadline_at: datetime


class TenderCancel(BaseModel):
    version: int | None = None
    reason: str = ""


class InvitationIn(BaseModel):
    """``{counterparty_id, contact_id?}`` или ``{prospect_id}``."""

    counterparty_id: UUID | None = None
    contact_id: UUID | None = None
    prospect_id: UUID | None = None


class ContactIn(BaseModel):
    counterparty_id: UUID | None = None
    email: str = ""
    name: str = ""
    phone: str = ""
    is_primary: bool = False
    is_active: bool = True


class ContactUpdate(BaseModel):
    email: str | None = None
    name: str | None = None
    phone: str | None = None
    is_primary: bool | None = None
    is_active: bool | None = None


class ProspectIn(BaseModel):
    name: str = ""
    email: str = ""
    reg_number: str = ""
    country_code: str = "KZ"


class ProspectUpdate(BaseModel):
    version: int | None = None
    name: str | None = None
    email: str | None = None
    reg_number: str | None = None
    country_code: str | None = None



# ── портал поставщика: предложение (T3.3) ───────────────────────────────
# Только ТИПЫ; значения проверяет ``services/portal/offers.py`` и отвечает
# конвертом ``fields`` с именами полей тела (``lines[0].price``).

class PortalLineIn(BaseModel):
    item_id: str
    participates: bool | None = None
    price: Decimal | None = None
    qty: Decimal | None = None
    delivery_date: date | None = None
    is_analog: bool | None = None
    analog_note: str | None = None
    comment: str | None = None


class PortalExtraIn(BaseModel):
    amount: Decimal | None = None
    included_in_price: bool | None = None
    note: str | None = None


class PortalSchemeIn(BaseModel):
    kind: str
    advance_pct: Decimal | None = None
    postpay_days: int | None = None


class PortalOfferIn(BaseModel):
    """``PUT supplier/<token>/offer``: меняются только переданные блоки.
    ``version`` обязателен — без него правка шла бы мимо оптимистичной
    блокировки (две вкладки затирали бы друг друга молча)."""

    version: int
    currency_code: str | None = None
    with_vat: bool | None = None
    vat_rate: Decimal | None = None
    valid_until: date | None = None
    extra_terms: str | None = None
    lines: list[PortalLineIn] | None = None
    extras: dict[str, PortalExtraIn] | None = None
    payment_scheme: PortalSchemeIn | None = None
    requisites: dict[str, str | bool | None] | None = None


class PortalSubmitIn(BaseModel):
    version: int
    pd_consent: bool = False


class AwardLineIn(BaseModel):
    line_id: str
    qty: Decimal | None = None
    comment: str = ""


class AwardExtraIn(BaseModel):
    extra_id: str
    comment: str = ""


class AwardIn(BaseModel):
    """``PUT tenders/<id>/award`` — выбор целиком: прежний заменяется."""
    version: int
    comment: str = ""
    lines: list[AwardLineIn] = []
    extras: list[AwardExtraIn] = []


class ReceiptLineIn(BaseModel):
    award_id: str
    qty: Decimal


class ReceiptIn(BaseModel):
    """``POST tenders/<id>/receipts`` — приёмка товара или работ."""
    invitation_id: str
    received_at: date
    kind: str = "goods"
    lines: list[ReceiptLineIn] = []
    comment: str = ""
    originals_at: date | None = None
    originals_to: str = ""


class ReceiptOriginalsIn(BaseModel):
    originals_at: date | None = None
    originals_to: str = ""


class ReceiptCancelIn(BaseModel):
    comment: str = ""


class PortalVersionIn(BaseModel):
    version: int


class PortalDeclineIn(BaseModel):
    reason: str = ""

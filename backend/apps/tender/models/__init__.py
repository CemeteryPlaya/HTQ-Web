"""Модели тендерного модуля (docs/plans/2026-10-06-tender-master-plan.md, §3.2).

Тенантные: таблицы живут в схеме компании, поля компании нет и быть не
должно (CLAUDE.md, «Мультикомпанейность»). Ссылки на bpp/project/refdata —
голые UUIDField без FK: между аппками связь только через interface.
"""

from .core import AuditLog, NumberSequence, TenderModel, VersionedModel
from .offer import ExtraKind, Offer, OfferExtra, OfferLine, OfferStatus
from .portal import PortalEvent, PortalEventKind
from .request import (
    InitiatorRole,
    PartKind,
    PurchaseType,
    TenderRequest,
    TenderRequestItem,
    TenderRequestPart,
    TenderRequestStatus,
)
from .supplier import (
    DeviceBinding,
    Invitation,
    InvitationStatus,
    SupplierContact,
    SupplierProspect,
)
from .tender import (
    ACTIVE_TENDER_STATUSES,
    PaymentKind,
    PaymentScheme,
    PaymentStage,
    PaymentTrigger,
    Tender,
    TenderStatus,
)

__all__ = [
    "PortalEvent", "PortalEventKind",
    "ExtraKind", "Offer", "OfferExtra", "OfferLine", "OfferStatus",
    "ACTIVE_TENDER_STATUSES", "DeviceBinding", "Invitation", "InvitationStatus",
    "PaymentKind", "PaymentScheme", "PaymentStage", "PaymentTrigger", "SupplierContact",
    "SupplierProspect", "Tender", "TenderStatus",
    "AuditLog", "InitiatorRole", "NumberSequence", "PartKind", "PurchaseType",
    "TenderModel", "TenderRequest", "TenderRequestItem", "TenderRequestPart",
    "TenderRequestStatus", "VersionedModel",
]

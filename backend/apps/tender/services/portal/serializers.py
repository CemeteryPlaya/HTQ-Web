"""Ответы портала поставщика — БЕЛЫМ СПИСКОМ (T3.2; план этапа 3, §1; T-26).

Словари собираются явно, поле за полем: ни ``model_to_dict``, ни
``__dict__``. Поставщик видит своё приглашение и тендер, но не плановые цены
заявки, не бюджет, не других участников и не их число. Сторож — тест
``test_portal_access.py::forbidden_keys`` по каждому ответу.
"""

from __future__ import annotations

from django.utils import timezone

from apps.companies import interface as companies
from apps.files import interface as files
from apps.refdata import interface as refdata
from apps.tender.models import Award, InvitationStatus, PaymentScheme, Tender, TenderStatus
from apps.tender.services.tenders import schemes

from .access import PortalContext, company_slug

SPEC_OWNER = "tender.request"
SPEC_TYPE = "tender_spec"


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def intake_open(tender: Tender) -> bool:
    return (tender.status == TenderStatus.INTAKE and tender.deadline_at is not None
            and tender.deadline_at > timezone.now())


def company_name(request) -> str:
    company = companies.get_company(company_slug(request) or "") or {}
    return company.get("name") or ""


def card(request, tender: Tender, *, bound: bool) -> dict:
    """Промежуточная карточка ``GET supplier/<token>`` — до привязки."""
    return {"company_name": company_name(request), "tender_number": tender.number,
            "deadline_at": _iso(tender.deadline_at), "intake_open": intake_open(tender),
            "bound": bound}


def spec_files(tender: Tender) -> list[dict]:
    """Файлы ТЗ и чертежей заявки: ключ документа, имя, размер."""
    return [{"id": row["document_id"], "name": row["name"], "size": row["size"]}
            for row in files.current_files(SPEC_OWNER, tender.request_id, SPEC_TYPE)]


#: Тендер, по которому выбор утверждён, — итог известен (TND-035).
_DECIDED = (TenderStatus.AWARDED, TenderStatus.HANDED_OVER, TenderStatus.DELIVERY,
            TenderStatus.CLOSED)


def _result(tender: Tender, invitation) -> str:
    """Итог для поставщика (TND-035): «ожидается решение», «выбрано по
    позициям», «не выбрано», «отменён», «не состоялся»."""
    if tender.status == TenderStatus.CANCELLED:
        return "cancelled"
    if tender.status == TenderStatus.FAILED:
        return "failed"
    if tender.status in _DECIDED:
        return "awarded" if invitation.status == InvitationStatus.AWARDED else "not_awarded"
    return "awaiting"


def _result_items(tender: Tender, invitation) -> list[dict]:
    """Свои выбранные позиции — только у победителя и только после утверждения;
    чужих сумм и поставщиков здесь нет (белый список)."""
    if tender.status not in _DECIDED or invitation.status != InvitationStatus.AWARDED:
        return []
    rows = (Award.objects.filter(tender=tender, offer__invitation=invitation,
                                 line__isnull=False)
            .select_related("line__item").order_by("line__item__line_no"))
    return [{"line_no": a.line.item.line_no, "name": a.line.item.name, "qty": str(a.qty)}
            for a in rows]


def tender_view(request, ctx: PortalContext) -> dict:
    tender, req = ctx.tender, ctx.tender.request
    items = list(req.items.order_by("line_no"))
    uoms = refdata.uom_brief([str(i.uom_id) for i in items]) if items else {}
    scheme = schemes.out(PaymentScheme.objects.filter(tender=tender).first())
    return {
        "customer": company_name(request),
        "number": tender.number,
        "deadline_at": _iso(tender.deadline_at),
        "currency_code": tender.currency_code,
        "payment_scheme": scheme,
        "delivery_terms": tender.delivery_terms,
        "delivery_address": req.delivery_address,
        "items": [{
            "id": str(i.pk), "line_no": i.line_no, "name": i.name, "specs": i.specs,
            "uom": {"code": (uoms.get(str(i.uom_id)) or {}).get("code", ""),
                    "short_name": (uoms.get(str(i.uom_id)) or {}).get("short_name", "")},
            "qty": str(i.qty), "need_date": _iso(i.need_date or req.need_date),
        } for i in items],
        "needs_delivery": req.needs_delivery,
        "needs_works": req.needs_works,
        "works_scope": req.works_scope if req.needs_works else "",
        "allow_analogs": req.allow_analogs,
        "allow_partial": req.allow_partial,
        "files": spec_files(tender),
        "intake_open": intake_open(tender),
        "participation_status": ctx.invitation.status,
        "result": _result(tender, ctx.invitation),
        "result_items": _result_items(tender, ctx.invitation),
    }

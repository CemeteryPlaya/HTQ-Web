"""Выбор альтернативы по счёту без договора — ФД (B5.1, ТЗ §12.4 п.3,
SelectAlternativeOffer §26; решения D-B51-1, D-B51-2, D-B51-6).

Одна транзакция:

1. замок процесса решения ФД, затем строки счёта — порядок движка
   (``signoff.lock_process_for``, D-B51-2);
2. проверки:
   - счёт «На рассмотрении ФД», версия;
   - комментарий не короче 10 символов;
   - решение ждёт именно этого ФД — его задача в процессе, как у «Оплатить»;
   - АП к этому счёту;
   - BR-093;
3. ``lifecycle.mark_selected`` — пока счёт ещё «На рассмотрении ФД» (окно
   подачи открыто), прочие «Подано» → «Не выбрано»;
4. отзыв процесса решения ФД (этапы аннулируются) и «Заменён альтернативой»;
5. новый документ — ``documents.replace_with``.
"""

from __future__ import annotations

import uuid

from django.db import transaction

from apps.bpp.models import AlternativeOffer, Invoice, InvoiceStatus
from apps.bpp.models.alternatives import OfferSource
from apps.bpp.services.actor import Actor
from apps.bpp.services.alternatives import kpi, lifecycle
from apps.bpp.services.core.errors import check_version
from apps.bpp.services.invoices import decisions
from apps.bpp.services.invoices import invoices as service
from apps.signoff import interface as signoff
from htqweb.errors import DomainError

from . import checks, documents

NODE = "bpp.alternatives.select"


def _uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _offer_of(inv: Invoice, offer_id) -> AlternativeOffer:
    key = _uuid(offer_id)
    offer = (AlternativeOffer.objects.select_related("counterparty")
             .filter(pk=key, source_type=OfferSource.INVOICE, source_id=inv.pk).first()
             if key else None)
    if offer is None:
        raise DomainError("E-NOT-FOUND", f"У счёта {inv.number} нет такой альтернативы.",
                          status=404)
    return offer


@transaction.atomic
def select(actor: Actor, invoice_id, *, offer_id, comment: str,
           expected_version: int | None) -> dict:
    """«Выбрать» альтернативу по счёту. ``{"invoice", "result_type", "result",
    "remainder", "kpi"}``."""
    if not actor.can(NODE, "edit"):
        raise service._deny("Альтернативу по счёту выбирает финансовый директор.")
    signoff.lock_process_for(service.SUBJECT, str(invoice_id))     # D-B51-2: процесс первым
    inv = service.lock(invoice_id)
    service.require_status(inv, (InvoiceStatus.UNDER_REVIEW,), "выбрать альтернативу к")
    check_version(inv, expected_version)
    comment = service.comment_of(comment)
    decisions._task_of(inv, actor.user_id)                        # решение ждёт этого ФД
    offer = _offer_of(inv, offer_id)
    checks.check_budget(offer, project_id=inv.project_id, article_id=inv.article_id)

    lifecycle.mark_selected(offer.pk, actor_id=actor.user_id, comment=comment)
    process = signoff.get_process_for(service.SUBJECT, str(inv.pk))
    if process is not None and process["state"] == "pending":
        try:
            signoff.cancel_process(process_id=process["id"], actor_id=actor.user_id)
        except signoff.SignoffError as exc:
            raise DomainError("E-SGN-01", str(exc), status=409) from exc
        inv.refresh_from_db()
    inv.status, inv.status_comment = InvoiceStatus.REPLACED, comment
    service.touch(inv, actor.user_id, "status", "status_comment")
    kpi.sync_for_document("invoice", inv.pk)       # B-5: переход тоже синхронизирует KPI
    offer.refresh_from_db()
    replaced = documents.replace_with(offer, inv, selector_id=actor.user_id)
    return {"invoice": inv, **replaced}

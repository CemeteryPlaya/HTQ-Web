"""Закрывающие документы на счёт БЗО и закрытие тендера (T5.5; T-16; ТЗ
TND-042).

Сканы приёмки (накладная, акт, счёт-фактура) хранятся у tender и уходят на
счёт поставщика, когда БУХ запросил закрывающие (счёт «Ждёт закрывающих»,
D-13 держит БЗО: ``bpp.attach_closing_docs`` принимает только запрошенные
типы). Поводы: слушатель смены статуса счёта (``on_document``), новая
приёмка и загрузка скана (``attach_for_supplier``). Повтор файла не
дублирует. Последний счёт «Закрыт» при всём принятом — тендер и заявка
«Закрыт».
"""

from __future__ import annotations

from apps.bpp import interface as bpp
from apps.files import interface as files
from apps.tender.models import Invitation, Receipt, TenderRequestStatus, TenderStatus
from apps.tender.services.core import audit

RECEIPT_OWNER = "tender.receipt"
#: Тип скана приёмки → тип закрывающего у счёта БЗО и ключ запроса БУХ.
SCAN_TYPES = {"tender_waybill": ("waybill", "waybill"), "tender_act": ("act", "avr"),
              "tender_vat_invoice": ("vat_invoice", "vat_invoice")}


def _scans(tender, invitation_id) -> list[dict]:
    out = []
    for receipt in Receipt.objects.filter(tender=tender, invitation_id=invitation_id,
                                          cancelled_at__isnull=True):
        for row in files.current_files(RECEIPT_OWNER, receipt.pk):
            if row["file_type"] in SCAN_TYPES:
                out.append(row)
    return out


def _attach(tender, invoice_id: str, docs_required: dict, scans: list[dict]) -> None:
    wanted = [bpp.ClosingFileIn(media_file_id=row["media_file_id"],
                                file_type=SCAN_TYPES[row["file_type"]][0], name=row["name"])
              for row in scans if docs_required.get(SCAN_TYPES[row["file_type"]][1])]
    if wanted:
        bpp.attach_closing_docs(invoice_id, wanted,
                                actor=bpp.TenderActor(user_id=tender.author_id))


def attach_for_supplier(tender, invitation_id) -> None:
    """Счета поставщика, ждущие закрывающих, — получить сканы его приёмок."""
    from . import stages

    scans = _scans(tender, invitation_id)
    if not scans:
        return
    for doc in stages.supplier_documents(tender).get(str(invitation_id), []):
        if doc.doc_type == "invoice" and doc.status == "awaiting_docs":
            _attach(tender, doc.doc_id, doc.docs_required, scans)


def close_if_done(tender) -> None:
    from apps.tender.services.tenders import tenders

    from . import stages

    if tender.status not in (TenderStatus.HANDED_OVER, TenderStatus.DELIVERY):
        return
    if not stages.all_closed(tender):
        return
    from apps.tender.services.award import remainder

    # Невыбранный остаток ЗЗ держит резерв бюджета: пока закупщик его не
    # закрыл, тендер остаётся в поставке — иначе кнопка «Закрыть остаток»
    # пропала бы, а снять резерв было бы нечем (S5-13).
    if remainder.candidates(tender):
        return
    tender.status = TenderStatus.CLOSED
    tenders._touch(tender, tender.author_id)
    req = tender.request
    if req.status == TenderRequestStatus.HANDED_OVER:
        tenders._set_request_status(req, TenderRequestStatus.CLOSED, tender.author_id,
                                    "closed", tender)
    audit.record(tender, "closed", actor_id=None)


def on_document(status: bpp.DocumentStatusOut) -> None:
    """Слушатель БЗО (в транзакции смены статуса документа из тендера)."""
    invitation_id = status.tender_key.split(":", 1)[0]
    invitation = Invitation.objects.select_related("tender").filter(pk=invitation_id).first()
    if invitation is None:
        return
    tender = invitation.tender
    if status.doc_type == "invoice" and status.status == "awaiting_docs":
        scans = _scans(tender, invitation.pk)
        if scans:
            _attach(tender, status.doc_id, status.docs_required, scans)
    if status.status == "closed":
        close_if_done(tender)

"""Пакет B-2 для тендерного модуля (тендер T5.3; спека этапа 5 tender, §3
T5.3; мастер-план tender §3.4, T-15, T-16, T-20).

Документы по утверждённой ЗЗ ``source="tender"`` создаёт только
``bpp.interface.create_documents_from_tender`` — черновики от имени закупщика,
идемпотентно по ключу «поставщик × часть»; статусы и оплаты отдаёт
``documents_status``; приёмку пишет ``set_acceptance`` (схема 3 — срок
оплаты от приёмки в банковских днях); закрывающие вкладывает
``attach_closing_docs`` по правилу D-13."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.bpp import interface as bpp
from apps.bpp.models import (
    Agreement,
    Counterparty,
    Invoice,
    InvoiceStatus,
    PaymentMark,
    PurchaseRequest,
)
from apps.bpp.services.invoices import read
from apps.bpp.services.requests import listeners
from apps.bpp.tests import stage2 as s
from apps.bpp.tests.test_files import PDF, memory_storage  # noqa: F401  (фикстура)
from apps.bpp.tests.test_tender_bridge import _approve, _part, _pipe, _setup, _submit
from apps.files import interface as files
from apps.refdata import interface as refdata
from htqweb.errors import DomainError

pytestmark = pytest.mark.django_db
TN = "ТН-2026-000001"


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(listeners, "_LISTENERS", [])


@pytest.fixture
def zz(company_context):
    """Утверждённая ЗЗ тендера: металл, две позиции (1 шт × 600 и 1 шт × 400)."""
    proj = _setup(company_context["slug"])
    ref = _submit(proj, _part(s.metal(), "600", "400"))[0]
    req = _approve(ref)
    assert req.status == "approved"
    cp = Counterparty.objects.create(name="ТОО «Сталь»", kind="legal", country_code="KZ",
                                     reg_number="991140000017", status="active")
    return {"req": req, "items": list(req.items.order_by("line_no")), "cp": cp,
            "slug": company_context["slug"]}


def _doc(zz, *, kind="invoice", payment="prepay", key=None, lines=None, days=None,
         media=()) -> bpp.HandoverDocIn:
    items = zz["items"]
    return bpp.HandoverDocIn(
        key=key or f"inv-1:{zz['req'].pk}", bpp_request_id=str(zz["req"].pk),
        counterparty_id=str(zz["cp"].pk), currency_code="KZT", with_vat=True,
        vat_rate=Decimal("16"), kind=kind, payment=payment, postpay_days=days,
        lines=lines or [bpp.HandoverLineIn(bpp_request_item_id=str(items[0].pk),
                                           qty=Decimal("1"), amount=Decimal("580")),
                        bpp.HandoverLineIn(bpp_request_item_id=str(items[1].pk),
                                           qty=Decimal("1"), amount=Decimal("390"))],
        offer_media_file_ids=list(media))


def _handover(zz, *docs, user_id=s.SN):
    return bpp.create_documents_from_tender(bpp.TenderHandover(
        actor=bpp.TenderActor(user_id=user_id), tender_number=TN, docs=list(docs)))


def test_invoice_draft_from_tender(zz):
    [ref] = _handover(zz, _doc(zz))
    inv = Invoice.objects.get(pk=ref.doc_id)
    assert (ref.doc_type, inv.status, inv.author_id) == ("invoice", "draft", s.SN)
    assert (inv.counterparty_id, inv.amount, inv.is_advance) == (zz["cp"].pk, Decimal("970.00"),
                                                                 True)
    assert (inv.source_tender, inv.tender_key, inv.pay_after_receipt) == (
        TN, f"inv-1:{zz['req'].pk}", False)
    assert inv.basis == "no_contract"


def test_advance_is_one_invoice(zz):
    [ref] = _handover(zz, _doc(zz, payment="advance"))
    inv = Invoice.objects.get(pk=ref.doc_id)
    assert inv.is_advance and not inv.pay_after_receipt
    assert Invoice.objects.filter(tender_key=inv.tender_key).count() == 1


def test_postpay_waits_for_receipt_and_due_date_in_bank_days(zz):
    [ref] = _handover(zz, _doc(zz, payment="postpay", days=14))
    inv = Invoice.objects.get(pk=ref.doc_id)
    assert (inv.pay_after_receipt, inv.postpay_days, inv.is_advance) == (True, 14, False)
    # До приёмки срока нет — счёт не «просрочен» в очереди бухгалтера.
    assert inv.due_date is None
    assert read.awaiting_receipt(inv)
    received = date(2026, 11, 6)                             # пятница
    bpp.set_acceptance([str(inv.pk)], received_at=received, originals_at=date(2026, 11, 9),
                       originals_to="Бухгалтерия, Иванова А.", actor=bpp.TenderActor(user_id=s.SN))
    inv.refresh_from_db()
    assert inv.received_at == received and inv.originals_to == "Бухгалтерия, Иванова А."
    assert inv.due_date == refdata.add_bank_days(received, 14)


def test_agreement_draft(zz):
    [ref] = _handover(zz, _doc(zz, kind="agreement", key="inv-2:x"))
    agr = Agreement.objects.get(pk=ref.doc_id)
    assert (agr.status, agr.author_id, agr.counterparty_id) == ("draft", s.SN, zz["cp"].pk)
    assert (agr.source_tender, agr.tender_key) == (TN, "inv-2:x")
    assert agr.items.count() == 2


def test_repeat_returns_same_documents(zz):
    first = _handover(zz, _doc(zz))
    again = _handover(zz, _doc(zz))
    assert [r.doc_id for r in first] == [r.doc_id for r in again]
    assert Invoice.objects.filter(source_tender=TN).count() == 1


def test_only_the_request_author(zz):
    s.user(s.SN2)
    with pytest.raises(DomainError) as exc:
        _handover(zz, _doc(zz), user_id=s.SN2)
    assert exc.value.status == 403


def test_request_must_be_from_the_tender(zz, company_context):
    PurchaseRequest.objects.filter(pk=zz["req"].pk).update(source="")
    with pytest.raises(DomainError) as exc:
        _handover(zz, _doc(zz))
    assert exc.value.status == 409


def test_line_must_belong_to_the_request(zz):
    import uuid

    bad = _doc(zz, lines=[bpp.HandoverLineIn(bpp_request_item_id=str(uuid.uuid4()),
                                             qty=Decimal("1"), amount=Decimal("10"))])
    with pytest.raises(DomainError) as exc:
        _handover(zz, bad)
    assert exc.value.status == 422


def test_offer_file_goes_to_the_document(zz, memory_storage):  # noqa: F811
    s.user(s.SN)
    holder = _handover(zz, _doc(zz, key="kp:1"))[0]
    doc = files.attach_bytes("bpp.invoice", holder.doc_id, file_type="invoice", data=PDF,
                             filename="seed.pdf", mime="application/pdf", actor_id=s.SN)
    media = files.current_files("bpp.invoice", holder.doc_id, "invoice")[0]["media_file_id"]
    assert doc
    [ref] = _handover(zz, _doc(zz, key="kp:2", media=[media]))
    names = [f["name"] for f in files.current_files("bpp.invoice", ref.doc_id, "alternative_offer")]
    assert names == ["seed.pdf"]


def test_status_reports_payments(zz):
    [ref] = _handover(zz, _doc(zz))
    Invoice.objects.filter(pk=ref.doc_id).update(status=InvoiceStatus.PARTIALLY_PAID)
    PaymentMark.objects.create(invoice_id=ref.doc_id, pay_date=date(2026, 10, 1),
                               amount=Decimal("300"), marked_by_id=s.SN)
    PaymentMark.objects.create(invoice_id=ref.doc_id, pay_date=date(2026, 10, 2),
                               amount=Decimal("100"), marked_by_id=s.SN,
                               cancelled_at="2026-10-03T00:00:00Z")
    [row] = bpp.documents_status([str(zz["req"].pk)])
    assert (row.doc_type, row.doc_id, row.status) == ("invoice", ref.doc_id, "partially_paid")
    assert (row.paid_amount, row.amount, row.tender_key) == (Decimal("300.00"), Decimal("970.00"),
                                                             ref.key)
    assert row.replaced_by is None


def test_closing_docs_only_in_awaiting_docs_and_requested_type(zz, memory_storage):  # noqa: F811
    s.user(s.SN)
    [ref] = _handover(zz, _doc(zz))
    files.attach_bytes("bpp.invoice", ref.doc_id, file_type="invoice", data=PDF,
                       filename="scan.pdf", mime="application/pdf", actor_id=s.SN)
    media = files.current_files("bpp.invoice", ref.doc_id, "invoice")[0]["media_file_id"]
    scan = bpp.ClosingFileIn(media_file_id=media, file_type="waybill", name="Накладная.pdf")
    actor = bpp.TenderActor(user_id=s.SN)
    Invoice.objects.filter(pk=ref.doc_id).update(status=InvoiceStatus.PAID)
    with pytest.raises(DomainError) as exc:
        bpp.attach_closing_docs(ref.doc_id, [scan], actor=actor)
    assert exc.value.status == 409
    Invoice.objects.filter(pk=ref.doc_id).update(
        status=InvoiceStatus.AWAITING_DOCS, docs_required={"avr": True, "waybill": False,
                                                            "vat_invoice": False})
    with pytest.raises(DomainError):
        bpp.attach_closing_docs(ref.doc_id, [scan], actor=actor)         # тип не запрошен
    Invoice.objects.filter(pk=ref.doc_id).update(docs_required={"waybill": True})
    attached = bpp.attach_closing_docs(ref.doc_id, [scan], actor=actor)
    again = bpp.attach_closing_docs(ref.doc_id, [scan], actor=actor)
    assert attached == again and len(attached) == 1
    assert len(files.current_files("bpp.invoice", ref.doc_id, "waybill")) == 1


def test_listener_hears_status_changes_of_tender_documents(zz, monkeypatch):
    from apps.bpp.services.core import doc_listeners
    from apps.bpp.services.invoices import payments
    from apps.bpp.services.actor import Actor

    monkeypatch.setattr(doc_listeners, "_LISTENERS", [])
    heard: list = []
    bpp.register_document_listener(heard.append)
    [ref] = _handover(zz, _doc(zz))
    Invoice.objects.filter(pk=ref.doc_id).update(status=InvoiceStatus.PAID)
    s.user(907)
    s.grant(zz["slug"], 907, "bpp-buh")
    payments.request_docs(Actor.for_user(907, company=zz["slug"]), ref.doc_id)
    assert [(h.doc_id, h.status) for h in heard] == [(ref.doc_id, "awaiting_docs")]


def test_invoice_by_tender_agreement_is_a_tender_invoice(zz, memory_storage,  # noqa: F811
                                                          monkeypatch):
    """Счёт по договору из тендера оформляют в БЗО (ТЗ §9.4), своего ключа
    передачи у него нет — но поставку ведёт тендер: слушатель получает его с
    ключом договора, приёмка и закрывающие из тендера на него ложатся."""
    from apps.bpp.services.core import doc_listeners
    from apps.bpp.services.invoices import invoices as invoice_service

    [ref] = _handover(zz, _doc(zz, kind="agreement", key="inv-9:x"))
    Agreement.objects.filter(pk=ref.doc_id).update(status="active")
    sn = s.actor(zz["slug"], s.SN, "bpp-sn")
    inv = invoice_service.create_from_agreement(sn, ref.doc_id)
    assert inv.tender_key == ""
    heard: list = []
    monkeypatch.setattr(doc_listeners, "_LISTENERS", [heard.append])
    doc_listeners.status_changed("invoice", inv.pk)
    [out] = heard
    assert out is not None and out.tender_key == "inv-9:x" and out.agreement_id == ref.doc_id

    actor = bpp.TenderActor(user_id=s.SN)
    bpp.set_acceptance([str(inv.pk)], received_at=date(2026, 10, 20), originals_at=None,
                       originals_to="", actor=actor)
    inv.refresh_from_db()
    assert inv.received_at == date(2026, 10, 20)

    s.user(s.SN)
    files.attach_bytes("bpp.invoice", inv.pk, file_type="invoice", data=PDF,
                       filename="scan.pdf", mime="application/pdf", actor_id=s.SN)
    media = files.current_files("bpp.invoice", inv.pk, "invoice")[0]["media_file_id"]
    Invoice.objects.filter(pk=inv.pk).update(status=InvoiceStatus.AWAITING_DOCS,
                                             docs_required={"waybill": True})
    scan = bpp.ClosingFileIn(media_file_id=media, file_type="waybill", name="Накладная.pdf")
    assert len(bpp.attach_closing_docs(str(inv.pk), [scan], actor=actor)) == 1


def test_acceptance_keeps_planned_date_set_by_fd(zz):
    """Плановую дату, которую ФД поставил при «Оплатить», приёмка не перебивает;
    срок оплаты «после приёмки» — ставит."""
    [ref] = _handover(zz, _doc(zz, payment="postpay", days=14))
    Invoice.objects.filter(pk=ref.doc_id).update(planned_pay_date=date(2026, 12, 1))
    received = date(2026, 11, 6)
    bpp.set_acceptance([ref.doc_id], received_at=received, originals_at=None, originals_to="",
                       actor=bpp.TenderActor(user_id=s.SN))
    inv = Invoice.objects.get(pk=ref.doc_id)
    assert inv.planned_pay_date == date(2026, 12, 1)
    assert inv.due_date == refdata.add_bank_days(received, 14)
    assert not read.awaiting_receipt(inv)


def test_document_replacing_a_tender_document_stays_in_the_tender(zz, monkeypatch):
    """Счёт, заменивший документ из тендера выбранной альтернативой (B5.1, T-18),
    своего ключа передачи не имеет — но поставку по нему ведёт тендер:
    слушатель получает его с ключом исходного, приёмка на него ложится."""
    from apps.bpp.models import AlternativeOffer
    from apps.bpp.services.core import doc_listeners

    source, new = _handover(zz, _doc(zz, key="inv-9:src"), _doc(zz, key="inv-9:new"))
    Invoice.objects.filter(pk=new.doc_id).update(tender_key="")
    Invoice.objects.filter(pk=source.doc_id).update(status=InvoiceStatus.REPLACED)
    AlternativeOffer.objects.create(
        number="АП-2026-000901", source_type="invoice", source_id=source.doc_id,
        author_id=s.SN, author_role="sn", result_type="invoice", result_id=new.doc_id)

    heard: list = []
    monkeypatch.setattr(doc_listeners, "_LISTENERS", [heard.append])
    doc_listeners.status_changed("invoice", new.doc_id)
    assert [out.tender_key for out in heard] == ["inv-9:src"]

    bpp.set_acceptance([new.doc_id], received_at=date(2026, 10, 20), originals_at=None,
                       originals_to="", actor=bpp.TenderActor(user_id=s.SN))
    assert Invoice.objects.get(pk=new.doc_id).received_at == date(2026, 10, 20)

    # Документ не из тендера и не замена — по-прежнему чужой.
    Invoice.objects.filter(pk=source.doc_id).update(tender_key="")
    heard.clear()
    doc_listeners.status_changed("invoice", new.doc_id)
    assert heard == []

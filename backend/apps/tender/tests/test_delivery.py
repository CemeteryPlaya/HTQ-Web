"""Стадии поставки (T5.5; спека этапа 5, §3 T5.5; ТЗ «Оплата и доставка»).

Документы БЗО — заглушка ``documents_status`` (настоящие — сквозной сценарий
``test_stage5_e2e``). Мир ``stage5``: A — аванс 30 %, B — предоплата, C —
постоплата."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from apps.bpp import interface as bpp
from apps.tender.models import Handover, Tender
from apps.tender.services.delivery import closing, stages
from apps.tender.tests import helpers as h
from apps.tender.tests.test_award import cheapest, line, put
from apps.tender.tests.test_comparison import _opened
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db


class Docs:
    """Заглушка БЗО: документы по ключу передачи, оплаты, приёмки, вложения."""

    def __init__(self):
        self.rows: list[bpp.DocumentStatusOut] = []
        self.acceptance: list = []
        self.attached: list = []

    def status(self, request_ids):
        return list(self.rows)

    def set_acceptance(self, invoice_ids, *, received_at, originals_at, originals_to, actor):
        self.acceptance.append((sorted(invoice_ids), received_at, originals_to))

    def attach(self, invoice_id, scans, *, actor):
        self.attached.append((invoice_id, [s.file_type for s in scans]))
        return [str(uuid.uuid4()) for _ in scans]

    def add(self, world, key: str, *, doc_type="invoice", status="to_pay", amount="0", paid="0",
            docs_required=None, replaced_by=None, tender_key=None):
        part = world.parts["goods"]
        row = bpp.DocumentStatusOut(
            request_id=str(part.bpp_request_id), doc_type=doc_type,
            doc_id=str(uuid.uuid4()), number=f"СЧ-{len(self.rows) + 1}", status=status,
            amount=Decimal(amount), currency_code="KZT", counterparty_id=None,
            paid_amount=Decimal(paid), docs_required=docs_required or {},
            tender_key=(f"{world.inv[key].id}:{part.pk}" if tender_key is None else tender_key),
            replaced_by=replaced_by)
        self.rows.append(row)
        return row


@pytest.fixture
def docs(monkeypatch):
    stub = Docs()
    monkeypatch.setattr(bpp, "documents_status", stub.status)
    monkeypatch.setattr(bpp, "set_acceptance", stub.set_acceptance)
    monkeypatch.setattr(bpp, "attach_closing_docs", stub.attach)
    return stub


@pytest.fixture
def world(company_context):
    slug = company_context["slug"]
    h.staff(slug)
    return _opened(slug)


def handed_over(world, lines, extras=(), comment=""):
    resp = put(world, lines, extras, comment=comment)
    assert resp.status_code == 200, resp.content
    with use_company(world.slug):
        Tender.objects.filter(pk=world.tender.pk).update(status="handed_over")


def stage_of(world, key: str) -> dict:
    with use_company(world.slug):
        tender = Tender.objects.get(pk=world.tender.pk)
        rows = stages.delivery_of(tender)
    return next(r for r in rows if r["invitation_id"] == str(world.inv[key].id))


def test_prepay_needs_full_payment_before_shipment(world, docs):
    handed_over(world, *cheapest(world))
    total = Decimal(stage_of(world, "B")["total"])
    docs.add(world, "B", status="draft", amount=str(total))
    assert stage_of(world, "B")["stage"] == "awaiting_documents"
    docs.rows[0].status = "to_pay"
    assert stage_of(world, "B")["stage"] == "awaiting_shipment_payment"
    docs.rows[0].paid_amount = total
    docs.rows[0].status = "paid"
    assert stage_of(world, "B")["stage"] == "in_delivery"


def test_advance_30_percent_ships_after_advance(world, docs):
    handed_over(world, *cheapest(world))
    a = stage_of(world, "A")
    total = Decimal(a["total"])
    assert Decimal(a["shipment_share"]) == Decimal("0.3")
    docs.add(world, "A", status="partially_paid", amount=str(total), paid=str(total * Decimal("0.3")))
    assert stage_of(world, "A")["stage"] == "in_delivery"


def test_postpay_ships_once_the_document_is_approved(world, docs):
    lines = [{"line_id": line(world, "C", 1), "comment": "Только у C есть сертификат"}]
    handed_over(world, lines, comment="Только у C есть сертификат на марку")
    docs.add(world, "C", status="to_pay", amount="2620000")
    assert stage_of(world, "C")["stage"] == "in_delivery"


def test_replaced_document_is_followed(world, docs):
    handed_over(world, *cheapest(world))
    new = docs.add(world, "B", status="paid", amount="100", paid="100", tender_key="")
    docs.add(world, "B", status="replaced", amount="100",
             replaced_by=bpp.ReplacedBy(doc_type="invoice", doc_id=new.doc_id, number=new.number,
                                        offer_number="АП-2026-000001"))
    b = stage_of(world, "B")
    assert {d["doc_id"] for d in b["documents"]} == {docs.rows[0].doc_id, docs.rows[1].doc_id}
    assert b["documents"][0]["replaced_by"]["offer_number"] == "АП-2026-000001"


def test_tender_closes_when_every_supplier_is_closed(world, docs):
    lines = [{"line_id": line(world, "A", 3)}]                     # только A, позиция 3
    handed_over(world, lines)
    total = Decimal(stage_of(world, "A")["total"])
    docs.add(world, "A", status="closed", amount=str(total), paid=str(total))
    from types import SimpleNamespace

    from apps.tender.services.delivery import receipts
    from apps.tender.services.tenders.ctx import Ctx

    with use_company(world.slug):
        award = Tender.objects.get(pk=world.tender.pk).awards.get(line__isnull=False)
        receipts.create(Ctx(SimpleNamespace(user_id=h.SN, is_superuser=False), world.slug),
                        world.tender.pk, {"invitation_id": str(world.inv["A"].id),
                                          "received_at": "2026-10-20", "kind": "goods",
                                          "lines": [{"award_id": str(award.pk), "qty": "2"}]})
        closing.close_if_done(Tender.objects.get(pk=world.tender.pk))
        tender = Tender.objects.get(pk=world.tender.pk)
        world.req.refresh_from_db()
    assert tender.status == "closed"
    assert stage_of(world, "A")["stage"] == "closed"


def test_delivery_endpoint(world, docs):
    handed_over(world, *cheapest(world))
    resp = h.call("get", f"tenders/{world.tender.id}/delivery", world.slug, h.SN)
    assert resp.status_code == 200, resp.content
    assert {r["supplier"] for r in resp.json()["suppliers"]} == {
        world.inv["A"].name, world.inv["B"].name}
    assert Handover  # модель передачи — в тестах передачи

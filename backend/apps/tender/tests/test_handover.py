"""Передача выбора в БЗО (T5.5; спека этапа 5, §3 T5.5; S5-10…S5-13).

Документы БЗО создаёт пакет B-2 (его тесты — ``apps/bpp/tests/test_tender_
documents.py``); здесь ``create_documents_from_tender`` и
``cancel_requests_from_tender`` — записывающие заглушки, а карточка
контрагента из потенциального поставщика заводится по-настоящему."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from apps.bpp import interface as bpp
from apps.bpp.models import Counterparty
from apps.refdata import interface as refdata
from apps.tender.models import Handover, SupplierProspect, Tender
from apps.tender.tests import helpers as h
from apps.tender.tests.test_award import cheapest, extra, line, put
from apps.tender.tests.test_comparison import _opened
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db


class FakeBpp:
    def __init__(self):
        self.created: list = []
        self.cancelled: list = []

    def create(self, data):
        self.created.append(data)
        prefix = {"invoice": "СЧ", "agreement": "ДГ"}
        return [bpp.DocumentRef(key=doc.key, doc_type=doc.kind,
                                doc_id=str(uuid.uuid5(uuid.NAMESPACE_URL, doc.key)),
                                number=f"{prefix[doc.kind]}-2026-{i:06d}", status="draft")
                for i, doc in enumerate(data.docs, start=1)]

    def cancel(self, ids, *, actor, comment):
        self.cancelled.append(list(ids))


@pytest.fixture
def fake(monkeypatch):
    stub = FakeBpp()
    monkeypatch.setattr(bpp, "create_documents_from_tender", stub.create)
    monkeypatch.setattr(bpp, "cancel_requests_from_tender", stub.cancel)
    return stub


@pytest.fixture
def world(company_context):
    slug = company_context["slug"]
    h.staff(slug)
    h.grant(slug, h.SN, "bpp-sn")             # заводить контрагентов в БЗО
    return _opened(slug)


def _awarded(world, lines, extras=(), comment=""):
    resp = put(world, lines, extras, comment=comment)
    assert resp.status_code == 200, resp.content
    with use_company(world.slug):
        Tender.objects.filter(pk=world.tender.pk).update(status="awarded")


def _handover(world, user_id=h.SN):
    with use_company(world.slug):
        version = Tender.objects.get(pk=world.tender.pk).version
    return h.call("post", f"tenders/{world.tender.id}/handover", world.slug, user_id,
                  {"version": version})


def _all_from_c(world):
    lines = [{"line_id": line(world, "C", n), "comment": "Один поставщик на всё"}
             for n in (1, 2, 3)]
    extras = [{"extra_id": extra(world, "C", kind), "comment": "Один поставщик на всё"}
              for kind in ("delivery", "works")]
    _awarded(world, lines, extras, comment="Берём всё у C — гарантия на монтаж")


def test_threshold_per_document(world, fake, monkeypatch):
    _all_from_c(world)
    monkeypatch.setattr(refdata, "contract_threshold", lambda on: Decimal("3000000"))
    resp = _handover(world)
    assert resp.status_code == 200, resp.content
    docs = {doc.bpp_request_id: doc for doc in fake.created[0].docs}
    kinds = {world.parts[k].bpp_request_id: k for k in ("goods", "delivery", "works")}
    by_kind = {kinds[uuid.UUID(rid)]: d.kind for rid, d in docs.items()}
    # Товар C 4 138 000 > 3 000 000 — договор; доставка и СМР у того же C — счета.
    assert by_kind == {"goods": "agreement", "delivery": "invoice", "works": "invoice"}


def test_boundary_equal_to_threshold_is_an_invoice(world, fake, monkeypatch):
    _all_from_c(world)
    monkeypatch.setattr(refdata, "contract_threshold", lambda on: Decimal("4138000.00"))
    assert _handover(world).status_code == 200
    assert {d.kind for d in fake.created[0].docs} == {"invoice"}


def test_supplier_scheme_goes_to_documents(world, fake):
    lines, extras = cheapest(world)
    _awarded(world, lines, extras)
    assert _handover(world).status_code == 200
    by_key = {d.key.split(":")[0]: d for d in fake.created[0].docs}
    a, b = str(world.inv["A"].id), str(world.inv["B"].id)
    assert (by_key[a].payment, by_key[b].payment) == ("advance", "prepay")
    usd = next(d for d in fake.created[0].docs if d.currency_code == "USD")
    assert usd.with_vat is False and usd.vat_rate is None


def test_prospect_becomes_counterparty_once(world, fake):
    _all_from_c(world)
    assert _handover(world).status_code == 200
    with use_company(world.slug):
        prospect = SupplierProspect.objects.get(pk=world.prospects["C"].pk)
        assert prospect.counterparty_id is not None
        cp = Counterparty.objects.get(pk=prospect.counterparty_id)
        assert (cp.reg_number, cp.status) == (prospect.reg_number, "active")
    assert {d.counterparty_id for d in fake.created[0].docs} == {str(cp.pk)}


def test_prospect_without_reg_number_is_422(world, fake):
    _all_from_c(world)
    with use_company(world.slug):
        SupplierProspect.objects.filter(pk=world.prospects["C"].pk).update(reg_number="")
        from apps.tender.models import Offer
        offer = Offer.objects.get(invitation=world.inv["C"], status="submitted")
        offer.requisites = {**offer.requisites, "reg_number": ""}
        offer.save(update_fields=["requisites"])
    resp = _handover(world)
    assert (resp.status_code, resp.json()["code"]) == (422, "E-TND-14")
    assert fake.created == []
    with use_company(world.slug):
        assert Tender.objects.get(pk=world.tender.pk).status == "awarded"


def test_handover_twice_is_idempotent(world, fake):
    lines, extras = cheapest(world)
    _awarded(world, lines, extras)
    first = _handover(world)
    again = _handover(world)
    assert first.status_code == again.status_code == 200
    assert first.json()["documents"] == again.json()["documents"]
    assert len(fake.created) == 1
    with use_company(world.slug):
        assert Handover.objects.filter(tender=world.tender).count() == len(
            fake.created[0].docs)


def test_unawarded_part_is_closed(world, fake):
    lines, extras = cheapest(world)               # доставка — только «в цене» у A
    _awarded(world, lines, extras)
    resp = _handover(world)
    assert resp.status_code == 200
    assert fake.cancelled == [[str(world.parts["delivery"].bpp_request_id)]]
    assert resp.json()["closed_parts"] == [str(world.parts["delivery"].pk)]
    keys = {d.key for d in fake.created[0].docs}
    assert all(str(world.parts["delivery"].pk) not in key for key in keys)


def test_status_handed_over(world, fake):
    lines, extras = cheapest(world)
    _awarded(world, lines, extras)
    body = _handover(world).json()
    assert body["status"] == "handed_over"
    with use_company(world.slug):
        world.req.refresh_from_db()
        assert world.req.status == "handed_over"
        from apps.tender.models import AuditLog
        assert AuditLog.objects.filter(object_id=str(world.tender.pk), action="handover").exists()


def test_only_awarded_tender(world, fake):
    lines, extras = cheapest(world)
    put(world, lines, extras)                      # выбор есть, но не утверждён
    resp = _handover(world)
    assert (resp.status_code, resp.json()["code"]) == (409, "E-STS-01")

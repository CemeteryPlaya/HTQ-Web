"""Приёмка и закрывающие (T5.5; спека этапа 5, §3 T5.5; ТЗ TND-041, TND-042;
T-16, T-17)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from apps.bpp.tests.test_files import PDF, memory_storage  # noqa: F401  (фикстура)
from apps.files import interface as files
from apps.tender.models import Tender
from apps.tender.services.delivery import closing
from apps.tender.tests import helpers as h
from apps.tender.tests.test_award import cheapest, extra
from apps.tender.tests.test_comparison import _opened
from apps.tender.tests.test_delivery import Docs, docs, handed_over, stage_of  # noqa: F401
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(company_context):
    slug = company_context["slug"]
    h.staff(slug)
    world = _opened(slug)
    handed_over(world, *cheapest(world))          # B — позиции 1–2 и СМР, A — позиция 3
    return world


def award(world, key: str, *, kind: str = "line", n: int | None = None):
    with use_company(world.slug):
        tender = Tender.objects.get(pk=world.tender.pk)
        rows = tender.awards.filter(offer__invitation=world.inv[key])
        if kind == "line":
            return rows.filter(line__item=world.items[n - 1]).get()
        return rows.filter(extra__kind=kind).get()


def receive(world, key: str, lines, *, kind="goods", when="2026-10-20"):
    return h.call("post", f"tenders/{world.tender.id}/receipts", world.slug, h.SN, {
        "invitation_id": str(world.inv[key].id), "received_at": when, "kind": kind,
        "lines": [{"award_id": str(a.pk), "qty": q} for a, q in lines]})


def test_partial_receipt_and_acceptance_on_invoices(world, docs):
    inv = docs.add(world, "B", status="paid", amount="100", paid="100")
    resp = receive(world, "B", [(award(world, "B", n=1), "4")])
    assert resp.status_code == 201, resp.content
    assert stage_of(world, "B")["stage"] == "partially_received"
    assert docs.acceptance == [([inv.doc_id], date(2026, 10, 20), "")]
    with use_company(world.slug):
        assert Tender.objects.get(pk=world.tender.pk).status == "delivery"


def test_receipt_above_awarded_is_422(world, docs):
    resp = receive(world, "B", [(award(world, "B", n=1), "11")])          # выбрано 10
    assert (resp.status_code, resp.json()["code"]) == (422, "E-TND-13")
    assert receive(world, "B", [(award(world, "B", n=1), "10")]).status_code == 201
    again = receive(world, "B", [(award(world, "B", n=1), "1")])
    assert (again.status_code, again.json()["code"]) == (422, "E-TND-13")


def test_works_accepted_with_their_own_kind(world, docs):
    works = award(world, "B", kind="works")
    wrong = receive(world, "B", [(works, "1")], kind="goods")
    assert wrong.status_code == 422
    assert receive(world, "B", [(works, "1")], kind="works").status_code == 201


def test_receipt_in_the_future_is_422(world, docs):
    assert receive(world, "B", [(award(world, "B", n=1), "1")], when="2099-01-01").status_code == 422


def test_cancel_receipt_rolls_back(world, docs):
    total = stage_of(world, "B")["total"]                   # предоплата 100 % — оплачено всё
    inv = docs.add(world, "B", status="paid", amount=total, paid=total)
    first = receive(world, "B", [(award(world, "B", n=1), "10"), (award(world, "B", n=2), "3")])
    rid = first.json()["id"]
    assert stage_of(world, "B")["stage"] in ("partially_received", "received",
                                             "awaiting_final_payment")
    short = h.call("post", f"tenders/{world.tender.id}/receipts/{rid}/cancel", world.slug, h.SN,
                   {"comment": "коротко"})
    assert short.status_code == 422
    resp = h.call("post", f"tenders/{world.tender.id}/receipts/{rid}/cancel", world.slug, h.SN,
                  {"comment": "Ошиблись поставщиком при отметке"})
    assert resp.status_code == 200, resp.content
    assert stage_of(world, "B")["stage"] == "in_delivery"
    assert docs.acceptance[-1] == ([inv.doc_id], None, "")
    assert receive(world, "B", [(award(world, "B", n=1), "10")]).status_code == 201


def test_originals_go_to_the_invoice(world, docs):
    inv = docs.add(world, "B", status="paid", amount="100", paid="100")
    rid = receive(world, "B", [(award(world, "B", n=1), "4")]).json()["id"]
    resp = h.call("patch", f"tenders/{world.tender.id}/receipts/{rid}", world.slug, h.SN,
                  {"originals_at": "2026-10-20", "originals_to": "Бухгалтерия, Иванова А."})
    assert resp.status_code == 200, resp.content
    assert docs.acceptance[-1] == ([inv.doc_id], date(2026, 10, 20), "Бухгалтерия, Иванова А.")


def test_scans_go_to_the_invoice_only_when_requested(world, docs, memory_storage):  # noqa: F811
    inv = docs.add(world, "B", status="awaiting_docs", amount="100", paid="100",
                   docs_required={"waybill": True, "avr": False, "vat_invoice": False})
    rid = receive(world, "B", [(award(world, "B", n=1), "10")]).json()["id"]
    with use_company(world.slug):
        files.attach_bytes("tender.receipt", rid, file_type="tender_vat_invoice", data=PDF,
                           filename="СФ.pdf", mime="application/pdf", actor_id=h.SN)
        assert docs.attached == []                                         # СФ не запрошена
        files.attach_bytes("tender.receipt", rid, file_type="tender_waybill", data=PDF,
                           filename="Накладная.pdf", mime="application/pdf", actor_id=h.SN)
    assert docs.attached[-1] == (inv.doc_id, ["waybill"])
    docs.attached.clear()
    with use_company(world.slug):
        closing.on_document(inv)                                           # слушатель БЗО
    assert docs.attached == [(inv.doc_id, ["waybill"])]


def test_viewer_and_reviewer_do_not_see_closing_scans(world, docs):
    from apps.tender.file_owners import _receipt_can_view_type

    rid = receive(world, "B", [(award(world, "B", n=1), "1")]).json()["id"]
    viewer = SimpleNamespace(user_id=h.VIEWER, is_superuser=False)
    reviewer = SimpleNamespace(user_id=h.TD, is_superuser=False)
    fd = SimpleNamespace(user_id=h.FD, is_superuser=False)
    author = SimpleNamespace(user_id=h.SN, is_superuser=False)
    with use_company(world.slug):
        for token in (viewer, reviewer):
            assert not _receipt_can_view_type(rid, token, "tender_waybill")
            assert _receipt_can_view_type(rid, token, "tender_photo")
        assert _receipt_can_view_type(rid, fd, "tender_waybill")
        assert _receipt_can_view_type(rid, author, "tender_act")


def test_receipt_needs_handed_over_tender(company_context, docs):
    slug = company_context["slug"]
    h.staff(slug)
    world = _opened(slug)
    resp = h.call("post", f"tenders/{world.tender.id}/receipts", slug, h.SN, {
        "invitation_id": str(world.inv["A"].id), "received_at": "2026-10-20",
        "lines": []})
    assert resp.status_code == 409
    assert extra  # хелпер выбора доставки/СМР — в тестах выбора

"""Выбор поставщиков (T5.2; спека этапа 5, §3 T5.2, S5-05…S5-07).

Мир ``stage5`` после вскрытия: самый дешёвый по позициям 1–2 — B (USD),
по позиции 3 — A; доставка дешевле всего у A (в цене), СМР — у B."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.tender.models import Award, OfferExtra, OfferLine, Tender
from apps.tender.tests import helpers as h
from apps.tender.tests.test_comparison import _opened
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(company_context):
    slug = company_context["slug"]
    h.staff(slug)
    return _opened(slug)


def _version(world) -> int:
    with use_company(world.slug):
        return Tender.objects.get(pk=world.tender.pk).version


def line(world, key: str, n: int) -> str:
    with use_company(world.slug):
        return str(OfferLine.objects.get(offer__invitation=world.inv[key], offer__status="submitted",
                                         item=world.items[n - 1]).pk)


def extra(world, key: str, kind: str) -> str:
    with use_company(world.slug):
        return str(OfferExtra.objects.get(offer__invitation=world.inv[key],
                                          offer__status="submitted", kind=kind).pk)


def put(world, lines, extras=(), comment="", user_id=h.SN, version=None):
    body = {"version": version if version is not None else _version(world), "comment": comment,
            "lines": [dict(row) for row in lines], "extras": [dict(row) for row in extras]}
    return h.call("put", f"tenders/{world.tender.id}/award", world.slug, user_id, body)


def cheapest(world):
    """Самый дешёвый выбор: B — позиции 1–2, A — позиция 3, СМР у B."""
    return ([{"line_id": line(world, "B", 1)}, {"line_id": line(world, "B", 2)},
             {"line_id": line(world, "A", 3)}],
            [{"extra_id": extra(world, "B", "works")}])


def test_cheapest_selection_needs_no_comment(world):
    lines, extras = cheapest(world)
    resp = put(world, lines, extras)
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert len(body["lines"]) == 3 and all(row["is_cheapest"] for row in body["lines"])
    kinds = sorted((e["kind"], e["invitation_id"]) for e in body["extras"])
    # Доставка A «в цене» выбрана сама — вместе с позицией A.
    assert ("delivery", str(world.inv["A"].id)) in kinds
    auto = next(e for e in body["extras"] if e["kind"] == "delivery")
    assert (auto["included_in_price"], Decimal(auto["amount_kzt"])) == (True, Decimal("0"))


def test_one_supplier_per_item(world):
    resp = put(world, [{"line_id": line(world, "A", 1)}, {"line_id": line(world, "B", 1)}])
    assert resp.status_code == 422
    assert resp.json()["fields"][0]["field"] == "lines[1].line_id"


def test_qty_not_above_offered(world):
    resp = put(world, [{"line_id": line(world, "B", 2), "qty": "4"}])      # B предложил 3 т
    assert resp.status_code == 422
    assert resp.json()["fields"][0]["field"] == "lines[0].qty"


def test_partial_qty_is_kept(world):
    resp = put(world, [{"line_id": line(world, "B", 2), "qty": "2"}])
    assert resp.status_code == 200, resp.content
    row = resp.json()["lines"][0]
    assert Decimal(row["qty"]) == Decimal("2")
    assert Decimal(row["amount"]) == Decimal("796.00")                    # 398 × 2 USD


def test_extra_only_from_item_winner(world):
    resp = put(world, [{"line_id": line(world, "A", 1)}],
               [{"extra_id": extra(world, "C", "delivery")}])
    assert resp.status_code == 422
    assert resp.json()["fields"][0]["field"] == "extras[0].extra_id"


def test_not_cheapest_needs_both_comments(world):
    lines = [{"line_id": line(world, "C", 1)}]                            # C дороже B и A
    bare = put(world, lines)
    assert (bare.status_code, bare.json()["code"]) == (422, "E-TND-12")
    assert {f["field"] for f in bare.json()["fields"]} == {"comment", "lines[0].comment"}
    assert bare.json()["details"]["rows"][0]["line_id"] == lines[0]["line_id"]
    only_total = put(world, lines, comment="Берём у C: гарантия на монтаж")
    assert {f["field"] for f in only_total.json()["fields"]} == {"lines[0].comment"}
    only_row = put(world, [{**lines[0], "comment": "Сталь сертифицирована"}])
    assert {f["field"] for f in only_row.json()["fields"]} == {"comment"}
    ok = put(world, [{**lines[0], "comment": "Сталь сертифицирована"}],
             comment="Берём у C: гарантия на монтаж")
    assert ok.status_code == 200, ok.content
    assert ok.json()["lines"][0]["comment"] == "Сталь сертифицирована"
    assert ok.json()["comment"] == "Берём у C: гарантия на монтаж"


def test_award_only_after_opening(company_context):
    from apps.tender.tests import stage5

    slug = company_context["slug"]
    h.staff(slug)
    world = stage5.build(slug)                                             # ещё на приёме
    resp = put(world, [{"line_id": line(world, "A", 1)}])
    assert (resp.status_code, resp.json()["code"]) == (409, "E-STS-01")


def test_not_author_cannot_award(world):
    lines, _ = cheapest(world)
    assert put(world, lines, user_id=h.FD).status_code == 403


def test_save_replaces_previous_selection(world):
    lines, extras = cheapest(world)
    first = put(world, lines, extras)
    assert first.status_code == 200
    stale = put(world, lines[:1], version=first.json()["version"] - 1)
    assert (stale.status_code, stale.json()["code"]) == (409, "E-CON-01")
    second = put(world, lines[:1], version=first.json()["version"])
    assert second.status_code == 200
    with use_company(world.slug):
        assert Award.objects.filter(tender=world.tender, line__isnull=False).count() == 1
    view = h.call("get", f"tenders/{world.tender.id}/award", world.slug, h.SN).json()
    assert [r["line_id"] for r in view["lines"]] == [lines[0]["line_id"]]


def test_view_totals_by_supplier_and_part(world):
    lines, extras = cheapest(world)
    body = put(world, lines, extras).json()
    by_inv = {s["invitation_id"]: s for s in body["suppliers"]}
    a = by_inv[str(world.inv["A"].id)]
    assert Decimal(a["amount_kzt"]) == Decimal("558000.00")               # позиция 3, доставка в цене
    goods = next(p for p in body["parts"] if p["kind"] == "goods")
    assert Decimal(goods["plan_kzt"]) == Decimal("3880000.00")            # 2 450 000 + 860 000 + 570 000


def test_reviewer_can_change_after_opening(world):
    resp = h.call("patch", f"tenders/{world.tender.id}", world.slug, h.SN,
                  {"version": _version(world), "quality_reviewer_user_id": h.TD})
    assert resp.status_code == 200, resp.content
    assert "reviewer" in resp.json()["allowed_actions"]
    assert "award" in resp.json()["allowed_actions"]

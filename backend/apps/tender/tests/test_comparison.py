"""Сравнение предложений (T5.1; спека этапа 5, §1 и §3 T5.1).

Числа — мир ``stage5``: A — KZT с НДС, доставка в цене; B — USD (курс 515,20),
позиции 1–2, уголок 3 т из 4; C — KZT без НДС. Общий набор — позиции 1–2
(B не предложил позицию 3). Суммы — по сумме к оплате (S5-03)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.files.models import FileEvent
from apps.refdata.models import ExchangeRate
from apps.tender.models import Tender
from apps.tender.tests import helpers as h
from apps.tender.tests import stage5
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db
D = Decimal


def _opened(slug, **kw):
    world = stage5.build(slug, **kw)
    with use_company(slug):
        version = Tender.objects.get(pk=world.tender.pk).version
    resp = h.call("post", f"tenders/{world.tender.id}/open", slug, h.SN, {"version": version})
    assert resp.status_code == 200, resp.content
    return world


@pytest.fixture
def world(company_context):
    slug = company_context["slug"]
    h.staff(slug)
    return _opened(slug)


def _table(world, user_id=h.SN):
    resp = h.call("get", f"tenders/{world.tender.id}/comparison", world.slug, user_id)
    assert resp.status_code == 200, resp.content
    return resp.json()


def _supplier(table, world, key):
    inv = str(world.inv[key].id)
    return next(s for s in table["suppliers"] if s["invitation_id"] == inv)


def test_before_opening_is_409_even_for_fd(company_context):
    slug = company_context["slug"]
    h.staff(slug)
    world = stage5.build(slug)
    for user in (h.SN, h.FD):
        resp = h.call("get", f"tenders/{world.tender.id}/comparison", slug, user)
        assert (resp.status_code, resp.json()["code"]) == (409, "E-TND-07"), user


def test_full_cost_and_common_set(world):
    table = _table(world)
    a, b, c = (_supplier(table, world, k) for k in "ABC")
    assert [i["in_common_set"] for i in table["items"]] == [True, True, False]
    assert D(a["total_common_kzt"]) == D("4406000.00")           # 2 380 000 + 876 000 + 0 + 1 150 000
    assert D(a["total_full_kzt"]) == D("4964000.00")             # + 558 000 позиции 3
    assert D(b["total_common_kzt"]) == D("4355500.80")
    assert D(c["total_common_kzt"]) == D("5156000.00")
    assert b["coverage"] == {"offered": 2, "total": 3}
    assert a["coverage"] == {"offered": 3, "total": 3}


def test_usd_line_converted_by_rate(world):
    table = _table(world)
    b = _supplier(table, world, "B")
    assert (b["currency_code"], D(b["rate"])) == ("USD", D("515.20"))
    first = table["items"][0]["offers"][str(world.inv["B"].id)]
    assert (D(first["amount"]), D(first["amount_kzt"])) == (D("4520.00"), D("2328704.00"))
    second = table["items"][1]["offers"][str(world.inv["B"].id)]
    assert (D(second["qty"]), second["is_analog"]) == (D("3"), True)
    assert D(second["unit_price_kzt"]) == D("205049.60")


def test_cheapest_per_item_and_extra(world):
    table = _table(world)
    ids = {k: str(v.id) for k, v in world.inv.items()}
    assert [i["cheapest_invitation_id"] for i in table["items"]] == [ids["B"], ids["B"], ids["A"]]
    extras = {e["kind"]: e for e in table["extras"]}
    assert extras["delivery"]["cheapest_invitation_id"] == ids["A"]
    assert extras["delivery"]["offers"][ids["A"]]["included_in_price"] is True
    assert D(extras["delivery"]["offers"][ids["A"]]["amount_kzt"]) == D("0")
    assert extras["works"]["cheapest_invitation_id"] == ids["B"]
    assert D(extras["delivery"]["plan_amount"]) == D("350000.00")


def test_saving_against_plan(world):
    table = _table(world)
    a, b, c = (_supplier(table, world, k) for k in "ABC")
    assert D(a["saving_common_kzt"]) == D("454000.00")            # план 4 860 000 − 4 406 000
    assert D(b["saving_common_kzt"]) == D("289499.20")            # план по 3 т уголка
    assert D(c["saving_common_kzt"]) == D("-296000.00")           # удорожание
    assert D(table["items"][0]["plan_amount"]) == D("2450000.00")


def test_missing_rate_is_null_with_warning(company_context):
    slug = company_context["slug"]
    h.staff(slug)
    world = _opened(slug, rate_on=date(2001, 1, 1))     # курс USD только из прошлого века
    with use_company(slug):
        ExchangeRate.objects.filter(currency_code="USD").delete()
    table = _table(world)
    b = _supplier(table, world, "B")
    assert b["total_full_kzt"] is None and b["rate"] is None
    assert any(w["code"] == "no_rate" and w["invitation_id"] == b["invitation_id"]
               for w in table["warnings"])


def test_expired_validity_is_warned(world):
    from datetime import timedelta

    from django.utils import timezone

    from apps.tender.models import Offer
    with use_company(world.slug):
        Offer.objects.filter(invitation=world.inv["C"], status="submitted").update(
            valid_until=timezone.localdate() - timedelta(days=1))
    table = _table(world)
    assert _supplier(table, world, "C")["valid_expired"] is True
    assert any(w["code"] == "valid_expired" for w in table["warnings"])


def test_withdrawn_and_declined_not_in_table(world):
    table = _table(world)
    ids = {s["invitation_id"] for s in table["suppliers"]}
    assert str(world.inv["D"].id) not in ids and str(world.inv["E"].id) not in ids
    declined = table["totals"]["declined"]
    assert [(d["name"], d["reason"]) for d in declined] == [
        ("ИП «Демо Склад»", "Нет нужного проката на складе")]


def test_viewer_sees_table_stranger_does_not(world):
    assert _table(world, h.VIEWER)["suppliers"]
    assert h.call("get", f"tenders/{world.tender.id}/comparison", world.slug,
                  h.SN2).status_code == 404


def test_offer_file_link_journals_download(world, memory_storage):  # noqa: F811
    from apps.bpp.tests.test_files import PDF
    from apps.files import interface as files

    with use_company(world.slug):
        offer = world.inv["A"].offers.get(status="submitted")
        doc = files.attach_bytes("tender.offer", offer.pk, file_type="tender_offer", data=PDF,
                                 filename="КП.pdf", mime="application/pdf", actor_id=h.SN)
    table = _table(world)
    listed = _supplier(table, world, "A")["files"]
    assert [f["id"] for f in listed] == [doc["document_id"]]
    resp = h.call("get", f"tenders/{world.tender.id}/offers/{offer.pk}/files/{doc['document_id']}",
                  world.slug, h.SN)
    assert resp.status_code == 200 and resp.json()["url"]
    with use_company(world.slug):
        assert FileEvent.objects.filter(event="file_downloaded").exists()


from apps.bpp.tests.test_files import memory_storage  # noqa: E402,F401  (фикстура)

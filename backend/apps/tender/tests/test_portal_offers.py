"""Предложение поставщика — сервис портала (T3.3; план этапа 3, §1, §2 T3.3).

Сервис вызывается с контекстом портала (``invitation``, ``tender``) — его
собирает ``access.require_device`` (T3.2); здесь контекст строится прямо из
строк, а события пишутся в список.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.tender.models import (
    Invitation,
    Offer,
    OfferLine,
    SupplierProspect,
    Tender,
    TenderRequest,
)
from apps.tender.services.portal import offers
from apps.tender.tests import helpers as h
from htqweb.errors import DomainError
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db

#: Ключи, которых в ответе портала быть не должно (план этапа 3, §1).
FORBIDDEN = {"plan_price", "delivery_plan_amount", "works_plan_amount", "budget",
             "invitations", "counters", "token", "token_hash", "secret_hash", "author_id"}
FORBIDDEN_PREFIXES = ("quality_reviewer", "bpp_")


def forbidden_keys(value, path="") -> list[str]:
    found = []
    if isinstance(value, dict):
        for key, inner in value.items():
            if key in FORBIDDEN or key.startswith(FORBIDDEN_PREFIXES):
                found.append(f"{path}.{key}")
            found += forbidden_keys(inner, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, inner in enumerate(value):
            found += forbidden_keys(inner, f"{path}[{index}]")
    return found


def _request(slug, **extra) -> TenderRequest:
    with use_company(slug):
        proj = h.project(f"П-{700 + TenderRequest.objects.count()}")
    created = h.call("post", "requests", slug, h.SN, h.body(proj, items=[
        h.item("Лист 10 мм", qty="10", price="100"),
        h.item("Уголок 50×50", qty="4", price="250")], **extra))
    assert created.status_code == 201, created.content
    with use_company(slug):
        TenderRequest.objects.filter(pk=created.json()["id"]).update(status="in_tender")
        return TenderRequest.objects.get(pk=created.json()["id"])


def _tender(req, number="ТН-2026-000901") -> Tender:
    return Tender.objects.create(number=number, request=req, author_id=h.SN,
                                 deadline_at=timezone.now() + timedelta(days=7),
                                 currency_code="KZT", status="intake")


def _invite(tender, *, cp=None, prospect=None, email="sales@alfa.kz") -> Invitation:
    return Invitation.objects.create(
        tender=tender, counterparty_id=cp.id if cp else None, prospect=prospect,
        email=email, name=(cp.name if cp else prospect.name),
        token_hash=f"{Invitation.objects.count():064d}", status="sent",
        sent_at=timezone.now())


@pytest.fixture
def world(company_context):
    slug = company_context["slug"]
    h.staff(slug)
    req = _request(slug, needs_delivery=True,
                   delivery_article_id=str(h.article("T-DELIV", "Доставка").id),
                   delivery_plan_amount="500")
    with use_company(slug):
        tender = _tender(req)
        cp = h.counterparty(email="sales@alfa.kz")
        inv = _invite(tender, cp=cp)
        prospect = SupplierProspect.objects.create(name="ИП Бета", email="beta@mail.kz",
                                                   reg_number="900101300123")
        inv2 = _invite(tender, prospect=prospect, email="beta@mail.kz")
    return SimpleNamespace(slug=slug, req=req, tender=tender, cp=cp, inv=inv, inv2=inv2)


def ctx(world, inv=None):
    inv = inv or world.inv
    return SimpleNamespace(invitation=inv, tender=world.tender, binding=None)


class Events(list):
    def __call__(self, kind, meta):
        self.append((kind, meta))


def _items(world):
    return list(world.req.items.order_by("line_no"))


def _filled(world, **over) -> dict:
    a, b = _items(world)
    return {"valid_until": timezone.localdate() + timedelta(days=30),
            "with_vat": True, "vat_rate": "12",
            "lines": [{"item_id": str(a.pk), "participates": True, "price": "95",
                       "qty": "10", "delivery_date": timezone.localdate() + timedelta(days=5)},
                      {"item_id": str(b.pk), "participates": True, "price": "240",
                       "qty": "4"}],
            "extras": {"delivery": {"amount": "450", "included_in_price": False}},
            **over}


def _view(world, inv=None):
    with use_company(world.slug):
        return offers.offer_view(ctx(world, inv))


def _save(world, data, inv=None, events=None):
    with use_company(world.slug):
        version = offers.offer_view(ctx(world, inv))["version"]
        return offers.save_draft(ctx(world, inv), {"version": version, **data},
                                 event=events if events is not None else Events())


def _submit(world, inv=None, events=None, **body):
    with use_company(world.slug):
        version = offers.offer_view(ctx(world, inv))["version"]
        return offers.submit(ctx(world, inv), {"version": version, **body},
                             event=events if events is not None else Events())


def _error(call) -> DomainError:
    with pytest.raises(DomainError) as exc:
        call()
    return exc.value


# ── черновик ────────────────────────────────────────────────────────────

def test_blank_draft_has_a_line_per_item_and_no_plan_prices(world):
    view = _view(world)
    assert forbidden_keys(view) == []
    assert (view["editable"], view["intake_open"], view["declined"]) == (True, True, False)
    assert view["invitation_status"] == "sent"
    offer = view
    assert offer["status"] == "draft" and offer["number"] is None
    assert [(line["name"], line["qty_requested"]) for line in offer["lines"]] == [
        ("Лист 10 мм", "10.000"), ("Уголок 50×50", "4.000")]
    assert [e["kind"] for e in offer["extras"]] == ["delivery"]
    assert offer["requisites"]["name"] == "ТОО «Альфа»"
    assert offer["requisites_readonly"] is True
    with use_company(world.slug):
        assert Offer.objects.filter(invitation=world.inv).count() == 1
        _view(world)  # повторное чтение не заводит второй черновик
        assert Offer.objects.filter(invitation=world.inv).count() == 1


def test_save_checks_the_lines(world):
    a, b = _items(world)
    events = Events()
    saved = _save(world, _filled(world), events=events)
    assert events == [("offer_saved", {"offer_id": str(saved.pk)})]
    with use_company(world.slug):
        line = OfferLine.objects.get(offer=saved, item=a)
        assert (line.price, line.qty) == (Decimal("95.00"), Decimal("10.000"))

    over = _filled(world)
    over["lines"][0]["qty"] = "11"
    err = _error(lambda: _save(world, over))
    assert (err.code, err.status, err.fields[0]["field"]) == ("E-VAL-01", 422, "lines[0].qty")

    zero = _filled(world)
    zero["lines"][1]["price"] = "0"
    assert _error(lambda: _save(world, zero)).fields[0]["field"] == "lines[1].price"


def test_line_of_another_request_is_refused(world):
    other = _request(world.slug)
    foreign = other.items.first()
    data = _filled(world)
    data["lines"][0]["item_id"] = str(foreign.pk)
    err = _error(lambda: _save(world, data))
    assert (err.code, err.fields[0]["field"]) == ("E-VAL-01", "lines[0].item_id")


def test_analog_and_partial_only_when_allowed(world):
    data = _filled(world)
    data["lines"][0].update(is_analog=True, analog_note="Лист 10 мм С345")
    err = _error(lambda: _save(world, data))
    assert (err.code, err.fields[0]["field"]) == ("E-TND-09", "lines[0].is_analog")
    with use_company(world.slug):
        TenderRequest.objects.filter(pk=world.req.pk).update(allow_analogs=True,
                                                             allow_partial=False)
    world.tender.refresh_from_db()
    assert _save(world, data)

    partial = _filled(world)
    partial["lines"][1]["participates"] = False
    err = _error(lambda: _save(world, partial))
    assert (err.code, err.fields[0]["field"]) == ("E-TND-09", "lines[1].participates")
    less = _filled(world)
    less["lines"][0]["qty"] = "5"
    assert _error(lambda: _save(world, less)).code == "E-TND-09"


def test_extras_only_when_requested(world):
    data = _filled(world, extras={"works": {"amount": "100"}})
    err = _error(lambda: _save(world, data))
    assert (err.code, err.fields[0]["field"]) == ("E-VAL-01", "extras.works")


def test_known_counterparty_keeps_its_requisites(world):
    same = _view(world)["requisites"]
    assert _save(world, _filled(world, requisites=same))
    err = _error(lambda: _save(world, _filled(world, requisites={**same, "name": "Другое"})))
    assert (err.code, err.fields[0]["field"]) == ("E-VAL-01", "requisites")

    # Потенциальный поставщик реквизиты вводит сам.
    saved = _save(world, _filled(world, requisites={"name": "ИП Бета-2", "phone": "+7 701"}),
                  inv=world.inv2)
    assert saved.requisites["name"] == "ИП Бета-2"
    assert _view(world, world.inv2)["requisites_readonly"] is False


def test_payment_scheme_of_the_offer(world):
    saved = _save(world, _filled(world, payment_scheme={"kind": "advance", "advance_pct": 30}))
    view = _view(world)
    assert view["payment_scheme"]["kind"] == "advance"
    assert [s["pct"] for s in view["payment_scheme"]["stages"]] == ["30.00", "70.00"]
    with use_company(world.slug):
        assert saved.payment_schemes.count() == 1
    err = _error(lambda: _save(world, _filled(world, payment_scheme={"kind": "staged"})))
    assert err.fields[0]["field"] == "payment_scheme.kind"


def test_stale_version_is_409(world):
    _save(world, _filled(world))
    with use_company(world.slug):
        err = _error(lambda: offers.save_draft(ctx(world), {"version": 1, **_filled(world)},
                                               event=Events()))
    assert (err.code, err.status) == ("E-CON-01", 409)


# ── отправка ────────────────────────────────────────────────────────────

def test_submit_needs_consent_once_and_resubmit_is_version_two(world):
    _save(world, _filled(world))
    err = _error(lambda: _submit(world))
    assert (err.code, err.status) == ("E-TND-08", 422)

    events = Events()
    first = _submit(world, events=events, pd_consent=True)
    assert (first.status, first.number) == ("submitted", 1)
    assert first.pd_consent_at is not None
    assert events == [("offer_submitted", {"offer_id": str(first.pk), "number": 1})]
    with use_company(world.slug):
        world.inv.refresh_from_db()
    assert world.inv.status == "submitted"

    view = _view(world)
    assert view["status"] == "submitted" and view["can_withdraw"] is True
    assert view["invitation_status"] == "submitted" and view["pd_consent_at"]
    # Правка после отправки — черновик-копия; согласие уже дано.
    _save(world, _filled(world, extra_terms="Цена держится 30 дней"))
    second = _submit(world)
    assert second.number == 2
    with use_company(world.slug):
        first.refresh_from_db()
    assert first.status == "replaced"
    assert [(v["number"], v["status"]) for v in _view(world)["history"]] == [
        (2, "submitted"), (1, "replaced")]


def test_submit_checks_completeness(world):
    data = _filled(world, valid_until=timezone.localdate() - timedelta(days=1))
    _save(world, data)
    err = _error(lambda: _submit(world, pd_consent=True))
    assert err.fields[0]["field"] == "valid_until"

    none = _filled(world)
    for line in none["lines"]:
        line["participates"] = False
    _save(world, none)
    err = _error(lambda: _submit(world, pd_consent=True))
    assert err.fields[0]["field"] == "lines"

    no_delivery = _filled(world, extras={"delivery": {"amount": None}})
    _save(world, no_delivery)
    err = _error(lambda: _submit(world, pd_consent=True))
    assert err.fields[0]["field"] == "extras.delivery.amount"


def test_after_the_deadline_nothing_is_accepted(world, pinned_clock):
    _save(world, _filled(world))
    pinned_clock(world.tender.deadline_at + timedelta(minutes=1), "UTC")
    for call in (lambda: _save(world, _filled(world)),
                 lambda: _submit(world, pd_consent=True)):
        err = _error(call)
        assert (err.code, err.status) == ("E-TND-05", 409)
    view = _view(world)
    assert (view["intake_open"], view["editable"]) == (False, False)


def test_tender_not_in_intake_is_closed(world):
    _save(world, _filled(world))
    with use_company(world.slug):
        Tender.objects.filter(pk=world.tender.pk).update(status="opened")
    world.tender.refresh_from_db()
    err = _error(lambda: _save(world, _filled(world)))
    assert (err.code, err.status) == ("E-TND-05", 409)


# ── отзыв и отказ ───────────────────────────────────────────────────────

def test_withdraw_and_decline(world):
    _save(world, _filled(world))
    sent = _submit(world, pd_consent=True)
    events = Events()
    with use_company(world.slug):
        offers.withdraw(ctx(world), {"version": sent.version}, event=events)
        sent.refresh_from_db()
        world.inv.refresh_from_db()
    assert sent.status == "withdrawn" and world.inv.status == "opened"
    assert events[0][0] == "offer_withdrawn"
    with use_company(world.slug):
        err = _error(lambda: offers.withdraw(ctx(world), {"version": None}, event=Events()))
    assert (err.code, err.status) == ("E-STS-01", 409)

    with use_company(world.slug):
        err = _error(lambda: offers.decline(ctx(world), {"reason": "Нет"}, event=Events()))
        assert err.fields[0]["field"] == "reason"
        offers.decline(ctx(world), {"reason": "Нет такого металла на складе"}, event=events)
        world.inv.refresh_from_db()
        assert world.inv.status == "declined"
        assert not Offer.objects.filter(invitation=world.inv, status="draft").exists()
    assert events[-1] == ("declined", {"reason": "Нет такого металла на складе"})
    err = _error(lambda: _save(world, _filled(world)))
    assert (err.code, err.status) == ("E-STS-01", 409)
    view = _view(world)
    assert view["declined"] is True and view["editable"] is False
    assert view["invitation_status"] == "declined"


# ── ручки портала ``supplier/<token>/offer…`` (T3.3) ─────────────────────

def _http_world(slug, **kw):
    from django.test import Client

    from apps.tender.tests import test_portal_access as portal

    world = portal.build(slug, **kw)
    client = Client()
    bound = portal.post(client, slug, f"{world.token}/bind")
    assert bound.status_code == 200, bound.content
    return world, client, portal


@pytest.fixture
def portal_env(settings):
    from django.core.cache import cache

    settings.PUBLIC_BASE_URL = "https://htq.group"
    cache.clear()
    yield
    cache.clear()


def _put(portal, client, world, body):
    return client.put(f"{portal.BASE}/{world.token}/offer", data=json.dumps(body),
                      content_type="application/json", HTTP_X_HTQ_COMPANY=world.slug,
                      HTTP_X_REAL_IP=portal.REAL_IP, HTTP_ORIGIN=portal.origin(world.slug))


def test_http_offer_flow_and_journal(company_context, portal_env):
    from apps.tender.models import PortalEvent

    world, client, portal = _http_world(company_context["slug"])
    resp = portal.get(client, world.slug, f"{world.token}/offer")
    assert resp.status_code == 200, resp.content
    offer = resp.json()
    assert portal.forbidden_keys(offer) == []
    assert (offer["editable"], offer["invitation_status"]) == (True, "opened")
    line = offer["lines"][0]
    assert line["qty_requested"] == "10.000" and "plan_price" not in line

    saved = _put(portal, client, world, {
        "version": offer["version"],
        "valid_until": str(timezone.localdate() + timedelta(days=30)),
        "lines": [{"item_id": line["item_id"], "participates": True, "price": "750",
                   "qty": "10"}],
        "extras": {"works": {"amount": "450000", "note": "Монтаж за 10 дней"}},
        "payment_scheme": {"kind": "postpay", "postpay_days": 15}})
    assert saved.status_code == 200, saved.content
    saved = saved.json()
    assert portal.forbidden_keys(saved) == [] and saved["lines"][0]["price"] == "750.00"

    no_consent = portal.post(client, world.slug, f"{world.token}/offer/submit",
                             {"version": saved["version"]})
    assert (no_consent.status_code, no_consent.json()["code"]) == (422, "E-TND-08")
    sent = portal.post(client, world.slug, f"{world.token}/offer/submit",
                       {"version": saved["version"], "pd_consent": True})
    assert sent.status_code == 200, sent.content
    sent = sent.json()
    assert (sent["status"], sent["number"], sent["invitation_status"]) == (
        "submitted", 1, "submitted")
    assert portal.forbidden_keys(sent) == []

    withdrawn = portal.post(client, world.slug, f"{world.token}/offer/withdraw",
                            {"version": sent["version"]})
    assert withdrawn.status_code == 200, withdrawn.content
    assert withdrawn.json()["invitation_status"] == "opened"

    declined = portal.post(client, world.slug, f"{world.token}/decline",
                           {"reason": "Нет такого металла на складе"})
    assert declined.status_code == 200, declined.content
    assert (declined.json()["invitation_status"], declined.json()["editable"]) == (
        "declined", False)

    with use_company(world.slug):
        kinds = list(PortalEvent.objects.filter(invitation=world.inv)
                     .order_by("created_at").values_list("kind", flat=True))
        ips = set(PortalEvent.objects.filter(invitation=world.inv)
                  .values_list("ip", flat=True))
    assert kinds == ["bound", "offer_saved", "offer_submitted", "offer_withdrawn", "declined"]
    assert ips == {portal.REAL_IP}


def test_http_offer_needs_the_bound_device_and_origin(company_context, portal_env):
    from django.test import Client

    world, client, portal = _http_world(company_context["slug"])
    stranger = portal.get(Client(), world.slug, f"{world.token}/offer")
    assert (stranger.status_code, stranger.json()["code"]) == (403, "E-TND-06")
    no_origin = portal.post(client, world.slug, f"{world.token}/offer/submit",
                            {"pd_consent": True}, with_origin=False)
    assert no_origin.status_code == 403
    text = portal.post(client, world.slug, f"{world.token}/decline", {"reason": "x" * 20},
                       content_type="text/plain")
    assert text.status_code == 415


def test_http_offer_after_the_deadline_is_409(company_context, portal_env, pinned_clock):
    world, client, portal = _http_world(company_context["slug"])
    offer = portal.get(client, world.slug, f"{world.token}/offer").json()
    pinned_clock(world.tender.deadline_at + timedelta(seconds=1), "UTC")
    resp = _put(portal, client, world, {"version": offer["version"], "extra_terms": "x"})
    assert (resp.status_code, resp.json()["code"]) == (409, "E-TND-05")
    view = portal.get(client, world.slug, f"{world.token}/offer").json()
    assert view["editable"] is False and view["status"] == "draft"

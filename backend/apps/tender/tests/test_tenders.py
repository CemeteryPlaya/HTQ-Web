"""Тендер: черновик, схема оплаты, продление, отмена (T2.1; план этапов 0–2,
§4.1–§4.3).

Тендер объявляется только по утверждённой заявке (иначе 409 ``E-STS-01``),
у заявки — не больше одного активного тендера (409 ``E-TND-01``). Публикация
переводит заявку «В тендере», отмена возвращает её в «Утверждена». Видит
тендер автор, с ``tender.tenders.all`` — все; действует только автор.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.tender.models import AuditLog, Tender, TenderRequest
from apps.tender.services.tenders import schemes
from apps.tender.tests import helpers as h
from htqweb.errors import DomainError
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db

CARD_KEYS = {"id", "number", "status", "request_id", "request_number", "deadline_at",
             "currency_code", "delivery_terms", "quality_reviewer_user_id", "cancel_reason",
             "round", "version", "allowed_actions", "payment_scheme", "counters",
             "invitations"}
ROW_KEYS = {"id", "number", "status", "request_id", "request_number", "deadline_at",
            "counters"}


@pytest.fixture
def world(company_context):
    slug = company_context["slug"]
    h.staff(slug)
    req = h.approved_request(slug)
    return SimpleNamespace(slug=slug, req=req)


def _create(world, user_id=h.SN, **over):
    return h.call("post", "tenders", world.slug, user_id, h.tender_body(world.req, **over))


def _ready(world, **over) -> dict:
    """Черновик со схемой оплаты и одним участником — готов к публикации."""
    card = _create(world, **over).json()
    h.call("put", f"tenders/{card['id']}/payment-scheme", world.slug, h.SN,
           {"kind": "prepay"})
    with use_company(world.slug):
        cp = h.counterparty(email="sales@alfa.kz")
    added = h.call("post", f"tenders/{card['id']}/invitations", world.slug, h.SN,
                   {"counterparty_id": str(cp.id)})
    assert added.status_code == 201, added.content
    return h.call("get", f"tenders/{card['id']}", world.slug, h.SN).json()


def _req_status(world) -> str:
    with use_company(world.slug):
        return TenderRequest.objects.get(pk=world.req.pk).status


# ── схемы оплаты ───────────────────────────────────────────────────────────

def test_scheme_templates_sum_to_one_hundred():
    assert schemes.from_template("prepay") == [
        {"order": 1, "trigger": "before_shipment", "pct": schemes.D("100"), "days": None}]
    advance = schemes.from_template("advance", advance_pct="30.5")
    assert [(s["trigger"], s["pct"]) for s in advance] == [
        ("before_shipment", schemes.D("30.50")), ("on_receipt", schemes.D("69.50"))]
    post = schemes.from_template("postpay", days=30)
    assert [(s["trigger"], s["pct"], s["days"]) for s in post] == [
        ("on_receipt", schemes.D("100"), 30)]


@pytest.mark.parametrize("kind,kwargs,field", [
    ("advance", {}, "advance_pct"),
    ("advance", {"advance_pct": "0"}, "advance_pct"),
    ("advance", {"advance_pct": "100"}, "advance_pct"),
    ("postpay", {}, "postpay_days"),
    ("postpay", {"days": 0}, "postpay_days"),
    ("staged", {}, "kind"),
])
def test_bad_scheme_is_422(kind, kwargs, field):
    with pytest.raises(DomainError) as caught:
        schemes.from_template(kind, **kwargs)
    assert caught.value.status == 422
    assert [f["field"] for f in caught.value.fields] == [field]


def test_put_scheme_replaces_the_previous_one(world):
    card = _create(world).json()
    path = f"tenders/{card['id']}/payment-scheme"
    resp = h.call("put", path, world.slug, h.SN, {"kind": "advance", "advance_pct": "30.5"})
    assert resp.status_code == 200, resp.content
    resp = h.call("put", path, world.slug, h.SN, {"kind": "postpay", "postpay_days": 45})
    scheme = resp.json()["payment_scheme"]
    assert scheme == {"kind": "postpay", "postpay_days": 45, "stages": [
        {"order": 1, "trigger": "on_receipt", "pct": "100.00", "days": 45}]}
    staged = h.call("put", path, world.slug, h.SN, {"kind": "staged"})
    assert staged.status_code == 422
    assert h.call("put", path, world.slug, h.SN2, {"kind": "prepay"}).status_code == 404


# ── черновик ───────────────────────────────────────────────────────────────

def test_buyer_declares_a_tender_on_an_approved_request(world):
    resp = _create(world)
    assert resp.status_code == 201, resp.content
    card = resp.json()
    assert set(card) >= CARD_KEYS
    assert card["number"] == f"ТН-{timezone.localdate().year}-000001"
    assert card["status"] == "draft" and card["round"] == 1 and card["version"] == 1
    assert card["request_id"] == str(world.req.id)
    assert card["request_number"] == world.req.number
    assert card["payment_scheme"] is None
    assert card["counters"] == {"sent": 0, "opened": 0, "submitted": 0}
    assert set(card["allowed_actions"]) == {"edit", "publish", "cancel", "invite", "reviewer"}
    assert _req_status(world) == "approved"        # «В тендере» — с публикации
    with use_company(world.slug):
        assert AuditLog.objects.filter(object_type="tender.tender", object_id=card["id"],
                                       action="created").exists()


@pytest.mark.parametrize("status", ["draft", "in_approval", "rework", "rejected",
                                    "in_tender", "cancelled"])
def test_tender_on_a_non_approved_request_is_409(world, status):
    with use_company(world.slug):
        TenderRequest.objects.filter(pk=world.req.pk).update(status=status)
    resp = _create(world)
    assert resp.status_code == 409 and resp.json()["code"] == "E-STS-01"


def test_second_active_tender_is_409(world):
    assert _create(world).status_code == 201
    resp = _create(world)
    assert resp.status_code == 409 and resp.json()["code"] == "E-TND-01"


def test_database_holds_one_active_tender_per_request(world):
    _create(world)
    with use_company(world.slug):
        first = Tender.objects.get()
        with pytest.raises(IntegrityError), transaction.atomic():
            Tender.objects.create(number="ТН-2026-999999", request_id=world.req.pk,
                                  author_id=h.SN)
        # Отменённый активным не считается: после отмены тендер объявляется заново.
        Tender.objects.filter(pk=first.pk).update(status="cancelled")
        Tender.objects.create(number="ТН-2026-999998", request_id=world.req.pk,
                              author_id=h.SN)


def test_only_the_request_visible_to_the_buyer(world):
    resp = _create(world, h.SN2)
    assert resp.status_code == 404
    assert h.call("post", "tenders", world.slug, h.SN, {"request_id": "nope"}).status_code in (
        404, 422)


def test_roles_without_create_cannot_declare(world):
    for user_id in (h.FD, h.VIEWER, h.TD):
        assert _create(world, user_id).status_code == 403


def test_patch_draft_with_version(world):
    card = _create(world).json()
    path = f"tenders/{card['id']}"
    resp = h.call("patch", path, world.slug, h.SN,
                  {"version": 1, "delivery_terms": "EXW Алматы", "currency_code": "USD"})
    assert resp.status_code == 200, resp.content
    assert (resp.json()["delivery_terms"], resp.json()["currency_code"]) == (
        "EXW Алматы", "USD")
    assert resp.json()["version"] == 2
    stale = h.call("patch", path, world.slug, h.SN, {"version": 1, "delivery_terms": "x"})
    assert stale.status_code == 409 and stale.json()["code"] == "E-CON-01"
    assert h.call("patch", path, world.slug, h.FD, {"version": 2}).status_code == 403
    past = h.call("patch", path, world.slug, h.SN,
                  {"version": 2, "deadline_at": (timezone.now() - timedelta(hours=1)).isoformat()})
    assert past.status_code == 422 and past.json()["fields"][0]["field"] == "deadline_at"


def test_quality_reviewer_must_hold_the_quality_role(world):
    card = _create(world).json()
    path = f"tenders/{card['id']}"
    bad = h.call("patch", path, world.slug, h.SN, {"version": 1,
                                                   "quality_reviewer_user_id": h.FD})
    assert bad.status_code == 422
    assert bad.json()["fields"][0]["field"] == "quality_reviewer_user_id"
    good = h.call("patch", path, world.slug, h.SN, {"version": 1,
                                                    "quality_reviewer_user_id": h.TD})
    assert good.status_code == 200, good.content
    assert good.json()["quality_reviewer_user_id"] == h.TD
    assert "Тестов956" in good.json()["quality_reviewer_name"]
    cleared = h.call("patch", path, world.slug, h.SN, {"version": 2,
                                                       "quality_reviewer_user_id": None})
    assert cleared.json()["quality_reviewer_user_id"] is None


# ── публикация, продление, отмена ──────────────────────────────────────────

def test_publish_needs_participants_deadline_and_scheme(world):
    card = _create(world).json()
    resp = h.call("post", f"tenders/{card['id']}/publish", world.slug, h.SN, {"version": 1})
    assert resp.status_code == 422 and resp.json()["code"] == "E-TND-04"
    assert {f["field"] for f in resp.json()["fields"]} == {"invitations", "payment_scheme"}


def test_publish_moves_the_request_in_tender(world):
    card = _ready(world)
    resp = h.call("post", f"tenders/{card['id']}/publish", world.slug, h.SN,
                  {"version": card["version"]})
    assert resp.status_code == 200, resp.content
    published = h.call("get", f"tenders/{card['id']}", world.slug, h.SN).json()
    assert published["status"] == "intake"
    assert set(published["allowed_actions"]) == {"extend", "cancel", "invite", "reviewer"}
    assert published["counters"] == {"sent": 1, "opened": 0, "submitted": 0}
    assert _req_status(world) == "in_tender"
    again = h.call("post", f"tenders/{card['id']}/publish", world.slug, h.SN,
                   {"version": published["version"]})
    assert again.status_code == 409 and again.json()["code"] == "E-STS-01"


def test_publish_refuses_a_request_no_longer_approved(world):
    card = _ready(world)
    with use_company(world.slug):
        TenderRequest.objects.filter(pk=world.req.pk).update(status="cancelled")
    resp = h.call("post", f"tenders/{card['id']}/publish", world.slug, h.SN,
                  {"version": card["version"]})
    assert resp.status_code == 409 and resp.json()["code"] == "E-STS-01"


def test_extend_only_forward(world):
    card = _ready(world)
    h.call("post", f"tenders/{card['id']}/publish", world.slug, h.SN,
           {"version": card["version"]})
    card = h.call("get", f"tenders/{card['id']}", world.slug, h.SN).json()
    path = f"tenders/{card['id']}/extend"
    earlier = h.call("post", path, world.slug, h.SN,
                     {"version": card["version"], "deadline_at": h.future(3)})
    assert earlier.status_code == 422 and earlier.json()["fields"][0]["field"] == "deadline_at"
    later = h.call("post", path, world.slug, h.SN,
                   {"version": card["version"], "deadline_at": h.future(20)})
    assert later.status_code == 200, later.content
    assert later.json()["deadline_at"] > card["deadline_at"]


def test_extend_only_while_intake(world):
    card = _create(world).json()
    resp = h.call("post", f"tenders/{card['id']}/extend", world.slug, h.SN,
                  {"version": 1, "deadline_at": h.future(20)})
    assert resp.status_code == 409 and resp.json()["code"] == "E-STS-01"


def test_cancel_with_reason_returns_the_request(world):
    card = _ready(world)
    h.call("post", f"tenders/{card['id']}/publish", world.slug, h.SN,
           {"version": card["version"]})
    card = h.call("get", f"tenders/{card['id']}", world.slug, h.SN).json()
    path = f"tenders/{card['id']}/cancel"
    short = h.call("post", path, world.slug, h.SN, {"version": card["version"],
                                                    "reason": "мало"})
    assert short.status_code == 422 and short.json()["fields"][0]["field"] == "reason"
    resp = h.call("post", path, world.slug, h.SN,
                  {"version": card["version"], "reason": "Потребность снята заказчиком"})
    assert resp.status_code == 200, resp.content
    cancelled = resp.json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancel_reason"] == "Потребность снята заказчиком"
    assert cancelled["allowed_actions"] == []
    assert {i["status"] for i in cancelled["invitations"]} == {"revoked"}
    assert _req_status(world) == "approved"
    # Заявка снова свободна: можно объявить новый тендер.
    assert _create(world).status_code == 201


def test_cancel_a_draft_leaves_the_request_approved(world):
    card = _create(world).json()
    resp = h.call("post", f"tenders/{card['id']}/cancel", world.slug, h.SN,
                  {"version": 1, "reason": "Объявим позже, после уточнения"})
    assert resp.status_code == 200
    assert _req_status(world) == "approved"


# ── видимость ──────────────────────────────────────────────────────────────

def test_registry_and_card_visibility(world):
    mine = _create(world).json()
    other_req = h.approved_request(world.slug, author=h.SN2)
    theirs = h.call("post", "tenders", world.slug, h.SN2, h.tender_body(other_req)).json()

    rows = h.call("get", "tenders", world.slug, h.SN).json()["results"]
    assert [r["id"] for r in rows] == [mine["id"]]
    assert set(rows[0]) >= ROW_KEYS
    assert rows[0]["request_number"] == world.req.number
    assert rows[0]["counters"] == {"sent": 0, "opened": 0, "submitted": 0}

    for user_id in (h.FD, h.VIEWER, h.TD):            # tender.tenders.all
        ids = {r["id"] for r in h.call("get", "tenders", world.slug, user_id).json()["results"]}
        assert ids == {mine["id"], theirs["id"]}
    assert h.call("get", f"tenders/{theirs['id']}", world.slug, h.SN).status_code == 404
    fd = h.call("get", f"tenders/{mine['id']}", world.slug, h.FD).json()
    assert fd["allowed_actions"] == []

    by_status = h.call("get", "tenders?status=intake", world.slug, h.FD).json()["results"]
    assert by_status == []
    by_request = h.call("get", f"tenders?request_id={world.req.id}", world.slug,
                        h.FD).json()["results"]
    assert [r["id"] for r in by_request] == [mine["id"]]


def test_history_follows_visibility(world):
    from django.test import RequestFactory

    from apps.access.tests.helpers import token
    from apps.tender.services.core import audit
    from apps.tender.services.tenders import tenders
    from htqweb.authn.jwt import decode_token

    tenders.register()
    card = _create(world).json()

    def request_of(user_id):
        req = RequestFactory().get("/")
        req.token = decode_token(token(user_id=user_id, sub=str(user_id), company=world.slug))
        req.company = {"slug": world.slug}
        return req

    with use_company(world.slug):
        assert audit.can_view_history(request_of(h.SN), "tender.tender", card["id"])
        assert audit.can_view_history(request_of(h.TD), "tender.tender", card["id"])
        assert not audit.can_view_history(request_of(h.SN2), "tender.tender", card["id"])

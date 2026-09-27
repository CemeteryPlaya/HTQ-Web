"""«Задействовано» — CALC-002 (D-08, задача B2.4) и его ночная сверка."""

from __future__ import annotations

import random
from decimal import Decimal

import pytest

from apps.bpp.models import ItemStatus, PurchaseRequest, PurchaseRequestItem, RequestStatus
from apps.bpp.services.budget import check
from apps.bpp.services.budget import committed as calc
from apps.bpp.services.requests import requests as service
from apps.bpp.tests import stage2 as s
from htqweb.fallback import FallbackNotAllowed

pytestmark = pytest.mark.django_db


def _request(sn, proj, art, *amounts):
    return service.create_draft(sn, {**s.header(proj, art),
                                     "items": s.items(*[(1, a) for a in amounts])})


def _setup(slug):
    proj, art = s.project(), s.metal()
    s.approved_budget(slug, proj, {art: 10_000_000})
    return proj, art, s.actor(slug, s.SN, "bpp-sn")


def test_formula_by_request_and_item_status(company_context):
    slug = company_context["slug"]
    proj, art, sn = _setup(slug)
    draft = _request(sn, proj, art, 100)
    on_review = _request(sn, proj, art, 200, 300)
    approved = _request(sn, proj, art, 400)
    rejected = _request(sn, proj, art, 800)
    PurchaseRequest.objects.filter(pk=on_review.pk).update(status=RequestStatus.ON_REVIEW)
    PurchaseRequest.objects.filter(pk=approved.pk).update(status=RequestStatus.APPROVED)
    PurchaseRequest.objects.filter(pk=rejected.pk).update(status=RequestStatus.REJECTED)
    assert calc.committed_for(proj.id, art.id) == Decimal("900.00")

    # Аннулированная позиция без счетов не занимает ничего.
    PurchaseRequestItem.objects.filter(request=on_review, line_no=2).update(
        status=ItemStatus.ANNULLED)
    assert calc.committed_for(proj.id, art.id) == Decimal("600.00")
    assert draft.status == RequestStatus.DRAFT


def test_exclude_request_leaves_out_its_own_items(company_context):
    slug = company_context["slug"]
    proj, art, sn = _setup(slug)
    req = _request(sn, proj, art, 250)
    PurchaseRequest.objects.filter(pk=req.pk).update(status=RequestStatus.APPROVED)
    assert calc.committed_for(proj.id, art.id) == Decimal("250.00")
    assert calc.committed_for(proj.id, art.id, exclude_request_id=req.pk) == Decimal("0.00")


def test_aggregate_matches_the_reference_on_random_requests(company_context):
    slug = company_context["slug"]
    proj, art, sn = _setup(slug)
    rng = random.Random(20260927)
    statuses = list(RequestStatus.values)
    for _ in range(50):
        req = _request(sn, proj, art, *[rng.randint(1, 50_000) for _ in range(rng.randint(1, 4))])
        PurchaseRequest.objects.filter(pk=req.pk).update(status=rng.choice(statuses))
        for item in req.items.all():
            item.status = rng.choice(list(ItemStatus.values))
            item.save(update_fields=["status"])
    assert calc.committed_for(proj.id, art.id) == calc.committed_reference(proj.id, art.id)
    assert check.mismatches() == []


def test_nightly_check_catches_a_planted_mismatch(company_context, monkeypatch):
    slug = company_context["slug"]
    proj, art, sn = _setup(slug)
    req = _request(sn, proj, art, 100)
    PurchaseRequest.objects.filter(pk=req.pk).update(status=RequestStatus.APPROVED)
    monkeypatch.setattr(calc, "_item_reference", lambda item: Decimal("1.00"))
    assert check.mismatches()[0]["aggregate"] == "100.00"
    with pytest.raises(FallbackNotAllowed):
        check.run()

"""Итог тендера для поставщика в портале (TND-035; спека этапа 5, §3 T5.5)."""

from __future__ import annotations

import pytest

from apps.tender.models import Invitation, Tender
from apps.tender.services.portal import serializers
from apps.tender.tests import helpers as h
from apps.tender.tests.test_award import cheapest, put
from apps.tender.tests.test_comparison import _opened
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(company_context):
    slug = company_context["slug"]
    h.staff(slug)
    return _opened(slug)


def _result(world, key):
    with use_company(world.slug):
        tender = Tender.objects.get(pk=world.tender.pk)
        inv = Invitation.objects.get(pk=world.inv[key].pk)
        return serializers._result(tender, inv), serializers._result_items(tender, inv)


def test_awaiting_until_award_is_approved(world):
    put(world, *cheapest(world))
    assert _result(world, "B") == ("awaiting", [])


def test_awarded_supplier_sees_own_items_only(world):
    put(world, *cheapest(world))
    with use_company(world.slug):
        Tender.objects.filter(pk=world.tender.pk).update(status="awarded")
        Invitation.objects.filter(pk__in=[world.inv["A"].pk, world.inv["B"].pk]).update(
            status="awarded")
        Invitation.objects.filter(pk=world.inv["C"].pk).update(status="not_awarded")
    result, items = _result(world, "B")
    assert result == "awarded"
    assert [i["name"] for i in items] == ["Швеллер 12П", "Уголок 50×5"]
    assert h.portal_forbidden_keys(items) == []
    assert _result(world, "C") == ("not_awarded", [])


def test_cancelled_and_failed(world):
    with use_company(world.slug):
        Tender.objects.filter(pk=world.tender.pk).update(status="cancelled")
    assert _result(world, "A")[0] == "cancelled"
    with use_company(world.slug):
        Tender.objects.filter(pk=world.tender.pk).update(status="failed")
    assert _result(world, "A")[0] == "failed"

"""Демо-данные тендерного модуля (seed_tender_demo): три сценария этапа 5,
повторный запуск ничего не дублирует, без демо-проекта — понятный отказ."""

from __future__ import annotations

import io

import pytest
from django.core.management import CommandError, call_command

from apps.bpp.tests import stage2 as s
from apps.bpp.tests.test_files import memory_storage  # noqa: F401  (фикстура)
from apps.bpp.tests.test_seed_bpp_demo import BUH, _setup as bpp_setup
from apps.tender.models import Invitation, Offer, Tender
from apps.tender.tests import helpers as h

pytestmark = pytest.mark.django_db


def _run(slug: str, **options) -> str:
    out = io.StringIO()
    call_command("seed_tender_demo", company=slug, stdout=out, **options)
    return out.getvalue()


def test_seed_builds_stage5_scenarios_once(company_context, memory_storage):  # noqa: F811
    slug = company_context["slug"]
    bpp_setup(slug)
    call_command("seed_bpp_demo", company=slug, stdout=io.StringIO(),
                 sn=s.SN, pm=s.PM, fd=s.FD, buh=BUH)
    h.grant(slug, s.SN, "tender-buyer")

    text = _run(slug, buyer=s.SN)
    assert "Готово." in text
    tenders = {t.request.justification.split("[демо-тендер:")[1].rstrip("]"): t
               for t in Tender.objects.select_related("request")}
    assert set(tenders) == {"к-вскрытию", "приём-идёт", "без-предложений"}
    assert {t.status for t in tenders.values()} == {"intake"}

    ready = tenders["к-вскрытию"]
    assert ready.request.parts.count() == 3                      # основные, доставка, СМР
    assert {p.bpp_status for p in ready.request.parts.all()} == {"approved"}
    statuses = sorted(ready.invitations.values_list("status", flat=True))
    assert statuses == ["declined", "sent", "submitted", "submitted", "submitted"]
    sent = Offer.objects.filter(invitation__tender=ready, status="submitted")
    assert {o.currency_code for o in sent} == {"KZT", "USD"}
    partial = sent.get(currency_code="USD")
    assert partial.lines.filter(participates=False).count() == 1
    assert partial.lines.filter(is_analog=True).count() == 1

    from django.utils import timezone
    assert ready.deadline_at < timezone.now()
    assert tenders["приём-идёт"].deadline_at > timezone.now()
    assert Offer.objects.filter(invitation__tender=tenders["приём-идёт"], status="draft").count() == 1
    assert not Offer.objects.filter(invitation__tender=tenders["без-предложений"]).exists()

    before = (Tender.objects.count(), Invitation.objects.count(), Offer.objects.count())
    again = _run(slug, buyer=s.SN)
    assert again.count("уже есть") == 3
    assert (Tender.objects.count(), Invitation.objects.count(), Offer.objects.count()) == before


def test_missing_demo_project_is_explained(company_context):
    slug = company_context["slug"]
    h.user(s.SN)
    with pytest.raises(CommandError, match="seed_bpp_demo"):
        _run(slug, buyer=s.SN)
    assert not Tender.objects.exists()

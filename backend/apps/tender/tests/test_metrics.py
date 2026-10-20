"""Бизнес-метрики тендерного модуля (T5.6; спека этапа 5, §3 T5.6).

``collect()`` — в схеме одной компании; веер по компаниям и метка
``company`` — ``apps.core.metrics.collect_all``. Сторожа наблюдаемости —
``apps/core/tests/test_metrics_are_observed.py``."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from apps.signoff.models import ApprovalProcessStage
from apps.tender import metrics
from apps.tender.models import Tender
from apps.tender.tests import helpers as h
from apps.tender.tests.test_award import cheapest, line, put
from apps.tender.tests.test_award_signoff import route, submit, td_position
from apps.tender.tests.test_comparison import _opened
from apps.tender.tests.test_delivery import Docs, docs, handed_over  # noqa: F401  (фикстура)
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db

ALMATY = "Asia/Almaty"


def _values(collected: dict, name: str) -> dict:
    return dict(collected[name]["values"])


@pytest.fixture
def world(company_context):
    slug = company_context["slug"]
    h.staff(slug)
    world = _opened(slug)
    with use_company(slug):
        route()
        td_position()
    return world


def test_collect_counts_by_status(world):
    with use_company(world.slug):
        collected = metrics.collect()
    counts = _values(collected, "tender_tenders")
    assert counts[("opened",)] == 1
    assert counts[("draft",)] == 0                          # каждый статус — серией, и нулём
    assert set(collected["tender_tenders"]["labels"]) == {"status"}


def _on_approval_since(world, moment: datetime) -> None:
    put(world, *cheapest(world))
    assert submit(world).status_code == 200
    with use_company(world.slug):
        ApprovalProcessStage.objects.filter(
            process__subject_type=Tender.SIGNOFF_SUBJECT_TYPE,
            process__subject_id=str(world.tender.pk)).update(activated_at=moment)


@pytest.mark.parametrize(("today", "stale"), [
    (date(2026, 10, 15), 0),        # Пн 12.10 → Вт, Ср, Чт: ровно 3 — ещё нет
    (date(2026, 10, 16), 1),        # пятница — четвёртый рабочий день
])
def test_stale_award_counted_after_three_working_days(world, pinned_clock, today, stale):
    _on_approval_since(world, datetime(2026, 10, 12, 10, 0, tzinfo=ZoneInfo(ALMATY)))
    pinned_clock(datetime.combine(today, datetime.min.time(), tzinfo=ZoneInfo(ALMATY))
                 + timedelta(hours=12), ALMATY)
    with use_company(world.slug):
        collected = metrics.collect()
    assert _values(collected, "tender_award_approval_stale")[()] == stale


def test_weekend_is_not_counted(world, pinned_clock):
    # Чт 15.10 → Пт, (Сб, Вс), Пн: три рабочих — не застрял.
    _on_approval_since(world, datetime(2026, 10, 15, 10, 0, tzinfo=ZoneInfo(ALMATY)))
    pinned_clock(datetime(2026, 10, 19, 12, 0, tzinfo=ZoneInfo(ALMATY)), ALMATY)
    with use_company(world.slug):
        assert _values(metrics.collect(), "tender_award_approval_stale")[()] == 0


def test_signoff_off_drops_only_the_stale_metric(world, monkeypatch):
    real = metrics.service_enabled
    monkeypatch.setattr(metrics, "service_enabled", lambda name: name != "signoff" and real(name))
    with use_company(world.slug):
        collected = metrics.collect()
    assert "tender_award_approval_stale" not in collected
    assert "tender_tenders" in collected


def test_delivery_overdue_after_offer_delivery_date(world, docs, pinned_clock):  # noqa: F811
    # У C — срок поставки строки 1 в мире этапа 5; постоплата: везёт сразу.
    lines = [{"line_id": line(world, "C", 1), "comment": "Только у C есть сертификат"}]
    handed_over(world, lines, comment="Только у C есть сертификат на марку")
    docs.add(world, "C", status="to_pay", amount="2620000")
    with use_company(world.slug):
        tender = Tender.objects.get(pk=world.tender.pk)
        last = max(a.line.delivery_date for a in tender.awards.select_related("line")
                   if a.line_id)
    pinned_clock(datetime.combine(last, datetime.min.time(), tzinfo=ZoneInfo(ALMATY))
                 + timedelta(hours=12), ALMATY)
    with use_company(world.slug):
        assert _values(metrics.collect(), "tender_delivery_overdue")[()] == 0   # срок — сегодня
    pinned_clock(datetime.combine(last + timedelta(days=1), datetime.min.time(),
                                  tzinfo=ZoneInfo(ALMATY)) + timedelta(hours=12), ALMATY)
    with use_company(world.slug):
        assert _values(metrics.collect(), "tender_delivery_overdue")[()] == 1
    assert Docs

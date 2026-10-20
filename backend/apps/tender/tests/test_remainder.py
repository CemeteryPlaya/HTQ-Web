"""«Закрыть остаток» (S5-13; спека этапа 5, §3 T5.5 п.5).

Документы БЗО — заглушка ``documents_status`` из тестов поставки; закрытие
ЗЗ — заглушка ``cancel_requests_from_tender`` (настоящее «Закрыть остаток» в
БЗО проверяют тесты моста ``apps/bpp/tests/test_tender_bridge.py``)."""

from __future__ import annotations

import pytest

from apps.bpp import interface as bpp
from apps.tender.models import AuditLog, Handover, Tender, TenderRequestPart
from apps.tender.tests import helpers as h
from apps.tender.tests.test_award import line
from apps.tender.tests.test_comparison import _opened
from apps.tender.tests.test_delivery import Docs, docs, handed_over  # noqa: F401  (фикстура)
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db

REASON = "Остаток закупим в следующем квартале"


@pytest.fixture
def cancelled(monkeypatch):
    calls: list = []

    def cancel(ids, *, actor, comment):
        # Как настоящий БЗО: «Закрыть остаток» — ЗЗ «Закрыта», слушатель статусов
        # пишет зеркало части в той же транзакции.
        calls.append((list(ids), comment))
        TenderRequestPart.objects.filter(bpp_request_id__in=list(ids)).update(bpp_status="closed")

    monkeypatch.setattr(bpp, "cancel_requests_from_tender", cancel)
    return calls


@pytest.fixture
def world(company_context):
    slug = company_context["slug"]
    h.staff(slug)
    return _opened(slug)


def _partial(world, qty="6"):
    """A — только позиция 1, и та не целиком; документы переданы."""
    handed_over(world, [{"line_id": line(world, "A", 1), "qty": qty,
                         "comment": "Остальное возьмём позже"}],
                comment="Берём часть сейчас — склад занят")
    with use_company(world.slug):
        tender = Tender.objects.get(pk=world.tender.pk)
        Handover.objects.create(tender=tender, invitation=world.inv["A"],
                                part_id=world.parts["goods"].pk, bpp_document_type="invoice",
                                bpp_document_id=world.parts["goods"].bpp_request_id,
                                bpp_number="СЧ-1", created_by=h.SN, updated_by=h.SN)


def _close(world, comment=REASON, user_id=h.SN):
    with use_company(world.slug):
        version = Tender.objects.get(pk=world.tender.pk).version
    return h.call("post", f"tenders/{world.tender.id}/close-remainder", world.slug, user_id,
                  {"version": version, "comment": comment})


def _actions(world) -> list[str]:
    resp = h.call("get", f"tenders/{world.tender.id}", world.slug, h.SN)
    return resp.json()["allowed_actions"]


def test_closes_remainder_of_partially_awarded_part(world, docs, cancelled):  # noqa: F811
    _partial(world)
    docs.add(world, "A", status="to_pay", amount="100")
    assert "close_remainder" in _actions(world)
    resp = _close(world)
    assert resp.status_code == 200, resp.content
    assert cancelled == [([str(world.parts["goods"].bpp_request_id)],
                          f"Остаток после тендера {world.tender.number}: {REASON}")]
    with use_company(world.slug):
        assert AuditLog.objects.filter(object_id=str(world.tender.pk),
                                       action="remainder_closed").exists()


def test_unapproved_document_blocks(world, docs, cancelled):  # noqa: F811
    _partial(world)
    docs.add(world, "A", status="under_review", amount="100")
    resp = _close(world)
    assert (resp.status_code, resp.json()["code"]) == (409, "E-STS-01")
    assert resp.json()["details"]["documents"] == ["СЧ-1"]
    assert cancelled == []


def test_nothing_to_close_when_everything_awarded(world, docs, cancelled):  # noqa: F811
    _partial(world, qty="10")
    with use_company(world.slug):
        # Позиции 2 и 3 части — «выбраны» другими поставщиками целиком: убираем их
        # из части, чтобы остаток был только у позиции 1.
        world.items[1].part = None
        world.items[1].save(update_fields=["part"])
        world.items[2].part = None
        world.items[2].save(update_fields=["part"])
    assert "close_remainder" not in _actions(world)
    resp = _close(world)
    assert (resp.status_code, resp.json()["code"]) == (409, "E-STS-01")


def test_comment_required(world, docs, cancelled):  # noqa: F811
    _partial(world)
    docs.add(world, "A", status="to_pay", amount="100")
    resp = _close(world, comment="коротко")
    assert resp.status_code == 422
    assert cancelled == []


def test_only_the_author(world, docs, cancelled):  # noqa: F811
    _partial(world)
    assert _close(world, user_id=h.FD).status_code in (403, 404)
    assert Docs


def test_open_remainder_keeps_tender_out_of_closed(world, docs, cancelled, monkeypatch):  # noqa: F811
    """Всё поставлено и оплачено, но невыбранный остаток ЗЗ держит резерв: тендер
    не закрывается сам, пока закупщик не закроет остаток; закрыл — тендер «Закрыт»."""
    from apps.tender.services.delivery import closing, stages

    _partial(world)
    docs.add(world, "A", status="closed", amount="100", paid="100")
    monkeypatch.setattr(stages, "all_closed", lambda tender: True)
    with use_company(world.slug):
        closing.close_if_done(Tender.objects.get(pk=world.tender.pk))
        assert Tender.objects.get(pk=world.tender.pk).status == "handed_over"
    assert "close_remainder" in _actions(world)
    assert _close(world).status_code == 200
    with use_company(world.slug):
        assert Tender.objects.get(pk=world.tender.pk).status == "closed"


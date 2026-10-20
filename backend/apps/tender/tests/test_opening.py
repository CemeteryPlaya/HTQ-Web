"""Вскрытие предложений (T5.1; спека этапа 5, §3 T5.1).

После срока автор вскрывает тендер: предложения, файлы КП и сравнение
открываются, приглашения без отправленной версии — «Срок истёк». До срока —
только когда ответили все. Без единого предложения — «Не состоялся», заявка
снова «Утверждена»."""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from apps.tender.models import AuditLog, Invitation, Tender
from apps.tender.tests import helpers as h
from apps.tender.tests import stage5
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(company_context):
    slug = company_context["slug"]
    h.staff(slug)
    return stage5.build(slug)


def _open(world, user_id=h.SN, version=None):
    if version is None:
        # Клиент после ответа возвращает search_path на public — читаем в схеме.
        with use_company(world.slug):
            version = Tender.objects.get(pk=world.tender.pk).version
    return h.call("post", f"tenders/{world.tender.id}/open", world.slug, user_id,
                  {"version": version})


def test_open_after_deadline(world):
    resp = _open(world)
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["status"] == "opened" and body["opened_at"]
    with use_company(world.slug):
        tender = Tender.objects.get(pk=world.tender.pk)
        assert tender.rate_date == timezone.localdate()
        statuses = {k: Invitation.objects.get(pk=v.pk).status for k, v in world.inv.items()}
        assert AuditLog.objects.filter(object_id=str(tender.pk), action="opened").exists()
    assert statuses == {"A": "submitted", "B": "submitted", "C": "submitted",
                        "D": "declined", "E": "expired"}


def test_open_action_is_offered_after_deadline(world):
    card = h.call("get", f"tenders/{world.tender.id}", world.slug, h.SN).json()
    assert "open" in card["allowed_actions"]


def test_open_before_deadline_only_when_everyone_answered(company_context):
    slug = company_context["slug"]
    h.staff(slug)
    world = stage5.build(slug, close=False)
    card = h.call("get", f"tenders/{world.tender.id}", slug, h.SN).json()
    assert "open" not in card["allowed_actions"]
    early = _open(world)
    assert (early.status_code, early.json()["code"]) == (409, "E-STS-01")
    with use_company(slug):           # молчавший E отказывается — ответили все
        from apps.tender.services.portal import offers
        offers.decline(stage5.portal_ctx(world.inv["E"]), {"reason": "Не успеваем к сроку"})
    assert _open(world).status_code == 200


def test_open_without_offers_fails_the_tender(company_context):
    slug = company_context["slug"]
    h.staff(slug)
    world = stage5.build(slug, offers_from="")
    resp = _open(world)
    assert resp.status_code == 200, resp.content
    assert resp.json()["status"] == "failed"
    with use_company(slug):
        world.req.refresh_from_db()
        assert world.req.status == "approved"


def test_not_author_cannot_open(world):
    assert _open(world, user_id=h.FD).status_code == 403


def test_open_twice_is_409(world):
    assert _open(world).status_code == 200
    again = _open(world)
    assert (again.status_code, again.json()["code"]) == (409, "E-STS-01")


def test_portal_is_closed_after_opening(world):
    assert _open(world).status_code == 200
    from apps.tender.services.portal import offers
    from htqweb.errors import DomainError
    with use_company(world.slug), pytest.raises(DomainError) as exc:
        ctx = stage5.portal_ctx(world.inv["A"])
        offers.save_draft(ctx, {"version": 1, "extra_terms": "после вскрытия"})
    assert exc.value.code == "E-TND-05"


def test_offer_files_open_after_opening(world):
    from apps.files import interface as files
    from apps.tender.file_owners import _offer_can_view
    from types import SimpleNamespace

    with use_company(world.slug):
        offer = world.inv["A"].offers.get(status="submitted")
        fd = SimpleNamespace(user_id=h.FD, is_superuser=False)
        author = SimpleNamespace(user_id=h.SN, is_superuser=False)
        stranger = SimpleNamespace(user_id=h.TD + 100, is_superuser=False)
        assert not _offer_can_view(offer.pk, fd) and not _offer_can_view(offer.pk, author)
    assert _open(world).status_code == 200
    with use_company(world.slug):
        assert _offer_can_view(offer.pk, author) and _offer_can_view(offer.pk, fd)
        assert not _offer_can_view(offer.pk, stranger)
    assert files  # подсистема та же — правило лишь в колбэке владельца


@pytest.mark.django_db(transaction=True)
def test_parallel_open_opens_once(company_schema):
    """Два одновременных «Вскрыть» — одно вскрытие. Сервисом, а не ручкой:
    транзакционный тест чистит ``public`` вместе с ролями из миграций, а
    автору-суперпользователю роли не нужны."""
    from types import SimpleNamespace

    from apps.tender.services.comparison import opening
    from apps.tender.services.tenders.ctx import Ctx
    from htqweb.errors import DomainError

    slug = company_schema["slug"]
    world = stage5.build(slug)
    results = []

    def worker():
        try:
            with use_company(slug):
                ctx = Ctx(SimpleNamespace(user_id=h.SN, is_superuser=True), slug)
                try:
                    opening.open_tender(ctx, world.tender.id)
                    results.append(200)
                except DomainError as exc:
                    results.append(exc.status)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [200, 409]
    with use_company(slug):
        assert Tender.objects.get(pk=world.tender.pk).status == "opened"


def test_card_before_deadline_has_no_open_for_draft(company_context):
    slug = company_context["slug"]
    h.staff(slug)
    req = h.approved_request(slug)
    draft = h.call("post", "tenders", slug, h.SN, h.tender_body(req)).json()
    assert "open" not in draft["allowed_actions"]
    assert timedelta  # импорт нужен тестам с часами

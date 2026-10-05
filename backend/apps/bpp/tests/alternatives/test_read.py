"""Лента L-09, сравнение предложений, карточка АП, «Мои альтернативы» и
видимость АП (ТЗ §12.2–12.4, F-07, AC-014; план этапа 5 A, задача 4).

Документы и АП для ленты — прямо в базе (свои фабрики ниже: помощники KPI
правит задача 3), для сравнения и карточки — фабриками B и настоящей подачей
(``common``). Ручки — тестовым ``Client``; чтение БД после запроса — внутри
``use_company``.
"""

from __future__ import annotations

import itertools
import uuid
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from apps.bpp.models import (
    Agreement,
    AgreementStatus,
    AlternativeOffer,
    InvoiceBasis,
    InvoiceStatus,
    OfferStatus,
)
from apps.bpp.services.alternatives import file_owner, read
from apps.bpp.tests import stage2 as s
from apps.bpp.tests import test_invoices as invoice_flow
from apps.bpp.tests.bank.common import counterparty, orm_invoice
from apps.bpp.tests.test_files import memory_storage  # noqa: F401  (фикстура)
from htqweb.tenancy.db import use_company

from . import common

D = Decimal
BASE = "/api/bpp/v1"
BUH = invoice_flow.BUH
pytestmark = pytest.mark.django_db

_SEQ = itertools.count(1)


# ── фабрики ─────────────────────────────────────────────────────────────

def _cp():
    return counterparty(f"5{next(_SEQ):011d}")


def _invoice(*, status=InvoiceStatus.UNDER_REVIEW, author_id=s.SN, amount=1000):
    return orm_invoice(_cp(), amount, status=status, author_id=author_id)


def _agreement(*, status=AgreementStatus.ON_REVIEW, author_id=s.SN, amount=5000, **extra):
    n = next(_SEQ)
    return Agreement.objects.create(
        number=f"ДГ-2026-{600000 + n:06d}", project_id=uuid.uuid4(), article_id=uuid.uuid4(),
        counterparty=_cp(), ext_number=f"Д-{n}", ext_date=timezone.localdate(),
        amount=D(str(amount)), status=status, author_id=author_id, **extra)


def _offer(source, *, author_id=common.SN2, status=OfferStatus.SUBMITTED,
           source_type=common.INVOICE):
    return AlternativeOffer.objects.create(
        number=f"АП-2026-{600000 + next(_SEQ):06d}", source_type=source_type,
        source_id=source.pk, project_id=source.project_id, article_id=source.article_id,
        author_id=author_id, author_role="sn", counterparty=_cp(), amount=D("900.00"),
        amount_kzt=D("900.00"), source_amount_kzt=D("1000.00"), status=status,
        submitted_at=None if status == OfferStatus.DRAFT else timezone.now())


def _get(slug, user_id, path, **params):
    return Client().get(f"{BASE}/{path}", data=params, **s.auth(slug, user_id))


def _feed(slug, user_id, **params) -> dict:
    response = _get(slug, user_id, "alternatives/feed", **params)
    assert response.status_code == 200, response.content
    return response.json()


def _ids(page: dict) -> set[str]:
    return {row["source_id"] for row in page["items"]}


# ── лента L-09 ──────────────────────────────────────────────────────────

def test_feed_lists_open_sources_only(company_context):
    """Счёт по договору, решённый счёт, договор-черновик, открытый договор и
    допсоглашение в ленту не попадают; свои документы — попадают."""
    slug = company_context["slug"]
    s.actor(slug, s.FD, "bpp-fd")
    open_invoice = _invoice()
    on_review = _agreement()
    active = _agreement(status=AgreementStatus.ACTIVE)
    by_contract = _invoice()
    by_contract.basis, by_contract.agreement = InvoiceBasis.CONTRACT, active
    by_contract.save()
    _invoice(status=InvoiceStatus.TO_PAY)
    _invoice(status=InvoiceStatus.DRAFT)
    _agreement(status=AgreementStatus.DRAFT)
    _agreement(is_open=True)
    _agreement(parent_agreement=active)

    page = _feed(slug, s.FD)

    assert _ids(page) == {str(open_invoice.pk), str(on_review.pk)}
    assert page["total"] == 2 and (page["page"], page["page_size"]) == (1, 50)
    kinds = {row["source_id"]: (row["source_type"], row["kind_label"]) for row in page["items"]}
    assert kinds[str(on_review.pk)] == ("agreement", "Договор")
    assert _ids(_feed(slug, s.FD, kind="invoice")) == {str(open_invoice.pk)}
    assert _ids(_feed(slug, s.FD, source=f"agreement:{on_review.pk}")) == {str(on_review.pk)}
    # Автор-СН видит в ленте и свой документ (ТЗ §12.2 «включая свои»).
    s.actor(slug, s.SN, "bpp-sn")
    assert _ids(_feed(slug, s.SN)) == {str(open_invoice.pk), str(on_review.pk)}


def test_feed_filters_without_offers_and_mine(company_context):
    slug = company_context["slug"]
    common.sn(slug, common.SN2)
    with_offer, without = _invoice(), _invoice()
    mine = _offer(with_offer, author_id=common.SN2)
    _offer(without, author_id=common.SN3, status=OfferStatus.WITHDRAWN)

    assert _ids(_feed(slug, common.SN2, without_offers="1")) == {str(without.pk)}
    page = _feed(slug, common.SN2, mine="yes")
    assert _ids(page) == {str(with_offer.pk)}
    assert page["items"][0]["my_offer"] == {"id": str(mine.pk), "number": mine.number,
                                            "status": "submitted", "status_label": "Подано"}
    no = _feed(slug, common.SN2, mine="no")
    assert _ids(no) == {str(without.pk)} and no["items"][0]["my_offer"] is None


def test_feed_counts_live_offers_only(company_context):
    """«Альтернатив подано» — «Подано» и «Выбрано»; «Отозвано»,
    «Аннулировано» и черновики не считаются (как лимит документа)."""
    slug = company_context["slug"]
    s.actor(slug, s.FD, "bpp-fd")
    inv = _invoice()
    for status in (OfferStatus.SUBMITTED, OfferStatus.SUBMITTED, OfferStatus.WITHDRAWN,
                   OfferStatus.ANNULLED, OfferStatus.DRAFT):
        _offer(inv, author_id=900 + next(_SEQ), status=status)
    agr = _agreement()
    _offer(agr, status=OfferStatus.ANNULLED, source_type=common.AGREEMENT)

    counts = {row["source_id"]: row["offers_count"] for row in _feed(slug, s.FD)["items"]}
    assert counts == {str(inv.pk): 2, str(agr.pk): 0}
    assert _ids(_feed(slug, s.FD, without_offers="1")) == {str(agr.pk)}


def test_feed_row_positions_sent_and_filters(company_context):
    """Строка ленты: позиции кратко (3 + «ещё N»), автор, отправлен (запись
    журнала ``submitted``); фильтры поиска по позициям и суммы; мусор — 422."""
    slug = company_context["slug"]
    s.actor(slug, s.FD, "bpp-fd")
    _, proj, inv = common.invoice_on_review(slug, 10, 20, 30, 40, 50)

    (row,) = _feed(slug, s.FD)["items"]
    assert row["positions"] == {"names": ["Позиция 1", "Позиция 2", "Позиция 3"],
                                "more": 2, "count": 5}
    assert row["number"] == inv.number and row["amount"] == "150.00"
    assert row["author_id"] == s.SN and row["author_name"]
    assert row["sent_at"] is not None and row["project"]["code"] == proj.code
    assert row["counterparty"]["reg_number"] and row["url"] == f"/bpp/invoices/{inv.pk}"
    assert _ids(_feed(slug, s.FD, q="Позиция 4")) == {str(inv.pk)}
    assert _ids(_feed(slug, s.FD, q="нет такой")) == set()
    assert _ids(_feed(slug, s.FD, amount_from="151")) == set()
    assert _ids(_feed(slug, s.FD, amount_to="150", project_id=str(proj.id))) == {str(inv.pk)}
    today = timezone.localdate().isoformat()
    assert _ids(_feed(slug, s.FD, sent_from=today, sent_to=today)) == {str(inv.pk)}
    for params in ({"kind": "act"}, {"mine": "maybe"}, {"source": "invoice:1"},
                   {"amount_from": "abc"}, {"sent_from": "30.09.2026"}):
        response = _get(slug, s.FD, "alternatives/feed", **params)
        assert response.status_code == 422, (params, response.content)


def test_feed_forbidden_without_alternatives_view(company_context):
    """БУХ и АДМ узла ``bpp.alternatives`` не имеют — 403 на ленту и списки."""
    slug = company_context["slug"]
    s.actor(slug, BUH, "bpp-buh")
    inv = _invoice()
    for path in ("alternatives/feed", "alternatives/offers?mine=1",
                 f"alternatives/sources/invoice/{inv.pk}/comparison"):
        response = _get(slug, BUH, path)
        assert response.status_code == 403, (path, response.content)
        assert response.json()["code"] == "E-ACC-01"


# ── сравнение и карточка ────────────────────────────────────────────────

def test_comparison_ac014(company_context):
    """AC-014: ФД видит экономию 350 000,00 KZT (12,5 %) в сравнении."""
    slug = company_context["slug"]
    s.actor(slug, s.FD, "bpp-fd")
    _, _, inv = common.invoice_on_review(slug, D("2800000"))
    offer = common.filed(common.sn(slug, common.SN2), inv, common.cp(2), price=D("2450000"))

    response = _get(slug, s.FD, f"alternatives/sources/invoice/{inv.pk}/comparison")
    assert response.status_code == 200, response.content
    data = response.json()
    assert data["source"]["number"] == inv.number
    assert data["source"]["amount"] == "2800000.00"
    assert data["source"]["counterparty"]["country_code"] == "KZ"
    (column,) = data["offers"]
    assert column["id"] == str(offer.pk) and column["status"] == "submitted"
    assert column["saving"] == {"amount": "350000.00", "pct": "12.50", "more_expensive": False}
    assert column["amount"] == "2450000.00" and len(column["files"]) == 1
    assert column["author"]["id"] == common.SN2
    (position,) = data["positions"]
    assert position["source_price"] == "2800000.00"
    assert position["offers"][str(offer.pk)] == {
        "price": "2450000.00", "amount": "2450000.00", "deviation_pct": "-12.50"}
    assert (data["limit"], data["submitted_count"], data["window_open"]) == (3, 1, True)
    # ФД альтернативы не подаёт; другой СН — может (лимит 3, у него АП нет).
    assert data["can_propose"] is False and data["my_offer_id"] is None
    common.sn(slug, common.SN3)
    other = _get(slug, common.SN3, f"alternatives/sources/invoice/{inv.pk}/comparison").json()
    assert other["can_propose"] is True and other["propose_blocked_reason"] is None
    assert other["offers"] == []  # чужая поданная АП СН не видна
    mine = _get(slug, common.SN2, f"alternatives/sources/invoice/{inv.pk}/comparison").json()
    assert mine["my_offer_id"] == str(offer.pk) and mine["can_propose"] is False


def test_comparison_hides_foreign_drafts(company_context):
    slug = company_context["slug"]
    s.actor(slug, s.FD, "bpp-fd")
    _, _, inv = common.invoice_on_review(slug, 1000)
    filed = common.filed(common.sn(slug, common.SN2), inv, common.cp(2), price=900)
    draft = common.draft(common.sn(slug, common.SN3), inv)

    def columns(user_id):
        response = _get(slug, user_id, f"alternatives/sources/invoice/{inv.pk}/comparison")
        assert response.status_code == 200, response.content
        return [column["id"] for column in response.json()["offers"]]

    assert columns(s.FD) == [str(filed.pk)]
    assert columns(s.SN) == [str(filed.pk)]            # автор исходного документа
    assert columns(common.SN3) == [str(draft.pk)]      # свой черновик — да, чужая АП — нет


def test_offer_card_fields_and_deviation(company_context):
    slug = company_context["slug"]
    s.actor(slug, s.FD, "bpp-fd")
    _, proj, inv = common.invoice_on_review(slug, 100, 200)
    offer = common.filed(common.sn(slug, common.SN2), inv, common.cp(2), price=None,
                         prices=[110, 150])

    response = _get(slug, s.FD, f"alternatives/offers/{offer.pk}")
    assert response.status_code == 200, response.content
    card = response.json()
    assert card["version"] == offer.version and card["allowed_actions"] == []
    assert [line["deviation_pct"] for line in card["lines"]] == ["10.00", "-25.00"]
    assert card["project"]["code"] == proj.code and card["author_name"]
    assert card["source"]["amount"] == "300.00" and card["source"]["author_id"] == s.SN
    assert card["source"]["counterparty"]["reg_number"]
    assert card["more_expensive"] is False
    author_card = _get(slug, common.SN2, f"alternatives/offers/{offer.pk}").json()
    assert author_card["allowed_actions"] == ["withdraw"]


# ── видимость ───────────────────────────────────────────────────────────

def test_pm_sees_offers_to_own_documents_only(company_context):
    """ПМ — «V (свои документы)»: АП к своему документу видит, чужую — 404;
    в ленте — только свои документы. КП — по тому же правилу."""
    slug = company_context["slug"]
    common.pm(slug)
    own_doc, other_doc = _invoice(author_id=s.PM), _invoice(author_id=s.SN)
    own_offer, other_offer = _offer(own_doc), _offer(other_doc)

    assert _get(slug, s.PM, f"alternatives/offers/{own_offer.pk}").status_code == 200
    assert _get(slug, s.PM, f"alternatives/offers/{other_offer.pk}").status_code == 404
    assert _get(slug, s.PM, f"alternatives/sources/invoice/{other_doc.pk}/comparison"
                ).status_code == 404
    assert _ids(_feed(slug, s.PM)) == {str(own_doc.pk)}
    with use_company(slug):
        token = s.actor(slug, s.PM, "bpp-pm").request.token
        assert file_owner._can_view(own_offer.pk, token) is True
        assert file_owner._can_view(other_offer.pk, token) is False


def test_can_view_rules(company_context):
    slug = company_context["slug"]
    inv = _invoice(author_id=s.SN)
    submitted, draft = _offer(inv), _offer(inv, author_id=common.SN3,
                                           status=OfferStatus.DRAFT)
    fd, td = s.actor(slug, s.FD, "bpp-fd"), s.actor(slug, s.TD, "bpp-td")
    source_author, stranger = common.sn(slug), common.sn(slug, common.SN4)
    buh = s.actor(slug, BUH, "bpp-buh")

    assert all(read.can_view(who, submitted) for who in (fd, td, source_author))
    assert not read.can_view(stranger, submitted) and not read.can_view(buh, submitted)
    assert read.can_view(common.sn(slug, common.SN3), draft)
    assert not any(read.can_view(who, draft) for who in (fd, source_author))


def test_history_of_offer_requires_view(company_context):
    slug = company_context["slug"]
    s.actor(slug, s.FD, "bpp-fd")
    common.sn(slug, common.SN2), common.sn(slug, common.SN3)
    offer = _offer(_invoice(), author_id=common.SN2)
    path = f"history/bpp.alternativeoffer/{offer.pk}"

    assert _get(slug, common.SN3, path).status_code == 404
    assert _get(slug, common.SN2, path).status_code == 200
    assert _get(slug, s.FD, path).status_code == 200


# ── «Мои альтернативы» ──────────────────────────────────────────────────

def test_my_offers_lists_own_only_with_status_filter(company_context):
    slug = company_context["slug"]
    common.sn(slug, common.SN2)
    inv = _invoice()
    submitted = _offer(inv, author_id=common.SN2)
    withdrawn = _offer(inv, author_id=common.SN2, status=OfferStatus.WITHDRAWN)
    _offer(inv, author_id=common.SN3)

    response = _get(slug, common.SN2, "alternatives/offers", mine="1")
    assert response.status_code == 200, response.content
    page = response.json()
    assert page["total"] == 2
    assert {row["id"] for row in page["items"]} == {str(submitted.pk), str(withdrawn.pk)}
    row = next(r for r in page["items"] if r["id"] == str(submitted.pk))
    assert row["source"] == {"type": "invoice", "id": str(inv.pk), "number": inv.number,
                             "kind_label": "Счёт на оплату", "url": f"/bpp/invoices/{inv.pk}"}
    only = _get(slug, common.SN2, "alternatives/offers", mine="1", status="withdrawn").json()
    assert [r["id"] for r in only["items"]] == [str(withdrawn.pk)]
    assert _get(slug, common.SN2, "alternatives/offers", status="bogus").status_code == 422
    assert _get(slug, common.SN2, "alternatives/offers", mine="0").status_code == 422

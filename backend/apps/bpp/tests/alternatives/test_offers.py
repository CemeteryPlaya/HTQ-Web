"""Альтернативные предложения: черновик, подача, отзыв, лимиты (ТЗ §12.1,
§12.3, §12.7, BR-090…092, AC-014, AC-018; план этапа 5 A, задача 2).

Документы — фабриками B (счёт «На рассмотрении ФД», договор «На
согласовании»), пользователи — ``tests/stage2.py``. Гонка за последнее
место в лимите (Review Focus 1) — транзакционный тест на ORM-документах.
"""

from __future__ import annotations

import threading
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test import Client
from django.utils import timezone

from apps.access.models import RoleAssignment
from apps.bpp.models import AlternativeOffer, AuditLog, Invoice, OfferStatus
from apps.bpp.services.alternatives import offers
from apps.bpp.services.invoices import decisions
from apps.bpp.services.invoices import invoices as invoice_service
from apps.bpp.tests import stage2 as s
from apps.bpp.tests import test_invoices as invoice_flow
from apps.bpp.tests.bank.common import counterparty as orm_counterparty
from apps.bpp.tests.test_files import memory_storage  # noqa: F401  (фикстура)
from apps.refdata.models import ExchangeRate
from htqweb.errors import DomainError
from htqweb.tenancy.db import use_company

from . import common

D = Decimal
BASE = "/api/bpp/v1"
pytestmark = pytest.mark.django_db


def _fail(call) -> DomainError:
    with pytest.raises(DomainError) as exc:
        call()
    return exc.value


def _fields(err: DomainError) -> list[str]:
    return [row["field"] for row in err.fields]


def _fd(slug):
    return s.actor(slug, s.FD, "bpp-fd")


# ── подача и экономия ──────────────────────────────────────────────────

def test_ac014_saving_visible_after_submit(company_context):
    slug = company_context["slug"]
    _, proj, inv = common.invoice_on_review(slug, D("2800000"))
    buyer = common.sn(slug, common.SN2)

    offer = common.filed(buyer, inv, common.cp(2), price=D("2450000"))

    assert offer.status == OfferStatus.SUBMITTED and offer.number.startswith("АП-")
    assert (offer.saving_amount, offer.saving_pct) == (D("350000.00"), D("12.50"))
    assert (offer.source_amount_kzt, offer.amount_kzt) == (D("2800000.00"), D("2450000.00"))
    assert offer.own_document is False and offer.author_role == "sn"
    # Снимок проекта и статьи исходного документа — для отчёта R-01.
    assert (str(offer.project_id), str(offer.article_id)) == (str(inv.project_id),
                                                              str(inv.article_id))
    assert AuditLog.objects.filter(object_id=str(offer.pk), action="submitted").count() == 1


def test_draft_takes_all_positions_without_prices(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 100, 200)
    offer = common.draft(common.sn(slug, common.SN2), inv)

    assert offer.status == OfferStatus.DRAFT and offer.currency_code == inv.currency_code
    lines = list(offer.lines.order_by("created_at"))
    assert [line.source_price for line in lines] == [D("100.00"), D("200.00")]
    assert all(line.price is None for line in lines)
    assert offer.saving_amount is None and offer.counterparty_id is None


def test_agreement_offer_takes_positions_and_saves(company_context):
    slug = company_context["slug"]
    _, _, agr = common.agreement_on_review(slug, D("1000000"))

    offer = common.filed(common.sn(slug, common.SN2), agr, common.cp(2), price=D("900000"),
                         source_type=common.AGREEMENT)

    assert offer.source_type == "agreement" and offer.source_id == agr.pk
    assert (offer.saving_amount, offer.saving_pct) == (D("100000.00"), D("10.00"))
    assert str(offer.project_id) == str(agr.project_id)


def test_offer_to_contract_invoice_is_422(company_context):
    slug = company_context["slug"]
    author, _, agr = invoice_flow._active_agreement(slug, 10_000_000)
    inv = invoice_service.create_from_agreement(author, agr.id)
    inv, _ = invoice_service.update_draft(author, inv.id, expected_version=None,
                                          data={"ext_number": "1"})
    invoice_flow._attach(inv)  # файл счёта обязателен для отправки, ТЗ §21
    inv = invoice_service.submit(author, inv.id, expected_version=None)

    err = _fail(lambda: common.draft(common.sn(slug, common.SN2), inv))
    assert (err.code, err.status, _fields(err)) == ("E-VAL-01", 422, ["source_id"])
    assert err.message == "Альтернатива к счёту по договору не подаётся"


def test_open_agreement_is_422(company_context):
    """D-S5-5: у открытого договора нет цен позиций — сравнивать не с чем."""
    slug = company_context["slug"]
    _, _, agr = common.agreement_on_review(slug, 500)
    type(agr).objects.filter(pk=agr.pk).update(is_open=True)

    err = _fail(lambda: common.draft(common.sn(slug, common.SN2), agr, common.AGREEMENT))
    assert (err.code, _fields(err)) == ("E-VAL-01", ["source_id"])
    assert err.message.startswith("К открытому договору альтернатива не подаётся")


def test_unknown_source_is_404(company_context):
    slug = company_context["slug"]
    buyer = common.sn(slug, common.SN2)
    assert _fail(lambda: offers.create(buyer, source_type="invoice",
                                       source_id=uuid.uuid4())).status == 404
    assert _fail(lambda: offers.create(buyer, source_type="request",
                                       source_id=uuid.uuid4())).status == 404


# ── контрагент, BR-091 ─────────────────────────────────────────────────

def test_same_counterparty_as_source_is_422_br091(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    buyer = common.sn(slug, common.SN2)
    offer = common.draft(buyer, inv)

    err = _fail(lambda: common.fill(buyer, offer, inv.counterparty, price=900, kp=False))
    assert (err.code, _fields(err)) == ("E-VAL-01", ["counterparty_id"])
    assert err.message == ("Контрагент совпадает с исходным или с другой альтернативой "
                           "по документу")


def test_same_counterparty_as_other_offer_is_422(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    first, second = common.sn(slug, common.SN2), common.sn(slug, common.SN3)
    other = common.cp(2)
    held = common.fill(first, common.draft(first, inv), other, price=900, kp=False)

    offer = common.draft(second, inv)
    err = _fail(lambda: common.fill(second, offer, other, price=800, kp=False))
    assert (err.code, _fields(err)) == ("E-VAL-01", ["counterparty_id"])

    # Отозванная АП контрагента не держит.
    common.attach_kp(held, first)
    offers.submit(first, held.id, expected_version=None)
    offers.withdraw(first, held.id, expected_version=None)
    assert common.fill(second, offer, other, price=800, kp=False).counterparty_id == other.pk


def test_submit_rechecks_counterparty_after_draft(company_context):
    """Контрагента заблокировали (или другая АП заняла) уже после черновика."""
    from apps.bpp.models import Counterparty, CounterpartyStatus

    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    first, second = common.sn(slug, common.SN2), common.sn(slug, common.SN3)
    party = common.cp(2)
    offer = common.fill(first, common.draft(first, inv), party, price=900)
    Counterparty.objects.filter(pk=party.pk).update(
        status=CounterpartyStatus.BLOCKED, blocked_at=timezone.now(), block_reason="спор")

    err = _fail(lambda: offers.submit(first, offer.id, expected_version=None))
    assert (err.code, _fields(err)) == ("E-CTR-01", ["counterparty_id"])
    offer.refresh_from_db()
    assert offer.status == OfferStatus.DRAFT

    # Контрагента исходного документа тоже не пропускаем при подаче.
    Counterparty.objects.filter(pk=party.pk).update(status=CounterpartyStatus.ACTIVE)
    AlternativeOffer.objects.filter(pk=offer.pk).update(counterparty=inv.counterparty)
    err = _fail(lambda: offers.submit(first, offer.id, expected_version=None))
    assert _fields(err) == ["counterparty_id"]


def test_submit_rechecks_delivery_date(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    buyer = common.sn(slug, common.SN2)
    offer = common.fill(buyer, common.draft(buyer, inv), common.cp(2), price=900)
    AlternativeOffer.objects.filter(pk=offer.pk).update(
        delivery_date=timezone.localdate() - timedelta(days=1))
    assert _fields(_fail(lambda: offers.submit(buyer, offer.id, expected_version=None))) == [
        "delivery_date"]


# ── свой документ, AC-018 ──────────────────────────────────────────────

def test_own_document_flag_ac018(company_context):
    slug = company_context["slug"]
    author, _, inv = common.invoice_on_review(slug, 1000)

    offer = common.filed(author, inv, common.cp(2), price=D("900"))

    assert offer.own_document is True and offer.status == OfferStatus.SUBMITTED


# ── окно подачи, BR-090 ────────────────────────────────────────────────

def test_window_closed_after_fd_decision_is_422(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    buyer = common.sn(slug, common.SN2)
    offer = common.fill(buyer, common.draft(buyer, inv), common.cp(2), price=900)
    assert offers.window_open(inv)

    decisions.decide(_fd(slug), inv.id, decision="pay")
    inv.refresh_from_db()

    assert not offers.window_open(inv)
    err = _fail(lambda: offers.submit(buyer, offer.id, expected_version=None))
    assert (err.code, err.message) == ("E-STATE-01",
                                       "Документ уже решён — альтернатива не подаётся")
    err = _fail(lambda: common.draft(common.sn(slug, common.SN3), inv))
    assert err.code == "E-STATE-01"


def test_withdraw_only_while_window_is_open(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    buyer, other = common.sn(slug, common.SN2), common.sn(slug, common.SN3)
    first = common.filed(buyer, inv, common.cp(2), price=900)
    second = common.filed(other, inv, common.cp(3), price=800)

    assert offers.withdraw(buyer, first.id, expected_version=None).status == \
        OfferStatus.WITHDRAWN
    assert _fail(lambda: offers.withdraw(other, second.id, expected_version=999)
                 ).code == "E-CON-01"
    assert _fail(lambda: offers.withdraw(buyer, first.id, expected_version=None)).status == 409

    decisions.decide(_fd(slug), inv.id, decision="pay")
    assert _fail(lambda: offers.withdraw(other, second.id, expected_version=None)).code == \
        "E-STATE-01"


# ── лимиты, BR-090…092, D-S5-2 ─────────────────────────────────────────

def test_document_limit_and_raise(company_context):
    slug = company_context["slug"]
    author, _, inv = common.invoice_on_review(slug, 1000)
    buyers = [common.sn(slug, uid) for uid in (common.SN2, common.SN3, common.SN4)]
    for n, buyer in enumerate(buyers, start=2):
        common.filed(buyer, inv, common.cp(n), price=900)

    err = _fail(lambda: common.draft(author, inv))
    assert (err.code, _fields(err)) == ("E-VAL-01", ["source_id"])
    assert err.message == "К документу уже подано 3 альтернатив — это лимит"

    assert offers.set_limit(author, source_type="invoice", source_id=inv.pk, limit=4) == 4
    inv.refresh_from_db()
    assert inv.alt_limit == 4
    fourth = common.filed(author, inv, common.cp(5), price=850)
    assert fourth.status == OfferStatus.SUBMITTED

    assert _fields(_fail(lambda: offers.set_limit(
        author, source_type="invoice", source_id=inv.pk, limit=11))) == ["limit"]
    assert _fields(_fail(lambda: offers.set_limit(
        author, source_type="invoice", source_id=inv.pk, limit=3))) == ["limit"]
    assert AuditLog.objects.filter(object_id=str(inv.pk), action="alt_limit_changed").count() == 1


def test_only_source_author_sets_the_limit(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    err = _fail(lambda: offers.set_limit(common.sn(slug, common.SN2), source_type="invoice",
                                         source_id=inv.pk, limit=5))
    assert (err.code, err.status) == ("E-ACC-01", 403)


def test_one_offer_per_buyer(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    buyer = common.sn(slug, common.SN2)
    common.draft(buyer, inv)

    err = _fail(lambda: common.draft(buyer, inv))
    assert (err.code, _fields(err)) == ("E-VAL-01", ["source_id"])


def test_withdrawn_offer_frees_the_buyer_slot(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    buyer = common.sn(slug, common.SN2)
    first = common.filed(buyer, inv, common.cp(2), price=900)
    offers.withdraw(buyer, first.id, expected_version=None)

    assert common.draft(buyer, inv).status == OfferStatus.DRAFT


def test_pm_limit_is_three_per_document(company_context, monkeypatch):
    """D-S5-1: ПМ подаёт до трёх — правило лимита в коде, хотя матрица ему
    ``create`` пока не даёт; роль автора подменяем, права — у СН."""
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    Invoice.objects.filter(pk=inv.pk).update(alt_limit=10)
    buyer = common.sn(slug, common.SN2)
    monkeypatch.setattr(offers, "_author_role", lambda actor: "pm")

    made = [common.draft(buyer, inv) for _ in range(3)]

    assert {offer.author_role for offer in made} == {"pm"}
    err = _fail(lambda: common.draft(buyer, inv))
    assert (err.code, _fields(err)) == ("E-VAL-01", ["source_id"])
    assert "3" in err.message


# ── частичная АП в валюте, Review Focus 3 ──────────────────────────────

def test_partial_offer_saving_on_chosen_lines_only(company_context):
    slug = company_context["slug"]
    ExchangeRate.objects.update_or_create(currency_code="USD", on_date=timezone.localdate(),
                                          defaults={"rate": D("500"), "source": "nbrk"})
    author, _, inv = invoice_flow._invoice(slug, 100, 200, 300)
    inv, _ = invoice_service.update_draft(author, inv.id, expected_version=None,
                                          data={"currency_code": "USD"})
    inv = invoice_service.submit(author, inv.id, expected_version=None)
    assert inv.rate == D("500")
    buyer = common.sn(slug, common.SN2)

    offer = common.fill(buyer, common.draft(buyer, inv), common.cp(2), currency_code="KZT",
                        prices=[D("40000"), D("90000")], keep=2)
    offer = offers.submit(buyer, offer.id, expected_version=None)

    assert offer.lines.count() == 2 and offer.currency_code == "KZT"
    # Исходная часть = (A + B) × 500 = 150 000, а не весь счёт (300 000).
    assert offer.source_amount_kzt == D("150000.00")
    assert offer.amount_kzt == D("130000.00")
    assert (offer.saving_amount, offer.saving_pct) == (D("20000.00"), D("13.33"))


def test_offer_in_foreign_currency_needs_a_rate(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    buyer = common.sn(slug, common.SN2)
    offer = common.fill(buyer, common.draft(buyer, inv), common.cp(2), price=D("1"),
                        currency_code="EUR")
    assert offer.amount_kzt is None and offer.saving_amount is None

    err = _fail(lambda: offers.submit(buyer, offer.id, expected_version=None))
    assert (err.code, _fields(err)) == ("E-REF-05", ["rate"])


# ── удорожание, ТЗ §12.3 ───────────────────────────────────────────────

def test_more_expensive_needs_30_chars(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    buyer = common.sn(slug, common.SN2)
    offer = common.fill(buyer, common.draft(buyer, inv), common.cp(2), price=D("1200"),
                        justification="х" * 29)
    assert offer.saving_amount == D("-200.00")

    err = _fail(lambda: offers.submit(buyer, offer.id, expected_version=None))
    assert (err.code, _fields(err)) == ("E-VAL-01", ["justification"])
    assert err.message == ("Альтернатива дороже исходного — опишите причину (сроки, "
                           "качество, наличие), не короче 30 символов")

    offer = offers.update_draft(buyer, offer.id, expected_version=None,
                                data={"justification": "х" * 30})
    assert offers.submit(buyer, offer.id, expected_version=None).status == OfferStatus.SUBMITTED


# ── обязательные поля и КП ─────────────────────────────────────────────

def test_submit_requires_kp_file(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    buyer = common.sn(slug, common.SN2)
    offer = common.fill(buyer, common.draft(buyer, inv), common.cp(2), price=900, kp=False)

    err = _fail(lambda: offers.submit(buyer, offer.id, expected_version=None))
    assert (err.code, _fields(err)) == ("E-VAL-01", ["files"])

    common.attach_kp(offer, buyer)
    assert offers.submit(buyer, offer.id, expected_version=None).status == OfferStatus.SUBMITTED


def test_submit_lists_every_missing_field(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    buyer = common.sn(slug, common.SN2)
    offer = common.draft(buyer, inv)

    err = _fail(lambda: offers.submit(buyer, offer.id, expected_version=None))
    assert set(_fields(err)) == {"counterparty_id", "lines", "delivery_date", "payment_terms",
                                 "justification", "files"}


def test_out_of_range_values_are_422_not_500(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    buyer = common.sn(slug, common.SN2)
    offer = common.draft(buyer, inv)
    line = offer.lines.get()

    def patch(**data):
        return _fail(lambda: offers.update_draft(buyer, offer.id, expected_version=None,
                                                 data=data))

    assert _fields(patch(lines=[{"source_line_id": str(line.source_line_id),
                                 "price": "99999999999999999.99"}])) == ["lines"]
    assert _fields(patch(lines=[{"source_line_id": str(line.source_line_id),
                                 "price": "0"}])) == ["lines"]
    assert _fields(patch(lines=[{"source_line_id": str(line.source_line_id),
                                 "price": "NaN"}])) == ["lines"]
    assert _fields(patch(lines=[])) == ["lines"]
    assert _fields(patch(lines=[{"source_line_id": "00000000-0000-0000-0000-000000000001",
                                 "price": 5}])) == ["lines"]
    assert _fields(patch(vat_rate=101)) == ["vat_rate"]
    assert _fields(patch(delivery_date=timezone.localdate() - timedelta(days=1))) == [
        "delivery_date"]
    assert _fields(patch(justification="коротко")) == ["justification"]
    assert _fields(patch(payment_terms="кредит")) == ["payment_terms"]
    # Цена в разы выше исходной: процент не влезает в столбец — 422, а не 500.
    hi = D("9999999999999")
    assert _fields(patch(lines=[{"source_line_id": str(line.source_line_id),
                                 "price": hi}])) == ["lines"]
    assert _fail(lambda: offers.update_draft(buyer, offer.id, expected_version=None,
                                             data={"currency_code": "тенге"})).code == "E-VAL-01"


def test_manual_vat_and_counterparty_default(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    buyer = common.sn(slug, common.SN2)
    offer = common.fill(buyer, common.draft(buyer, inv), common.cp(2), price=D("1160"),
                        kp=False)
    assert (offer.vat_source, offer.vat_rate, offer.vat_amount) == (
        "refdata", D("16.00"), D("160.00"))
    offer = offers.update_draft(buyer, offer.id, expected_version=None, data={"vat_rate": 10})
    assert (offer.vat_source, offer.vat_rate) == ("manual", D("10.00"))
    offer = offers.update_draft(buyer, offer.id, expected_version=None,
                                data={"with_vat": False})
    assert (offer.vat_rate, offer.vat_amount) == (None, None)


# ── права и версии ─────────────────────────────────────────────────────

def test_roles_without_create_are_403(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    for actor in (s.actor(slug, s.TD, "bpp-td"), common.pm(slug)):   # D-S5-1: ПМ — нет
        err = _fail(lambda actor=actor: common.draft(actor, inv))
        assert (err.code, err.status) == ("E-ACC-01", 403)


def test_foreign_buyer_cannot_touch_the_draft(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    owner, stranger = common.sn(slug, common.SN2), common.sn(slug, common.SN3)
    offer = common.draft(owner, inv)

    for call in (
            lambda: offers.update_draft(stranger, offer.id, expected_version=None,
                                        data={"justification": "Чужая правка текста"}),
            lambda: offers.delete_draft(stranger, offer.id, expected_version=None),
            lambda: offers.submit(stranger, offer.id, expected_version=None)):
        assert _fail(call).status == 403
    with pytest.raises(DomainError) as exc:
        offers.get_visible(stranger, offer.id)
    assert exc.value.status == 404          # чужой черновик не виден вовсе


def test_revoked_role_blocks_edit_and_submit_of_own_draft(company_context):
    """M11: право ``bpp.alternatives`` create перепроверяется на правке и
    подаче: СН без роли свой черновик не правит и не подаёт, но удаляет."""
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    owner = common.sn(slug, common.SN2)
    offer = common.fill(owner, common.draft(owner, inv), common.cp(2), price=900)
    RoleAssignment.objects.filter(company_slug=slug, user_id=common.SN2,
                                  role__code="bpp-sn").delete()
    former = s.actor(slug, common.SN2)
    for call in (
            lambda: offers.update_draft(former, offer.id, expected_version=None,
                                        data={"justification": "Правка без права на АП"}),
            lambda: offers.submit(former, offer.id, expected_version=None)):
        err = _fail(call)
        assert (err.code, err.status) == ("E-ACC-01", 403)
    assert offers.allowed_actions(former, AlternativeOffer.objects.get(pk=offer.pk)) == [
        "delete"]
    offers.delete_draft(former, offer.id, expected_version=None)
    assert not AlternativeOffer.objects.filter(pk=offer.pk).exists()


def test_stale_version_is_409_and_draft_delete_removes_the_row(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    buyer = common.sn(slug, common.SN2)
    offer = common.draft(buyer, inv)

    err = _fail(lambda: offers.update_draft(buyer, offer.id, expected_version=99, data={}))
    assert (err.code, err.status) == ("E-CON-01", 409)

    offers.delete_draft(buyer, offer.id, expected_version=offer.version)
    assert not AlternativeOffer.objects.filter(pk=offer.pk).exists()
    assert AuditLog.objects.filter(object_id=str(offer.pk), action="deleted").count() == 1


def test_submitted_offer_is_not_editable_or_deletable(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    buyer = common.sn(slug, common.SN2)
    offer = common.filed(buyer, inv, common.cp(2), price=900)

    assert _fail(lambda: offers.update_draft(buyer, offer.id, expected_version=None,
                                             data={})).status == 409
    assert _fail(lambda: offers.delete_draft(buyer, offer.id, expected_version=None)
                 ).status == 409
    assert offers.allowed_actions(buyer, offer) == ["withdraw"]


# ── HTTP: ручки и идемпотентность ──────────────────────────────────────

def test_http_flow_and_idempotent_create(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    buyer = common.sn(slug, common.SN2)
    cp = common.cp(2)
    client = Client()
    headers = {**s.auth(slug, common.SN2), "HTTP_IDEMPOTENCY_KEY": "alt-create-1"}
    body = {"source_type": "invoice", "source_id": str(inv.pk)}

    first = client.post(f"{BASE}/alternatives/offers", data=body, **headers)
    again = client.post(f"{BASE}/alternatives/offers", data=body, **headers)
    assert first.status_code == 201, first.content
    assert again.json()["id"] == first.json()["id"]
    card = first.json()
    with use_company(slug):
        assert AlternativeOffer.objects.count() == 1
        assert AuditLog.objects.filter(object_type="bpp.alternativeoffer",
                                       action="created").count() == 1
    assert card["status"] == "draft" and card["source"]["window_open"] is True
    assert "submit" in card["allowed_actions"] and len(card["lines"]) == 1

    line = card["lines"][0]
    patched = client.patch(f"{BASE}/alternatives/offers/{card['id']}", data={
        "version": card["version"], "counterparty_id": str(cp.pk),
        "lines": [{"source_line_id": line["source_line_id"], "price": "900.00"}],
        "delivery_date": str(timezone.localdate() + timedelta(days=5)),
        "payment_terms": "postpay", "justification": "Дешевле и быстрее"},
        **s.auth(slug, common.SN2))
    assert patched.status_code == 200, patched.content
    assert patched.json()["saving_amount"] == "100.00"

    with use_company(slug):
        common.attach_kp(AlternativeOffer.objects.get(pk=card["id"]), buyer)
    submitted = client.post(f"{BASE}/alternatives/offers/{card['id']}/submit",
                            data={"version": patched.json()["version"]},
                            **s.auth(slug, common.SN2))
    assert submitted.status_code == 200, submitted.content
    assert submitted.json()["status"] == "submitted"
    assert submitted.json()["saving_pct"] == "10.00"

    limit = client.post(f"{BASE}/alternatives/sources/invoice/{inv.pk}/limit",
                        data={"limit": 5}, **s.auth(slug, s.SN))
    assert limit.status_code == 200 and limit.json()["alt_limit"] == 5

    withdrawn = client.post(f"{BASE}/alternatives/offers/{card['id']}/withdraw",
                            data={"version": submitted.json()["version"]},
                            **s.auth(slug, common.SN2))
    assert withdrawn.status_code == 200 and withdrawn.json()["status"] == "withdrawn"
    assert client.get(f"{BASE}/alternatives/offers/not-a-uuid",
                      **s.auth(slug, common.SN2)).status_code == 404


def test_http_role_without_create_is_403(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    common.pm(slug)
    s.actor(slug, s.TD, "bpp-td")
    client = Client()
    for user in (s.PM, s.TD):
        response = client.post(f"{BASE}/alternatives/offers",
                               data={"source_type": "invoice", "source_id": str(inv.pk)},
                               **s.auth(slug, user))
        assert response.status_code == 403, response.content


# ── гонка за последнее место, Review Focus 1 ───────────────────────────

@pytest.mark.django_db(transaction=True)
def test_race_for_last_limit_slot(monkeypatch):
    """Лимит 3, подано 2. Два СН подают третью и четвёртую одновременно
    (барьер перед блокировкой исходного документа): проходит ровно одна,
    вторая — 422 про лимит. Подтверждённых потоков без исключений — все."""
    monkeypatch.setattr(offers.core_files, "list_files", lambda owner: [{"id": "kp"}])
    inv = common.orm_invoice_source([1000], author_id=901, alt_limit=3)
    buyers = [s.actor(None, uid, superuser=True) for uid in (911, 912, 913, 914)]
    cps = [orm_counterparty(f"10000000{n:04d}") for n in range(2, 6)]
    drafts = []
    for buyer, party in zip(buyers, cps, strict=True):
        offer = common.draft(buyer, inv)
        drafts.append(common.fill(buyer, offer, party, price=D("900"), kp=False))
    for buyer, offer in zip(buyers[:2], drafts[:2], strict=True):
        offers.submit(buyer, offer.id, expected_version=None)

    gate, barrier = threading.Event(), threading.Barrier(2)
    real = offers.source_of

    def gated(source_type, source_id, *, lock=False):
        if lock and gate.is_set():
            barrier.wait(timeout=10)
        return real(source_type, source_id, lock=lock)

    monkeypatch.setattr(offers, "source_of", gated)
    results: list = []
    crashes: list[str] = []
    guard = threading.Lock()

    def worker(buyer, offer):
        try:
            offers.submit(buyer, offer.id, expected_version=None)
            outcome = "ok"
        except DomainError as exc:
            outcome = (exc.code, _fields(exc), exc.message)
        except Exception as exc:  # noqa: BLE001 — любой другой исход — провал
            with guard:
                crashes.append(repr(exc))
            return
        finally:
            connection.close()
        with guard:
            results.append(outcome)

    gate.set()
    threads = [threading.Thread(target=worker, args=(b, o))
               for b, o in zip(buyers[2:], drafts[2:], strict=True)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert crashes == []
    assert results.count("ok") == 1
    (refusal,) = [row for row in results if row != "ok"]
    assert refusal[:2] == ("E-VAL-01", ["source_id"]) and "лимит" in refusal[2]
    assert AlternativeOffer.objects.filter(status=OfferStatus.SUBMITTED).count() == 3

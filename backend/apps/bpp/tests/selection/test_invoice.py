"""Выбор альтернативы по счёту без договора — ФД (B5.1; ТЗ §12.4 п.3–4,
AC-015, AC-016, BR-093, BR-094, BR-096; план B5.1, D-B51-1…7)."""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from apps.bpp.models import (
    Agreement,
    Invoice,
    InvoiceStatus,
    KpiRecord,
    KpiStatus,
    OfferStatus,
)
from apps.bpp.services.alternatives import offers
from apps.bpp.services.selection import invoice as selection
from apps.bpp.tests import stage2 as s
from apps.bpp.tests import test_invoices as invoice_flow
from apps.bpp.tests.alternatives import common
from apps.bpp.tests.test_files import memory_storage  # noqa: F401  (фикстура)
from apps.files import interface as files
from apps.signoff import interface as signoff
from htqweb.errors import DomainError
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db
COMMENT = "Дешевле при тех же сроках поставки"
BASE = "/api/bpp/v1"


def _fail(call) -> DomainError:
    with pytest.raises(DomainError) as exc:
        call()
    return exc.value


def _select(slug, inv, offer, *, comment=COMMENT, actor=None):
    return selection.select(actor or invoice_flow._fd(slug), inv.id, offer_id=offer.pk,
                            comment=comment, expected_version=None)


def test_ac015_fd_selects_and_a_draft_invoice_replaces_the_source(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1_400_000, 1_400_000)
    offer = common.filed(common.sn(slug, common.SN2), inv, common.cp(2), price=1_225_000)
    other = common.filed(common.sn(slug, common.SN3), inv, common.cp(3), price=1_300_000)

    done = _select(slug, inv, offer)

    inv.refresh_from_db(), offer.refresh_from_db(), other.refresh_from_db()
    assert inv.status == InvoiceStatus.REPLACED
    assert (offer.status, other.status) == (OfferStatus.SELECTED, OfferStatus.NOT_SELECTED)
    assert signoff.get_process_for(Invoice.SIGNOFF_SUBJECT_TYPE, str(inv.pk))["state"] \
        == "cancelled"
    new = done["result"]
    assert (done["result_type"], done["remainder"]) == ("invoice", None)
    # Автор — автор заявки (D-25), контрагент и цены — из АП.
    assert (new.status, new.basis, new.author_id, new.counterparty_id, new.amount) == (
        InvoiceStatus.DRAFT, "no_contract", s.SN, offer.counterparty_id, D("2450000.00"))
    assert sorted(line.amount for line in new.lines.all()) == [D("1225000.00")] * 2
    assert (offer.result_type, offer.result_id) == ("invoice", new.pk)
    assert [row["file_type"] for row in
            files.current_files(Invoice.SIGNOFF_SUBJECT_TYPE, new.pk, "alternative_offer")] \
        == ["alternative_offer"]                                   # КП переехало (D-B51-7)
    record = KpiRecord.objects.get(offer=offer)
    assert (record.status, record.result_id, record.saving_amount) == (
        KpiStatus.PRELIMINARY, new.pk, D("350000.00"))


def test_ac016_alternative_above_1000_mrp_becomes_a_draft_agreement(company_context):
    """BR-094: счёт 3 900 000, альтернатива 4 500 000 — новый документ — договор;
    разница 600 000 проверена по остатку статьи (BR-093)."""
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 3_900_000)
    offer = common.filed(common.sn(slug, common.SN2), inv, common.cp(2), price=4_500_000)

    done = _select(slug, inv, offer)

    agr = done["result"]
    assert done["result_type"] == "agreement" and isinstance(agr, Agreement)
    assert (agr.status, agr.amount, agr.counterparty_id, agr.author_id) == (
        "draft", D("4500000.00"), offer.counterparty_id, s.SN)
    assert [item.amount for item in agr.items.all()] == [D("4500000.00")]
    assert KpiRecord.objects.get(offer=offer).result_type == "agreement"


def test_br093_more_expensive_than_the_article_allows_is_refused(company_context):
    slug = company_context["slug"]
    _, _, inv = invoice_flow._submitted(slug, 1_000_000, limit=1_100_000)
    offer = common.filed(common.sn(slug, common.SN2), inv, common.cp(2), price=1_300_000)

    err = _fail(lambda: _select(slug, inv, offer))

    assert (err.code, err.status) == ("BR-093", 422)
    assert err.message == ("Альтернатива дороже исходного предложения на 300 000,00 KZT, "
                           "свободного остатка статьи 100 000,00 KZT недостаточно.")
    inv.refresh_from_db(), offer.refresh_from_db()
    assert (inv.status, offer.status) == (InvoiceStatus.UNDER_REVIEW, OfferStatus.SUBMITTED)


def test_partial_offer_gives_a_draft_by_the_alternative_and_one_by_the_rest(company_context):
    """D-25: АП на часть позиций — черновик по альтернативе и черновик по
    остатку с исходным контрагентом; KPI — только по альтернативе."""
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 500_000, 700_000)
    buyer = common.sn(slug, common.SN2)
    offer = common.fill(buyer, common.draft(buyer, inv), common.cp(2), price=450_000, keep=1)
    offer = offers.submit(buyer, offer.id, expected_version=None)

    done = _select(slug, inv, offer)

    new, rest = done["result"], done["remainder"]
    assert ([line.amount for line in new.lines.all()], new.counterparty_id) == (
        [D("450000.00")], offer.counterparty_id)
    assert ([line.amount for line in rest.lines.all()], rest.counterparty_id) == (
        [D("700000.00")], inv.counterparty_id)
    assert rest.status == InvoiceStatus.DRAFT and rest.author_id == s.SN
    assert KpiRecord.objects.get(offer=offer).result_id == new.pk


def test_only_the_fd_holding_the_decision_selects(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1_000_000)
    offer = common.filed(common.sn(slug, common.SN2), inv, common.cp(2), price=900_000)

    other_fd = s.actor(slug, 951, "bpp-fd")                      # роль есть, задачи нет
    assert _fail(lambda: _select(slug, inv, offer, actor=other_fd)).status == 403
    assert _fail(lambda: _select(slug, inv, offer, actor=common.sn(slug))).status == 403
    assert _fail(lambda: _select(slug, inv, offer, comment="коротко")).code == "BR-060"
    offer.refresh_from_db()
    assert offer.status == OfferStatus.SUBMITTED


def test_a_replaced_invoice_is_not_replaced_again(company_context):
    """BR-096: исходный документ заменяется альтернативой один раз."""
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1_000_000)
    first = common.filed(common.sn(slug, common.SN2), inv, common.cp(2), price=900_000)
    second = common.filed(common.sn(slug, common.SN3), inv, common.cp(3), price=950_000)
    _select(slug, inv, first)

    assert _fail(lambda: _select(slug, inv, second)).status in (409, 422)
    assert KpiRecord.objects.filter(source_id=inv.pk).count() == 1


def test_select_over_http_returns_the_source_card_and_the_new_document(company_context, client):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1_000_000)
    offer = common.filed(common.sn(slug, common.SN2), inv, common.cp(2), price=900_000)
    invoice_flow._fd(slug)

    response = client.post(
        f"{BASE}/invoices/{inv.pk}/select-alternative",
        data={"offer_id": str(offer.pk), "comment": COMMENT},
        **{**s.auth(slug, s.FD), "HTTP_IDEMPOTENCY_KEY": "select-1"})

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["invoice"]["status"] == "replaced"
    assert body["result"]["type"] == "invoice" and body["remainder"] is None
    with use_company(slug):           # клиент после ответа возвращает search_path на public
        assert Invoice.objects.get(pk=body["result"]["id"]).number == body["result"]["number"]


def test_new_invoice_beyond_5_percent_of_the_alternative_is_not_sent(company_context):
    """ТЗ §12.4 п.5 (B-3): сумма нового документа отличается от АП не больше
    чем на 5 % без повторного выбора."""
    from apps.bpp.services.invoices import invoices as invoice_service

    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1_000_000)
    offer = common.filed(common.sn(slug, common.SN2), inv, common.cp(2), price=900_000)
    new = _select(slug, inv, offer)["result"]
    author, line = common.sn(slug), new.lines.get()

    def priced(amount):
        draft, _ = invoice_service.update_draft(author, new.id, expected_version=None, data={
            "ext_number": "77", "amount": D(amount),
            "lines": [{"request_item_id": str(line.request_item_id), "qty": line.qty,
                       "amount": D(amount)}]})
        return draft

    common.with_file(priced("990000.00"), "invoice")                 # +10 %
    err = _fail(lambda: invoice_service.submit(author, new.id, expected_version=None))
    assert (err.code, err.fields[0]["field"]) == ("E-VAL-01", "amount")
    priced("936000.00")                                               # +4 %
    sent = invoice_service.submit(author, new.id, expected_version=None)
    assert sent.status == InvoiceStatus.UNDER_REVIEW


def test_cards_link_the_source_and_the_new_document(company_context):
    """Карточки: у исходного — чем заменён, у нового — «Основание: АП-…»;
    кнопка «Выбрать» — у ФД, пока счёт на его решении (D-B51-3)."""
    from apps.bpp.services.invoices import read

    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1_000_000)
    offer = common.filed(common.sn(slug, common.SN2), inv, common.cp(2), price=900_000)
    fd = invoice_flow._fd(slug)
    assert "select_alternative" in read.card(fd, inv)["allowed_actions"]
    assert "select_alternative" not in read.card(common.sn(slug), inv)["allowed_actions"]

    new = _select(slug, inv, offer)["result"]
    inv.refresh_from_db()

    source_card, new_card = read.card(fd, inv), read.card(fd, new)
    assert source_card["alternative"]["replaced_by"] == {
        "offer_id": str(offer.pk), "offer_number": offer.number, "result_type": "invoice",
        "result_id": str(new.pk), "result_number": new.number}
    assert new_card["alternative"] == {
        "basis": {"offer_id": str(offer.pk), "offer_number": offer.number},
        "replaced_by": None}
    assert "select_alternative" not in source_card["allowed_actions"]

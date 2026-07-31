"""Контрактные тесты ``/api/contracts/v1/invoices/*`` — счёт на оплату без
договора.

Счёт устроен параллельно договору, но с тремя отличиями, за которыми и следят
эти тесты: номера нет, валюта снимается со строки бюджета (а не приходит в
теле), и счёт бюджет НЕ занимает (в отличие от договора) — остаток по строке
от него не меняется.
"""

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.contracts.models import (
    BudgetStatus,
    CounterpartyStatus,
    Invoice,
    InvoiceStatus,
)

from .helpers import (
    BASE,
    admin_token,
    auth,
    make_agreement,
    make_counterparty,
    make_invoice,
    make_line,
    make_program,
    patch_json,
    post_json,
    token,
)


def _invoice_body(line, counterparty, **over) -> dict:
    body = {
        "name": "Канцелярские товары",
        "note": "Бумага, картриджи",
        "budget_line_id": line.pk,
        "counterparty_id": counterparty.pk,
        "amount": "400000.00",
    }
    body.update(over)
    return body


# ── Создание ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_create_invoice_expands_administrator_and_program():
    line = make_line(amount="5000000.00")
    counterparty = make_counterparty(country=line.budget.administrator.country)

    resp = post_json(Client(), f"{BASE}/invoices",
                     _invoice_body(line, counterparty), **auth(token()))
    assert resp.status_code == 201, resp.content
    created = resp.json()
    assert created["administrator_name"] == line.budget.administrator.display_name
    assert created["program_name"] == line.program.display_name
    assert created["expense_item"] == line.program.expense_item
    assert created["budget_id"] == line.budget_id
    assert created["status"] == InvoiceStatus.DRAFT.value
    assert created["created_by"] == 7


@pytest.mark.django_db
def test_currency_is_taken_from_the_budget_not_the_request():
    """Валюта не принимается извне: даже присланная в теле, она затирается
    валютой бюджета строки (см. докстринг модели Invoice)."""
    line = make_line(amount="5000000.00", currency="KZT")
    counterparty = make_counterparty(country=line.budget.administrator.country)

    resp = post_json(Client(), f"{BASE}/invoices",
                     _invoice_body(line, counterparty, currency="USD"),
                     **auth(token()))
    assert resp.status_code == 201, resp.content
    assert resp.json()["currency"] == "KZT"


@pytest.mark.django_db
def test_invoice_does_not_consume_the_budget():
    """Ключевое отличие от договора: счёт бюджет НЕ занимает. Договор на 4 млн
    уменьшил бы остаток, счёт той же суммы — нет."""
    line = make_line(amount="5000000.00")
    counterparty = make_counterparty(country=line.budget.administrator.country)

    resp = post_json(Client(), f"{BASE}/invoices",
                     _invoice_body(line, counterparty, amount="4000000.00"),
                     **auth(token()))
    assert resp.status_code == 201, resp.content

    budget = client_get_budget(line.budget_id)
    assert Decimal(budget["committed"]) == Decimal("0.00")
    assert Decimal(budget["remaining"]) == Decimal("5000000.00")


@pytest.mark.django_db
def test_invoice_over_budget_is_allowed():
    """Раз счёт не занимает бюджет — и проверять лимит не должен: счёт на
    сумму больше остатка проходит (в отличие от договора)."""
    line = make_line(amount="100000.00")
    counterparty = make_counterparty(country=line.budget.administrator.country)
    make_agreement(line=line, counterparty=counterparty, number="Д-001",
                   amount="100000.00", status="signed")  # остаток исчерпан договором

    resp = post_json(Client(), f"{BASE}/invoices",
                     _invoice_body(line, counterparty, amount="900000.00"),
                     **auth(token()))
    assert resp.status_code == 201, resp.content


def client_get_budget(budget_id: int) -> dict:
    resp = Client().get(f"{BASE}/budgets/{budget_id}", **auth(token()))
    assert resp.status_code == 200, resp.content
    return resp.json()


# ── Отказы контекста ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_closed_budget_rejects_new_invoices():
    line = make_line(amount="5000000.00")
    budget = line.budget
    budget.status = BudgetStatus.CLOSED
    budget.save(update_fields=["status"])
    counterparty = make_counterparty(country=budget.administrator.country)

    resp = post_json(Client(), f"{BASE}/invoices",
                     _invoice_body(line, counterparty), **auth(token()))
    assert resp.status_code == 409, resp.content


@pytest.mark.django_db
def test_blocked_counterparty_rejects_new_invoices():
    line = make_line(amount="5000000.00")
    counterparty = make_counterparty(country=line.budget.administrator.country,
                                     status=CounterpartyStatus.BLOCKED)

    resp = post_json(Client(), f"{BASE}/invoices",
                     _invoice_body(line, counterparty), **auth(token()))
    assert resp.status_code == 409, resp.content


# ── Смена статуса ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_status_transition_follows_the_allowed_table():
    line = make_line()
    invoice = make_invoice(line=line, amount="1000.00", status=InvoiceStatus.DRAFT)
    client = Client()

    ok = post_json(client, f"{BASE}/invoices/{invoice.pk}/status",
                   {"status": InvoiceStatus.ON_REVIEW.value}, **auth(admin_token()))
    assert ok.status_code == 200, ok.content
    assert ok.json()["status"] == InvoiceStatus.ON_REVIEW.value

    # draft → paid напрямую в таблице нет.
    bad = post_json(client, f"{BASE}/invoices/{invoice.pk}/status",
                    {"status": InvoiceStatus.PAID.value}, **auth(admin_token()))
    assert bad.status_code == 409, bad.content


@pytest.mark.django_db
def test_patch_cannot_smuggle_a_status_change():
    line = make_line()
    invoice = make_invoice(line=line, amount="1000.00", status=InvoiceStatus.DRAFT)

    resp = patch_json(Client(), f"{BASE}/invoices/{invoice.pk}",
                      {"status": InvoiceStatus.PAID.value, "name": "Новое имя"},
                      **auth(admin_token()))
    assert resp.status_code == 200, resp.content
    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.DRAFT
    assert invoice.name == "Новое имя"


# ── Редактирование и удаление ────────────────────────────────────────────

@pytest.mark.django_db
def test_moving_the_line_recomputes_the_currency():
    """Смена строки на строку бюджета в другой валюте переносит счёт в неё —
    валюта пересчитывается со строки, а не остаётся от прежнего бюджета."""
    kzt_line = make_line(amount="5000000.00", currency="KZT")
    invoice = make_invoice(line=kzt_line, amount="1000.00")
    # Другая программа — иначе два дефолтных make_program схлопнулись бы на
    # уникальном индексе «название + статья».
    usd_line = make_line(amount="5000000.00", currency="USD",
                         program=make_program(name="Связь", expense_item="Интернет"))

    resp = patch_json(Client(), f"{BASE}/invoices/{invoice.pk}",
                      {"budget_line_id": usd_line.pk}, **auth(admin_token()))
    assert resp.status_code == 200, resp.content
    assert resp.json()["currency"] == "USD"


@pytest.mark.django_db
def test_only_drafts_can_be_deleted():
    line = make_line()
    paid = make_invoice(line=line, amount="1000.00", status=InvoiceStatus.PAID)
    client = Client()

    assert client.delete(f"{BASE}/invoices/{paid.pk}",
                         **auth(admin_token())).status_code == 409

    draft = make_invoice(line=line, counterparty=paid.counterparty,
                         amount="1000.00", status=InvoiceStatus.DRAFT)
    assert client.delete(f"{BASE}/invoices/{draft.pk}",
                         **auth(admin_token())).status_code == 204


# ── Права ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_reading_needs_a_token_creating_does_not_need_an_admin():
    line = make_line()
    counterparty = make_counterparty(country=line.budget.administrator.country)
    client = Client()

    assert client.get(f"{BASE}/invoices").status_code == 401
    assert client.get(f"{BASE}/invoices", **auth(token())).status_code == 200

    resp = post_json(client, f"{BASE}/invoices",
                     _invoice_body(line, counterparty), **auth(token()))
    assert resp.status_code == 201, resp.content


@pytest.mark.django_db
def test_editing_and_deleting_still_need_an_admin():
    line = make_line()
    invoice = make_invoice(line=line, status=InvoiceStatus.DRAFT)
    client = Client()

    edited = patch_json(client, f"{BASE}/invoices/{invoice.pk}",
                        {"name": "Другое"}, **auth(token()))
    assert edited.status_code == 403
    assert client.delete(f"{BASE}/invoices/{invoice.pk}",
                         **auth(token())).status_code == 403


# ── Скан счёта ────────────────────────────────────────────────────────────

@pytest.fixture
def stub_storage(monkeypatch):
    monkeypatch.setattr(
        "apps.contracts.services.invoice_service.media.store_file",
        lambda **kw: {"id": "stored-inv-1"},
    )


def _upload(client, invoice_id: int, tok: str):
    return client.post(
        f"{BASE}/invoices/{invoice_id}/file",
        {"file": SimpleUploadedFile("schet.pdf", b"%PDF-1.4", "application/pdf")},
        **auth(tok),
    )


@pytest.mark.django_db
def test_the_author_attaches_a_scan_to_their_own_draft(stub_storage):
    line = make_line()
    invoice = make_invoice(line=line, status=InvoiceStatus.DRAFT, created_by=7)

    resp = _upload(Client(), invoice.pk, token())
    assert resp.status_code == 200, resp.content
    assert resp.json()["file_id"] == "stored-inv-1"


@pytest.mark.django_db
def test_a_stranger_cannot_attach_a_scan(stub_storage):
    line = make_line()
    invoice = make_invoice(line=line, status=InvoiceStatus.DRAFT, created_by=999)

    resp = _upload(Client(), invoice.pk, token())
    assert resp.status_code == 403
    assert "автор счёта или администратор" in resp.json()["detail"]


@pytest.mark.django_db
def test_an_admin_attaches_a_scan_to_anyones_invoice(stub_storage):
    line = make_line()
    invoice = make_invoice(line=line, status=InvoiceStatus.PAID, created_by=999)

    assert _upload(Client(), invoice.pk, admin_token()).status_code == 200


# ── Служебное ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_enums_expose_invoice_status_and_transitions():
    resp = Client().get(f"{BASE}/enums", **auth(token()))
    assert resp.status_code == 200
    body = resp.json()
    values = [row["value"] for row in body["invoice_status"]]
    assert values == [s.value for s in InvoiceStatus]
    # draft → on_review есть, draft → paid — нет.
    assert InvoiceStatus.ON_REVIEW.value in body["invoice_transitions"]["draft"]
    assert InvoiceStatus.PAID.value not in body["invoice_transitions"]["draft"]


@pytest.mark.django_db
def test_both_slash_spellings_resolve():
    client = Client()
    for path in (f"{BASE}/invoices", f"{BASE}/invoices/"):
        assert client.get(path, **auth(token())).status_code == 200, path

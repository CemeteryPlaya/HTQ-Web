"""Связь договора / счёта с заявкой конструктора «Запросы».

Правило одно и строгое (``services/request_link.py``): документ ПО заявке
заводится только по одобренной заявке и только на ту же строку бюджета,
под которую её одобрили. Всё остальное — 409 с текстом, который называет
заявку и причину.

Заявка собирается фабриками ``apps.approvals.tests.helpers`` (тесты из
проверки изоляции исключены): форма с виджетом ``budget_line_ref``, статус
проставляется напрямую — как заявка дошла до ``approved``, здесь не важно.
"""

import pytest
from django.core.cache import cache
from django.test import Client

from apps.approvals.models import RequestActivity, RequestStatus
from apps.approvals.tests.helpers import make_instance, make_template
from apps.contracts import interface
from apps.contracts.models import Agreement, Invoice
from apps.core.models import ServiceStatus

from .helpers import (
    BASE, admin_token, auth, make_counterparty, make_line, make_program, patch_json, post_json, token,
)

PURCHASE_SCHEMA = {"fields": [
    {"key": "budget", "type": "budget_line_ref", "label": "Бюджет", "required": True},
    {"key": "goal", "type": "text", "label": "Цель"},
]}


def make_request(line, *, status=RequestStatus.APPROVED, slug="zakup"):
    template = make_template(slug=slug, schema=PURCHASE_SCHEMA)
    return make_instance(template, status=status,
                         values={"budget": line.pk, "goal": "Ноутбуки"})


def agreement_body(line, counterparty, **over) -> dict:
    body = {
        "number": "Д-100", "name": "Поставка ноутбуков",
        "budget_line_id": line.pk, "counterparty_id": counterparty.pk,
        "amount": "400000.00", "payment_type": "postpayment",
        "currency": line.budget.currency,
    }
    body.update(over)
    return body


def invoice_body(line, counterparty, **over) -> dict:
    body = {"name": "Канцелярия", "budget_line_id": line.pk,
            "counterparty_id": counterparty.pk, "amount": "40000.00"}
    body.update(over)
    return body


# ── договор по заявке ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_agreement_by_approved_request_links_and_logs():
    line = make_line()
    counterparty = make_counterparty(country=line.budget.administrator.country)
    request = make_request(line)

    resp = post_json(Client(), f"{BASE}/agreements",
                     agreement_body(line, counterparty, request_id=request.pk),
                     **auth(token()))
    assert resp.status_code == 201, resp.content
    assert resp.json()["request_id"] == request.pk
    assert Agreement.objects.get(number="Д-100").request_id == request.pk

    # След в ленте заявки: кто, что и куда.
    event = RequestActivity.objects.get(request=request, event_type="document_linked")
    assert event.actor_id == 7
    assert event.payload["kind"] == "agreement"
    assert event.payload["url"] == f"/contracts/agreements/{resp.json()['id']}"
    assert "Д-100" in event.payload["title"]


@pytest.mark.django_db
def test_agreement_on_another_budget_line_is_409():
    line = make_line()
    other = make_line(budget=line.budget, program=make_program(name="Медицина"))
    counterparty = make_counterparty(country=line.budget.administrator.country)
    request = make_request(line)

    resp = post_json(Client(), f"{BASE}/agreements",
                     agreement_body(other, counterparty, request_id=request.pk),
                     **auth(token()))
    assert resp.status_code == 409, resp.content
    detail = resp.json()["detail"]
    assert request.code in detail and "другой строке бюджета" in detail
    assert not Agreement.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("status", [RequestStatus.PENDING, RequestStatus.DRAFT,
                                    RequestStatus.REJECTED])
def test_agreement_by_unapproved_request_is_409(status):
    line = make_line()
    counterparty = make_counterparty(country=line.budget.administrator.country)
    request = make_request(line, status=status)

    resp = post_json(Client(), f"{BASE}/agreements",
                     agreement_body(line, counterparty, request_id=request.pk),
                     **auth(token()))
    assert resp.status_code == 409
    assert "не одобрена" in resp.json()["detail"]


@pytest.mark.django_db
def test_agreement_by_unknown_request_is_409():
    line = make_line()
    counterparty = make_counterparty(country=line.budget.administrator.country)
    resp = post_json(Client(), f"{BASE}/agreements",
                     agreement_body(line, counterparty, request_id=9999),
                     **auth(token()))
    assert resp.status_code == 409
    assert "#9999" in resp.json()["detail"]


@pytest.mark.django_db
def test_request_without_budget_line_cannot_be_linked():
    line = make_line()
    counterparty = make_counterparty(country=line.budget.administrator.country)
    template = make_template(slug="otpusk-approved")  # simple_schema: без виджета
    request = make_instance(template, status=RequestStatus.APPROVED)

    resp = post_json(Client(), f"{BASE}/agreements",
                     agreement_body(line, counterparty, request_id=request.pk),
                     **auth(token()))
    assert resp.status_code == 409
    assert "не указана строка бюджета" in resp.json()["detail"]


@pytest.mark.django_db
def test_moving_a_linked_agreement_to_another_line_is_409():
    line = make_line()
    other = make_line(budget=line.budget, program=make_program(name="Медицина"))
    counterparty = make_counterparty(country=line.budget.administrator.country)
    request = make_request(line)
    created = post_json(Client(), f"{BASE}/agreements",
                        agreement_body(line, counterparty, request_id=request.pk),
                        **auth(token())).json()

    # PATCH договора — административная операция (API.md), связь при этом
    # перепроверяется так же строго.
    resp = patch_json(Client(), f"{BASE}/agreements/{created['id']}",
                      {"budget_line_id": other.pk}, **auth(admin_token()))
    assert resp.status_code == 409, resp.content
    assert "другой строке бюджета" in resp.json()["detail"]


@pytest.mark.django_db
def test_agreement_without_request_does_not_touch_approvals():
    line = make_line()
    counterparty = make_counterparty(country=line.budget.administrator.country)
    ServiceStatus.objects.update_or_create(app_label="approvals",
                                           defaults={"enabled": False})
    cache.clear()
    resp = post_json(Client(), f"{BASE}/agreements",
                     agreement_body(line, counterparty), **auth(token()))
    assert resp.status_code == 201, resp.content
    assert resp.json()["request_id"] is None


@pytest.mark.django_db
def test_agreement_by_request_is_503_when_approvals_is_off():
    line = make_line()
    counterparty = make_counterparty(country=line.budget.administrator.country)
    request = make_request(line)
    ServiceStatus.objects.update_or_create(app_label="approvals",
                                           defaults={"enabled": False})
    cache.clear()
    resp = post_json(Client(), f"{BASE}/agreements",
                     agreement_body(line, counterparty, request_id=request.pk),
                     **auth(token()))
    assert resp.status_code == 503
    assert resp.json()["service"] == "approvals"
    assert not Agreement.objects.exists()


# ── счёт по заявке ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_invoice_by_request_follows_the_same_rule():
    line = make_line()
    other = make_line(budget=line.budget, program=make_program(name="Медицина"))
    counterparty = make_counterparty(country=line.budget.administrator.country)
    request = make_request(line)

    bad = post_json(Client(), f"{BASE}/invoices",
                    invoice_body(other, counterparty, request_id=request.pk),
                    **auth(token()))
    assert bad.status_code == 409

    ok = post_json(Client(), f"{BASE}/invoices",
                   invoice_body(line, counterparty, request_id=request.pk),
                   **auth(token()))
    assert ok.status_code == 201, ok.content
    assert ok.json()["request_id"] == request.pk
    assert Invoice.objects.get(pk=ok.json()["id"]).request_id == request.pk
    event = RequestActivity.objects.get(request=request, event_type="document_linked")
    assert event.payload["kind"] == "invoice"


# ── чтение: заявки и документы по заявке ─────────────────────────────────

@pytest.mark.django_db
def test_linked_request_endpoints():
    line = make_line()
    counterparty = make_counterparty(country=line.budget.administrator.country)
    approved = make_request(line)
    make_request(line, status=RequestStatus.PENDING, slug="zakup-pending")
    client = Client()

    listed = client.get(f"{BASE}/requests", **auth(token()))
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [approved.pk]
    assert listed.json()[0]["budget_line_id"] == line.pk

    one = client.get(f"{BASE}/requests/{approved.pk}", **auth(token()))
    assert one.status_code == 200 and one.json()["code"] == approved.code
    assert client.get(f"{BASE}/requests/9999", **auth(token())).status_code == 404

    post_json(client, f"{BASE}/agreements",
              agreement_body(line, counterparty, request_id=approved.pk), **auth(token()))
    post_json(client, f"{BASE}/invoices",
              invoice_body(line, counterparty, request_id=approved.pk), **auth(token()))
    docs = client.get(f"{BASE}/requests/{approved.pk}/documents", **auth(token())).json()
    assert [row["number"] for row in docs["agreements"]] == ["Д-100"]
    assert [row["name"] for row in docs["invoices"]] == ["Канцелярия"]

    # Тот же набор — соседу через interface, одним плоским списком.
    flat = interface.list_documents_for_request(approved.pk)
    assert [(row["kind"], row["url"]) for row in flat] == [
        ("agreement", f"/contracts/agreements/{docs['agreements'][0]['id']}"),
        ("invoice", f"/contracts/invoices/{docs['invoices'][0]['id']}"),
    ]
    # Фильтр списков по заявке.
    assert len(client.get(f"{BASE}/agreements?request_id={approved.pk}",
                          **auth(token())).json()) == 1
    assert client.get(f"{BASE}/agreements?request_id=9999",
                      **auth(token())).json() == []

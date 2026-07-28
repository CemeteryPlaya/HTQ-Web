"""Контрактные тесты ``/api/contracts/v1/agreements/*`` и бюджетов.

Проверяют сквозной сценарий из спецификации: завели бюджет → зарегистрировали
договор → остаток бюджета уменьшился на сумму договора.
"""

from decimal import Decimal

import pytest
from django.test import Client

from apps.contracts.models import Agreement, AgreementStatus, BudgetStatus, CounterpartyStatus

from .helpers import (
    BASE,
    admin_token,
    auth,
    make_agreement,
    make_budget,
    make_counterparty,
    post_json,
    patch_json,
    token,
)


def _agreement_body(budget, counterparty, **over) -> dict:
    body = {
        "number": "Д-100",
        "name": "Поставка ноутбуков",
        "budget_id": budget.pk,
        "counterparty_id": counterparty.pk,
        "amount": "400000.00",
        "payment_type": "postpayment",
        "currency": budget.currency,
        "status": AgreementStatus.SIGNED.value,
    }
    body.update(over)
    return body


# ── Сквозной сценарий ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_agreement_reduces_budget_remaining_end_to_end():
    budget = make_budget(amount="5000000.00")
    counterparty = make_counterparty(country=budget.administrator.country)
    client = Client()

    resp = post_json(client, f"{BASE}/agreements",
                     _agreement_body(budget, counterparty),
                     **auth(admin_token()))
    assert resp.status_code == 201, resp.content
    created = resp.json()
    assert created["administrator_name"] == budget.administrator.full_name
    assert created["program_name"] == budget.program.name
    assert created["expense_item"] == budget.program.expense_item

    budget_resp = client.get(f"{BASE}/budgets/{budget.pk}", **auth(token()))
    assert budget_resp.status_code == 200
    body = budget_resp.json()
    assert Decimal(body["committed"]) == Decimal("400000.00")
    assert Decimal(body["remaining"]) == Decimal("4600000.00")


@pytest.mark.django_db
def test_created_agreement_records_the_author():
    budget = make_budget()
    counterparty = make_counterparty(country=budget.administrator.country)
    resp = post_json(Client(), f"{BASE}/agreements",
                     _agreement_body(budget, counterparty),
                     **auth(admin_token()))
    assert resp.json()["created_by"] == 9


# ── Отказы ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_agreement_over_budget_is_rejected_with_409():
    budget = make_budget(amount="1000000.00")
    counterparty = make_counterparty(country=budget.administrator.country)
    make_agreement(budget=budget, counterparty=counterparty, number="Д-001",
                   amount="800000.00", status=AgreementStatus.SIGNED)

    resp = post_json(Client(), f"{BASE}/agreements",
                     _agreement_body(budget, counterparty, number="Д-002",
                                     amount="300000.00"),
                     **auth(admin_token()))
    assert resp.status_code == 409, resp.content
    assert "остаток" in resp.json()["detail"].lower()
    assert Agreement.objects.filter(number="Д-002").count() == 0


@pytest.mark.django_db
def test_draft_over_budget_is_allowed():
    """Черновик лимит не занимает — значит и проверять его не должен."""
    budget = make_budget(amount="100000.00")
    counterparty = make_counterparty(country=budget.administrator.country)

    resp = post_json(Client(), f"{BASE}/agreements",
                     _agreement_body(budget, counterparty, amount="900000.00",
                                     status=AgreementStatus.DRAFT.value),
                     **auth(admin_token()))
    assert resp.status_code == 201, resp.content


@pytest.mark.django_db
def test_currency_mismatch_is_rejected():
    budget = make_budget(amount="5000000.00", currency="KZT")
    counterparty = make_counterparty(country=budget.administrator.country)

    resp = post_json(Client(), f"{BASE}/agreements",
                     _agreement_body(budget, counterparty, currency="USD"),
                     **auth(admin_token()))
    assert resp.status_code == 409
    assert "алют" in resp.json()["detail"]  # «валюта» / «Валюта»


@pytest.mark.django_db
def test_closed_budget_rejects_new_agreements():
    budget = make_budget(amount="5000000.00")
    budget.status = BudgetStatus.CLOSED
    budget.save(update_fields=["status"])
    counterparty = make_counterparty(country=budget.administrator.country)

    resp = post_json(Client(), f"{BASE}/agreements",
                     _agreement_body(budget, counterparty),
                     **auth(admin_token()))
    assert resp.status_code == 409


@pytest.mark.django_db
def test_blocked_counterparty_rejects_new_agreements():
    budget = make_budget(amount="5000000.00")
    counterparty = make_counterparty(country=budget.administrator.country,
                                     status=CounterpartyStatus.BLOCKED)

    resp = post_json(Client(), f"{BASE}/agreements",
                     _agreement_body(budget, counterparty),
                     **auth(admin_token()))
    assert resp.status_code == 409


@pytest.mark.django_db
def test_duplicate_number_is_409_not_500():
    budget = make_budget()
    counterparty = make_counterparty(country=budget.administrator.country)
    body = _agreement_body(budget, counterparty, amount="1000.00")
    client = Client()

    assert post_json(client, f"{BASE}/agreements", body, **auth(admin_token())).status_code == 201
    second = post_json(client, f"{BASE}/agreements", body, **auth(admin_token()))
    assert second.status_code == 409, second.content


# ── Смена статуса ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_status_transition_follows_the_allowed_table():
    budget = make_budget()
    agreement = make_agreement(budget=budget, amount="1000.00",
                               status=AgreementStatus.DRAFT)
    client = Client()

    ok = post_json(client, f"{BASE}/agreements/{agreement.pk}/status",
                   {"status": AgreementStatus.ON_REVIEW.value}, **auth(admin_token()))
    assert ok.status_code == 200
    assert ok.json()["status"] == AgreementStatus.ON_REVIEW.value

    # on_review → executed нет в таблице переходов.
    bad = post_json(client, f"{BASE}/agreements/{agreement.pk}/status",
                    {"status": AgreementStatus.EXECUTED.value}, **auth(admin_token()))
    assert bad.status_code == 409, bad.content
    agreement.refresh_from_db()
    assert agreement.status == AgreementStatus.ON_REVIEW


@pytest.mark.django_db
def test_moving_out_of_draft_checks_the_limit():
    """Черновик бюджет не занимал; переход в занимающий статус — занимает,
    и именно здесь проверяется лимит."""
    budget = make_budget(amount="500000.00")
    counterparty = make_counterparty(country=budget.administrator.country)
    make_agreement(budget=budget, counterparty=counterparty, number="Д-001",
                   amount="400000.00", status=AgreementStatus.SIGNED)
    draft = make_agreement(budget=budget, counterparty=counterparty, number="Д-002",
                           amount="300000.00", status=AgreementStatus.DRAFT)

    resp = post_json(Client(), f"{BASE}/agreements/{draft.pk}/status",
                     {"status": AgreementStatus.ON_REVIEW.value}, **auth(admin_token()))
    assert resp.status_code == 409, resp.content
    draft.refresh_from_db()
    assert draft.status == AgreementStatus.DRAFT


@pytest.mark.django_db
def test_patch_cannot_smuggle_a_status_change():
    """Статус меняется только через /status, где проверяется переход. PATCH
    его игнорирует — иначе таблица переходов обходилась бы одним полем."""
    budget = make_budget()
    agreement = make_agreement(budget=budget, amount="1000.00",
                               status=AgreementStatus.DRAFT)

    resp = patch_json(Client(), f"{BASE}/agreements/{agreement.pk}",
                      {"status": AgreementStatus.EXECUTED.value, "name": "Новое имя"},
                      **auth(admin_token()))
    assert resp.status_code == 200
    agreement.refresh_from_db()
    assert agreement.status == AgreementStatus.DRAFT
    assert agreement.name == "Новое имя"


# ── Редактирование и удаление ────────────────────────────────────────────

@pytest.mark.django_db
def test_agreement_can_grow_within_its_own_budget():
    budget = make_budget(amount="1000000.00")
    agreement = make_agreement(budget=budget, amount="900000.00",
                               status=AgreementStatus.SIGNED)

    resp = patch_json(Client(), f"{BASE}/agreements/{agreement.pk}",
                      {"amount": "950000.00"}, **auth(admin_token()))
    assert resp.status_code == 200, resp.content
    assert Decimal(resp.json()["amount"]) == Decimal("950000.00")


@pytest.mark.django_db
def test_editing_survives_a_counterparty_blocked_after_the_fact():
    """Контрагента заблокировали уже после подписания — договор всё равно
    должен оставаться редактируемым. Иначе опечатку в названии стало бы
    нечем исправить именно тогда, когда правки и нужны."""
    budget = make_budget()
    agreement = make_agreement(budget=budget, amount="1000.00",
                               status=AgreementStatus.SIGNED)
    counterparty = agreement.counterparty
    counterparty.status = CounterpartyStatus.BLOCKED
    counterparty.save(update_fields=["status"])

    resp = patch_json(Client(), f"{BASE}/agreements/{agreement.pk}",
                      {"name": "Исправленное название"}, **auth(admin_token()))
    assert resp.status_code == 200, resp.content

    # Но ПЕРЕВЕСТИ договор на заблокированного контрагента по-прежнему нельзя.
    other = make_counterparty(country=budget.administrator.country,
                              bin_iin="999999999999", name="ТОО «Бета»",
                              status=CounterpartyStatus.BLOCKED)
    moved = patch_json(Client(), f"{BASE}/agreements/{agreement.pk}",
                       {"counterparty_id": other.pk}, **auth(admin_token()))
    assert moved.status_code == 409, moved.content


@pytest.mark.django_db
def test_only_drafts_can_be_deleted():
    budget = make_budget()
    signed = make_agreement(budget=budget, number="Д-001", amount="1000.00",
                            status=AgreementStatus.SIGNED)
    client = Client()

    assert client.delete(f"{BASE}/agreements/{signed.pk}",
                         **auth(admin_token())).status_code == 409

    draft = make_agreement(budget=budget, counterparty=signed.counterparty,
                           number="Д-002", amount="1000.00",
                           status=AgreementStatus.DRAFT)
    assert client.delete(f"{BASE}/agreements/{draft.pk}",
                         **auth(admin_token())).status_code == 204


# ── Права ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_reading_needs_a_token_writing_needs_admin():
    budget = make_budget()
    counterparty = make_counterparty(country=budget.administrator.country)
    client = Client()

    assert client.get(f"{BASE}/agreements").status_code == 401
    assert client.get(f"{BASE}/agreements", **auth(token())).status_code == 200

    resp = post_json(client, f"{BASE}/agreements",
                     _agreement_body(budget, counterparty), **auth(token()))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_unsupported_method_returns_the_json_405_envelope():
    """У CBV 405 отдаёт ``View.dispatch`` → ``ApiView.http_method_not_allowed``,
    а не рукописный диспетчер, как в функциональных аппках. Дефолт Django
    здесь — HTML-тело, поэтому переопределение проверяется явно."""
    budget = make_budget()
    agreement = make_agreement(budget=budget, amount="1000.00",
                               status=AgreementStatus.DRAFT)
    client = Client()

    resp = client.put(f"{BASE}/agreements/{agreement.pk}", **auth(admin_token()))
    assert resp.status_code == 405
    assert resp.json() == {"detail": "Method Not Allowed"}

    # OPTIONS убран из http_method_names: иначе Django ответил бы на него
    # сам, в обход авторизации.
    assert client.options(f"{BASE}/agreements").status_code == 405


@pytest.mark.django_db
def test_both_slash_spellings_resolve():
    """APPEND_SLASH=False — Django сам не редиректит, оба написания
    зарегистрированы явно (правило №4)."""
    client = Client()
    for path in (f"{BASE}/agreements", f"{BASE}/agreements/",
                 f"{BASE}/budgets", f"{BASE}/budgets/",
                 f"{BASE}/counterparties", f"{BASE}/counterparties/"):
        assert client.get(path, **auth(token())).status_code == 200, path

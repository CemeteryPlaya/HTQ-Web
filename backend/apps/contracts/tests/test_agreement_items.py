"""Поля договора из ТЗ 9.2: позиции, дата договора, уникальность, срок действия.

* **Позиции** — из заявки на закуп (строки её повторяемой группы) или
  вписанные руками. Из заявки нельзя взять больше, чем осталось после
  других договоров; у стандартного договора сумма позиций = сумма договора
  (BR-033); без позиций договор на согласование не уходит.
* **Дата договора** — обязательна (по умолчанию сегодня), не раньше
  01.01.2020 и не позже сегодня + 30 дней.
* **Уникальность** — «контрагент + номер + дата» (BR-032), а не голый номер:
  у двух поставщиков свой «Договор № 1» — норма.
* **Срок действия по** — не раньше даты договора; после него новые оплаты
  по договору не заводятся (BR-036).
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from apps.approvals.models import RequestStatus
from apps.approvals.tests.helpers import make_instance, make_template
from apps.contracts.models import Agreement, AgreementItem, AgreementType
from apps.contracts.services import agreement_service
from apps.contracts.services.agreement_service import AgreementRuleViolation
from apps.signoff.models import ApprovalState

from .helpers import (
    BASE, admin_token, auth, make_agreement, make_counterparty, make_line,
    patch_json, post_json, token,
)

pytestmark = pytest.mark.django_db

PURCHASE_SCHEMA = {"fields": [
    {"key": "budget", "type": "budget_line_ref", "label": "Бюджет", "required": True},
    {"key": "items", "type": "group", "label": "Позиции", "repeatable": True,
     "summarize_keys": ["quantity"],
     "fields": [
         {"key": "name", "type": "text", "label": "ТРУ"},
         {"key": "quantity", "type": "number", "label": "Кол-во"},
         {"key": "unit", "type": "dropdown", "label": "Ед.", "options": ["шт", "кг"]},
     ]},
]}


def _request(line, rows=None):
    template = make_template(slug="zakup-items", schema=PURCHASE_SCHEMA)
    rows = rows if rows is not None else [
        {"name": "Ноутбук", "quantity": 10, "unit": "шт"},
        {"name": "Мышь", "quantity": 5, "unit": "шт"},
    ]
    return make_instance(template, status=RequestStatus.APPROVED,
                         values={"budget": line.pk, "items": rows})


def _body(line, counterparty, **over) -> dict:
    body = {
        "number": "Д-100", "name": "Поставка ноутбуков",
        "budget_line_id": line.pk, "counterparty_id": counterparty.pk,
        "amount": "400000.00", "currency": line.budget.currency,
        "items": [{"name": "Ноутбук", "unit": "шт", "quantity": "2",
                   "amount": "400000.00"}],
    }
    body.update(over)
    return body


def _setup():
    line = make_line()
    counterparty = make_counterparty(country=line.budget.administrator.country)
    return line, counterparty


# ── позиции ──────────────────────────────────────────────────────────────

def test_manual_items_are_saved_in_order():
    line, counterparty = _setup()
    resp = post_json(Client(), f"{BASE}/agreements", _body(line, counterparty, items=[
        {"name": "Ноутбук", "unit": "шт", "quantity": "2", "amount": "300000.00"},
        {"name": "Сумка", "unit": "шт", "quantity": "2", "amount": "100000.00"},
    ]), **auth(token()))
    assert resp.status_code == 201, resp.content
    items = resp.json()["items"]
    assert [(i["line_no"], i["name"]) for i in items] == [(1, "Ноутбук"), (2, "Сумка")]


def test_items_sum_must_equal_contract_amount():
    line, counterparty = _setup()
    resp = post_json(Client(), f"{BASE}/agreements", _body(line, counterparty, items=[
        {"name": "Ноутбук", "quantity": "2", "amount": "350000.00"},
    ]), **auth(token()))
    assert resp.status_code == 409
    assert "не равна сумме договора" in resp.json()["detail"]
    # Нарушение в позициях откатывает и сам договор — транзакция одна.
    assert not Agreement.objects.exists()


def test_open_contract_items_need_no_amount():
    line, counterparty = _setup()
    resp = post_json(Client(), f"{BASE}/agreements", _body(
        line, counterparty, contract_type=AgreementType.FRAMEWORK,
        items=[{"name": "Бетон М300", "unit": "м³", "quantity": "120"}],
    ), **auth(token()))
    assert resp.status_code == 201, resp.content
    assert resp.json()["items"][0]["amount"] is None


def test_request_items_list_shows_the_remaining_quantity():
    line, counterparty = _setup()
    request = _request(line)
    post_json(Client(), f"{BASE}/agreements", _body(
        line, counterparty, request_id=request.pk,
        items=[{"request_item_key": "items:1", "quantity": "4", "amount": "400000.00"}],
    ), **auth(token()))

    resp = Client().get(f"{BASE}/requests/{request.pk}/items", **auth(token()))
    assert resp.status_code == 200
    by_key = {row["key"]: row for row in resp.json()}
    assert by_key["items:1"]["name"] == "Ноутбук"
    assert Decimal(by_key["items:1"]["remaining"]) == Decimal("6")
    assert Decimal(by_key["items:2"]["remaining"]) == Decimal("5")


def test_item_from_request_takes_name_and_unit_from_the_request():
    line, counterparty = _setup()
    request = _request(line)
    resp = post_json(Client(), f"{BASE}/agreements", _body(
        line, counterparty, request_id=request.pk,
        items=[{"request_item_key": "items:1", "name": "что-то другое",
                "quantity": "3", "amount": "400000.00"}],
    ), **auth(token()))
    assert resp.status_code == 201, resp.content
    item = resp.json()["items"][0]
    assert (item["name"], item["unit"], item["request_item_key"]) == ("Ноутбук", "шт", "items:1")


def test_quantity_over_the_remaining_is_rejected():
    line, counterparty = _setup()
    request = _request(line)
    first = post_json(Client(), f"{BASE}/agreements", _body(
        line, counterparty, request_id=request.pk,
        items=[{"request_item_key": "items:1", "quantity": "8", "amount": "400000.00"}],
    ), **auth(token()))
    assert first.status_code == 201, first.content

    second = post_json(Client(), f"{BASE}/agreements", _body(
        line, counterparty, number="Д-101", request_id=request.pk,
        items=[{"request_item_key": "items:1", "quantity": "3", "amount": "400000.00"}],
    ), **auth(token()))
    assert second.status_code == 409
    assert "доступно 2" in second.json()["detail"]


def test_terminated_agreement_releases_its_quantity():
    line, counterparty = _setup()
    request = _request(line)
    made = post_json(Client(), f"{BASE}/agreements", _body(
        line, counterparty, request_id=request.pk,
        items=[{"request_item_key": "items:1", "quantity": "10", "amount": "400000.00"}],
    ), **auth(token()))
    Agreement.objects.filter(pk=made.json()["id"]).update(status="terminated")

    resp = Client().get(f"{BASE}/requests/{request.pk}/items", **auth(token()))
    assert Decimal(resp.json()[0]["remaining"]) == Decimal("10")


def test_editing_an_agreement_does_not_count_its_own_items_against_it():
    line, counterparty = _setup()
    request = _request(line)
    made = post_json(Client(), f"{BASE}/agreements", _body(
        line, counterparty, request_id=request.pk, status="draft",
        items=[{"request_item_key": "items:1", "quantity": "10", "amount": "400000.00"}],
    ), **auth(token()))
    resp = patch_json(Client(), f"{BASE}/agreements/{made.json()['id']}", {
        "items": [{"request_item_key": "items:1", "quantity": "10",
                   "amount": "400000.00"}],
    }, **auth(admin_token()))
    assert resp.status_code == 200, resp.content


def test_request_items_need_a_linked_request():
    line, counterparty = _setup()
    resp = post_json(Client(), f"{BASE}/agreements", _body(
        line, counterparty,
        items=[{"request_item_key": "items:1", "quantity": "1", "amount": "400000.00"}],
    ), **auth(token()))
    assert resp.status_code == 409
    assert "не привязан" in resp.json()["detail"]


def test_submit_without_items_is_allowed_while_the_form_has_no_items(monkeypatch):
    """Позиции при отправке пока необязательны: в форме договора нет их
    таблицы (``ITEMS_REQUIRED_FOR_APPROVAL``). Включённый флаг — отказ."""
    from apps.contracts.services import agreement_items

    line, counterparty = _setup()
    agreement = make_agreement(line=line, counterparty=counterparty, status="draft",
                               with_item=False)
    agreement_items.assert_ready_for_approval(agreement)

    monkeypatch.setattr(agreement_items, "ITEMS_REQUIRED_FOR_APPROVAL", True)
    with pytest.raises(agreement_items.AgreementItemsViolation,
                       match="нет ни одной позиции"):
        agreement_items.assert_ready_for_approval(agreement)


def test_submit_rechecks_the_sum_changed_after_items():
    line, counterparty = _setup()
    agreement = make_agreement(line=line, counterparty=counterparty, status="draft")
    # Черновик сохраняется «по формату»: одна сумма без позиций — можно…
    resp = patch_json(Client(), f"{BASE}/agreements/{agreement.pk}",
                      {"amount": "500000.00"}, **auth(admin_token()))
    assert resp.status_code == 200, resp.content
    # …а согласовывать расхождение — нет.
    with pytest.raises(AgreementRuleViolation, match="не равна сумме договора"):
        agreement_service.submit_for_approval(agreement.pk)


# ── дата договора ────────────────────────────────────────────────────────

def test_contract_date_defaults_to_today():
    line, counterparty = _setup()
    resp = post_json(Client(), f"{BASE}/agreements", _body(line, counterparty),
                     **auth(token()))
    assert resp.status_code == 201, resp.content
    assert resp.json()["signed_date"] == timezone.localdate().isoformat()


@pytest.mark.parametrize("signed", ["2019-12-31",
                                    (date.today() + timedelta(days=45)).isoformat()])
def test_contract_date_out_of_bounds_is_422(signed):
    line, counterparty = _setup()
    resp = post_json(Client(), f"{BASE}/agreements",
                     _body(line, counterparty, signed_date=signed), **auth(token()))
    assert resp.status_code == 422
    assert not Agreement.objects.exists()


def test_valid_until_before_contract_date_is_422():
    line, counterparty = _setup()
    resp = post_json(Client(), f"{BASE}/agreements", _body(
        line, counterparty, signed_date="2026-05-01", end_date="2026-04-30",
    ), **auth(token()))
    assert resp.status_code == 422
    assert "раньше даты договора" in str(resp.json()["detail"])


# ── уникальность «контрагент + номер + дата» ─────────────────────────────

def test_same_number_and_date_for_the_same_counterparty_is_refused():
    line, counterparty = _setup()
    first = post_json(Client(), f"{BASE}/agreements",
                      _body(line, counterparty, signed_date="2026-05-01"), **auth(token()))
    assert first.status_code == 201, first.content
    second = post_json(Client(), f"{BASE}/agreements",
                       _body(line, counterparty, signed_date="2026-05-01"), **auth(token()))
    assert second.status_code == 409
    assert "уже существует" in second.json()["detail"]


def test_same_number_is_fine_for_another_counterparty_or_date():
    line, counterparty = _setup()
    other = make_counterparty(country=line.budget.administrator.country,
                              bin_iin="210987654321", name="ТОО «Бета»")
    client = Client()
    assert post_json(client, f"{BASE}/agreements", _body(
        line, counterparty, signed_date="2026-05-01"), **auth(token())).status_code == 201
    assert post_json(client, f"{BASE}/agreements", _body(
        line, other, signed_date="2026-05-01"), **auth(token())).status_code == 201
    assert post_json(client, f"{BASE}/agreements", _body(
        line, counterparty, signed_date="2026-05-02"), **auth(token())).status_code == 201


def test_editing_into_a_duplicate_is_refused():
    line, counterparty = _setup()
    make_agreement(line=line, counterparty=counterparty, number="Д-1",
                   signed_date=date(2026, 5, 1))
    target = make_agreement(line=line, counterparty=counterparty, number="Д-2",
                            signed_date=date(2026, 5, 1), status="draft")
    resp = patch_json(Client(), f"{BASE}/agreements/{target.pk}", {"number": "Д-1"},
                      **auth(admin_token()))
    assert resp.status_code == 409


# ── срок действия ────────────────────────────────────────────────────────

def test_no_new_payments_after_the_term():
    from apps.contracts.services import advance_payment_service
    from apps.contracts.services.advance_payment_service import AdvancePaymentRuleViolation

    line, counterparty = _setup()
    agreement = make_agreement(line=line, counterparty=counterparty,
                               signed_date=date(2026, 1, 10), end_date=date(2026, 1, 31))
    Agreement.objects.filter(pk=agreement.pk).update(
        approval_state=ApprovalState.APPROVED)

    with pytest.raises(AdvancePaymentRuleViolation, match="истёк"):
        advance_payment_service.create_advance_payment(
            agreement_id=agreement.pk, amount=Decimal("100000.00"))


def test_item_quantity_must_be_positive():
    line, counterparty = _setup()
    resp = post_json(Client(), f"{BASE}/agreements", _body(line, counterparty, items=[
        {"name": "Ноутбук", "quantity": "0", "amount": "400000.00"},
    ]), **auth(token()))
    assert resp.status_code == 422
    assert not AgreementItem.objects.exists()

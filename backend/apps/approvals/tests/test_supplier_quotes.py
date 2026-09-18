"""Сравнительная таблица поставщиков: итог считает сервер, шаг знает, чего ждёт.

Виджет заводился ради двух вещей, и обе проверяются здесь:

* итог выбранного предложения (``total``) ВЫВОДИТСЯ при сохранении, а не
  присылается клиентом — по этому числу дальше утверждают деньги, сверяют
  счёт (``must_equal``) и считают ``total_amount``;
* этап, который требует таблицу, не закрывается, пока в ней нет цен и
  отметки выбранного, и объясняет это словами закупщика, а не «заполните
  поле».
"""

import json

import pytest
from django.test import Client

from apps.approvals.models import RequestInstance, RequestStatus
from apps.approvals.services import quotes
from apps.approvals.services.form_schema import validate_form_schema
from apps.approvals.services.value_validation import compute_total

from .helpers import BASE, auth, make_instance, make_template, token

pytestmark = pytest.mark.django_db

SCHEMA = {"fields": [
    {"key": "items", "type": "group", "label": "Позиции закупа",
     "repeatable": True, "summarize_keys": ["quantity"], "fields": [
         {"key": "name", "type": "text", "label": "ТРУ"},
         {"key": "quantity", "type": "number", "label": "Кол-во"},
     ]},
    {"key": "quotes", "type": "supplier_quotes", "label": "Сравнение поставщиков",
     "items_field": "items", "quantity_key": "quantity",
     "filled_by": "approver", "contributes_to_total": True},
    {"key": "invoice", "type": "money", "label": "Сумма счёта",
     "filled_by": "approver", "must_equal": "quotes.total"},
]}

ITEMS = [{"name": "Ноутбук", "quantity": 2}, {"name": "Док-станция", "quantity": 3}]


def values(prices_a=("100", "50"), prices_b=("90", "70"), chosen=0, **over):
    table = {
        "suppliers": [
            {"name": "ТОО «А»", "prices": list(prices_a)},
            {"name": "ТОО «Б»", "prices": list(prices_b)},
        ],
        "chosen": chosen,
    }
    table.update(over)
    return {"items": ITEMS, "quotes": table}


# ── расчёт ────────────────────────────────────────────────────────────

def test_the_total_is_the_chosen_supplier_priced_by_quantity():
    """Цена в клетке — за единицу: 100×2 + 50×3 = 350, а не 150."""
    schema = validate_form_schema(SCHEMA)
    out = quotes.derive(schema, values())
    assert out["quotes"]["total"] == "350"
    assert out["quotes"]["supplier_name"] == "ТОО «А»"
    # Итоги по всем предложениям — чтобы карточка не считала их заново.
    assert out["quotes"]["totals"] == ["350", "390"]


def test_choosing_the_other_supplier_changes_the_total():
    schema = validate_form_schema(SCHEMA)
    out = quotes.derive(schema, values(chosen=1))
    assert (out["quotes"]["total"], out["quotes"]["supplier_name"]) == ("390", "ТОО «Б»")


def test_a_client_sent_total_is_overwritten_not_trusted():
    """Итог присылать не нужно, а присланный — не в счёт: по нему
    утверждают деньги, и считать его вправе только сервер."""
    schema = validate_form_schema(SCHEMA)
    out = quotes.derive(schema, values(total="1", supplier_name="кто-то"))
    assert (out["quotes"]["total"], out["quotes"]["supplier_name"]) == ("350", "ТОО «А»")


def test_the_derived_total_feeds_the_request_total():
    """``<ключ>.total`` — обычное денежное поле для остальных механизмов."""
    schema = validate_form_schema(SCHEMA)
    assert compute_total(SCHEMA, quotes.derive(schema, values())) == 350


# ── чего не хватает шагу ──────────────────────────────────────────────

@pytest.mark.parametrize("table, expected", [
    ({}, "хотя бы одно предложение"),
    ({"suppliers": [{"name": "  "}]}, "хотя бы одно предложение"),
    ({"suppliers": [{"name": "ТОО «А»", "prices": ["100"]}], "chosen": 0},
     "заполнить цены"),
    ({"suppliers": [{"name": "ТОО «А»", "prices": ["100", "50"]}]},
     "отметить выбранного"),
])
def test_the_table_says_what_is_missing(table, expected):
    schema = validate_form_schema(SCHEMA)
    problem = quotes.problem(schema, {"items": ITEMS, "quotes": table}, "quotes")
    assert problem and expected in problem


def test_a_complete_table_has_no_problem():
    schema = validate_form_schema(SCHEMA)
    assert quotes.problem(schema, values(), "quotes") is None


def test_one_supplier_is_enough():
    """Сколько собирать предложений — решает закупщик: на товар, который
    возят двое, третьего не выдумать."""
    schema = validate_form_schema(SCHEMA)
    single = {"suppliers": [{"name": "ТОО «А»", "prices": ["100", "50"]}], "chosen": 0}
    assert quotes.problem(schema, {"items": ITEMS, "quotes": single}, "quotes") is None


def test_too_many_suppliers_are_refused():
    schema = validate_form_schema(SCHEMA)
    many = {"suppliers": [{"name": f"№{i}", "prices": ["1", "1"]}
                          for i in range(quotes.MAX_SUPPLIERS + 1)], "chosen": 0}
    problem = quotes.problem(schema, {"items": ITEMS, "quotes": many}, "quotes")
    assert problem and "слишком много" in problem


# ── связка: сохранение через API выводит итог ─────────────────────────

def test_saving_a_draft_derives_the_total_through_the_api():
    """Итог появляется на любом сохранении, а не только при отправке:
    иначе черновик и отправленная заявка расходились бы в сумме."""
    template = make_template(schema=SCHEMA)
    instance = make_instance(template, initiator_id=7, values={})
    client = Client()
    resp = client.patch(
        f"{BASE}/instances/{instance.pk}/",
        data=json.dumps({"form_values": values()}),
        content_type="application/json", **auth(token()))
    assert resp.status_code == 200, resp.content

    instance.refresh_from_db()
    assert instance.form_values_json["quotes"]["total"] == "350"
    assert instance.form_values_json["quotes"]["supplier_name"] == "ТОО «А»"


def test_a_broken_schema_does_not_block_saving_a_draft():
    """Сохранить черновик можно и при сломанной схеме — на неё пожалуются
    публикация и отправка, а не кнопка «сохранить»."""
    template = make_template(schema=SCHEMA)
    instance = make_instance(template, initiator_id=7, values={})
    RequestInstance.objects.filter(pk=instance.pk).update(status=RequestStatus.DRAFT)
    from apps.approvals.services.instance_service import _derived
    assert _derived({"fields": "не схема"}, {"a": 1}) == {"a": 1}

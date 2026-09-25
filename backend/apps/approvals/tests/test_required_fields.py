"""Незаполненное обязательное поле объясняется человеку, а не разработчику.

Текст 422 доходит до того, кто нажал «Отправить», поэтому он по-русски и
называет ПОДПИСЬ поля: ключ (``budget_line``) человеку ничего не говорит.
Проверяется и то, что пустым считается: `null`, пустая строка и пустой
список (у повторяемой группы это «ни одной строки»).
"""

import pytest
from django.test import Client

from apps.approvals.services.value_validation import validate_values

from .helpers import BASE, auth, make_instance, make_template

pytestmark = pytest.mark.django_db

SCHEMA = {"fields": [
    {"key": "budget_line", "type": "budget_line_ref",
     "label": "Бюджет (администратор → программа)", "required": True},
    {"key": "items", "type": "group", "label": "Позиции закупа", "required": True,
     "repeatable": True,
     "fields": [{"key": "name", "type": "text", "label": "ТРУ"}]},
    {"key": "note", "type": "text", "label": "Комментарий"},
]}


def test_the_message_names_the_label_in_russian():
    with pytest.raises(ValueError, match="Заполните обязательное поле «Бюджет"):
        validate_values(SCHEMA, {"budget_line": None, "items": [{"name": "x"}]})


@pytest.mark.parametrize("value", [None, "", [], {}])
def test_blank_shapes_all_count_as_missing(value):
    with pytest.raises(ValueError, match="Заполните обязательное поле"):
        validate_values(SCHEMA, {"budget_line": value, "items": [{"name": "x"}]})


def test_an_empty_repeatable_group_is_missing_too():
    """Ни одной строки в «Позициях» — то же самое, что пустое поле."""
    with pytest.raises(ValueError, match="«Позиции закупа»"):
        validate_values(SCHEMA, {"budget_line": 5, "items": []})


def test_a_filled_form_passes_and_optional_fields_may_be_empty():
    validate_values(SCHEMA, {"budget_line": 5, "items": [{"name": "Ноутбук"}]})
    validate_values(SCHEMA, {"budget_line": 5, "items": [{"name": "x"}], "note": ""})


def test_zero_and_false_are_not_blank():
    """0 и False — значения, а не пустота: количество «0» может быть
    осмысленным, а галочка «нет» — ответом."""
    schema = {"fields": [
        {"key": "qty", "type": "number", "label": "Кол-во", "required": True},
        {"key": "urgent", "type": "checkbox", "label": "Срочно", "required": True},
    ]}
    validate_values(schema, {"qty": 0, "urgent": False})


def test_submit_returns_the_human_message_as_422():
    template = make_template(schema=SCHEMA)
    instance = make_instance(template, values={"budget_line": None, "items": []})
    resp = Client().post(f"{BASE}/instances/{instance.id}/submit/", **auth())
    assert resp.status_code == 422
    assert "Заполните обязательное поле «Бюджет" in resp.json()["detail"]

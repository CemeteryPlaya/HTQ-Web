"""Поле обязано совпадать с другим полем — правило ``must_equal``.

Завелось ради главной проверки закупа: счёт выставляют ровно на ту сумму,
которую согласовали. Разойдутся — CFO утвердит одно, а заплатят другое, и
узнают об этом уже после оплаты. Поэтому расхождение не пропускает ни
отправку заявки, ни закрытие шага согласующего.

Само правило предметной области не знает: сравнивает любые два числовых
поля формы, в том числе внутри блоков (``группа.поле``).
"""

import pytest

from apps.approvals.services.form_schema import validate_form_schema
from apps.approvals.services.value_validation import (
    mismatch_in, validate_values,
)

pytestmark = pytest.mark.django_db

# Инициатор называет лимит, согласующий вписывает факт — и тот обязан
# совпасть. Форма нарочно не про закуп: правило общее.
SCHEMA = {"fields": [
    {"key": "limit", "type": "money", "label": "Лимит", "required": True},
    {"key": "fact", "type": "group", "label": "Факт", "repeatable": False,
     "filled_by": "approver", "fields": [
         {"key": "amount", "type": "money", "label": "Сумма",
          "required": True, "must_equal": "limit"},
     ]},
]}


def mismatch(values, field_key="fact"):
    return mismatch_in(validate_form_schema(SCHEMA), field_key, values)


# ── сравнение ─────────────────────────────────────────────────────────

def test_equal_values_pass_even_in_different_json_shapes():
    """Суммы приходят из JSON то числом, то строкой: ``1000 == "1000.00"``
    в Python ложно, поэтому сравнение идёт через Decimal."""
    assert mismatch({"limit": 1000, "fact": {"amount": 1000}}) is None
    assert mismatch({"limit": 1000, "fact": {"amount": "1000.00"}}) is None
    assert mismatch({"limit": "1000", "fact": {"amount": 1000.0}}) is None


def test_a_mismatch_names_both_fields_and_both_numbers():
    problem = mismatch({"limit": 1250000, "fact": {"amount": 1300000}})
    assert "«Факт → Сумма»" in problem
    assert "«Лимит»" in problem
    # Числа в тексте — чтобы человек увидел расхождение, а не шёл сверять.
    assert "1 300 000" in problem and "1 250 000" in problem


def test_an_empty_value_is_not_a_mismatch():
    """Пусто — забота обязательности, а не совпадения: иначе человек, ещё
    не начавший заполнять, получал бы «не совпадает»."""
    assert mismatch({"limit": 1000, "fact": {}}) is None
    assert mismatch({"limit": 1000, "fact": {"amount": None}}) is None
    assert mismatch({"fact": {"amount": 1000}}) is None


def test_only_the_asked_field_is_checked():
    """``mismatch_in`` смотрит одно поле верхнего уровня — на шаге проверяют
    блок этого шага, а не всю форму."""
    values = {"limit": 1000, "fact": {"amount": 999}}
    assert mismatch(values, "fact") is not None
    assert mismatch(values, "limit") is None


# ── настройка формы ───────────────────────────────────────────────────

@pytest.mark.parametrize("fields, why", [
    ([{"key": "a", "type": "text", "label": "A", "must_equal": "b"},
      {"key": "b", "type": "money", "label": "B"}], "сравнивать можно только"),
    ([{"key": "a", "type": "money", "label": "A", "must_equal": "nope"}], "нет или"),
    ([{"key": "a", "type": "money", "label": "A", "must_equal": "a"}], "само с собой"),
    ([{"key": "a", "type": "money", "label": "A", "must_equal": "b"},
      {"key": "b", "type": "text", "label": "B"}], "нет или"),
])
def test_a_broken_rule_is_refused_when_the_form_is_published(fields, why):
    """Правило, которое не сработает, ловится при публикации формы, а не в
    момент, когда согласующий упрётся в счёт."""
    with pytest.raises(ValueError, match=why):
        validate_form_schema({"fields": fields})


def test_a_repeatable_group_is_not_a_target():
    """У строк повторяемой группы нет ОДНОГО значения — путь туда ничего не
    обозначает, и цель в ней не находится."""
    with pytest.raises(ValueError, match="нет или"):
        validate_form_schema({"fields": [
            {"key": "rows", "type": "group", "label": "Строки", "repeatable": True,
             "fields": [{"key": "amount", "type": "money", "label": "Сумма"}]},
            {"key": "total", "type": "money", "label": "Итого",
             "must_equal": "rows.amount"},
        ]})


# ── подача заявки ─────────────────────────────────────────────────────

def test_submit_is_blocked_by_a_mismatch_between_initiator_fields():
    schema = {"fields": [
        {"key": "plan", "type": "money", "label": "План", "required": True},
        {"key": "copy", "type": "money", "label": "Дубль", "must_equal": "plan"},
    ]}
    validate_values(schema, {"plan": 500, "copy": 500})
    with pytest.raises(ValueError, match="не совпадает"):
        validate_values(schema, {"plan": 500, "copy": 700})


def test_submit_ignores_approver_fields_as_before():
    """Поля согласующего с инициатора не спрашиваются — ни на
    обязательность, ни на совпадение: он их и заполнить не может."""
    validate_values(SCHEMA, {"limit": 1000})
    validate_values(SCHEMA, {"limit": 1000, "fact": {"amount": 999}})

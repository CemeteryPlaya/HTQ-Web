import pytest

from app.services.value_validation import validate_values, compute_total

_SCHEMA = {"fields": [
    {"type": "money", "key": "amount", "label": "Amount", "required": True, "contributes_to_total": True},
    {"type": "number", "key": "qty", "label": "Qty", "contributes_to_total": True},
    {"type": "text", "key": "note", "label": "Note"},
    {"type": "money", "key": "tax", "label": "Tax"},
]}


def test_missing_required_rejected():
    with pytest.raises(ValueError):
        validate_values(_SCHEMA, {"note": "x"})


def test_unknown_key_rejected():
    with pytest.raises(ValueError):
        validate_values(_SCHEMA, {"amount": 100, "ghost": 1})


def test_valid_values_pass():
    validate_values(_SCHEMA, {"amount": 100, "note": "x"})  # qty/tax optional


def test_total_sums_only_contributing_numeric_fields():
    assert compute_total(_SCHEMA, {"amount": 100, "qty": 3, "tax": 50}) == 103


def test_formula_field_contributes_total():
    schema = {"fields": [
        {"type": "money", "key": "base", "label": "Base", "contributes_to_total": True},
        {"type": "formula", "key": "sum", "label": "Sum", "expr": "sum(items[].price)", "contributes_to_total": True},
    ]}
    assert compute_total(schema, {"base": 100, "sum": 250}) == 350

import pytest
from pydantic import ValidationError

from app.services.form_schema import validate_form_schema


def test_valid_schema_parses():
    schema = validate_form_schema({"fields": [
        {"type": "money", "key": "amount", "label": "Сумма", "required": True, "contributes_to_total": True},
        {"type": "text", "key": "reason", "label": "Обоснование", "max": 2000},
        {"type": "dropdown", "key": "cat", "label": "Категория", "options": ["a", "b"]},
        {"type": "table", "key": "items", "label": "Позиции", "columns": [
            {"key": "name", "type": "text"}, {"key": "price", "type": "money"}]},
        {"type": "file", "key": "invoice", "label": "Счёт", "max_size_mb": 20},
    ]})
    assert {f.key for f in schema.fields} == {"amount", "reason", "cat", "items", "invoice"}


def test_duplicate_keys_rejected():
    with pytest.raises(ValueError):
        validate_form_schema({"fields": [
            {"type": "text", "key": "x", "label": "A"},
            {"type": "text", "key": "x", "label": "B"},
        ]})


def test_unknown_field_type_rejected():
    with pytest.raises(ValidationError):
        validate_form_schema({"fields": [{"type": "wizardry", "key": "x", "label": "X"}]})


def test_bad_key_pattern_rejected():
    with pytest.raises(ValidationError):
        validate_form_schema({"fields": [{"type": "text", "key": "1bad key", "label": "X"}]})


def test_dropdown_requires_options():
    with pytest.raises(ValidationError):
        validate_form_schema({"fields": [{"type": "dropdown", "key": "d", "label": "D", "options": []}]})


def test_file_size_capped_at_50():
    with pytest.raises(ValidationError):
        validate_form_schema({"fields": [{"type": "file", "key": "f", "label": "F", "max_size_mb": 99}]})


def test_table_column_keys_must_be_unique():
    with pytest.raises(ValueError):
        validate_form_schema({"fields": [{"type": "table", "key": "t", "label": "T", "columns": [
            {"key": "c", "type": "text"}, {"key": "c", "type": "number"}]}]})


# ─── schema v2 (Lark parity) ────────────────────────────────────────────────


def test_amount_field_multi_currency():
    schema = validate_form_schema({"fields": [
        {"type": "amount", "key": "total", "label": "Сумма", "required": True,
         "currencies": ["USD", "KZT", "RUB", "UZS", "EUR"], "amount_in_words": False,
         "decimals": 2, "thousand_separator": True, "contributes_to_total": True},
    ]})
    fld = schema.fields[0]
    assert fld.type == "amount"
    assert fld.currencies == ["USD", "KZT", "RUB", "UZS", "EUR"]
    assert fld.decimals == 2


def test_amount_requires_at_least_one_currency():
    with pytest.raises(ValidationError):
        validate_form_schema({"fields": [
            {"type": "amount", "key": "a", "label": "A", "currencies": []}]})


def test_amount_currency_must_be_3_letters():
    with pytest.raises(ValidationError):
        validate_form_schema({"fields": [
            {"type": "amount", "key": "a", "label": "A", "currencies": ["DOLLAR"]}]})


def test_simple_v2_leaf_widgets_parse():
    schema = validate_form_schema({"fields": [
        {"type": "paragraph", "key": "note", "label": "Комментарий", "max": 4000},
        {"type": "static_text", "key": "hdr", "label": "Заголовок", "content": "Раздел A"},
        {"type": "serial", "key": "num", "label": "Номер", "prefix": "AVR-"},
        {"type": "link_ref", "key": "rel", "label": "Связанный", "multiple": True},
    ]})
    by = {f.key: f for f in schema.fields}
    assert by["note"].type == "paragraph" and by["note"].max == 4000
    assert by["hdr"].content == "Раздел A"
    assert by["num"].prefix == "AVR-"
    assert by["rel"].multiple is True


def test_static_text_requires_content():
    with pytest.raises(ValidationError):
        validate_form_schema({"fields": [
            {"type": "static_text", "key": "s", "label": "S", "content": ""}]})


def test_reference_field_with_dependency():
    schema = validate_form_schema({"fields": [
        {"type": "reference", "key": "program_admin", "label": "Администратор программы",
         "source": "program_admins", "column": "name"},
        {"type": "reference", "key": "budget", "label": "Бюджет проекта",
         "source": "budgets", "column": "name", "depends_on": "program_admin"},
    ]})
    by = {f.key: f for f in schema.fields}
    assert by["program_admin"].source == "program_admins"
    assert by["budget"].depends_on == "program_admin"


def test_reference_requires_source_and_column():
    with pytest.raises(ValidationError):
        validate_form_schema({"fields": [
            {"type": "reference", "key": "r", "label": "R", "source": "", "column": "x"}]})


def test_group_field_nested_and_summarize():
    schema = validate_form_schema({"fields": [
        {"type": "group", "key": "lines", "label": "Счёт без договора", "repeatable": True,
         "summarize_keys": ["amount"], "fields": [
            {"type": "text", "key": "tru", "label": "Наименование ТРУ", "required": True},
            {"type": "amount", "key": "amount", "label": "Сумма", "currencies": ["KZT", "USD"]},
            {"type": "file", "key": "invoice", "label": "Счёт"}]},
    ]})
    grp = schema.fields[0]
    assert grp.type == "group"
    assert {c.key for c in grp.fields} == {"tru", "amount", "invoice"}
    assert grp.summarize_keys == ["amount"]


def test_group_summarize_keys_must_exist_in_group():
    with pytest.raises(ValueError):
        validate_form_schema({"fields": [
            {"type": "group", "key": "g", "label": "G", "summarize_keys": ["ghost"],
             "fields": [{"type": "text", "key": "a", "label": "A"}]}]})


def test_group_nested_duplicate_keys_rejected():
    with pytest.raises(ValueError):
        validate_form_schema({"fields": [
            {"type": "group", "key": "g", "label": "G", "fields": [
                {"type": "text", "key": "dup", "label": "A"},
                {"type": "text", "key": "dup", "label": "B"}]}]})


def test_display_conditions_valid():
    schema = validate_form_schema({
        "fields": [
            {"type": "dropdown", "key": "has_contract", "label": "Наличие договора",
             "options": ["Без договора", "По договору"]},
            {"type": "group", "key": "no_contract", "label": "Без договора",
             "fields": [{"type": "text", "key": "tru", "label": "ТРУ"}]},
        ],
        "display_conditions": [
            {"target": "no_contract", "match": "all",
             "conditions": [{"field": "has_contract", "op": "is", "value": "Без договора"}]},
        ],
    })
    assert schema.display_conditions[0].target == "no_contract"
    assert "tru" in schema.all_keys


def test_display_condition_unknown_target_rejected():
    with pytest.raises(ValueError):
        validate_form_schema({
            "fields": [{"type": "text", "key": "a", "label": "A"}],
            "display_conditions": [
                {"target": "ghost", "conditions": [{"field": "a", "value": 1}]}]})


def test_display_condition_unknown_source_field_rejected():
    with pytest.raises(ValueError):
        validate_form_schema({
            "fields": [{"type": "text", "key": "a", "label": "A"}],
            "display_conditions": [
                {"target": "a", "conditions": [{"field": "ghost", "value": 1}]}]})

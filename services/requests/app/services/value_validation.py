"""Lightweight validation of submitted form_values against a schema, plus the
monetary total. Deep per-type validation is deferred; Phase 3a checks key
validity and required-field presence, and sums contributing money/number fields."""

from decimal import Decimal
from typing import Any

from app.services.form_schema import validate_form_schema

_CONTRIB_TYPES = {"money", "number", "formula"}


def validate_values(schema_json: dict, values: dict[str, Any]) -> None:
    schema = validate_form_schema(schema_json)
    valid_keys = schema.keys
    for k in values:
        if k not in valid_keys:
            raise ValueError(f"unknown field '{k}'")
    for field in schema.fields:
        if getattr(field, "required", False):
            v = values.get(field.key)
            if v is None or (isinstance(v, str) and v.strip() == ""):
                raise ValueError(f"required field '{field.key}' is missing")


def compute_total(schema_json: dict, values: dict[str, Any]) -> Decimal:
    schema = validate_form_schema(schema_json)
    total = Decimal(0)
    for field in schema.fields:
        if field.type in _CONTRIB_TYPES and getattr(field, "contributes_to_total", False):
            raw = values.get(field.key)
            if raw is not None:
                try:
                    total += Decimal(str(raw))
                except (ValueError, ArithmeticError):
                    raise ValueError(f"field '{field.key}' is not numeric: {raw!r}")
    return total

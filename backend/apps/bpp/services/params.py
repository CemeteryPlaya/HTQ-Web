"""Разбор параметров строки запроса реестров: неверное значение — 422, а не 500."""

from __future__ import annotations

from htqweb.errors import DomainError


def int_param(params, name: str, default: int | None = None, *, minimum: int | None = None):
    raw = params.get(name)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise DomainError("E-VAL-01", f"Параметр «{name}» должен быть целым числом.",
                          fields=[{"field": name, "message": "Целое число"}]) from None
    return max(minimum, value) if minimum is not None else value

"""Validation of submitted ``form_values`` against a schema, plus the total.

Ported from ``services/requests/app/services/value_validation.py``. As in the
original this is deliberately shallow: it rejects unknown keys and missing
required fields, and sums the fields that opted into the monetary total. Deep
per-type validation was never implemented upstream, and inventing it here
would reject submissions the running system accepts.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .form_schema import validate_form_schema

_CONTRIB_TYPES = {"money", "number", "formula"}


def validate_values(schema_json: dict, values: dict[str, Any]) -> None:
    """Проверить значения против схемы.

    Сообщение о незаполненном поле — на русском и с ПОДПИСЬЮ поля, а не с
    его ключом: этот текст доходит до человека, нажавшего «Отправить», в
    теле 422. Ключ (``budget_line``) ему ничего не говорит, а «Бюджет
    (администратор → программа)» — ровно то, что он видит в форме.

    ``unknown field`` остаётся техническим и английским намеренно: его
    получает не пользователь, а клиент, приславший поле не из схемы.
    """
    schema = validate_form_schema(schema_json)
    valid_keys = schema.keys
    for k in values:
        if k not in valid_keys:
            raise ValueError(f"unknown field '{k}'")
    for field in schema.fields:
        if getattr(field, "filled_by", "initiator") == "approver":
            # Заполняет согласующий на своём шаге — с инициатора не
            # спрашиваем: он этого и знать не может.
            continue
        if getattr(field, "required", False):
            v = values.get(field.key)
            if _is_blank(v):
                raise ValueError(
                    f"Заполните обязательное поле «{field.label}»")
        problem = mismatch_in(schema, field.key, values)
        if problem:
            raise ValueError(problem)


def value_at(values: dict[str, Any], path: str) -> Any:
    """Значение по пути ``key`` или ``group.key``."""
    head, _, tail = path.partition(".")
    value = values.get(head)
    if not tail:
        return value
    return value.get(tail) if isinstance(value, dict) else None


def mismatch_in(schema, field_key: str, values: dict[str, Any]) -> str | None:
    """Нарушение ``must_equal`` внутри поля верхнего уровня ``field_key``
    (у блока — его подполя) — текст для человека или ``None``.

    Сравниваем только когда ОБА значения есть: пустое — забота
    обязательности, а не совпадения. Через ``Decimal(str(..))``: суммы
    приходят из JSON и числом, и строкой, а ``1250000 == "1250000"`` в
    Python ложно.
    """
    from decimal import Decimal, InvalidOperation

    paths = schema.paths()
    labels = {path: _path_label(schema, path) for path in paths}
    for path, field in paths.items():
        if path.split(".")[0] != field_key:
            continue
        target = getattr(field, "must_equal", None)
        if not target or target not in paths:
            continue
        mine, theirs = value_at(values, path), value_at(values, target)
        if _is_blank(mine) or _is_blank(theirs):
            continue
        try:
            same = Decimal(str(mine)) == Decimal(str(theirs))
        except (InvalidOperation, ValueError):
            same = False
        if not same:
            return (f"«{labels[path]}» ({_money(mine)}) не совпадает с "
                    f"«{labels[target]}» ({_money(theirs)}) — суммы должны "
                    f"быть одинаковыми")
    return None


def _path_label(schema, path: str) -> str:
    """Подпись поля по пути — для сообщения человеку.

    Резолвится через ``schema.paths()``, а не обходом ``fields``: там же
    объявлены СИНТЕТИЧЕСКИЕ пути вроде ``<таблица>.total``, у которых нет
    родителя с вложенными полями, и обход по ``.fields`` на них падал.
    """
    field = schema.paths().get(path)
    if field is None:
        return path
    head, _, tail = path.partition(".")
    if not tail:
        return field.label
    top = next((f for f in schema.fields if f.key == head), None)
    # У синтетического пути подпись уже содержит имя родителя
    # («Сравнение поставщиков → сумма выбранного») — не удваиваем.
    if top is None or top.type == "supplier_quotes":
        return field.label
    return f"{top.label} → {field.label}"


def _money(value: Any) -> str:
    try:
        from decimal import Decimal
        number = Decimal(str(value))
        text = f"{number:,.2f}".replace(",", " ")
        return text[:-3] if text.endswith(".00") else text
    except Exception:
        return str(value)


def approver_fields(schema_json: dict) -> list:
    """Поля, которые заполняет согласующий на своём шаге, в порядке схемы."""
    schema = validate_form_schema(schema_json)
    return [field for field in schema.fields
            if getattr(field, "filled_by", "initiator") == "approver"]


def is_blank(value: Any) -> bool:
    return _is_blank(value)


def _is_blank(value: Any) -> bool:
    """Пусто ли значение поля.

    Пустой список — это «ни одной строки» у повторяемой группы и «ничего не
    выбрано» у многозначного списка; для обязательного поля и то, и другое
    означает незаполненность.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return not value
    return False


def compute_total(schema_json: dict, values: dict[str, Any]) -> Decimal:
    """Sum of the fields that declare ``contributes_to_total``.

    Считаются и поля внутри БЛОКОВ (неповторяемых групп) по пути
    ``группа.поле``: сумма закупа живёт в блоке согласующего
    («Согласованные условия → Сумма»), и без этого ``total_amount``
    заявки на закуп всегда был бы нулём. Внутрь повторяемой группы не
    идём — там у каждой строки своё значение, и «итог» по ней означал бы
    другое (для этого есть ``summarize_keys``).

    ``Decimal(str(raw))`` rather than ``Decimal(raw)``: the values arrive from
    JSON, where a money amount may already be a float, and going through the
    string form avoids binary-float noise in a monetary total.
    """
    schema = validate_form_schema(schema_json)
    total = Decimal(0)
    for path, field in schema.paths().items():
        if field.type not in _CONTRIB_TYPES \
                or not getattr(field, "contributes_to_total", False):
            continue
        raw = value_at(values, path)
        if raw is None or raw == "":
            continue
        try:
            total += Decimal(str(raw))
        except (ValueError, ArithmeticError):
            raise ValueError(f"field '{path}' is not numeric: {raw!r}")
    return total

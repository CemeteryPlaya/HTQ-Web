"""Виджет ``budget_line_ref``: проверка и подпись ссылок на строки бюджета.

Единственное место, где approvals ходит в ``apps.contracts`` — и только через
``apps.contracts.interface`` (``apps/core/tests/test_app_isolation.py``).
Форма хранит голый ``budget_line_id``; всё, что про него нужно знать —
существует ли, открыт ли бюджет, как его назвать человеку, — спрашивается
здесь, одним батчем на форму.

Две функции ведут себя по-разному при недоступном contracts, и это
намеренно:

* ``validate_budget_line_refs`` — вызывается при ОТПРАВКЕ. ``ServiceDisabled``
  не глушится: заявка, ссылающаяся на строку бюджета, не может уйти на
  согласование, пока некому подтвердить, что строка есть, — ``api_view``
  превратит исключение в 503 ``service_disabled``. При этом форма БЕЗ такого
  виджета contracts не трогает вовсе (ни одного вызова interface, если
  ссылок нет), так что выключенный домен договоров не задевает отпуска и
  прочие запросы.
* ``labels_for`` — только подписи для таблицы данных. Деградирует по
  правилу ``hydration``: недоступный сосед стоит подписи, а не строки.
"""

from __future__ import annotations

from typing import Any, Iterator

from apps.contracts import interface as contracts_interface

from . import hydration
from .form_schema import FormSchema, validate_form_schema

WIDGET_TYPE = "budget_line_ref"


def iter_refs(schema: FormSchema, values: dict[str, Any]) -> Iterator[tuple[str, Any]]:
    """``(путь поля, сырое значение)`` для каждого ``budget_line_ref`` формы.

    Обходит и строки групп: конструктор позволяет положить виджет внутрь
    повторяемой группы, и тогда значений столько, сколько строк. Путь
    поля в группе — ``группа.поле``, чтобы сообщение об ошибке указывало
    на конкретное место формы.
    """
    def walk(fields, container: dict[str, Any], prefix: str):
        for field in fields:
            path = f"{prefix}{field.key}"
            if field.type == WIDGET_TYPE:
                yield path, container.get(field.key)
            elif field.type == "group":
                rows = container.get(field.key)
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    if isinstance(row, dict):
                        yield from walk(field.fields, row, f"{path}.")

    yield from walk(schema.fields, values, "")


def _as_line_id(path: str, raw: Any) -> int:
    # ``bool`` — подкласс ``int``, и ``int(True) == 1`` подсунул бы первую
    # строку бюджета вместо ошибки; дробное число из JSON — тоже не id.
    if isinstance(raw, bool) or isinstance(raw, float) and not raw.is_integer():
        raise ValueError(f"budget_line_ref '{path}': {raw!r} is not a budget line id")
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"budget_line_ref '{path}': {raw!r} is not a budget line id")


def validate_budget_line_refs(schema_json: dict, values: dict[str, Any]) -> None:
    """Каждая заполненная ссылка указывает на существующую строку живого
    бюджета. ``ValueError`` — с путём поля и причиной; ``ServiceDisabled``
    пробрасывается (см. докстринг модуля)."""
    schema = validate_form_schema(schema_json)
    refs = [(path, raw) for path, raw in iter_refs(schema, values)
            if raw is not None and raw != ""]
    if not refs:
        return

    wanted = {path: _as_line_id(path, raw) for path, raw in refs}
    briefs = {row["id"]: row
              for row in contracts_interface.get_budget_lines_brief(wanted.values())}
    for path, line_id in wanted.items():
        brief = briefs.get(line_id)
        if brief is None:
            raise ValueError(
                f"budget_line_ref '{path}': budget line {line_id} not found")
        if brief["budget_status"] != "active":
            raise ValueError(
                f"budget_line_ref '{path}': budget line {line_id} belongs to a "
                f"closed budget")
        if not brief["administrator_is_active"]:
            raise ValueError(
                f"budget_line_ref '{path}': budget line {line_id} belongs to an "
                f"inactive budget administrator")


def label_for(brief: dict) -> str:
    """«Администратор — Программа (год, валюта)» — та же связка, что
    показывает каскад в форме, чтобы таблица данных читалась как форма."""
    return (f"{brief['administrator_name']} — {brief['program_name']} "
            f"({brief['period_year']}, {brief['currency']})")


def labels_for(line_ids) -> dict[int, str]:
    """Подписи батчем; для строки, которую contracts не назвал (удалена или
    домен недоступен), — ``«Строка бюджета #<id>»``, тот же приём, что
    ``"ID <n>"`` у людей в ``template_data_table``."""
    ids = sorted({int(x) for x in line_ids if x is not None})
    if not ids:
        return {}
    briefs = hydration.budget_line_briefs(ids)
    return {line_id: (label_for(briefs[line_id]) if line_id in briefs
                      else f"Строка бюджета #{line_id}")
            for line_id in ids}

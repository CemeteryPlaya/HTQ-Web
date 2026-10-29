"""Ячейки xlsx без формул от пользователей (T-27).

Текст, который ввёл человек (наименование поставщика, комментарий, примечание
к аналогу), начинающийся с ``= + - @``, табуляции или возврата каретки,
табличный редактор читателя может принять за формулу (CSV/формульная
инъекция: ``=HYPERLINK(…)`` выполнилась бы у бухгалтера). Такая строка
пишется ячейкой-ТЕКСТОМ (``data_type="s"``): значение остаётся как есть —
апостроф в начале испортил бы телефон «+7…» или «-5 %», — а формулой оно не
станет ни в Excel, ни в LibreOffice. Числа и даты не трогаются.
"""

from __future__ import annotations

from openpyxl.cell import WriteOnlyCell

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def is_dangerous(value) -> bool:
    return isinstance(value, str) and value.startswith(FORMULA_PREFIXES)


def safe_cell(sheet, value) -> WriteOnlyCell:
    """Ячейка потокового листа (``Workbook(write_only=True)``) для ``value``."""
    cell = WriteOnlyCell(sheet, value=value)
    if is_dangerous(value):
        cell.data_type = "s"
    return cell

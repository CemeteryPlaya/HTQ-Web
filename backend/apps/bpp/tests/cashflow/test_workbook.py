"""Разбор книги CashFlow в модуле (B6.2, D-B62-3) — копия разбора
``contracts``: на одной книге обе дают одни и те же строки, суммы и ключи
повтора. Пока старый разбор жив, этот тест не даёт им разойтись."""

from __future__ import annotations

from collections import defaultdict

import pytest

from apps.bpp.services.cashflow import workbook
from apps.contracts.services import cashflow_import as old_registry
from apps.contracts.services import cashflow_operations_import as old_ops
from apps.contracts.tests.test_cashflow_import import registry_row
from apps.contracts.tests.test_cashflow_operations_import import (
    ARALSK,
    BUDGET,
    DAMONA,
    build_book,
    by_agreement,
    op_row,
)

openpyxl = pytest.importorskip("openpyxl")

REGISTRY = [
    registry_row(admin=ARALSK, code="3020", program="Сопровождение проекта",
                 number="113-20-2026", name="Проживание и питание",
                 counterparty="ИП «Абулгазиев»", bin_iin="631031301177",
                 amount=None, type_="открытый", lark="L-OPEN"),
    registry_row(admin=DAMONA, code="3011", number="1", bin_iin="80340019927",
                 bin_length=11, amount=1250000.5, lark="L-1"),
    registry_row(admin=DAMONA, code="3011", number="1", bin_iin="123456789012",
                 amount=300000, lark="L-2", advance="70%"),
]
OPS = [
    by_agreement(),
    by_agreement(),                         # полный повтор — второй ключ
    op_row(amount=250000.75),
    op_row(kind="Без договора", budget=3011, goods="Щебень"),
]


def test_new_reader_equals_the_old_one(tmp_path):
    path = build_book(tmp_path, ops_rows=OPS, registry_rows=REGISTRY)
    book = openpyxl.load_workbook(path, data_only=True)

    assert [vars(row) for row in workbook.read_budget_sheet(book)] == \
        [vars(row) for row in old_registry.read_budget_sheet(book)]

    new_rows, new_warnings = workbook.read_registry_sheet(book)
    old_rows, old_warnings = old_registry.read_registry_sheet(book)
    kinds = {"works_services": "works", "goods": "goods"}
    types = {"standard": "standard", "framework": "open"}
    assert new_warnings == old_warnings
    assert [vars(row) for row in new_rows] == [
        {**vars(row), "kind": kinds[row.kind], "contract_type": types[row.contract_type]}
        for row in old_rows]
    assert new_rows[1].bin_iin == "080340019927"            # потерянный ноль

    new_ops, new_op_warnings = workbook.read_operations_sheet(book)
    old_ops_rows, old_op_warnings = old_ops.read_operations_sheet(book)
    assert new_op_warnings == old_op_warnings
    seen: dict[tuple, int] = defaultdict(int)
    old_keys = []
    for row in old_ops_rows:
        key = old_ops._content_key(row)
        old_keys.append(old_ops.fingerprint(row, seen[key]))
        seen[key] += 1
    assert [row.fingerprint for row in new_ops] == old_keys
    assert len(set(old_keys)) == len(old_keys) == 4         # повтор различим
    assert [(row.amount, row.document_date) for row in new_ops] == [
        (row.amount, row.document_date) for row in old_ops_rows]


def test_budget_sheet_is_required(tmp_path):
    book = openpyxl.Workbook()
    with pytest.raises(workbook.WorkbookError, match="нет листа «Бюджет»"):
        workbook.read_budget_sheet(book)
    assert BUDGET                                            # фабрика та же, что у старого

"""Разбор выписки Excel и CSV по шаблону банка (ТЗ §11.3 п.1–2, E-IMP-02,
E-IMP-03; план этапа 3 A, задача 3, Review Focus 3 и 4).

Чтение колонок по заголовку проверяют тесты шаблона (``test_templates.py``,
задача 2); здесь — отбор списаний своего счёта, итоги и предел строк.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.bpp.services.bank.parsers import MAX_ROWS, tabular
from htqweb.errors import DomainError

from . import common

OWN, OTHER = common.iban(1), common.iban(2)
ACCOUNT = SimpleNamespace(iban=OWN, currency="KZT")

COLUMNS = {**common.HEADERS, "payer_account": "Счёт плательщика", "currency": "Валюта"}
HEAD = [COLUMNS["doc_number"], COLUMNS["date"], COLUMNS["amount"], COLUMNS["purpose"],
        COLUMNS["recipient_name"], COLUMNS["recipient_bin"], COLUMNS["payer_account"],
        COLUMNS["currency"], "Остаток"]


def _parse(upload, tpl):
    return tabular.parse(upload.read(), name=upload.name, template=tpl, account=ACCOUNT)


def _error(fn, *args, **kwargs) -> DomainError:
    with pytest.raises(DomainError) as exc:
        fn(*args, **kwargs)
    return exc.value


def test_xlsx_numeric_amount_is_exact_decimal():
    """Число ячейки 1250000.1 (openpyxl отдаёт float) и строка
    «1 250 000,00» — ``Decimal`` без потерь."""
    tpl = common.template(columns=COLUMNS)
    upload = common.xlsx_file([
        ["Выписка по счёту", OWN], [],
        HEAD,
        ["1", "05.09.2026", -1250000.1, "Оплата", "ТОО А", 50140000656, OWN, "KZT", 0],
        ["2", date(2026, 9, 6), "-1 250 000,00", "Оплата", "ТОО Б", "990340000123", "", "", 0],
    ])
    result = _parse(upload, tpl)
    assert [line["amount"] for line in result.lines] == [Decimal("1250000.10"),
                                                        Decimal("1250000.00")]
    assert all(isinstance(line["amount"], Decimal) for line in result.lines)
    assert result.lines[0]["recipient_bin"] == "050140000656"  # ведущий ноль не потерян
    assert result.lines[1]["doc_date"] == date(2026, 9, 6)
    assert result.lines[1]["currency"] == "KZT"  # пусто — валюта счёта
    assert result.rows_total == 2 and result.errors == []


def test_xlsx_only_own_debits_and_totals():
    """Review Focus 4: поступление и платёж чужого счёта не загружаются, но
    строками файла считаются — «списаний 1 из 3»."""
    tpl = common.template(columns=COLUMNS)
    upload = common.xlsx_file([
        HEAD,
        ["1", "05.09.2026", -100, "Списание", "ТОО А", "", OWN, "KZT"],
        ["2", "05.09.2026", 200, "Поступление", "ТОО Б", "", OWN, "KZT"],
        ["3", "05.09.2026", -300, "Чужой счёт", "ТОО В", "", OTHER, "KZT"],
        [None, None, None, None, None],                      # пустая строка — не в счёт
        ["", "", "", "Остаток на конец дня", "", "", "", ""],  # подвал — не в счёт
    ])
    result = _parse(upload, tpl)
    assert (result.rows_total, len(result.lines)) == (3, 1)
    assert result.lines[0]["doc_number"] == "1"


def test_template_without_payer_column_takes_every_debit():
    """Колонка плательщика необязательна: выписка — по одному счёту."""
    tpl = common.template()
    upload = common.xlsx_file([
        [common.HEADERS["date"], common.HEADERS["doc_number"], common.HEADERS["amount"],
         common.HEADERS["purpose"]],
        ["05.09.2026", "1", -10, "Оплата"],
        ["05.09.2026", "2", 20, "Поступление"],
    ])
    result = _parse(upload, tpl)
    assert [line["doc_number"] for line in result.lines] == ["1"]


def test_csv_split_mode_with_semicolon_and_cp1251():
    columns = {"date": "Дата", "doc_number": "Номер", "debit": "Дебет", "credit": "Кредит",
               "purpose": "Назначение", "recipient_bin": "БИН"}
    tpl = common.template(format="csv", encoding="cp1251", columns=columns,
                          amount_mode="split")
    upload = common.csv_file([
        ["Дата", "Номер", "Дебет", "Кредит", "Назначение", "БИН"],
        ["05.09.2026", "11", "1 250 000,00", "", "Оплата за металл", "050140000656"],
        ["05.09.2026", "12", "", "500,00", "Возврат", ""],
        ["31.02.2026", "13", "10,00", "", "Кривая дата", ""],
    ])
    result = _parse(upload, tpl)
    assert [(line["doc_number"], line["amount"]) for line in result.lines] == [
        ("11", Decimal("1250000.00"))]
    assert result.lines[0]["purpose"] == "Оплата за металл"
    assert result.errors == ["Строка 4: не распознана дата „31.02.2026“"]
    assert result.rows_total == 3


def test_missing_required_column_is_e_imp_02_in_parse_and_precheck():
    tpl = common.template()
    upload = common.xlsx_file([[common.HEADERS["date"], common.HEADERS["amount"],
                                common.HEADERS["purpose"]],
                               ["05.09.2026", -1, "x"]])
    content = upload.read()
    for err in (_error(tabular.parse, content, name=upload.name, template=tpl, account=ACCOUNT),
                _error(tabular.precheck, content, name=upload.name, template=tpl)):
        assert err.code == "E-IMP-02" and common.HEADERS["doc_number"] in err.message


def test_over_ten_thousand_rows_is_e_imp_03():
    tpl = common.template(format="csv", encoding="utf-8", columns=dict(common.HEADERS))
    header = [common.HEADERS["date"], common.HEADERS["doc_number"], common.HEADERS["amount"],
              common.HEADERS["purpose"]]
    rows = [header] + [["05.09.2026", str(n), "-1,00", "x"] for n in range(MAX_ROWS + 1)]
    content = common.csv_file(rows, encoding="utf-8").read()
    for fn, kwargs in ((tabular.precheck, {}), (tabular.parse, {"account": ACCOUNT})):
        err = _error(fn, content, name="vypiska.csv", template=tpl, **kwargs)
        assert (err.code, err.status) == ("E-IMP-03", 422)
    exactly = common.csv_file(rows[:-1], encoding="utf-8").read()
    assert tabular.precheck(exactly, name="vypiska.csv", template=tpl)["documents"] == MAX_ROWS


def test_wrong_extension_is_e_imp_01():
    tpl = common.template()
    upload = common.csv_file([["a"]], name="vypiska.csv")
    err = _error(tabular.precheck, upload.read(), name=upload.name, template=tpl)
    assert err.code == "E-IMP-01"

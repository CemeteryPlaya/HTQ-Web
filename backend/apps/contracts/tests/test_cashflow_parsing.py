"""Разбор ячеек книги CashFlow.xlsx — чистые функции, без БД.

Каждый тест здесь закрывает конкретную особенность РЕАЛЬНОГО файла
заказчика, а не воображаемый случай: ведущий ноль в БИН, два написания
доли аванса, коды программ, склеенные с названием. Поэтому и значения в
них взяты из книги как есть.
"""

from decimal import Decimal

import pytest

from apps.contracts.models import PaymentType
from apps.contracts.services import cashflow_import as cf


# ── БИН и колонка настоящей длины ───────────────────────────────────────

def test_bin_gets_leading_zero_from_length_column():
    # Ровно случай ТОО «Снабкомплект Монтаж» из книги: Excel съел ведущий
    # ноль, а колонка без заголовка помнит, что знаков должно быть 12.
    number, warning = cf.normalize_bin("80340019927", 11)
    assert number == "080340019927"
    assert warning is None


def test_bin_already_full_length_is_untouched():
    number, warning = cf.normalize_bin("890406300239", 12)
    assert number == "890406300239"
    assert warning is None


def test_bin_is_padded_even_without_the_length_column():
    # Колонка длины — перекрёстная проверка, а не источник ширины: БИН
    # двенадцатизначен сам по себе, и её отсутствие ничего не меняет.
    number, warning = cf.normalize_bin("80340019927", None)
    assert number == "080340019927"
    assert warning is None


def test_stale_length_column_is_flagged_but_bin_still_padded():
    # Формула LEN(G) в книге пересчитывается не всегда. Расхождение — повод
    # сказать об этом, а не повод не чинить номер.
    number, warning = cf.normalize_bin("80340019927", 12)
    assert number == "080340019927"
    assert "устарела" in warning


def test_bin_longer_than_twelve_is_not_truncated():
    # Обрезать номер импорт не вправе: лишняя цифра — это ошибка ввода,
    # которую должен увидеть человек, а не потеря данных.
    number, warning = cf.normalize_bin("8904063002391", 13)
    assert number == "8904063002391"
    assert "длиннее" in warning


def test_numeric_bin_cell_does_not_get_float_tail():
    # Excel отдаёт БИН числом, и str(80340019927.0) дал бы «.0» в ключе.
    number, _ = cf.normalize_bin(80340019927.0, 11)
    assert number == "080340019927"


# ── Доля аванса ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("0", "0"), (0, "0"),
    ("1", "1"), (1, "1"),
    ("0.5", "0.5"), (0.5, "0.5"),
    ("0.3", "0.3"), ("0.7", "0.7"),
    ("0%", "0"), ("70%", "0.7"), ("100%", "1"),
    (None, "0"), ("", "0"),
])
def test_advance_share_accepts_both_spellings(raw, expected):
    assert cf.parse_advance_share(raw) == Decimal(expected)


def test_advance_share_rejects_bare_percent_number():
    # «70» без знака процента — это не 70%, а доля 70, которой не бывает.
    # Угадывать импорт не должен: ошибка строки видна в отчёте.
    with pytest.raises(ValueError, match="вне диапазона"):
        cf.parse_advance_share("70")


def test_advance_share_rejects_garbage():
    with pytest.raises(ValueError, match="не разобран аванс"):
        cf.parse_advance_share("по договорённости")


@pytest.mark.parametrize("share, expected", [
    ("0", PaymentType.POSTPAYMENT),
    ("0.3", PaymentType.STAGED),
    ("0.5", PaymentType.STAGED),
    ("1", PaymentType.PREPAYMENT),
])
def test_payment_type_derived_from_share(share, expected):
    assert cf.derive_payment_type(Decimal(share)) == expected


# ── Даты ────────────────────────────────────────────────────────────────

def test_excel_serial_becomes_date():
    # 46170 — дата подписания первого договора в книге.
    assert cf.parse_excel_date(46170).isoformat() == "2026-05-28"


def test_already_parsed_date_passes_through():
    import datetime as dt
    assert cf.parse_excel_date(dt.datetime(2026, 5, 28, 12, 0)) == dt.date(2026, 5, 28)


def test_empty_date_is_none():
    assert cf.parse_excel_date(None) is None
    assert cf.parse_excel_date("") is None


def test_unparseable_date_raises():
    with pytest.raises(ValueError, match="не разобрана дата"):
        cf.parse_excel_date("когда-то весной")


# ── Программа: «код Название» одной ячейкой ─────────────────────────────

def test_program_cell_splits_code_and_name():
    code, name = cf.split_program_cell("3019 Монтаж Ограждения/Земляные работы")
    assert code == "3019"
    assert name == "Монтаж Ограждения/Земляные работы"


def test_program_cell_without_code_returns_empty_code():
    code, name = cf.split_program_cell("Сопровождение проекта")
    assert code == ""
    assert name == "Сопровождение проекта"


# ── Раздача номеров договоров ───────────────────────────────────────────

def test_duplicate_numbers_get_dots():
    allocator = cf._NumberAllocator(set())
    assert allocator.allocate("1") == ("1", False)
    assert allocator.allocate("1") == ("1.", True)
    assert allocator.allocate("1") == ("1..", True)


def test_number_taken_in_database_is_avoided():
    # Импорт в непустую базу обязан обойти уже занятый номер, а не упасть
    # на IntegrityError.
    allocator = cf._NumberAllocator({"113-20-2026"})
    assert allocator.allocate("113-20-2026") == ("113-20-2026.", True)


def test_reserved_number_is_not_reissued():
    # Номер, закреплённый за уже загруженным договором, второй раз не выдаётся.
    allocator = cf._NumberAllocator(set())
    allocator.reserve("14.")
    assert allocator.allocate("14") == ("14", False)
    assert allocator.allocate("14") == ("14..", True)


# ── Суммы ───────────────────────────────────────────────────────────────

def test_money_drops_binary_tail():
    # Excel хранит 554038657.32 как 554038657.32000005 — в базу должен
    # уехать рубль в рубль, а не двоичный хвост.
    assert cf._money(554038657.32000005) == Decimal("554038657.32")


def test_empty_amount_is_zero():
    assert cf._money(None) == Decimal("0.00")
    assert cf._money("") == Decimal("0.00")

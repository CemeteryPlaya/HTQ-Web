"""Проверка реквизитов контрагента (ТЗ §18): БИН/ИИН на границе, номер
нерезидента, IBAN, БИК — Review Focus 3."""

from __future__ import annotations

import pytest

from apps.bpp.services.counterparties import validation as v
from htqweb.errors import DomainError

from . import common


def test_bin_check_first_pass():
    number = common.bin_first_pass()
    assert v.bin_iin_is_valid(number)
    wrong = number[:11] + str((int(number[11]) + 1) % 10)
    assert not v.bin_iin_is_valid(wrong)


def test_bin_check_second_pass_with_rest_ten():
    """Первый проход дал 10 — контроль по весам 3…11, 1, 2."""
    number = common.bin_second_pass()
    assert v.bin_iin_is_valid(number)
    # 12-й разряд «10» не бывает, поэтому любой другой — недействителен.
    others = [number[:11] + str(d) for d in range(10) if str(d) != number[11]]
    assert not any(v.bin_iin_is_valid(other) for other in others)


def test_bin_check_ten_in_second_pass_is_invalid():
    """Остаток 10 и во втором проходе — номер недействителен при любом
    12-м разряде."""
    body = common.bin_body_ten_twice()
    assert not any(v.bin_iin_is_valid(body + str(d)) for d in range(10))
    with pytest.raises(DomainError) as exc:
        v.check_reg_number("legal", "KZ", body + "0")
    assert exc.value.code == "E-CTR-03"
    assert exc.value.fields[0]["field"] == "reg_number"


def test_bin_check_length_and_letters():
    number = common.bin_first_pass()
    assert not v.bin_iin_is_valid(number[:11])
    assert not v.bin_iin_is_valid(number + "0")
    assert not v.bin_iin_is_valid("A" + number[1:])
    for raw in (number[:11], number + "0", "БИН" + number):
        with pytest.raises(DomainError) as exc:
            v.check_reg_number("ip", "KZ", raw)
        assert exc.value.code == "E-CTR-03"


def test_bin_check_drops_spaces_and_dashes():
    number = common.bin_first_pass()
    raw = f" {number[:3]} {number[3:6]}-{number[6:9]}–{number[9:]} "
    assert v.normalize_reg_number(raw) == number
    assert v.check_reg_number("individual", "kz", raw) == number


def test_bin_check_nonresident_free_number_up_to_30():
    assert v.check_reg_number("nonresident", "RU", "ОГРН 1027700132195") == "ОГРН1027700132195"
    thirty = "A" * 30
    assert v.check_reg_number("nonresident", "RU", thirty) == thirty
    # Пробелы и дефисы не считаются: 30 знаков + разделители — ещё можно.
    assert v.check_reg_number("nonresident", "KG", "-".join(thirty)) == thirty
    with pytest.raises(DomainError) as exc:
        v.check_reg_number("nonresident", "RU", "A" * 31)
    assert exc.value.code == "E-CTR-03"


def test_bin_check_empty_and_nonresident_from_kz():
    with pytest.raises(DomainError) as exc:
        v.check_reg_number("nonresident", "RU", " - ")
    assert exc.value.code == "E-CTR-03"
    with pytest.raises(DomainError) as exc:
        v.check_reg_number("nonresident", "KZ", common.bin_first_pass())
    assert exc.value.code == "E-CTR-03"


def test_bin_check_resident_kind_of_other_country_is_free():
    """Российское ИП — не БИН: алгоритм РК к чужим номерам не применяется."""
    assert v.check_reg_number("ip", "RU", "304500116000157") == "304500116000157"


def test_iban():
    good = "KZ86125KZT5004100100"  # пример из реестра IBAN
    assert v.iban_is_valid(good)
    assert v.iban_is_valid(common.kz_iban("125KZT5004100199"))
    assert not v.iban_is_valid("KZ87125KZT5004100100")          # контрольные цифры
    assert not v.iban_is_valid("KZ86125KZT500410010")            # 17 знаков после KZ
    assert not v.iban_is_valid("RU86125KZT5004100100")           # не Казахстан
    assert v.check_bank_details(iban=" kz86 125k zt50 0410 0100 ") == {"iban": good}
    with pytest.raises(DomainError) as exc:
        v.check_bank_details(iban="KZ87125KZT5004100100")
    assert (exc.value.code, exc.value.fields[0]["field"]) == ("E-CTR-04", "iban")


def test_bic():
    assert v.bic_is_valid("HSBKKZKX")
    assert v.bic_is_valid("HSBKKZKX001")
    for bad in ("HSBKKZK", "HSBKKZKX0", "HSBKKZKX0012", "1234KZKX", ""):
        assert not v.bic_is_valid(bad)
    assert v.check_bank_details(bic="hsbkkzkx") == {"bic": "HSBKKZKX"}
    with pytest.raises(DomainError) as exc:
        v.check_bank_details(bic="HSBK")
    assert (exc.value.code, exc.value.fields[0]["field"]) == ("E-CTR-04", "bic")

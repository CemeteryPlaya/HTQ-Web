"""Проверки реквизитов контрагента (ТЗ §18): БИН/ИИН, номер нерезидента,
IBAN, БИК.

БИН/ИИН — 12 цифр с контрольным разрядом по алгоритму РК: сумма первых 11
цифр с весами 1…11 по модулю 11; остаток 10 — второй проход с весами
3…11, 1, 2; остаток 10 во втором проходе — номер недействителен.
Остальные остатки сравниваются с 12-й цифрой.

Рег. номер нормализуется до проверки и хранится нормализованным: пробелы
и дефисы отбрасываются, буквы — в верхний регистр. Иначе «123 456 789 012»
и «123456789012» прошли бы уникальность (страна, номер) как два разных
контрагента.
"""

from __future__ import annotations

import re

from apps.bpp.models.counterparties import CounterpartyKind
from htqweb.errors import DomainError

__all__ = [
    "NONRESIDENT_MAX",
    "bic_is_valid",
    "bin_iin_is_valid",
    "check_bank_details",
    "check_reg_number",
    "iban_is_valid",
    "normalize_bic",
    "normalize_iban",
    "normalize_reg_number",
]

NONRESIDENT_MAX = 30
_WEIGHTS_1 = tuple(range(1, 12))
_WEIGHTS_2 = (3, 4, 5, 6, 7, 8, 9, 10, 11, 1, 2)
_STRIP = re.compile(r"[\s\-‐-―]+")  # пробелы и любые дефисы/тире
_IBAN_KZ = re.compile(r"KZ\d{2}[A-Z0-9]{16}")
_BIC = re.compile(r"[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?")


# ── рег. номер ──────────────────────────────────────────────────────────

def normalize_reg_number(raw) -> str:
    return _STRIP.sub("", str(raw or "")).upper()


def bin_iin_is_valid(value: str) -> bool:
    """Контрольный разряд БИН/ИИН. ``value`` — уже нормализованный номер."""
    if not re.fullmatch(r"\d{12}", value or ""):
        return False
    digits = [int(ch) for ch in value]
    rest = sum(d * w for d, w in zip(digits[:11], _WEIGHTS_1)) % 11
    if rest == 10:
        rest = sum(d * w for d, w in zip(digits[:11], _WEIGHTS_2)) % 11
        if rest == 10:
            return False
    return rest == digits[11]


def _reg_error(message: str) -> DomainError:
    return DomainError("E-CTR-03", message,
                       fields=[{"field": "reg_number", "message": message}])


def check_reg_number(kind: str, country_code: str, raw) -> str:
    """Проверить рег. номер и вернуть его нормализованным; неверный —
    ``DomainError("E-CTR-03")``.

    Казахстан и тип ЮЛ / ИП / ФЛ — БИН/ИИН с контрольным разрядом.
    Нерезидент — свободный номер до 30 символов. Резидентский тип с другой
    страной (российское ИП, иностранное ЮЛ, заведённое не нерезидентом)
    тоже получает свободный номер: алгоритм РК к чужим номерам неприменим.
    Нерезидент со страной «Казахстан» — противоречие, его не пропускаем.
    """
    number = normalize_reg_number(raw)
    country = (country_code or "").upper()
    if not number:
        raise _reg_error("Укажите БИН/ИИН или регистрационный номер контрагента.")
    if kind == CounterpartyKind.NONRESIDENT and country == "KZ":
        raise _reg_error("Нерезидент не может быть из Казахстана. Для казахстанского "
                         "контрагента выберите тип «Юридическое лицо», «ИП» или "
                         "«Физическое лицо» и укажите БИН/ИИН.")
    if country == "KZ":
        if not re.fullmatch(r"\d{12}", number):
            raise _reg_error(f"БИН/ИИН «{number}» должен состоять из 12 цифр. "
                             f"Проверьте номер по документам контрагента.")
        if not bin_iin_is_valid(number):
            raise _reg_error(f"БИН/ИИН «{number}» не прошёл проверку контрольного разряда. "
                             f"Проверьте номер по документам контрагента.")
        return number
    if len(number) > NONRESIDENT_MAX:
        raise _reg_error(f"Регистрационный номер нерезидента — не длиннее "
                         f"{NONRESIDENT_MAX} символов (без пробелов и дефисов).")
    return number


# ── банковские реквизиты ────────────────────────────────────────────────

def normalize_iban(raw) -> str:
    return re.sub(r"\s+", "", str(raw or "")).upper()


def normalize_bic(raw) -> str:
    return re.sub(r"\s+", "", str(raw or "")).upper()


def iban_is_valid(value: str) -> bool:
    """IBAN Казахстана: ``KZ`` + 18 знаков, контроль ISO 13616 (mod 97 = 1)."""
    if not _IBAN_KZ.fullmatch(value or ""):
        return False
    moved = value[4:] + value[:4]
    numeric = "".join(str(int(ch, 36)) for ch in moved)
    return int(numeric) % 97 == 1


def bic_is_valid(value: str) -> bool:
    """БИК (SWIFT): 8 или 11 знаков — банк, страна, город, филиал."""
    return bool(_BIC.fullmatch(value or ""))


def _bank_error(field: str, message: str) -> DomainError:
    return DomainError("E-CTR-04", message, fields=[{"field": field, "message": message}])


def check_bank_details(*, iban=None, bic=None) -> dict:
    """Нормализовать и проверить IBAN и (или) БИК; неверный —
    ``DomainError("E-CTR-04")``. Возвращает только переданные поля."""
    clean = {}
    if iban is not None:
        value = normalize_iban(iban)
        if not iban_is_valid(value):
            raise _bank_error("iban", f"IBAN «{value}» неверен: нужен счёт вида KZ + 18 знаков "
                                      f"с верными контрольными цифрами. Проверьте реквизиты.")
        clean["iban"] = value
    if bic is not None:
        value = normalize_bic(bic)
        if not bic_is_valid(value):
            raise _bank_error("bic", f"БИК «{value}» неверен: нужно 8 или 11 латинских букв "
                                     f"и цифр (например, HSBKKZKX). Проверьте реквизиты.")
        clean["bic"] = value
    return clean

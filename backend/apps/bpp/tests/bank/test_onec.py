"""Разбор выписки 1С — 1CClientBankExchange (ТЗ §11.3 п.1–2, E-IMP-01,
E-IMP-03; план этапа 3 A, задача 3, Review Focus 1 и 4, решение D-S3-3).

Разборщик базы не трогает: счёт организации — простой объект с ``iban`` и
``currency``, файл собирается в тесте в cp1251 с CRLF, как его отдаёт
банк-клиент.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.bpp.services.bank.parsers import MAX_ROWS, onec
from htqweb.errors import DomainError

from . import common

OWN, OTHER = common.iban(1), common.iban(2)
ACCOUNT = SimpleNamespace(iban=OWN, currency="KZT")

#: Текст E-IMP-01 — ТЗ §26.1 дословно.
E_IMP_01 = ("Файл не распознан как выписка формата 1С: нет строки „1CClientBankExchange“. "
            "Выберите другой формат или файл.")


def _error(fn, *args, **kwargs) -> DomainError:
    with pytest.raises(DomainError) as exc:
        fn(*args, **kwargs)
    return exc.value


def _line_of(content: bytes, text: str) -> int:
    """Номер строки файла (с 1), где стоит ``text``."""
    lines = content.decode("cp1251").split("\r\n")
    return next(n for n, line in enumerate(lines, start=1) if line == text)


def test_onec_dirty_file_bad_date_goes_to_errors_other_documents_load():
    """Review Focus 1: CP1251 и CRLF, три документа, у одного «31.02.2026» —
    два списания и ошибка «Строка N: …» с номером строки файла."""
    docs = [common.onec_doc("101", "05.09.2026", "1250000.00", OWN),
            common.onec_doc("102", "31.02.2026", "10.00", OWN),
            common.onec_doc("103", "06.09.2026", "500.5", OWN, recipient_bin="990340000123")]
    content = common.onec_bytes(OWN, docs)
    assert b"\r\n" in content and "Номер".encode("cp1251") in content

    result = onec.parse(content, account=ACCOUNT)

    assert result.rows_total == 3
    assert [line["doc_number"] for line in result.lines] == ["101", "103"]
    bad_line = _line_of(content, "Дата=31.02.2026")
    assert result.errors == [f"Строка {bad_line}: не распознана дата „31.02.2026“"]
    first = result.lines[0]
    assert first["doc_date"] == date(2026, 9, 5)
    assert first["amount"] == Decimal("1250000.00")
    assert result.lines[1]["amount"] == Decimal("500.50")
    assert first["recipient_bin"] == "050140000656"
    assert first["recipient_name"] == "ТОО «Ромашка»"
    assert first["purpose"] == "Оплата по счёту СЧ-2026-000001"
    assert first["currency"] == "KZT"
    assert (result.period_from, result.period_to) == (date(2026, 9, 1), date(2026, 9, 30))


def test_onec_without_header_is_e_imp_01_verbatim():
    content = common.onec_bytes(OWN, [common.onec_doc("1", "05.09.2026", "1.00", OWN)],
                                header=False)
    err = _error(onec.parse, content, account=ACCOUNT)
    assert (err.code, err.status, err.message) == ("E-IMP-01", 422, E_IMP_01)
    assert err.fields[0]["field"] == "file"
    # Excel вместо выписки — тот же ответ, и у быстрой проверки тоже.
    assert _error(onec.precheck, b"PK\x03\x04garbage", account=ACCOUNT).message == E_IMP_01


def test_onec_only_own_debits_are_loaded():
    """Review Focus 4: поступление (плательщик — контрагент, получатель —
    наш счёт) и платёж чужого счёта не загружаются, но в строках файла
    считаются: «списаний 1 из 3»."""
    docs = [common.onec_doc("1", "05.09.2026", "100.00", OWN),
            common.onec_doc("2", "05.09.2026", "200.00", OTHER, recipient_iban=OWN),
            common.onec_doc("3", "05.09.2026", "300.00", OTHER)]
    result = onec.parse(common.onec_bytes(OWN, docs), account=ACCOUNT)
    assert (result.rows_total, len(result.lines), result.errors) == (3, 1, [])
    assert result.lines[0]["amount"] == Decimal("100.00")


@pytest.mark.parametrize(("payer_key", "bin_key"), [
    ("ПлательщикСчет", "ПолучательИНН"),
    ("ПлательщикИИК", "ПолучательБИН"),
    ("ПлательщикРасчСчет", "ПолучательИИН"),
])
def test_onec_field_synonyms(payer_key, bin_key):
    """D-S3-3: поля казахстанского варианта читаются наравне со стандартом."""
    doc = common.onec_doc("7", "05.09.2026", "10.00", OWN, payer_key=payer_key,
                          bin_key=bin_key, recipient_bin="870412300123")
    result = onec.parse(common.onec_bytes(OWN, [doc]), account=ACCOUNT)
    assert len(result.lines) == 1 and result.lines[0]["recipient_bin"] == "870412300123"


def test_onec_debit_date_is_preferred_to_document_date():
    """``ДатаСписано`` — дата списания со счёта — точнее даты документа."""
    doc = common.onec_doc("7", "01.09.2026", "10.00", OWN, extra=("ДатаСписано=03.09.2026",))
    result = onec.parse(common.onec_bytes(OWN, [doc]), account=ACCOUNT)
    assert result.lines[0]["doc_date"] == date(2026, 9, 3)


def test_onec_iban_with_spaces_and_lower_case_is_the_same_account():
    spaced = f"{OWN[:4].lower()} {OWN[4:12]} {OWN[12:]}"
    doc = common.onec_doc("1", "05.09.2026", "10.00", spaced)
    result = onec.parse(common.onec_bytes(spaced, [doc]), account=ACCOUNT)
    assert len(result.lines) == 1


def test_onec_bad_amount_and_missing_number_are_row_errors():
    docs = [common.onec_doc("1", "05.09.2026", "сто", OWN),
            common.onec_doc("", "05.09.2026", "10.00", OWN),
            common.onec_doc("3", "05.09.2026", "10.00", OWN)]
    content = common.onec_bytes(OWN, docs)
    result = onec.parse(content, account=ACCOUNT)
    assert len(result.lines) == 1
    assert result.errors[0] == f"Строка {_line_of(content, 'Сумма=сто')}: не распознана сумма „сто“"
    assert "нет номера документа" in result.errors[1]


def test_onec_statement_of_another_account_is_rejected():
    """Выписка выгружена по другому счёту — отказ, а не «0 списаний»."""
    content = common.onec_bytes(OTHER, [common.onec_doc("1", "05.09.2026", "1.00", OTHER)])
    err = _error(onec.parse, content, account=ACCOUNT)
    assert err.code == "E-VAL-01" and err.fields[0]["field"] == "account_id"
    assert OTHER in err.message


def test_onec_over_ten_thousand_documents_is_e_imp_03():
    doc = common.onec_doc("1", "05.09.2026", "1.00", OWN)
    too_many = common.onec_bytes(OWN, [doc] * (MAX_ROWS + 1))
    for fn in (onec.parse, onec.precheck):
        err = _error(fn, too_many, account=ACCOUNT)
        assert (err.code, err.status) == ("E-IMP-03", 422)
        assert "10 000" in err.message
    # Ровно предел — принимается.
    exactly = common.onec_bytes(OWN, [doc] * MAX_ROWS)
    assert onec.precheck(exactly, account=ACCOUNT)["documents"] == MAX_ROWS


def test_onec_precheck_reads_the_period_from_the_header():
    content = common.onec_bytes(OWN, [common.onec_doc("1", "05.09.2026", "1.00", OWN)],
                                period=("01.08.2026", "31.08.2026"))
    assert onec.precheck(content, account=ACCOUNT) == {
        "period_from": date(2026, 8, 1), "period_to": date(2026, 8, 31), "documents": 1}
    no_period = common.onec_bytes(OWN, [common.onec_doc("1", "05.09.2026", "1.00", OWN)],
                                  period=None)
    found = onec.precheck(no_period, account=ACCOUNT)
    assert (found["period_from"], found["period_to"]) == (None, None)


def test_onec_utf8_bom_file_is_read():
    """BOM UTF-8 — признак UTF-8 сильнее кодировки шаблона."""
    text = "\r\n".join(common.onec_lines(OWN, [common.onec_doc("1", "05.09.2026", "1.00", OWN)]))
    result = onec.parse(b"\xef\xbb\xbf" + text.encode("utf-8"), account=ACCOUNT)
    assert len(result.lines) == 1 and result.lines[0]["recipient_name"] == "ТОО «Ромашка»"


def test_onec_without_any_payer_account_says_so_instead_of_zero_debits():
    """Ни у одного документа нет счёта плательщика — не молчаливые «0
    списаний», а строка ошибки: списание не отличить от поступления."""
    docs = [common.onec_doc("1", "05.09.2026", "10.00", ""),
            common.onec_doc("2", "06.09.2026", "20.00", "")]
    result = onec.parse(common.onec_bytes(OWN, docs), account=ACCOUNT)
    assert (result.rows_total, result.lines) == (2, [])
    assert result.errors == [onec.NO_PAYER]
    assert "нет счёта плательщика" in onec.NO_PAYER
    # Хоть у одного документа плательщик есть — строки ошибки нет.
    docs.append(common.onec_doc("3", "06.09.2026", "30.00", OTHER))
    assert onec.parse(common.onec_bytes(OWN, docs), account=ACCOUNT).errors == []


def test_onec_malformed_credit_or_foreign_payment_is_not_a_row_error():
    """Поступление и платёж чужого счёта не загружаются — их битая дата,
    сумма или пустой номер ошибкой строки не считаются: исправлять то, что
    в базу не попало бы всё равно, некому. Ошибки — только у списаний
    своего счёта."""
    docs = [common.onec_doc("1", "31.02.2026", "100.00", OTHER, recipient_iban=OWN),
            common.onec_doc("2", "05.09.2026", "сто", OTHER),
            common.onec_doc("", "05.09.2026", "10.00", OTHER),
            common.onec_doc("4", "05.09.2026", "1e20", OTHER),
            common.onec_doc("5", "31.02.2026", "50.00", OWN),
            common.onec_doc("6", "06.09.2026", "60.00", OWN)]
    content = common.onec_bytes(OWN, docs)
    result = onec.parse(content, account=ACCOUNT)
    assert result.rows_total == 6
    assert [line["doc_number"] for line in result.lines] == ["6"]
    # Строка «Дата=31.02.2026» — первая у поступления, вторая у списания.
    lines = content.decode("cp1251").split("\r\n")
    own_bad = [n for n, text in enumerate(lines, start=1) if text == "Дата=31.02.2026"][1]
    assert result.errors == [f"Строка {own_bad}: не распознана дата „31.02.2026“"]


def test_onec_document_without_payer_keeps_its_row_errors():
    """Плательщика нет — списание ли это, не понять: ошибки такого
    документа показываются, а сам он (и исправный без плательщика) не
    загружается."""
    docs = [common.onec_doc("1", "31.02.2026", "10.00", ""),
            common.onec_doc("2", "05.09.2026", "20.00", ""),
            common.onec_doc("3", "05.09.2026", "30.00", OWN)]
    content = common.onec_bytes(OWN, docs)
    result = onec.parse(content, account=ACCOUNT)
    assert [line["doc_number"] for line in result.lines] == ["3"]
    assert result.errors == [f"Строка {_line_of(content, 'Дата=31.02.2026')}: "
                             f"не распознана дата „31.02.2026“"]


@pytest.mark.parametrize("raw", ["100000000000000000000", "10000000000000000.00",
                                 "9999999999999999.995"])
def test_onec_amount_too_large_is_a_row_error(raw):
    """Сумма, которую не вместит ``numeric(18, 2)`` строки выписки, — ошибка
    строки «сумма слишком большая», а не отказ всей выписки при записи."""
    docs = [common.onec_doc("1", "05.09.2026", raw, OWN),
            common.onec_doc("2", "05.09.2026", "9999999999999999.99", OWN)]
    content = common.onec_bytes(OWN, docs)
    result = onec.parse(content, account=ACCOUNT)
    assert [line["amount"] for line in result.lines] == [Decimal("9999999999999999.99")]
    assert result.errors == [
        f"Строка {_line_of(content, f'Сумма={raw}')}: сумма слишком большая „{raw}“ — "
        f"в сумме не больше 16 цифр до запятой"]

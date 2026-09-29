"""Шаблоны выписок: колонки по заголовку и предпросмотр образца (ТЗ §11.3
п.1, задача A3.1; Review Focus 3).

Разбор не ходит в базу: шаблон — несохранённый экземпляр модели, файл —
собранный в тесте. Ручка предпросмотра проверяется в конце, уже с базой.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

import pytest
from django.test import Client

from apps.bpp.services.bank import settings as bank_settings
from apps.bpp.services.bank import templates
from apps.bpp.tests import stage2 as s
from htqweb.errors import DomainError
from htqweb.tenancy.db import use_company

from . import common

H = common.HEADERS


def _error(fn, *args, **kwargs) -> DomainError:
    with pytest.raises(DomainError) as exc:
        fn(*args, **kwargs)
    return exc.value


# ── колонки по заголовку ────────────────────────────────────────────────

def test_resolve_columns_ignores_case_spaces_and_extra_columns():
    header = ["  назначение   ПЛАТЕЖА ", "Лишняя", "СУММА", "дата операции", None,
              "№  документа", 17]
    found = templates.resolve_columns(header, common.template())
    assert found == {"purpose": 0, "amount": 2, "date": 3, "doc_number": 5}


def test_template_reads_columns_by_header_in_any_order():
    """Колонки в файле — в порядке, отличном от шаблона, плюс лишние: поля
    находятся по заголовку, лишние колонки не мешают."""
    upload = common.xlsx_file([
        ["Остаток", H["purpose"], H["amount"], "Код", H["doc_number"], H["date"],
         H["recipient_bin"], H["recipient_name"]],
        ["x", "Оплата по счёту СЧ-2026-000017", -125000.5, "K1", "17", "05.09.2026",
         "123456789012", "ТОО «Альфа»"],
    ])
    result = templates.preview(upload, common.template())
    assert result["errors"] == []
    assert result["header_row"] == 1
    [row] = result["rows"]
    assert row["row_no"] == 2
    assert row["date"] == date(2026, 9, 5)
    assert row["doc_number"] == "17"
    assert row["amount"] == Decimal("125000.50") and row["direction"] == "debit"
    assert row["purpose"] == "Оплата по счёту СЧ-2026-000017"
    assert row["recipient_bin"] == "123456789012"
    assert row["recipient_name"] == "ТОО «Альфа»"
    by_field = {c["field"]: c for c in result["columns"]}
    assert by_field["amount"]["index"] == 2 and by_field["amount"]["header"] == H["amount"]
    assert by_field["date"]["label"] == "Дата"


def test_template_header_in_fourth_row():
    """Шапка банка над таблицей: заголовок в 4-й строке находится."""
    upload = common.xlsx_file([
        ["Выписка по счёту KZ00 0000 0000 0000 0000"],
        ["за период 01.09.2026 — 30.09.2026"],
        [],
        [H["date"], H["doc_number"], H["amount"], H["purpose"]],
        ["01.09.2026", "5", "-1000", "Аренда"],
    ])
    result = templates.preview(upload, common.template())
    assert result["header_row"] == 4
    assert [r["row_no"] for r in result["rows"]] == [5]


def test_template_header_found_up_to_row_thirty_not_beyond():
    """Заголовок ищется в первых HEADER_SCAN_ROWS = 30 строках: в 30-й
    находится, в 31-й — уже E-IMP-02."""
    header = [H["date"], H["doc_number"], H["amount"], H["purpose"]]
    data = ["01.09.2026", "5", "-1000", "Аренда"]
    filler = [[f"Шапка банка, строка {n}"] for n in range(1, templates.HEADER_SCAN_ROWS)]
    at_30 = templates.preview(common.xlsx_file([*filler, header, data]), common.template())
    assert at_30["header_row"] == templates.HEADER_SCAN_ROWS == 30
    assert [r["doc_number"] for r in at_30["rows"]] == ["5"]

    at_31 = common.xlsx_file([*filler, ["Ещё строка шапки"], header, data])
    err = _error(templates.preview, at_31, common.template())
    assert err.code == "E-IMP-02" and "первых 30 строках" in err.message


def test_headers_match_despite_yo_and_nbsp():
    """«ё» = «е», неразрывный пробел — тот же пробел, регистр не важен."""
    tpl = common.template(columns={**H, "doc_number": "Номер платёжки",
                                   "purpose": "Назначение платежа"})
    upload = common.xlsx_file([
        ["Дата операции", "НОМЕР ПЛАТЕЖКИ", H["amount"], "Назначение платёжа"],
        ["01.09.2026", "5", "-1000", "Аренда"],
    ])
    result = templates.preview(upload, tpl)
    assert result["errors"] == [] and [r["doc_number"] for r in result["rows"]] == ["5"]
    by_field = {c["field"]: c["index"] for c in result["columns"]}
    assert (by_field["date"], by_field["doc_number"], by_field["purpose"]) == (0, 1, 3)


def test_template_missing_required_column_is_e_imp_02_with_its_name():
    upload = common.xlsx_file([
        [H["date"], H["doc_number"], H["amount"], "Комментарий"],
        ["01.09.2026", "5", "-1000", "Аренда"],
    ])
    err = _error(templates.preview, upload, common.template())
    assert err.code == "E-IMP-02" and err.status == 422
    assert "«Назначение платежа»" in err.message
    assert err.fields == [{"field": "purpose", "message": "Назначение платежа"}]


def test_template_split_mode_needs_both_debit_and_credit():
    columns = {k: v for k, v in H.items() if k != "amount"}
    tpl = common.template(amount_mode="split", columns={**columns, "debit": "Дебет"})
    upload = common.xlsx_file([[H["date"], H["doc_number"], "Дебет", "Кредит", H["purpose"]]])
    err = _error(templates.preview, upload, tpl)
    assert err.code == "E-IMP-02"  # в шаблоне нет «Кредита» — сумма не читается


# ── суммы и даты ────────────────────────────────────────────────────────

@pytest.mark.parametrize(("raw", "expected"), [
    ("1 250 000,00", Decimal("1250000.00")),
    ("1 250 000,5", Decimal("1250000.50")),
    ("-1 250 000.10", Decimal("-1250000.10")),
    ("1,250,000.10", Decimal("1250000.10")),
    ("1.250.000,10", Decimal("1250000.10")),
    (1250000.1, Decimal("1250000.10")),
    (0.1 + 0.2, Decimal("0.30")),
    (1250000, Decimal("1250000.00")),
    (Decimal("10.005"), Decimal("10.01")),
])
def test_parse_amount_gives_decimal_without_float_loss(raw, expected):
    value = templates.parse_amount(raw)
    assert isinstance(value, Decimal) and value == expected
    assert value.as_tuple().exponent == -2


@pytest.mark.parametrize("raw", ["abc", "1,2,3.4.5", "--5", True])
def test_parse_amount_rejects_garbage(raw):
    with pytest.raises(ValueError):
        templates.parse_amount(raw)


@pytest.mark.parametrize("raw", [1e20, 10 ** 16, "10 000 000 000 000 000,00",
                                 Decimal("-10000000000000000"), "9999999999999999,995",
                                 Decimal("1E+30")])
def test_parse_amount_over_sixteen_integer_digits_is_too_large(raw):
    """``numeric(18, 2)`` строки выписки — 16 цифр до запятой: больше (в
    том числе после округления) — ``AmountTooLarge``, наследник
    ``ValueError``."""
    with pytest.raises(templates.AmountTooLarge):
        templates.parse_amount(raw)
    assert templates.parse_amount("9 999 999 999 999 999,99") == Decimal("9999999999999999.99")
    assert templates.parse_amount(-999999999999999.5) == Decimal("-999999999999999.50")


def test_amount_too_large_is_a_row_error_not_a_failed_statement():
    """Числовая ячейка 1E+20 распознаётся, но в столбец не влезет: ошибка
    строки «сумма слишком большая» — и в режиме ``signed``, и в дебете или
    кредите ``split``; остальные строки читаются."""
    upload = common.xlsx_file([
        [H["date"], H["doc_number"], H["amount"], H["purpose"]],
        ["01.09.2026", "1", -1e20, "Опечатка"],
        ["01.09.2026", "2", "-100", "Обычная"],
    ])
    result = templates.preview(upload, common.template())
    assert [r["doc_number"] for r in result["rows"]] == ["2"]
    assert result["errors"] == [
        "Строка 2: сумма слишком большая „-1e+20“ — в сумме не больше 16 цифр до запятой"]

    upload = common.xlsx_file([
        [H["date"], H["doc_number"], "Дебет", "Кредит", H["purpose"]],
        ["01.09.2026", "1", None, "100000000000000000", "Кредит"],
        ["01.09.2026", "2", "1 000,00", None, "Списание"],
    ])
    result = templates.preview(upload, _split_template())
    assert [r["doc_number"] for r in result["rows"]] == ["2"]
    assert result["errors"] == [
        "Строка 2: сумма слишком большая „100000000000000000“ — в сумме не больше 16 цифр "
        "до запятой"]


def test_template_amount_string_and_float_cell_both_exact():
    """Review Focus 3: «1 250 000,00» строкой и 1250000.1 числом ячейки."""
    upload = common.xlsx_file([
        [H["date"], H["doc_number"], H["amount"], H["purpose"]],
        ["01.09.2026", "1", "-1 250 000,00", "Первая"],
        [datetime(2026, 9, 2, 10, 15), 2, -1250000.1, "Вторая"],
    ])
    rows = templates.preview(upload, common.template())["rows"]
    assert [r["amount"] for r in rows] == [Decimal("1250000.00"), Decimal("1250000.10")]
    assert rows[1]["date"] == date(2026, 9, 2)  # ячейка-дата с временем
    assert rows[1]["doc_number"] == "2"         # число — строкой, без «.0»


def test_bad_date_goes_to_errors_other_rows_stay():
    upload = common.xlsx_file([
        [H["date"], H["doc_number"], H["amount"], H["purpose"]],
        ["01.09.2026", "1", "-100", "Первая"],
        ["31.02.2026", "2", "-200", "Вторая"],
        ["", "", "", ""],                       # пустая строка — не ошибка
        ["03.09.2026 12:00:00", "3", "сто", "Третья"],
        ["04.09.2026", "4", "-400", "Четвёртая"],
    ])
    result = templates.preview(upload, common.template())
    assert [r["doc_number"] for r in result["rows"]] == ["1", "4"]
    assert result["errors"] == [
        "Строка 3: не распознана дата „31.02.2026“",
        "Строка 5: не распознана сумма „сто“",
    ]


def test_signed_positive_is_credit_split_reads_debit_and_credit():
    upload = common.xlsx_file([[H["date"], H["doc_number"], H["amount"], H["purpose"]],
                               ["01.09.2026", "1", "500", "Поступление"]])
    [row] = templates.preview(upload, common.template())["rows"]
    assert row["direction"] == "credit" and row["amount"] == Decimal("500.00")

    columns = {k: v for k, v in H.items() if k != "amount"}
    tpl = common.template(amount_mode="split",
                          columns={**columns, "debit": "Дебет", "credit": "Кредит"})
    upload = common.xlsx_file([
        [H["date"], H["doc_number"], "Дебет", "Кредит", H["purpose"]],
        ["01.09.2026", "1", "1 000,00", "0", "Списание"],
        ["01.09.2026", "2", None, "300", "Поступление"],
    ])
    rows = templates.preview(upload, tpl)["rows"]
    assert [(r["direction"], r["amount"]) for r in rows] == [
        ("debit", Decimal("1000.00")), ("credit", Decimal("300.00"))]


def _split_template():
    columns = {k: v for k, v in H.items() if k != "amount"}
    return common.template(amount_mode="split",
                           columns={**columns, "debit": "Дебет", "credit": "Кредит"})


def test_split_negative_debit_is_taken_by_modulus_and_both_filled_is_an_error():
    upload = common.xlsx_file([
        [H["date"], H["doc_number"], "Дебет", "Кредит", H["purpose"]],
        ["01.09.2026", "1", "-1 000,00", None, "Списание с минусом"],
        ["01.09.2026", "2", "500", "300", "Обе колонки"],
        ["01.09.2026", "3", None, -200, "Кредит с минусом"],
    ])
    result = templates.preview(upload, _split_template())
    assert [(r["doc_number"], r["direction"], r["amount"]) for r in result["rows"]] == [
        ("1", "debit", Decimal("1000.00")), ("3", "credit", Decimal("200.00"))]
    assert result["errors"] == [
        "Строка 3: сумма и в дебете, и в кредите — у операции должна быть одна"]


def test_signed_zero_amount_is_a_row_error():
    upload = common.xlsx_file([
        [H["date"], H["doc_number"], H["amount"], H["purpose"]],
        ["01.09.2026", "1", "0,00", "Ноль"],
        ["01.09.2026", "2", 0, "Ноль числом"],
        ["01.09.2026", "3", "-10", "Обычная"],
    ])
    result = templates.preview(upload, common.template())
    assert [r["doc_number"] for r in result["rows"]] == ["3"]
    assert result["errors"] == ["Строка 2: нулевая сумма", "Строка 3: нулевая сумма"]


def test_rows_without_date_number_and_amount_are_skipped_but_totals_are_errors():
    """Подвал банка («Остаток на конец дня») — не операция и не ошибка;
    «Итого» с суммой, но без номера документа — ошибка строки: деньги в
    ней есть, молча терять их нельзя."""
    upload = common.xlsx_file([
        [H["date"], H["doc_number"], H["amount"], H["purpose"]],
        ["01.09.2026", "1", "-100", "Первая"],
        [None, None, None, "Остаток на конец дня: 1 000 000,00"],
        ["", "  ", "", "Подпись ответственного"],
        ["Итого", None, "-100", None],
        [None, None, "-100", "Итого за период"],
    ])
    result = templates.preview(upload, common.template())
    assert [r["doc_number"] for r in result["rows"]] == ["1"]
    assert result["errors"] == [
        "Строка 5: не распознана дата „Итого“",
        "Строка 6: не распознана дата „“",
    ]


def test_numeric_bin_keeps_its_leading_zero():
    """БИН 050140000656 в числовой ячейке xlsx приходит числом 50140000656:
    ведущий ноль возвращается дополнением до 12 цифр."""
    upload = common.xlsx_file([
        [H["date"], H["doc_number"], H["amount"], H["purpose"], H["recipient_bin"]],
        ["01.09.2026", "1", "-100", "Число", 50140000656],
        ["01.09.2026", "2", "-100", "Дробь с нулём", 50140000656.0],
        ["01.09.2026", "3", "-100", "Текст", "050140000656"],
        ["01.09.2026", "4", "-100", "Пусто", None],
    ])
    rows = templates.preview(upload, common.template())["rows"]
    assert [r["recipient_bin"] for r in rows] == [
        "050140000656", "050140000656", "050140000656", ""]


def test_date_mask_to_pattern():
    assert templates.date_pattern("ДД.ММ.ГГГГ") == "%d.%m.%Y"
    assert templates.date_pattern("ГГГГ-ММ-ДД") == "%Y-%m-%d"
    assert templates.date_pattern("DD/MM/YY") == "%d/%m/%y"
    with pytest.raises(ValueError):
        templates.date_pattern("ММ.ГГГГ")  # без дня


def test_preview_stops_at_twenty_rows():
    rows = [[H["date"], H["doc_number"], H["amount"], H["purpose"]]]
    rows += [["01.09.2026", str(n), "-1", "П"] for n in range(1, 40)]
    result = templates.preview(common.xlsx_file(rows), common.template())
    assert len(result["rows"]) == templates.PREVIEW_ROWS == 20


# ── CSV и формат файла ──────────────────────────────────────────────────

def test_csv_reads_with_template_delimiter_and_encoding():
    tpl = common.template(format="csv", encoding="cp1251", delimiter=";")
    upload = common.csv_file([
        ["Отчёт банка"],
        [H["purpose"], H["date"], H["amount"], H["doc_number"]],
        ["Оплата «Альфа»", "05.09.2026", "-1 250 000,00", "88"],
    ])
    result = templates.preview(upload, tpl)
    assert result["header_row"] == 2 and result["errors"] == []
    [row] = result["rows"]
    assert row["purpose"] == "Оплата «Альфа»" and row["amount"] == Decimal("1250000.00")


def test_csv_in_wrong_encoding_is_e_imp_01():
    tpl = common.template(format="csv", encoding="utf-8")
    upload = common.csv_file([[H["date"], "Назначение"]], encoding="cp1251")
    assert _error(templates.preview, upload, tpl).code == "E-IMP-01"


def test_csv_with_utf8_bom_reads_even_with_cp1251_template():
    """Excel сохраняет CSV «UTF-8 с BOM» и там, где шаблон банка — cp1251:
    BOM — признак UTF-8, и к первому заголовку он не прилипает."""
    tpl = common.template(format="csv", encoding="cp1251", delimiter=";")
    upload = common.csv_file([
        [H["date"], H["doc_number"], H["amount"], H["purpose"]],
        ["05.09.2026", "88", "-1 250 000,00", "Оплата «Альфа»"],
    ], encoding="utf-8-sig")
    assert upload.read().startswith(b"\xef\xbb\xbf")
    result = templates.preview(upload, tpl)
    assert result["header_row"] == 1 and result["errors"] == []
    [row] = result["rows"]
    assert row["purpose"] == "Оплата «Альфа»" and row["amount"] == Decimal("1250000.00")


def test_extension_must_match_template_format():
    upload = common.xlsx_file([[H["date"]]], name="vypiska.pdf")
    err = _error(templates.preview, upload, common.template())
    assert err.code == "E-IMP-01"
    assert err.message == ("Файл не соответствует формату Excel: нужен файл .xlsx. "
                           "Выберите другой формат или файл.")
    assert err.fields == [{"field": "file", "message": err.message}]

    csv_tpl = common.template(format="csv", encoding="cp1251")
    err = _error(templates.preview, common.xlsx_file([[H["date"]]]), csv_tpl)
    assert err.message == ("Файл не соответствует формату CSV: нужен файл .csv или .txt. "
                           "Выберите другой формат или файл.")


def test_broken_xlsx_is_e_imp_01():
    from django.core.files.uploadedfile import SimpleUploadedFile

    upload = SimpleUploadedFile("vypiska.xlsx", b"not a zip at all")
    assert _error(templates.preview, upload, common.template()).code == "E-IMP-01"


def test_xlsx_with_truncated_sheet_is_e_imp_01_not_500():
    """Архив цел, а XML листа оборван: openpyxl падает не при открытии, а
    на чтении строк (``ParseError``) — это тоже E-IMP-01."""
    rows = [[H["date"], H["doc_number"], H["amount"], H["purpose"]]]
    # Строк меньше PREVIEW_ROWS: предпросмотр дочитывает до обрыва.
    rows += [["01.09.2026", str(n), "-1", "Оплата"] for n in range(1, 10)]
    err = _error(templates.preview, common.truncated_xlsx(rows), common.template())
    assert err.code == "E-IMP-01" and "Excel" in err.message


def test_xlsx_unpacked_size_is_capped(monkeypatch):
    """Zip-бомба: объявленный распакованный размер больше потолка — E-IMP-01
    до открытия книги. Потолок в тесте опущен до нуля: любая книга больше."""
    monkeypatch.setattr(templates, "XLSX_UNPACKED_MAX_MB", 0)
    upload = common.xlsx_file([[H["date"], H["doc_number"], H["amount"], H["purpose"]]])
    err = _error(templates.preview, upload, common.template())
    assert err.code == "E-IMP-01" and "после распаковки больше 0 МБ" in err.message


def test_onec_template_has_no_preview():
    """Решение задачи 2: предпросмотр — для Excel и CSV; 1С разбирается по
    стандарту формата (задача 3), колонок шаблона у неё нет."""
    tpl = common.template(format="onec", columns={})
    upload = common.csv_file([["1CClientBankExchange"]], name="kl_to_1c.txt")
    err = _error(templates.preview, upload, tpl)
    assert err.code == "E-VAL-01" and err.status == 422


# ── ручка предпросмотра ────────────────────────────────────────────────

ADM, FD, TD, BUH = 941, 942, 943, 944
BASE = "/api/bpp/v1/bank/templates"


@pytest.fixture
def slug(company_context):
    slug = company_context["slug"]
    s.grant(slug, ADM, "bpp-adm")
    s.grant(slug, FD, "bpp-fd")
    s.grant(slug, TD, "bpp-td")
    s.grant(slug, BUH, "bpp-buh")
    return slug


def _headers(slug, user_id):
    headers = s.auth(slug, user_id)
    headers.pop("content_type")  # multipart ставит клиент сам
    return headers


@pytest.mark.django_db
def test_preview_handle_returns_money_as_string_and_saves_nothing(slug):
    tpl = bank_settings.create_template(
        {"name": "Банк Excel", "format": "xlsx", "columns": dict(H)}, actor_id=ADM)
    upload = common.xlsx_file([[H["date"], H["doc_number"], H["amount"], H["purpose"]],
                               ["01.09.2026", "1", -1250000.1, "Оплата"]])
    client = Client()
    response = client.post(f"{BASE}/{tpl.pk}/preview", {"file": upload},
                           **_headers(slug, FD))
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["rows"][0]["amount"] == "1250000.10"
    assert body["rows"][0]["date"] == "2026-09-01"
    with use_company(slug):  # запрос вернул search_path в public
        tpl.refresh_from_db()
    assert tpl.version == 1

    # ТД не видит ни счетов, ни шаблонов.
    upload.seek(0)
    denied = client.post(f"{BASE}/{tpl.pk}/preview", {"file": upload}, **_headers(slug, TD))
    assert denied.status_code == 403 and denied.json()["code"] == "E-ACC-01"


@pytest.mark.django_db
def test_preview_handle_without_file_is_422(slug):
    tpl = bank_settings.create_template(
        {"name": "Банк Excel", "format": "xlsx", "columns": dict(H)}, actor_id=ADM)
    response = Client().post(f"{BASE}/{tpl.pk}/preview", {}, **_headers(slug, ADM))
    assert response.status_code == 422 and response.json()["code"] == "E-VAL-01"
    assert json.loads(response.content)["fields"][0]["field"] == "file"


@pytest.mark.django_db
def test_fd_and_buh_cannot_create_templates(slug):
    """Шаблоны настраивает АДМ (ТЗ §11.1): ФД справочник только видит
    (``bpp.settings:view``), БУХ — только читает для загрузки выписки."""
    from apps.bpp.models.bank import StatementTemplate

    body = json.dumps({"name": "Свой шаблон", "format": "xlsx", "columns": dict(H)})
    client = Client()
    for user_id in (FD, BUH):
        denied = client.post(BASE, body, **s.auth(slug, user_id))
        assert denied.status_code == 403, (user_id, denied.content)
        assert denied.json()["code"] == "E-ACC-01"
    with use_company(slug):  # запрос вернул search_path в public
        assert not StatementTemplate.objects.exists()
    allowed = client.post(BASE, body, **s.auth(slug, ADM))
    assert allowed.status_code == 201, allowed.json()
    with use_company(slug):  # и проверка выше смотрела в нужную схему
        assert StatementTemplate.objects.count() == 1

"""Загрузка книги CashFlow.xlsx в модели — сквозные проверки с БД.

Книга собирается здесь же, openpyxl'ом, из тех же строк, что лежат в файле
заказчика. Своей копии .xlsx в репозитории нет намеренно: тест обязан
объяснять, ЧТО именно в данных проверяется, а бинарный файл этого не
показывает, и правится он только Excel'ем.
"""

from decimal import Decimal

import pytest

from apps.contracts.models import (
    Administrator,
    Agreement,
    AgreementStatus,
    AgreementType,
    Budget,
    BudgetLine,
    Counterparty,
    PaymentType,
    Program,
)
from apps.contracts.services import cashflow_import as cf

openpyxl = pytest.importorskip("openpyxl")


# ── Сборка книги ────────────────────────────────────────────────────────

BUDGET_HEADER = ["Администратор бюджета", "Бюджетная программа", "Лимит", "Валюта"]

# Заголовок реестра: 13 подписей и БЕЗЫМЯННАЯ четырнадцатая — та самая
# колонка N с настоящей длиной БИН. Пустая ячейка здесь не случайность, а
# воспроизведение книги: колонка адресуется только положением.
REGISTRY_HEADER = [
    "Администратор бюджета", "Код программы", "Программа", "Номер договора",
    "Наименование договора", "Контрагент", "БИН/ИИН", "Сумма договор",
    "Аванс (ТИП ОПЛАТЫ)", "Дата подписания", "Вид", "Тип",
    "Идентификатор LARK", None,
]

ARALSK = "QAZAQSTAN-Aralsk"
DAMONA = "QAZAQSTAN-Damona"


def registry_row(*, admin=ARALSK, code="3021", program="Трекерная система",
                 number="DOC-1", name="Монтаж", counterparty="ИП «Иманбетов»",
                 bin_iin="890406300239", amount=1000, advance="0",
                 signed=46196, kind="РиУ", type_="стандарт", lark="202606190002",
                 bin_length=12):
    return [admin, code, program, number, name, counterparty, bin_iin, amount,
            advance, signed, kind, type_, lark, bin_length]


def build_book(tmp_path, *, budget_rows, registry_rows, name="CashFlow.xlsx"):
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)

    budget = workbook.create_sheet(cf.SHEET_BUDGET)
    budget.append(BUDGET_HEADER)
    for row in budget_rows:
        budget.append(row)

    registry = workbook.create_sheet(cf.SHEET_REGISTRY)
    registry.append(REGISTRY_HEADER)
    for row in registry_rows:
        registry.append(row)

    path = tmp_path / name
    workbook.save(path)
    return str(path)


DEFAULT_BUDGET = [
    [ARALSK, "3021 Монтаж Трекерной системы", 63741398, "KZT"],
    [ARALSK, "3020 Сопровождение проекта", 21414971, "KZT"],
    [DAMONA, "3011 Сопровождение проекта", 10000000, "KZT"],
]


# ── Счастливый путь ─────────────────────────────────────────────────────

@pytest.mark.django_db
def test_reference_data_and_agreement_are_created(tmp_path):
    path = build_book(tmp_path, budget_rows=DEFAULT_BUDGET,
                      registry_rows=[registry_row(amount=60554327.85, advance="0")])

    report = cf.run_import(path)

    assert report.rows_read == 1
    agreement = Agreement.objects.get()
    assert agreement.number == "DOC-1"
    assert agreement.amount == Decimal("60554327.85")
    assert agreement.currency == "KZT"
    assert agreement.status == AgreementStatus.SIGNED
    assert agreement.signed_date.isoformat() == "2026-06-23"
    assert agreement.external_id == "202606190002"

    # Строка бюджета — та, что названа кодом программы у этого администратора.
    assert agreement.budget_line.program.code == "3021"
    assert agreement.budget_line.amount == Decimal("63741398.00")
    assert agreement.budget_line.budget.administrator.project_name == ARALSK
    assert agreement.budget_line.budget.period_year == 2026


@pytest.mark.django_db
def test_year_comes_from_latest_signing_date(tmp_path):
    # Года в книге нет ни одной колонкой. Брать текущий нельзя: файл
    # прошлого года завёл бы бюджеты не того периода.
    path = build_book(tmp_path, budget_rows=DEFAULT_BUDGET, registry_rows=[
        registry_row(number="A", lark="1", signed=46080),   # 2026-02-27
        registry_row(number="B", lark="2", signed=46272),   # 2026-09-07
    ])
    cf.run_import(path)
    assert {b.period_year for b in Budget.objects.all()} == {2026}


@pytest.mark.django_db
def test_explicit_year_overrides_dates(tmp_path):
    path = build_book(tmp_path, budget_rows=DEFAULT_BUDGET,
                      registry_rows=[registry_row()])
    cf.run_import(path, year=2025)
    assert Budget.objects.filter(period_year=2025).exists()


# ── Ведущий ноль в БИН ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_bin_is_padded_from_unnamed_length_column(tmp_path):
    path = build_book(tmp_path, budget_rows=DEFAULT_BUDGET, registry_rows=[
        registry_row(counterparty="ТОО «Снабкомплект Монтаж»",
                     bin_iin="80340019927", bin_length=11),
    ])
    cf.run_import(path)
    assert Counterparty.objects.get().bin_iin == "080340019927"


# ── Повторяющиеся номера ────────────────────────────────────────────────

@pytest.mark.django_db
def test_duplicate_numbers_are_suffixed_with_dots(tmp_path):
    # В книге номер «1» носят три РАЗНЫХ договора разных контрагентов.
    path = build_book(tmp_path, budget_rows=DEFAULT_BUDGET, registry_rows=[
        registry_row(number="1", lark="a", counterparty="ИП «Arsen»",
                     bin_iin="980711301185"),
        registry_row(number="1", lark="b", counterparty="ТОО «ОА Ер-Нұр»",
                     bin_iin="080640021107", bin_length=11),
        registry_row(number="1", lark="c", counterparty='ИП "Шахманов Н.Б."',
                     bin_iin="940204300381"),
    ])

    report = cf.run_import(path)

    assert sorted(Agreement.objects.values_list("number", flat=True)) == ["1", "1.", "1.."]
    # Молча переименовывать договор нельзя — по номеру его ищут глазами.
    assert sum("уже занят" in w for w in report.warnings) == 2


@pytest.mark.django_db
def test_existing_number_in_database_is_avoided(tmp_path):
    from .helpers import make_agreement, make_counterparty, make_line
    make_agreement(line=make_line(),
                   counterparty=make_counterparty(bin_iin="111111111111"),
                   number="1")

    path = build_book(tmp_path, budget_rows=DEFAULT_BUDGET,
                      registry_rows=[registry_row(number="1", lark="a")])
    cf.run_import(path)

    assert Agreement.objects.filter(external_id="a").get().number == "1."


# ── Открытые договоры ───────────────────────────────────────────────────

@pytest.mark.django_db
def test_open_contract_without_amount_loads_as_zero(tmp_path):
    path = build_book(tmp_path, budget_rows=DEFAULT_BUDGET, registry_rows=[
        registry_row(amount=None, type_="открытый", kind="ТМЦ", advance="100%"),
    ])

    report = cf.run_import(path)

    agreement = Agreement.objects.get()
    assert agreement.amount == Decimal("0.00")
    # Ноль читается как «суммы ещё нет» только вместе с этим признаком.
    assert agreement.contract_type == AgreementType.OPEN
    assert agreement.payment_type == PaymentType.PREPAYMENT
    assert agreement.advance_share == Decimal("1.000")
    assert not report.warnings


@pytest.mark.django_db
def test_standard_contract_without_amount_is_flagged(tmp_path):
    # Стандартный договор без суммы — это не «открытый», а пропуск в книге.
    path = build_book(tmp_path, budget_rows=DEFAULT_BUDGET,
                      registry_rows=[registry_row(amount=None, type_="стандарт")])

    report = cf.run_import(path)

    assert Agreement.objects.get().amount == Decimal("0.00")
    assert any("не помечен открытым" in w for w in report.warnings)


# ── Программы: ключ — код ───────────────────────────────────────────────

@pytest.mark.django_db
def test_same_name_different_codes_are_two_programs(tmp_path):
    # «Сопровождение проекта» — это и 3011, и 3020. Ключ по названию не
    # пустил бы вторую программу в базу.
    path = build_book(tmp_path, budget_rows=DEFAULT_BUDGET, registry_rows=[
        registry_row(admin=ARALSK, code="3020", program="Сопровождение проекта",
                     number="A", lark="1"),
        registry_row(admin=DAMONA, code="3011", program="Сопровождение проекта",
                     number="B", lark="2"),
    ])

    cf.run_import(path)

    codes = set(Program.objects.values_list("code", flat=True))
    assert {"3011", "3020"} <= codes
    assert Program.objects.filter(name="Сопровождение проекта").count() == 2


@pytest.mark.django_db
def test_program_name_from_budget_sheet_expense_item_from_registry(tmp_path):
    # Длинное название есть только в «Бюджете», короткое — только в реестре.
    path = build_book(tmp_path, budget_rows=DEFAULT_BUDGET,
                      registry_rows=[registry_row(code="3021",
                                                  program="Трекерная система")])
    cf.run_import(path)

    program = Program.objects.get(code="3021")
    assert program.name == "Монтаж Трекерной системы"
    assert program.expense_item == "Трекерная система"
    assert program.display_name == "3021 Монтаж Трекерной системы"


# ── Строки бюджета, которых нет на листе лимитов ────────────────────────

@pytest.mark.django_db
def test_missing_budget_line_is_created_with_zero_limit(tmp_path):
    path = build_book(tmp_path, budget_rows=DEFAULT_BUDGET, registry_rows=[
        registry_row(admin="Офис управления проектами Hi-Tech Group",
                     code="112", program="Строительство МСЭС Б.Момышулы",
                     amount=38000000),
    ])

    report = cf.run_import(path)

    line = Agreement.objects.get().budget_line
    assert line.amount == Decimal("0.00")
    assert "лимит" in line.note
    # Нулевой лимит значит, что весь договор лежит вне бюджета — это обязан
    # увидеть человек, а не только база.
    assert any("нулевым лимитом" in w for w in report.warnings)


# ── Контрагенты ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_counterparty_is_keyed_by_bin_not_name(tmp_path):
    path = build_book(tmp_path, budget_rows=DEFAULT_BUDGET, registry_rows=[
        registry_row(number="A", lark="1", counterparty="ТОО «Арал құрылысы»",
                     bin_iin="50140002157", bin_length=11),
        registry_row(number="B", lark="2", counterparty="ТОО «Арал курылысы»",
                     bin_iin="50140002157", bin_length=11),
    ])

    report = cf.run_import(path)

    counterparty = Counterparty.objects.get()
    assert counterparty.bin_iin == "050140002157"
    # Побеждает первое написание, второе — в отчёт: выбирать правильное за
    # финансистов импорт не вправе.
    assert counterparty.name == "ТОО «Арал құрылысы»"
    assert any("несколько написаний" in w for w in report.warnings)


# ── Перерасход ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_overrun_is_loaded_and_reported(tmp_path):
    # Импорт переносит уже случившийся факт: остановиться на перерасходе
    # значило бы не дать перенести реальность. Но и промолчать нельзя.
    path = build_book(tmp_path,
                      budget_rows=[[DAMONA, "3011 Сопровождение проекта", 10000000, "KZT"]],
                      registry_rows=[registry_row(admin=DAMONA, code="3011",
                                                  program="Сопровождение проекта",
                                                  amount=169262362)])

    report = cf.run_import(path)

    assert Agreement.objects.get().amount == Decimal("169262362.00")
    assert any("перерасход" in o for o in report.overruns)


# ── Повторный прогон ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_second_run_updates_instead_of_duplicating(tmp_path):
    rows = [
        registry_row(number="1", lark="a", counterparty="ИП «Arsen»",
                     bin_iin="980711301185"),
        registry_row(number="1", lark="b", counterparty="ИП «TECH SERVICE»",
                     bin_iin="920203400735"),
    ]
    path = build_book(tmp_path, budget_rows=DEFAULT_BUDGET, registry_rows=rows)

    cf.run_import(path)
    first = dict(Agreement.objects.values_list("external_id", "number"))

    report = cf.run_import(path)

    assert Agreement.objects.count() == 2
    assert Counterparty.objects.count() == 2
    assert report.created.get("Agreement", 0) == 0
    assert report.updated["Agreement"] == 2
    # Точки, выданные первым прогоном, обязаны пережить второй: иначе ссылка
    # на договор менялась бы от запуска к запуску.
    assert dict(Agreement.objects.values_list("external_id", "number")) == first


@pytest.mark.django_db
def test_second_run_picks_up_changed_amount(tmp_path):
    path = build_book(tmp_path, budget_rows=DEFAULT_BUDGET,
                      registry_rows=[registry_row(amount=100)])
    cf.run_import(path)

    path = build_book(tmp_path, budget_rows=DEFAULT_BUDGET, name="CashFlow2.xlsx",
                      registry_rows=[registry_row(amount=250)])
    cf.run_import(path)

    assert Agreement.objects.get().amount == Decimal("250.00")


# ── Согласование ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_import_does_not_touch_approval_state(tmp_path):
    # Колонку ведёт движок signoff. Проставить «согласовано» в обход процесса
    # значило бы завести согласованный объект без единого решения.
    path = build_book(tmp_path, budget_rows=DEFAULT_BUDGET,
                      registry_rows=[registry_row()])
    cf.run_import(path)

    agreement = Agreement.objects.get()
    assert agreement.approval_state == "draft"
    assert agreement.budget_line.budget.approval_state == "draft"


# ── Сухой прогон ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_dry_run_writes_nothing_but_reports_everything(tmp_path):
    path = build_book(tmp_path, budget_rows=DEFAULT_BUDGET, registry_rows=[
        registry_row(number="1", lark="a"),
        registry_row(number="1", lark="b", counterparty="ИП «Arsen»",
                     bin_iin="980711301185"),
    ])

    report = cf.run_import(path, dry_run=True)

    assert Agreement.objects.count() == 0
    assert Counterparty.objects.count() == 0
    assert BudgetLine.objects.count() == 0
    assert Administrator.objects.count() == 0
    # Отчёт при этом полный — ради него сухой прогон и запускают.
    assert report.created["Agreement"] == 2
    assert any("уже занят" in w for w in report.warnings)


# ── Форма книги ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_missing_column_is_a_clear_error(tmp_path):
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    budget = workbook.create_sheet(cf.SHEET_BUDGET)
    budget.append(BUDGET_HEADER)
    registry = workbook.create_sheet(cf.SHEET_REGISTRY)
    registry.append([h for h in REGISTRY_HEADER if h != "БИН/ИИН"])
    path = tmp_path / "broken.xlsx"
    workbook.save(path)

    with pytest.raises(cf.CashflowImportError, match="БИН/ИИН"):
        cf.run_import(str(path))


@pytest.mark.django_db
def test_columns_are_found_by_header_not_position(tmp_path):
    # Книгу ведут руками: вставленная колонка не должна тихо начать грузить
    # наименование в номер.
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    budget = workbook.create_sheet(cf.SHEET_BUDGET)
    budget.append(BUDGET_HEADER)
    for row in DEFAULT_BUDGET:
        budget.append(row)

    registry = workbook.create_sheet(cf.SHEET_REGISTRY)
    registry.append(["Комментарий"] + REGISTRY_HEADER)
    registry.append(["чья-то заметка"] + registry_row(number="DOC-9", lark="z"))
    path = tmp_path / "shifted.xlsx"
    workbook.save(path)

    cf.run_import(str(path))

    assert Agreement.objects.get().number == "DOC-9"


@pytest.mark.django_db
def test_missing_sheet_is_a_clear_error(tmp_path):
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    workbook.create_sheet(cf.SHEET_BUDGET).append(BUDGET_HEADER)
    path = tmp_path / "no-registry.xlsx"
    workbook.save(path)

    with pytest.raises(cf.CashflowImportError, match=cf.SHEET_REGISTRY):
        cf.run_import(str(path))


@pytest.mark.django_db
def test_blank_trailing_rows_are_ignored(tmp_path):
    # В реальной книге лист тянется до 982-й строки, данных — 43.
    path = build_book(tmp_path, budget_rows=DEFAULT_BUDGET, registry_rows=[
        registry_row(),
        [None] * 14,
        [None] * 14,
    ])

    report = cf.run_import(path)

    assert report.rows_read == 1
    assert Agreement.objects.count() == 1

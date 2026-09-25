"""Загрузка листа «Операции» — счета по договорам и без, сквозь БД.

Книга собирается openpyxl'ом здесь же — в той же форме, что у заказчика:
строка секций над строкой заголовков, «БИН» дважды (в секции договора — с
потерянным нулём, в секции счёта — полный), колонка «Бюджет» то голым кодом,
то «код Название». Каждый тест закрывает особенность реальной книги.
"""

from decimal import Decimal

import pytest

from apps.contracts.models import (
    AdvancePaymentStatus,
    Agreement,
    BudgetLine,
    ContractPayment,
    Counterparty,
    Invoice,
    InvoiceStatus,
    Program,
)
from apps.contracts.services import budget_calc
from apps.contracts.services import cashflow_import as registry
from apps.contracts.services import cashflow_operations_import as ops

from .test_cashflow_import import BUDGET_HEADER, REGISTRY_HEADER, registry_row

openpyxl = pytest.importorskip("openpyxl")

ARALSK = "QAZAQSTAN-Aralsk"
DAMONA = "QAZAQSTAN-Damona"
ARAL30 = 'Команда управления проектом СЭС "Арал" 30Мвт'
OFFICE = "Офис управления проектами Hi-Tech Group"

SECTION_ROW = ["Договор", None, None, None, "АВР/Накладная"] + [None] * 13 + ["ЭСФ"]
OPS_HEADER = [
    "№", "Идентификатор договора (LARK)", "Контрагент", "БИН", "Администратор",
    "Договор", "АВР/НАКЛАДНАЯ", "№ документа", "Дата документа", "Сумма",
    "Наименование администратора программы", "Наличие договора", "Дата",
    "Сумма счета", "БИН", "Наименование поставщика", "Наименование ТРУ", "Бюджет",
    "№ ЭСФ", "Дата ЭСФ", "Связь с номером договора", "Связь с контрагентом",
]

BUDGET = [
    [ARALSK, "3020 Сопровождение проекта", 21414971, "KZT"],
    [ARALSK, "3026 Монтаж силовых-низковольных кабелей (LV)", 11599916, "KZT"],
    [DAMONA, "3011 Сопровождение проекта", 10000000, "KZT"],
]

# Открытый договор проживания — у него в книге четыре оплаты при нулевой сумме.
REGISTRY = [
    registry_row(admin=ARALSK, code="3020", program="Сопровождение проекта",
                 number="113-20-2026", name="Проживание и питание",
                 counterparty="ИП «Абулгазиев»", bin_iin="631031301177",
                 amount=None, type_="открытый", lark="L-OPEN"),
]


def op_row(*, kind="Без договора", lark=None, admin=DAMONA, date=46268,
           amount=100000, bin_iin="740605301794", supplier="ИП «Зайнеденов»",
           goods="Аренда экскаватора", budget="3011 Сопровождение проекта"):
    row = [None] * len(OPS_HEADER)
    row[0] = 1
    if kind == "По договору":
        # Секция договора: LARK и БИН — тот, что с потерянным нулём.
        row[1], row[2], row[3] = lark, supplier, bin_iin.lstrip("0")
    row[10], row[11], row[12], row[13] = admin, kind, date, amount
    row[14], row[15], row[16], row[17] = bin_iin, supplier, goods, budget
    return row


def by_agreement(**over):
    defaults = dict(kind="По договору", lark="L-OPEN", admin=ARALSK,
                    bin_iin="631031301177", supplier="ИП «Абулгазиев»",
                    goods="Проживание, июль", amount=1416000, budget=3020)
    return op_row(**{**defaults, **over})


def build_book(tmp_path, *, ops_rows, budget_rows=BUDGET, registry_rows=REGISTRY,
               ops_header=OPS_HEADER, name="CashFlow pr.xlsx"):
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    sheet = workbook.create_sheet(registry.SHEET_BUDGET)
    sheet.append(BUDGET_HEADER)
    for row in budget_rows:
        sheet.append(row)
    sheet = workbook.create_sheet(registry.SHEET_REGISTRY)
    sheet.append(REGISTRY_HEADER)
    for row in registry_rows:
        sheet.append(row)
    sheet = workbook.create_sheet(ops.SHEET_OPERATIONS)
    sheet.append(SECTION_ROW)
    sheet.append(ops_header)
    for row in ops_rows:
        sheet.append(row)
    path = tmp_path / name
    workbook.save(path)
    return str(path)


def load_both(path, **options):
    registry.run_import(path)
    return ops.run_import(path, **options)


def line_of(admin, code):
    return BudgetLine.objects.select_related("program").get(
        budget__administrator__project_name=admin, program__code=code)


# ── По договору → ContractPayment ───────────────────────────────────────

@pytest.mark.django_db
def test_payment_by_agreement_is_linked_through_lark(tmp_path):
    report = load_both(build_book(tmp_path, ops_rows=[by_agreement()]))

    payment = ContractPayment.objects.get()
    assert payment.agreement.external_id == "L-OPEN"
    assert payment.amount == Decimal("1416000.00")
    assert payment.status == AdvancePaymentStatus.CLOSED
    assert payment.document_date.isoformat() == "2026-09-03"
    assert payment.administrator == payment.agreement.budget_line.budget.administrator
    assert payment.external_id.startswith("ops:")
    assert not [w for w in report.warnings if "строка" in w]


@pytest.mark.django_db
def test_open_agreement_payment_reaches_the_budget(tmp_path):
    # Сумма открытого договора — ноль, но деньги по нему ушли, и остаток
    # программы обязан это показать.
    load_both(build_book(tmp_path, ops_rows=[by_agreement()]))
    assert budget_calc.committed_for(line_of(ARALSK, "3020").pk) == Decimal("1416000.00")


@pytest.mark.django_db
def test_unknown_agreement_is_reported_not_invented(tmp_path):
    report = load_both(build_book(tmp_path, ops_rows=[by_agreement(lark="NOPE")]))

    assert ContractPayment.objects.count() == 0
    assert any("«NOPE» не найден" in w for w in report.warnings)


@pytest.mark.django_db
def test_program_mismatch_is_reported_but_payment_stays_on_agreement(tmp_path):
    report = load_both(build_book(tmp_path, ops_rows=[by_agreement(budget=3026)]))

    payment = ContractPayment.objects.get()
    assert payment.agreement.budget_line.program.code == "3020"
    assert any("программа 3026" in w and "на программе 3020" in w for w in report.warnings)


# ── Без договора → Invoice ──────────────────────────────────────────────

@pytest.mark.django_db
def test_invoice_lands_on_administrator_and_code_line(tmp_path):
    load_both(build_book(tmp_path, ops_rows=[op_row()]))

    invoice = Invoice.objects.get()
    assert invoice.budget_line == line_of(DAMONA, "3011")
    assert invoice.status == InvoiceStatus.PAID
    assert invoice.currency == "KZT"
    assert invoice.name == "Аренда экскаватора"
    assert invoice.counterparty.bin_iin == "740605301794"
    # Счёт без договора в статусе «оплачен» — расход бюджета.
    assert budget_calc.committed_for(invoice.budget_line_id) == Decimal("100000.00")


@pytest.mark.django_db
def test_same_code_under_another_administrator_is_another_program(tmp_path):
    # 3026 у Аральска — «Кабели LV», у «Арал 30 МВт» — «Система заземления».
    # Поиск по одному коду положил бы счёт на чужую программу.
    report = load_both(build_book(tmp_path, ops_rows=[
        op_row(admin=ARAL30, budget="3026 Система заземления", goods="Заземлитель"),
    ]))

    invoice = Invoice.objects.get()
    assert invoice.budget_line.budget.administrator.project_name == ARAL30
    assert invoice.budget_line.program.name == "Система заземления"
    assert invoice.budget_line != line_of(ARALSK, "3026")
    assert Program.objects.filter(code="3026").count() == 2
    assert any("нулевым лимитом" in w for w in report.warnings)


@pytest.mark.django_db
def test_bare_code_is_resolved_through_budget_sheet_of_that_administrator(tmp_path):
    # Реестр не грузим: строки Аральск × 3026 в базе нет, и и название, и
    # лимит обязаны прийти с листа «Бюджет» — строки ИМЕННО этого
    # администратора.
    path = build_book(tmp_path, ops_rows=[op_row(admin=ARALSK, budget=3026, goods="Кабель")])
    ops.run_import(path)

    line = line_of(ARALSK, "3026")
    assert line.program.name == "Монтаж силовых-низковольных кабелей (LV)"
    assert line.amount == Decimal("11599916.00")
    assert Invoice.objects.get().budget_line == line


@pytest.mark.django_db
def test_bare_code_unknown_everywhere_is_skipped(tmp_path):
    # Код без названия, которого нет ни в базе, ни на листе «Бюджет»: из
    # чего завести программу — неизвестно, и выдумывать импорт не вправе.
    report = load_both(build_book(tmp_path, ops_rows=[op_row(admin=OFFICE, budget=111)]))

    assert Invoice.objects.count() == 0
    assert any("название взять неоткуда" in w for w in report.warnings)


@pytest.mark.django_db
def test_existing_line_limit_is_never_touched(tmp_path):
    # Лимиты правят финансисты; импорт расходов их не откатывает.
    path = build_book(tmp_path, ops_rows=[op_row()])
    registry.run_import(path)
    line = line_of(DAMONA, "3011")
    line.amount = Decimal("250000000.00")
    line.save(update_fields=["amount"])

    ops.run_import(path)

    line.refresh_from_db()
    assert line.amount == Decimal("250000000.00")


@pytest.mark.django_db
def test_supplier_without_bin_is_skipped_and_reported(tmp_path):
    report = load_both(build_book(tmp_path, ops_rows=[
        op_row(bin_iin="", supplier="Таможенный орган", goods="Таможенная пошлина"),
    ]))

    assert Invoice.objects.count() == 0
    assert any("Таможенный орган" in w and "нет БИН" in w for w in report.warnings)


@pytest.mark.django_db
def test_invoice_next_to_active_agreement_is_loaded_and_reported(tmp_path):
    # Платформа не даёт завести счёт без договора на программу с
    # действующим договором. Книга такое содержит — грузим и говорим.
    report = load_both(build_book(tmp_path, ops_rows=[
        op_row(admin=ARALSK, budget="3020 Сопровождение проекта", goods="Вода"),
    ]))

    assert Invoice.objects.count() == 1
    assert any("при действующем договоре" in w for w in report.warnings)


@pytest.mark.django_db
def test_long_goods_name_is_cut_but_kept_in_note(tmp_path):
    goods = "Монтаж " + "очень длинное наименование " * 20
    load_both(build_book(tmp_path, ops_rows=[op_row(goods=goods)]))

    invoice = Invoice.objects.get()
    assert len(invoice.name) == ops.INVOICE_NAME_MAX
    assert invoice.note == goods.strip()


@pytest.mark.django_db
def test_supplier_is_matched_to_existing_counterparty_by_bin(tmp_path):
    # Поставщик, уже заведённый реестром, не дублируется и не переименовывается.
    load_both(build_book(tmp_path, ops_rows=[
        op_row(admin=ARALSK, bin_iin="631031301177", supplier="ИП Абулгазиев А.",
               budget="3020 Сопровождение проекта"),
    ]))

    assert Counterparty.objects.filter(bin_iin="631031301177").count() == 1
    assert Invoice.objects.get().counterparty.name == "ИП «Абулгазиев»"


# ── Повторы, повторный прогон, статусы ──────────────────────────────────

@pytest.mark.django_db
def test_identical_rows_are_all_loaded_and_reported(tmp_path):
    report = load_both(build_book(tmp_path, ops_rows=[op_row(), op_row()]))

    assert Invoice.objects.count() == 2
    assert any("полностью совпадают" in w for w in report.warnings)


@pytest.mark.django_db
def test_second_run_creates_nothing(tmp_path):
    path = build_book(tmp_path, ops_rows=[op_row(), op_row(), by_agreement()])
    load_both(path)

    report = ops.run_import(path)

    assert Invoice.objects.count() == 2
    assert ContractPayment.objects.count() == 1
    assert report.created.get("Invoice", 0) == 0
    assert report.created.get("ContractPayment", 0) == 0


@pytest.mark.django_db
def test_approved_status_preset(tmp_path):
    load_both(build_book(tmp_path, ops_rows=[op_row(), by_agreement()]), status="approved")

    assert Invoice.objects.get().status == InvoiceStatus.APPROVED
    assert ContractPayment.objects.get().status == AdvancePaymentStatus.AWAITING_ACCOUNTING


@pytest.mark.django_db
def test_imported_invoices_and_payments_are_approved(tmp_path):
    # Оплаченный документ, оставшийся «черновиком» согласования, можно было
    # бы править после оплаты — у заведённых в платформе такого не бывает.
    load_both(build_book(tmp_path, ops_rows=[op_row(), by_agreement()]))

    assert Invoice.objects.get().approval_state == "approved"
    assert ContractPayment.objects.get().approval_state == "approved"


@pytest.mark.django_db
def test_draft_preset_leaves_documents_unapproved(tmp_path):
    load_both(build_book(tmp_path, ops_rows=[op_row(), by_agreement()]), status="draft")

    assert Invoice.objects.get().approval_state == "draft"
    assert ContractPayment.objects.get().approval_state == "draft"


@pytest.mark.django_db
def test_agreement_with_payments_is_approved(tmp_path):
    report = load_both(build_book(tmp_path, ops_rows=[by_agreement()]))

    assert Agreement.objects.get(external_id="L-OPEN").approval_state == "approved"
    assert any("согласованными" in note and "1" in note for note in report.notes)


@pytest.mark.django_db
def test_agreement_without_payments_stays_draft(tmp_path):
    # Подтверждения, что договор в работе, книга даёт только оплатой.
    registry_rows = REGISTRY + [
        registry_row(admin=DAMONA, code="3011", program="Сопровождение проекта",
                     number="NO-PAY", lark="L-IDLE"),
    ]
    load_both(build_book(tmp_path, registry_rows=registry_rows, ops_rows=[by_agreement()]))

    assert Agreement.objects.get(external_id="L-OPEN").approval_state == "approved"
    assert Agreement.objects.get(external_id="L-IDLE").approval_state == "draft"


@pytest.mark.django_db
def test_imported_agreement_with_payments_is_payable_in_the_ui(tmp_path, monkeypatch):
    # Ради чего всё: по импортированному договору можно завести следующую
    # оплату обычной формой, а не только импортом.
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.test import Client

    from .helpers import BASE, auth, token

    load_both(build_book(tmp_path, ops_rows=[by_agreement()]))
    agreement = Agreement.objects.select_related("budget_line__budget").get(external_id="L-OPEN")
    monkeypatch.setattr(
        "apps.contracts.services.contract_payment_service.media.store_file",
        lambda **kwargs: {"id": "invoice-1"},
    )

    response = Client().post(f"{BASE}/contract-payments", {
        "administrator_id": str(agreement.budget_line.budget.administrator_id),
        "agreement_id": str(agreement.pk), "amount": "354000.00",
        "invoice": SimpleUploadedFile("invoice.pdf", b"PDF"),
    }, **auth(token()))

    assert response.status_code == 201, response.content


@pytest.mark.django_db
def test_agreement_in_unagreed_status_is_not_approved(tmp_path):
    # Черновик с оплатами — повод посмотреть глазами, а не «одобрить».
    path = build_book(tmp_path, ops_rows=[by_agreement()])
    registry.run_import(path, status="draft")

    report = ops.run_import(path)

    assert Agreement.objects.get(external_id="L-OPEN").approval_state == "draft"
    assert any("согласованным не отмечен" in w for w in report.warnings)


@pytest.mark.django_db
def test_dry_run_does_not_approve_anything(tmp_path):
    path = build_book(tmp_path, ops_rows=[by_agreement()])
    registry.run_import(path)

    ops.run_import(path, dry_run=True)

    assert Agreement.objects.get(external_id="L-OPEN").approval_state == "draft"


@pytest.mark.django_db
def test_dry_run_writes_nothing(tmp_path):
    path = build_book(tmp_path, ops_rows=[op_row(), by_agreement()])
    registry.run_import(path)
    agreements = Agreement.objects.count()

    report = ops.run_import(path, dry_run=True)

    assert Invoice.objects.count() == 0
    assert ContractPayment.objects.count() == 0
    assert Agreement.objects.count() == agreements
    assert report.created["Invoice"] == 1
    assert report.created["ContractPayment"] == 1


# ── Форма листа ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_second_bin_column_is_used(tmp_path):
    # У счёта без договора первая колонка «БИН» пуста — брать надо вторую.
    load_both(build_book(tmp_path, ops_rows=[op_row(bin_iin="080340019927")]))
    assert Invoice.objects.get().counterparty.bin_iin == "080340019927"


@pytest.mark.django_db
def test_missing_budget_column_is_a_clear_error(tmp_path):
    header = [h if h != "Бюджет" else "Референс" for h in OPS_HEADER]
    path = build_book(tmp_path, ops_rows=[op_row()], ops_header=header)

    with pytest.raises(registry.CashflowImportError, match="Бюджет"):
        ops.run_import(path)


@pytest.mark.parametrize("cell, expected", [
    (3020, ("3020", "")),
    (3020.0, ("3020", "")),
    ("3020", ("3020", "")),
    ("3011 Сопровождение проекта", ("3011", "Сопровождение проекта")),
    ("Сопровождение проекта", ("", "Сопровождение проекта")),
    (None, ("", "")),
])
def test_budget_cell_parsing(cell, expected):
    assert ops.parse_budget_cell(cell) == expected

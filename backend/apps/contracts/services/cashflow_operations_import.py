"""Загрузка листа «Операции» книги CashFlow в модели contracts.

    python manage.py import_cashflow_operations "CashFlow pr.xlsx" [--dry-run]

Второй проход после ``import_cashflow`` (реестр договоров) и НЕ повторяет
его: договоры к этому моменту уже загружены и, возможно, поправлены руками,
а повторный импорт реестра переписал бы правки. Этот модуль договоры
ищет — по ``Agreement.external_id``, — и не создаёт; единственное, что он в
договоре меняет, — согласование (см. «Согласование» ниже).

## Что в листе на самом деле

Лист разбит на секции «Договор / АВР/Накладная / ЭСФ», но заполнена в нём
одна — счета на оплату (колонки «Наименование администратора программы» …
«Бюджет»). Колонки актов (АВР/накладная) и ЭСФ пусты во всех строках, и
разбирать их здесь не из чего; колонки ищутся по заголовкам, так что
появятся данные — добавятся и они, без перестройки модуля.

Каждая строка — счёт, и колонка «Наличие договора» делит их на два вида:

- **«По договору»** → ``ContractPayment`` (оплата по договору). Договор
  находится по идентификатору LARK. Программа, администратор и контрагент
  у такой оплаты — договорные; то, что написано в строке, лишь сверяется с
  договором, и расхождение попадает в отчёт.
- **«Без договора»** → ``Invoice`` (счёт на оплату без договора). Строка
  бюджета ищется по «администратору × коду программы» из колонки «Бюджет».

## Колонка «Бюджет»

В ней либо голый код (``3020``), либо код с названием (``3020
Сопровождение проекта``). Голый код разрешается через лист «Бюджет»,
колонка B («код Название»), — но ТОЛЬКО среди строк того же
администратора: коды у финансистов свои у каждого проекта, и 3026 у
Аральска («Кабели LV») — не то же, что 3026 у «Арал 30 МВт» («Система
заземления»). Поиск по одному коду положил бы счёт на чужую программу.

Строки бюджета, которой нет, заводятся с лимитом с листа «Бюджет», если он
там есть, и с нулевым — если нет (с предупреждением). Лимиты СУЩЕСТВУЮЩИХ
строк этот импорт не трогает никогда: их правят финансисты.

## Идентификатор строки

У счёта в книге своего идентификатора нет (LARK в строке — это договор, а не
счёт). Поэтому ``external_id`` — отпечаток содержимого строки: администратор,
договор, БИН, сумма, дата, наименование, программа — и номер повтора среди
полностью одинаковых строк (в книге такие есть, и это могут быть и честные
повторные закупки, и двойной ввод — различить их по данным нельзя, поэтому
грузятся все и перечисляются в отчёте).

Следствие: повторный прогон по той же книге ничего не удваивает, но строка,
в которой поправили сумму или дату, — для импорта уже другая строка, и
старый счёт останется рядом с новым. Импорт одноразовый; если книгу
придётся перезаливать после правок, старые записи удаляются по их
``external_id`` (все начинаются с ``ops:``).

## Статус

По умолчанию счета — ``paid``, оплаты по договорам — ``closed``: книга —
это учёт уже случившихся расходов, и расход обязан сразу появиться в
остатках бюджета.

## Согласование

Всё, что здесь грузится, согласовано ВНЕ платформы — в LARK, — и без
отметки об этом застревает: signoff о нём не знает, а отправить его на
согласование задним числом нельзя.

- **Договор, к которому этот импорт привязал оплату**, становится
  согласованным (``approval_state = approved``). Иначе по импортированному
  договору в интерфейсе нельзя завести ни оплату, ни предоплату, ни акт —
  все три требуют согласованного договора, — а отправить подписанный
  договор на согласование тоже нельзя: из «подписан» в черновик хода нет.
  Договоры БЕЗ оплат в листе не трогаются: подтверждения, что они в работе,
  книга по ним не даёт.
- **Счета и оплаты** грузятся согласованными (кроме ``--status draft``):
  оплаченный документ, оставшийся «черновиком» согласования, можно было бы
  править после оплаты — чего у заведённых в платформе не бывает.

В итоге импортированное ведёт себя ровно как заведённое и согласованное в
платформе: оплачивается и заперто для правки. Истории согласования в
signoff у него нет — решение принималось не здесь; поправить такую запись
можно через django-admin.

## Чего импорт НЕ проверяет

Как и реестр — ни лимит строки бюджета, ни остаток договора, ни правило
«счёт без договора нельзя завести на программу с действующим договором»
(``invoice_service._assert_no_active_agreement``). Переносится случившийся
факт; каждое такое расхождение считается и печатается в отчёт.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass

from django.db import transaction

from apps.contracts.models import (
    AdvancePaymentStatus,
    Agreement,
    AgreementStatus,
    Counterparty,
    ContractPayment,
    Country,
    Invoice,
    InvoiceStatus,
)
from apps.contracts.services import budget_calc
from apps.contracts.services import cashflow_import as base
from apps.signoff import interface as signoff

SHEET_OPERATIONS = "Операции"

# Колонки листа «Операции». Значение — подпись в книге и номер её вхождения
# в строку заголовков: «БИН» в листе ДВАЖДЫ — в секции договора (с
# потерянными ведущими нулями) и в секции счёта (полный). Нужен второй: у
# счетов без договора первый пуст.
OPERATIONS_COLUMNS = {
    "agreement_lark": ("Идентификатор договора (LARK)", 1),
    "administrator": ("Наименование администратора программы", 1),
    "has_agreement": ("Наличие договора", 1),
    "document_date": ("Дата", 1),
    "amount": ("Сумма счета", 1),
    "bin_iin": ("БИН", 2),
    "supplier": ("Наименование поставщика", 1),
    "goods": ("Наименование ТРУ", 1),
    "budget": ("Бюджет", 1),
}

KIND_BY_AGREEMENT = "по договору"
KIND_WITHOUT_AGREEMENT = "без договора"

# Как «--status» раскладывается на две модели: у счёта и у оплаты по
# договору машины статусов разные, а смысл выбора один.
STATUS_PRESETS = {
    "paid": (InvoiceStatus.PAID, AdvancePaymentStatus.CLOSED),
    "approved": (InvoiceStatus.APPROVED, AdvancePaymentStatus.AWAITING_ACCOUNTING),
    "draft": (InvoiceStatus.DRAFT, AdvancePaymentStatus.DRAFT),
}

# Статусы договора, в которых он уже был согласован сторонами. Только такой
# договор импорт отмечает согласованным: черновик или расторгнутый договор с
# оплатами — повод посмотреть глазами, а не повод его «одобрить».
AGREED_STATUSES = (AgreementStatus.APPROVED, AgreementStatus.SIGNED,
                   AgreementStatus.EXECUTED)

INVOICE_NAME_MAX = 300


@dataclass
class OperationRow:
    excel_row: int
    kind: str
    agreement_lark: str
    administrator: str
    program_code: str
    program_name: str
    bin_iin: str
    supplier: str
    goods: str
    amount: object
    document_date: object


# ── Разбор ──────────────────────────────────────────────────────────────

def parse_budget_cell(value) -> tuple[str, str]:
    """Колонка «Бюджет» → ``(код, название)``.

    Голый код (``3020``, в том числе числом ``3020.0``) даёт пустое
    название — его потом берут с листа «Бюджет». Текст без ведущего кода
    даёт пустой код: такую строку привязать не к чему.
    """
    text = base._text(value)
    if not text:
        return "", ""
    if re.fullmatch(r"\d+(\.0+)?", text):
        return str(int(float(text))), ""
    return base.split_program_cell(text)


def _header_positions(header_row, expected: dict[str, tuple[str, int]],
                      sheet: str) -> dict[str, int]:
    """Как ``cashflow_import._header_map``, но с номером вхождения подписи —
    в этом листе заголовки повторяются."""
    seen: dict[str, list[int]] = defaultdict(list)
    for index, cell in enumerate(header_row):
        label = base._text(cell)
        if label:
            seen[label].append(index)

    mapping, missing = {}, []
    for key, (label, occurrence) in expected.items():
        positions = seen.get(label, [])
        if len(positions) >= occurrence:
            mapping[key] = positions[occurrence - 1]
        else:
            missing.append(label if occurrence == 1 else f"{label} (#{occurrence})")
    if missing:
        raise base.CashflowImportError(
            f"лист «{sheet}»: не найдены колонки {missing}. Найдены: {sorted(seen)}"
        )
    return mapping


def read_operations_sheet(workbook) -> tuple[list[OperationRow], list[str]]:
    """Лист «Операции» → строки + предупреждения разбора.

    Над строкой заголовков лежит строка с названиями секций, поэтому
    заголовки ищутся среди первых строк листа — по той, где есть колонка
    «Наличие договора», — а не берутся первой строкой.
    """
    if SHEET_OPERATIONS not in workbook.sheetnames:
        raise base.CashflowImportError(
            f"в книге нет листа «{SHEET_OPERATIONS}» (есть: {workbook.sheetnames})"
        )
    rows = base._rows(workbook[SHEET_OPERATIONS])

    marker = OPERATIONS_COLUMNS["has_agreement"][0]
    columns = None
    for _, values in rows:
        if any(base._text(v) == marker for v in values):
            columns = _header_positions(values, OPERATIONS_COLUMNS, SHEET_OPERATIONS)
            break
    if columns is None:
        raise base.CashflowImportError(
            f"лист «{SHEET_OPERATIONS}»: не найдена строка заголовков "
            f"(нет колонки «{marker}»)"
        )

    def cell(values, key):
        index = columns[key]
        return values[index] if index < len(values) else None

    parsed, warnings = [], []
    for excel_row, values in rows:
        kind = base._text(cell(values, "has_agreement")).lower()
        amount_raw = cell(values, "amount")
        # Строка, где нет ни вида, ни суммы, ни поставщика, — пустая, даже
        # если в ней стоит порядковый номер.
        if not kind and base._text(amount_raw) == "" and not base._text(cell(values, "supplier")):
            continue

        label = f"строка {excel_row}"
        if kind not in (KIND_BY_AGREEMENT, KIND_WITHOUT_AGREEMENT):
            warnings.append(f"{label}: «Наличие договора» = «{kind}» неизвестно — пропущена")
            continue

        try:
            amount = base._money(amount_raw)
            document_date = base.parse_excel_date(cell(values, "document_date"))
        except (ValueError, ArithmeticError) as exc:
            warnings.append(f"{label}: {exc} — пропущена")
            continue
        if amount <= 0:
            warnings.append(f"{label}: сумма счёта пустая или нулевая — пропущена")
            continue

        code, name = parse_budget_cell(cell(values, "budget"))
        bin_iin, _ = base.normalize_bin(cell(values, "bin_iin"), None)

        parsed.append(OperationRow(
            excel_row=excel_row,
            kind=kind,
            agreement_lark=base._text(cell(values, "agreement_lark")),
            administrator=base._text(cell(values, "administrator")),
            program_code=code,
            program_name=name,
            bin_iin=bin_iin,
            supplier=base._text(cell(values, "supplier")),
            goods=base._text(cell(values, "goods")),
            amount=amount,
            document_date=document_date,
        ))
    return parsed, warnings


# ── Идентификатор строки ────────────────────────────────────────────────

def _content_key(row: OperationRow) -> tuple:
    return (row.kind, row.administrator, row.agreement_lark, row.bin_iin,
            str(row.amount), row.document_date.isoformat() if row.document_date else "",
            row.goods, row.program_code)


def fingerprint(row: OperationRow, occurrence: int) -> str:
    """``ops:`` + SHA-1 содержимого строки и номера её повтора в книге."""
    raw = "\x1f".join([*map(str, _content_key(row)), str(occurrence)])
    return "ops:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()


# ── Загрузка ────────────────────────────────────────────────────────────

def _load_contract_payments(rows: list[OperationRow], *, status: str,
                            approval_state: str, resolver: base.BudgetResolver,
                            ids: dict[int, str], report: base.ImportReport) -> set[int]:
    """Оплаты по договорам. Возвращает id договоров, получивших оплату."""
    larks = {row.agreement_lark for row in rows if row.agreement_lark}
    agreements = {
        agreement.external_id: agreement
        for agreement in (Agreement.objects
                          .filter(external_id__in=larks)
                          .select_related("counterparty", "budget_line__program",
                                          "budget_line__budget__administrator"))
    }
    paid: set[int] = set()

    for row in rows:
        label = f"строка {row.excel_row}"
        agreement = agreements.get(row.agreement_lark)
        if agreement is None:
            report.warn(
                f"{label}: договор с идентификатором «{row.agreement_lark}» не найден "
                f"(реестр договоров загружен?) — оплата пропущена"
            )
            continue

        line = agreement.budget_line
        administrator = line.budget.administrator
        # Строка для отчёта о перерасходе: у открытых договоров расход по
        # этой строке теперь складывается из загружаемых оплат.
        resolver.lines.setdefault((administrator.project_name, line.program.code), line)

        # Программа, администратор и контрагент у оплаты — договорные. То,
        # что написано в строке, лишь сверяется: расхождение — повод
        # посмотреть глазами, а не повод переносить оплату на чужую строку.
        if row.program_code and row.program_code != line.program.code:
            report.warn(
                f"{label}: в колонке «Бюджет» программа {row.program_code}, а договор "
                f"«{agreement.number}» — на программе {line.program.code}; "
                f"оплата записана на договор"
            )
        if row.administrator and row.administrator != administrator.project_name:
            report.warn(
                f"{label}: администратор «{row.administrator}», а у договора "
                f"«{agreement.number}» — «{administrator.project_name}»"
            )
        if row.bin_iin and row.bin_iin != agreement.counterparty.bin_iin:
            report.warn(
                f"{label}: БИН поставщика {row.bin_iin}, а у контрагента договора "
                f"«{agreement.number}» — {agreement.counterparty.bin_iin}"
            )

        _, created = ContractPayment.objects.update_or_create(
            external_id=ids[row.excel_row],
            defaults={
                "administrator": administrator,
                "agreement": agreement,
                "amount": row.amount,
                "status": status,
                "approval_state": approval_state,
                "document_date": row.document_date,
            },
        )
        report.bump("ContractPayment", created)
        paid.add(agreement.pk)
    return paid


def _approve_paid_agreements(agreement_ids: set[int], report: base.ImportReport) -> None:
    """Отметить согласованными договоры, к которым привязаны оплаты.

    Почему это вообще делается и почему только для них — в разделе
    «Согласование» докстринга модуля. Трогаются лишь договоры из импорта
    (непустой ``external_id``), ещё не бывавшие в signoff (``draft``) и уже
    согласованные сторонами по своему статусу: живой процесс согласования
    или отказ, принятый в платформе, импорт не перекрывает.
    """
    candidates = (Agreement.objects
                  .filter(pk__in=agreement_ids)
                  .exclude(external_id=""))
    approved = (candidates
                .filter(approval_state=signoff.ApprovalState.DRAFT,
                        status__in=AGREED_STATUSES)
                .update(approval_state=signoff.ApprovalState.APPROVED))
    if approved:
        report.notes.append(
            f"договоров отмечено согласованными (по ним есть оплаты): {approved}"
        )

    for agreement in (candidates
                      .filter(approval_state=signoff.ApprovalState.DRAFT)
                      .exclude(status__in=AGREED_STATUSES)
                      .only("number", "status")):
        report.warn(
            f"договор «{agreement.number}» в статусе «{agreement.get_status_display()}» "
            f"с оплатами — согласованным не отмечен, проверьте"
        )


def _load_invoices(rows: list[OperationRow], budget_rows: list[base.BudgetRow], *,
                   status: str, approval_state: str, country: Country,
                   resolver: base.BudgetResolver,
                   ids: dict[int, str], report: base.ImportReport) -> None:
    # Лист «Бюджет» по паре «администратор × код» — источник названия для
    # голого кода и лимита для строки, которую придётся завести.
    limits = {(row.administrator, row.program_code): row
              for row in budget_rows if row.program_code}

    counterparties: dict[str, Counterparty] = {}
    spellings: dict[str, set[str]] = defaultdict(set)
    # Строка бюджета → есть ли на ней действующий договор; и сколько счетов
    # без договора на такие строки легло. Спрашивается раз на строку.
    has_active_agreement: dict[int, bool] = {}
    conflicts: dict[tuple[str, str], int] = defaultdict(int)

    for row in rows:
        label = f"строка {row.excel_row}"
        if not row.administrator:
            report.warn(f"{label}: не указан администратор программы — счёт пропущен")
            continue
        if not row.program_code:
            report.warn(f"{label}: в колонке «Бюджет» нет кода программы — счёт пропущен")
            continue
        if not row.bin_iin:
            report.warn(
                f"{label}: у поставщика «{row.supplier}» нет БИН "
                f"(«{row.goods}», {row.amount}) — счёт пропущен"
            )
            continue

        sheet_row = limits.get((row.administrator, row.program_code))
        name = row.program_name or (sheet_row.program_name if sheet_row else "")
        line = resolver.line(
            row.administrator, row.program_code, name=name, expense_item=name,
            limit=sheet_row.limit if sheet_row else None,
            currency=sheet_row.currency if sheet_row else None,
        )
        if line is None:
            report.warn(
                f"{label}: программы {row.program_code} нет ни в бюджете "
                f"«{row.administrator}», ни на листе «{base.SHEET_BUDGET}» — "
                f"название взять неоткуда, счёт пропущен"
            )
            continue

        spellings[row.bin_iin].add(row.supplier)
        counterparty = counterparties.get(row.bin_iin)
        if counterparty is None:
            counterparty, created = Counterparty.objects.get_or_create(
                bin_iin=row.bin_iin,
                defaults={"name": row.supplier or row.bin_iin, "country": country},
            )
            counterparties[row.bin_iin] = counterparty
            report.bump("Counterparty", created)

        # Наименование закупки длиннее поля — обрезается, но не теряется:
        # полный текст уходит в пояснение.
        goods = row.goods or "(без наименования)"
        name_field, note = goods, ""
        if len(goods) > INVOICE_NAME_MAX:
            name_field, note = goods[:INVOICE_NAME_MAX - 1] + "…", goods

        _, created = Invoice.objects.update_or_create(
            external_id=ids[row.excel_row],
            defaults={
                "name": name_field,
                "note": note,
                "budget_line": line,
                "counterparty": counterparty,
                "amount": row.amount,
                # Валюта — с бюджета строки, как у всякого счёта (см. Invoice).
                "currency": line.budget.currency,
                "status": status,
                "approval_state": approval_state,
                "document_date": row.document_date,
            },
        )
        report.bump("Invoice", created)

        if line.pk not in has_active_agreement:
            has_active_agreement[line.pk] = Agreement.objects.filter(
                budget_line=line, status__in=budget_calc.COMMITTING_STATUSES,
            ).exists()
        if has_active_agreement[line.pk]:
            conflicts[(row.administrator, row.program_code)] += 1

    for bin_iin, names in sorted(spellings.items()):
        if len(names) > 1:
            report.warn(
                f"БИН {bin_iin}: несколько написаний поставщика "
                f"({', '.join(sorted(names))}) — сохранено «{counterparties[bin_iin].name}»"
            )

    for (project_name, code), count in sorted(conflicts.items()):
        report.warn(
            f"«{project_name}» × программа {code}: {count} счетов без договора "
            f"при действующем договоре на той же программе — платформа такое "
            f"создать не даёт, загружены как есть"
        )


def run_import(path, *, year: int | None = None,
               country_name: str = base.DEFAULT_COUNTRY,
               status: str = "paid", dry_run: bool = False) -> base.ImportReport:
    """Прочитать лист «Операции» и загрузить его. Единственная точка входа.

    ``year`` — год бюджетов для строк, которые придётся завести; по
    умолчанию — год самого позднего счёта в листе (так же, как реестр берёт
    его из дат подписания).
    """
    if status not in STATUS_PRESETS:
        raise base.CashflowImportError(
            f"неизвестный статус «{status}» (есть: {', '.join(STATUS_PRESETS)})"
        )
    invoice_status, payment_status = STATUS_PRESETS[status]
    # Черновик — единственный пресет, который ещё не решён; всё остальное
    # согласовано в LARK (см. «Согласование» в докстринге модуля).
    approval_state = (signoff.ApprovalState.DRAFT if status == "draft"
                      else signoff.ApprovalState.APPROVED)

    workbook = base.load_workbook_file(path)
    try:
        budget_rows = base.read_budget_sheet(workbook)
        rows, parse_warnings = read_operations_sheet(workbook)
    finally:
        workbook.close()

    report = base.ImportReport(dry_run=dry_run)
    report.rows_read = len(rows)
    for warning in parse_warnings:
        report.warn(warning)
    if not rows:
        raise base.CashflowImportError(f"на листе «{SHEET_OPERATIONS}» нет ни одной строки данных")

    if year is None:
        dates = [row.document_date for row in rows if row.document_date]
        if not dates:
            raise base.CashflowImportError(
                "не удалось определить год бюджета: в листе нет ни одной даты — "
                "укажите --year явно"
            )
        year = max(dates).year

    # Идентификаторы строк — до записи: повторы считаются по всей книге.
    ids: dict[int, str] = {}
    seen: dict[tuple, list[int]] = defaultdict(list)
    for row in rows:
        key = _content_key(row)
        ids[row.excel_row] = fingerprint(row, len(seen[key]))
        seen[key].append(row.excel_row)
    for key, excel_rows in seen.items():
        if len(excel_rows) > 1:
            report.warn(
                f"строки {', '.join(map(str, excel_rows))} полностью совпадают "
                f"(«{key[6]}», {key[4]}) — загружены все: повторная закупка это "
                f"или двойной ввод, по данным не различить"
            )

    try:
        with transaction.atomic():
            country, created = Country.objects.get_or_create(name=country_name)
            report.bump("Country", created)

            resolver = base.BudgetResolver(
                year=year, country=country, report=report,
                currencies={row.administrator: row.currency for row in budget_rows},
                missing_limit_note=(
                    f"Заведена импортом листа «{SHEET_OPERATIONS}»: лимит на листе "
                    f"«{base.SHEET_BUDGET}» отсутствует"
                ),
            )
            paid_agreements = _load_contract_payments(
                [row for row in rows if row.kind == KIND_BY_AGREEMENT],
                status=payment_status, approval_state=approval_state,
                resolver=resolver, ids=ids, report=report,
            )
            _approve_paid_agreements(paid_agreements, report)
            _load_invoices(
                [row for row in rows if row.kind == KIND_WITHOUT_AGREEMENT],
                budget_rows, status=invoice_status, approval_state=approval_state,
                country=country, resolver=resolver, ids=ids, report=report,
            )
            base._report_overruns(resolver, report)

            if dry_run:
                raise base._Rollback
    except base._Rollback:
        pass

    return report

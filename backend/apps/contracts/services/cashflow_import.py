"""Загрузка реестра договоров заказчика (CashFlow.xlsx) в модели contracts.

    python manage.py import_cashflow CashFlow.xlsx [--dry-run]

Источник — рабочая книга финансистов, а не выгрузка из системы. Отсюда всё
устройство этого модуля: файл ведут руками, в нём есть опечатки, повторы и
пробелы, и «просто прочитать колонки» недостаточно — каждое расхождение
должно либо чиниться по понятному правилу, либо попадать в отчёт, но никогда
не проходить молча.

## Что откуда берётся

Читаются ДВА листа, и порядок между ними обязателен:

1. **«Бюджет»** (``администратор | «код Название» | лимит | валюта``) →
   ``Country`` → ``Administrator`` → ``Program`` → ``Budget`` → ``BudgetLine``.
2. **«Реестр договоров»** (13 колонок + безымянная) → ``Counterparty`` и
   ``Agreement``.

Второй лист сам по себе загрузиться не может: ``Agreement.budget_line`` —
обязательный ``PROTECT``-ключ, то есть строка бюджета обязана существовать
раньше договора, который на неё ссылается.

## Колонки ищутся по ЗАГОЛОВКУ, а не по номеру

Книга живёт своей жизнью: колонку вставят или переставят местами, и импорт,
привязанный к позициям, тихо начнёт грузить наименование в номер. Поэтому
позиция вычисляется из строки заголовков, а отсутствие ожидаемого заголовка —
ошибка с перечислением того, что реально нашлось.

Ровно одно исключение — колонка ``N`` (см. ниже): у неё заголовка НЕТ, и
адресовать её больше нечем, кроме как «сразу за идентификатором LARK».

## Правила чинки данных (каждое — из реальной особенности файла)

- **Ведущий ноль в БИН.** Excel хранит БИН как число и съедает ведущий ноль,
  поэтому рядом ведётся колонка без заголовка с настоящей ДЛИНОЙ номера: 11
  означает «был двенадцатизначный, ноль потерялся». Номер дополняется нулями
  слева до указанной длины. Если после дополнения длина всё равно не сошлась —
  предупреждение, а не молчаливая подмена.
- **Контрагент опознаётся по БИН, а не по названию.** Одна и та же
  организация приходит в разных написаниях («Арал құрылысы» / «Арал
  курылысы»), и название — не ключ. Побеждает первое встреченное написание,
  остальные попадают в отчёт: выбирать за финансистов, как правильно, импорт
  не вправе.
- **Программа опознаётся по КОДУ.** Названия у разных программ совпадают
  («Сопровождение проекта» — это и 3011, и 3020), а код различает их всегда;
  под это же переписан и уникальный ключ ``Program`` (см. его ``Meta``).
  Название берётся из «Бюджета» (там оно полное), статья расходов — из
  реестра (там оно короткое, каким его пишут в договорах).
- **Повторяющиеся номера договоров.** ``Agreement.number`` уникален, а в
  реестре один номер носят до трёх РАЗНЫХ договоров (у «1» — три разных
  контрагента). Повторам приписывается точка в конец («1», «1.», «1..»),
  исходный номер попадает в отчёт. Точка — не косметика: по номеру теперь
  нельзя искать вслепую, и импорт обязан сказать, где он это сделал.
- **Договоры без суммы.** У «открытых» (рамочных) договоров суммы нет по
  существу — она известна только по факту поставки. Такие грузятся с
  ``amount = 0`` и ``contract_type = open``; ноль в паре с этим признаком
  читается как «суммы ещё нет», а не как потерянные данные.
- **Строки бюджета, которых нет в «Бюджете».** Реестр ссылается на пары
  «администратор × программа», отсутствующие на листе лимитов. Договор без
  строки бюджета не сохранить, поэтому строка заводится с НУЛЕВЫМ лимитом и
  пометкой в ``note`` — и обязательно с предупреждением: нулевой лимит
  означает, что весь договор висит за пределами бюджета, и это должен увидеть
  человек, а не только база.

## Чего импорт НЕ делает

- **Не трогает ``approval_state``.** Эту колонку ведёт исключительно движок
  ``apps.signoff`` (см. докстринг ``Approvable``), и проставить «согласовано»
  в обход процесса значило бы создать согласованный объект, за которым нет ни
  одного решения. Загруженные договоры получают предметный ``status``
  (по умолчанию «подписан» — они и правда подписаны, дата есть у каждого), а
  согласование остаётся в ``draft``.
- **Не проверяет лимит бюджета** (``budget_calc.check_capacity``). Проверка
  сторожит ВВОД новых договоров, а здесь переносится уже случившийся факт:
  два лимита в файле пробиты по-настоящему, и импорт, который бы на этом
  остановился, просто не дал бы перенести реальность. Перерасход считается
  и печатается в отчёт — как раз чтобы его увидели.
- **Не пишет файлы и не ходит в S3**: скана договора в реестре нет,
  ``file_id`` остаётся пустым.

## Повторный прогон

Идемпотентен: ключ — ``Agreement.external_id`` (идентификатор LARK), а не
номер, который импорт сам же и правит точками. Повторный прогон обновляет те
же строки; уже выданный номер с точками за договором сохраняется, чтобы
ссылки на него не разъезжались от запуска к запуску.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from apps.contracts.models import (
    Administrator,
    Agreement,
    AgreementKind,
    AgreementStatus,
    AgreementType,
    Budget,
    BudgetLine,
    Counterparty,
    Country,
    PaymentType,
    Program,
)

# ── Разбор книги ────────────────────────────────────────────────────────

SHEET_BUDGET = "Бюджет"
SHEET_REGISTRY = "Реестр договоров"

# Заголовки листа «Реестр договоров». Ключ — имя поля в этом модуле,
# значение — подпись в книге. Все обязательны: пропажа любой означает, что
# книга изменилась настолько, что гадать нельзя.
REGISTRY_COLUMNS = {
    "administrator": "Администратор бюджета",
    "program_code": "Код программы",
    "program_name": "Программа",
    "number": "Номер договора",
    "name": "Наименование договора",
    "counterparty": "Контрагент",
    "bin_iin": "БИН/ИИН",
    "amount": "Сумма договор",
    "advance": "Аванс (ТИП ОПЛАТЫ)",
    "signed_date": "Дата подписания",
    "kind": "Вид",
    "contract_type": "Тип",
    "external_id": "Идентификатор LARK",
}

BUDGET_COLUMNS = {
    "administrator": "Администратор бюджета",
    "program": "Бюджетная программа",
    "limit": "Лимит",
    "currency": "Валюта",
}

# «Вид» и «Тип» — как их пишут в книге. Сопоставление регистронезависимое и
# по очищенной строке: в файле встречаются и «РиУ», и «риу».
KIND_BY_LABEL = {
    "риу": AgreementKind.WORKS_SERVICES,
    "тмц": AgreementKind.GOODS,
}
# «Открытый» из реестра — это FRAMEWORK: одно понятие (договор без общей
# суммы) под двумя именами, см. докстринг AgreementType. Отдельного значения
# ``open`` в перечислении нет намеренно, иначе договоры разошлись бы по двум
# значениям, а проверка «суммы может не быть» читала бы только одно.
TYPE_BY_LABEL = {
    "стандарт": AgreementType.STANDARD,
    "открытый": AgreementType.FRAMEWORK,
}

# БИН и ИИН в Казахстане всегда двенадцатизначные — до этой ширины и
# дополняются номера, у которых Excel съел ведущий ноль.
BIN_LENGTH = 12

MONEY = Decimal("0.01")
SHARE = Decimal("0.001")
ZERO = Decimal("0.00")

# Excel считает дни от 1900-01-00 с известной ошибкой високосного 1900-го;
# практический эпох-сдвиг, совпадающий с самим Excel, — 1899-12-30.
EXCEL_EPOCH = dt.date(1899, 12, 30)

DEFAULT_COUNTRY = "Казахстан"
DEFAULT_CURRENCY = "KZT"


class CashflowImportError(Exception):
    """Книга не той формы — читать нечего, продолжать нельзя."""


@dataclass
class ImportReport:
    """Что импорт сделал и на что просит посмотреть человека.

    ``warnings`` — не ошибки: каждая строка здесь означает, что данные
    загружены, но по ним принято решение, которое стоит проверить (номер с
    точкой, нулевой лимит, разнобой в названии контрагента). Печатаются они
    всегда, в том числе при ``--dry-run``, ради которого отчёт и собирается
    отдельным объектом, а не выводится по ходу дела.
    """

    created: dict[str, int] = field(default_factory=dict)
    updated: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    overruns: list[str] = field(default_factory=list)
    rows_read: int = 0
    dry_run: bool = False

    def bump(self, entity: str, was_created: bool) -> None:
        target = self.created if was_created else self.updated
        target[entity] = target.get(entity, 0) + 1

    def warn(self, message: str) -> None:
        self.warnings.append(message)


@dataclass
class RegistryRow:
    """Одна строка реестра, уже приведённая к типам Python."""

    excel_row: int
    administrator: str
    program_code: str
    program_name: str
    number: str
    name: str
    counterparty: str
    bin_iin: str
    amount: Decimal
    has_amount: bool
    advance_share: Decimal
    signed_date: dt.date | None
    kind: str
    contract_type: str
    external_id: str


@dataclass
class BudgetRow:
    excel_row: int
    administrator: str
    program_code: str
    program_name: str
    limit: Decimal
    currency: str


# ── Нормализация значений ───────────────────────────────────────────────

def _text(value) -> str:
    """Ячейка → строка без краевых пробелов и неразрывных пробелов.

    Числовые ячейки приводятся без ``.0``: коды программ и БИН лежат в книге
    то текстом, то числом, и ``str(3019.0)`` испортил бы ключ.
    """
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).replace("\xa0", " ").strip()


def _money(value) -> Decimal:
    """Ячейка → сумма с двумя знаками.

    Через ``repr`` числа, а не ``Decimal(float)``: Excel хранит суммы
    двоичными дробями (554038657.32 лежит как 554038657.32000005), и прямое
    преобразование потащило бы в базу весь двоичный хвост.
    """
    if value is None or value == "":
        return ZERO
    if isinstance(value, Decimal):
        return value.quantize(MONEY, rounding=ROUND_HALF_UP)
    if isinstance(value, (int, float)):
        return Decimal(repr(value)).quantize(MONEY, rounding=ROUND_HALF_UP)
    cleaned = _text(value).replace(" ", "").replace(",", ".")
    return Decimal(cleaned).quantize(MONEY, rounding=ROUND_HALF_UP)


def parse_advance_share(value) -> Decimal:
    """«Аванс (ТИП ОПЛАТЫ)» → доля 0..1.

    В книге лежит и то и другое написание: доля (``0``, ``0.5``, ``1``) и
    процент (``0%``, ``70%``, ``100%``). Различать их по одному лишь числу
    нельзя — «1» это и 100%, и 1%, — поэтому решает ЗНАК ПРОЦЕНТА: со
    знаком делим на сто, без знака считаем долей.

    Отдельно ловится случай «70» без знака: доля больше единицы смысла не
    имеет, а проверка в БД такую строку и не примет, поэтому это ошибка
    строки, а не повод угадать.
    """
    if value is None or value == "":
        return Decimal(0)

    raw = _text(value)
    is_percent = raw.endswith("%")
    if is_percent:
        raw = raw[:-1].strip()
    raw = raw.replace(",", ".")

    try:
        share = Decimal(raw)
    except Exception as exc:  # noqa: BLE001 — сообщение важнее типа
        raise ValueError(f"не разобран аванс {value!r}") from exc

    if is_percent:
        share = share / Decimal(100)
    if share < 0 or share > 1:
        raise ValueError(
            f"доля аванса {value!r} вне диапазона 0..1 "
            f"(проценты пишутся со знаком: «70%», не «70»)"
        )
    return share.quantize(SHARE, rounding=ROUND_HALF_UP)


def parse_excel_date(value) -> dt.date | None:
    """Ячейка → дата.

    openpyxl отдаёт дату уже разобранной, если формат ячейки датный, и голым
    порядковым числом, если нет — в этой книге встречается и то, и другое.
    """
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, (int, float)):
        return EXCEL_EPOCH + dt.timedelta(days=int(value))
    text = _text(value)
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    if text.isdigit():
        return EXCEL_EPOCH + dt.timedelta(days=int(text))
    raise ValueError(f"не разобрана дата подписания {value!r}")


def normalize_bin(raw, declared_length) -> tuple[str, str | None]:
    """БИН/ИИН → двенадцатизначный номер. Возвращает ``(номер, предупреждение)``.

    Excel хранит БИН числом, поэтому ведущий ноль пропадает уже при вводе: у
    ТОО «Снабкомплект Монтаж» БИН 080340019927 лежит в книге как
    80340019927. Такие организации в реестре не исключение — их четыре.

    Рядом финансисты ведут колонку без заголовка с ДЛИНОЙ номера (по сути
    ``LEN(G)``): ``11`` означает, что цифр одиннадцать, то есть одного нуля
    не хватает. Это признак, а не целевая ширина — дополняем всегда до
    ДВЕНАДЦАТИ, а колонка длины служит перекрёстной проверкой: если она
    разошлась с фактической длиной, значит формула в книге устарела, и об
    этом надо сказать.

    Номер длиннее двенадцати не обрезается: лишняя цифра — это опечатка,
    которую должен увидеть человек, а не потеря данных, которую импорт
    устроил сам.
    """
    number = _text(raw)
    if not number:
        return "", "БИН пустой"

    warning = None
    declared = _text(declared_length)
    if declared.isdigit() and int(declared) != len(number):
        warning = (
            f"БИН {number}: в колонке длины {declared}, а знаков {len(number)} — "
            f"формула в книге устарела"
        )

    if len(number) < BIN_LENGTH:
        number = number.rjust(BIN_LENGTH, "0")
    elif len(number) > BIN_LENGTH:
        return number, (
            f"БИН {number} длиннее {BIN_LENGTH} знаков — оставлен как есть"
        )
    return number, warning


def split_program_cell(value) -> tuple[str, str]:
    """«3019 Монтаж ограждения…» → ``("3019", "Монтаж ограждения…")``.

    Так программа записана на листе «Бюджет»: код и название в одной ячейке.
    Ячейка без ведущего кода возвращает пустой код — вызывающий сам решает,
    ошибка это или нет.
    """
    text = _text(value)
    match = re.match(r"^(\d+)\s+(.+)$", text)
    if not match:
        return "", text
    return match.group(1), match.group(2).strip()


# ── Чтение листов ───────────────────────────────────────────────────────

def _header_map(header_row, expected: dict[str, str], sheet: str) -> dict[str, int]:
    """Подписи заголовков → номера колонок.

    Позиции колонок нигде в модуле не зашиты: книгу ведут руками, и
    вставленная колонка не должна превращать импорт в тихую порчу данных.
    Отсутствие ожидаемого заголовка — ошибка, и в ней перечисляется то, что
    реально нашлось: иначе разбираться пришлось бы, открывая файл глазами.
    """
    found = {}
    for index, cell in enumerate(header_row):
        label = _text(cell)
        if label:
            found.setdefault(label, index)

    mapping = {}
    missing = []
    for key, label in expected.items():
        if label in found:
            mapping[key] = found[label]
        else:
            missing.append(label)

    if missing:
        raise CashflowImportError(
            f"лист «{sheet}»: не найдены колонки {missing}. "
            f"Найдены: {sorted(found)}"
        )
    return mapping


def _rows(worksheet):
    """Строки листа как списки значений, с номером строки Excel."""
    for index, row in enumerate(worksheet.iter_rows(values_only=True), start=1):
        yield index, list(row)


def _is_blank(values) -> bool:
    return all(v is None or _text(v) == "" for v in values)


def read_budget_sheet(workbook) -> list[BudgetRow]:
    if SHEET_BUDGET not in workbook.sheetnames:
        raise CashflowImportError(
            f"в книге нет листа «{SHEET_BUDGET}» (есть: {workbook.sheetnames})"
        )
    sheet = workbook[SHEET_BUDGET]
    rows = _rows(sheet)
    try:
        _, header = next(rows)
    except StopIteration:
        raise CashflowImportError(f"лист «{SHEET_BUDGET}» пуст") from None

    columns = _header_map(header, BUDGET_COLUMNS, SHEET_BUDGET)

    def cell(values, key):
        index = columns[key]
        return values[index] if index < len(values) else None

    result = []
    for excel_row, values in rows:
        if _is_blank(values):
            continue
        code, name = split_program_cell(cell(values, "program"))
        result.append(BudgetRow(
            excel_row=excel_row,
            administrator=_text(cell(values, "administrator")),
            program_code=code,
            program_name=name,
            limit=_money(cell(values, "limit")),
            currency=_text(cell(values, "currency")).upper() or DEFAULT_CURRENCY,
        ))
    return result


def read_registry_sheet(workbook) -> tuple[list[RegistryRow], list[str]]:
    """Лист договоров → строки + предупреждения разбора.

    Строка, которую не удалось разобрать (не читается дата, аванс вне
    диапазона), в результат не попадает и превращается в предупреждение с
    номером строки Excel: остальные 42 договора не должны застревать из-за
    одной кривой ячейки.
    """
    if SHEET_REGISTRY not in workbook.sheetnames:
        raise CashflowImportError(
            f"в книге нет листа «{SHEET_REGISTRY}» (есть: {workbook.sheetnames})"
        )
    sheet = workbook[SHEET_REGISTRY]
    rows = _rows(sheet)
    try:
        _, header = next(rows)
    except StopIteration:
        raise CashflowImportError(f"лист «{SHEET_REGISTRY}» пуст") from None

    columns = _header_map(header, REGISTRY_COLUMNS, SHEET_REGISTRY)
    # Колонка настоящей длины БИН заголовка НЕ имеет — адресуется только
    # положением сразу за идентификатором LARK. Единственное место в модуле,
    # где колонка берётся по номеру, и другого способа у неё нет.
    bin_length_column = columns["external_id"] + 1

    parsed: list[RegistryRow] = []
    warnings: list[str] = []

    def cell(values, index):
        return values[index] if index is not None and index < len(values) else None

    for excel_row, values in rows:
        if _is_blank(values):
            continue

        external_id = _text(cell(values, columns["external_id"]))
        number = _text(cell(values, columns["number"]))
        if not external_id and not number:
            warnings.append(f"строка {excel_row}: нет ни номера, ни идентификатора — пропущена")
            continue

        try:
            advance_share = parse_advance_share(cell(values, columns["advance"]))
            signed_date = parse_excel_date(cell(values, columns["signed_date"]))
        except ValueError as exc:
            warnings.append(f"строка {excel_row} ({number or external_id}): {exc} — пропущена")
            continue

        bin_iin, bin_warning = normalize_bin(
            cell(values, columns["bin_iin"]), cell(values, bin_length_column),
        )
        if bin_warning:
            warnings.append(f"строка {excel_row} ({number or external_id}): {bin_warning}")
        if not bin_iin:
            warnings.append(f"строка {excel_row} ({number or external_id}): без БИН — пропущена")
            continue

        kind_label = _text(cell(values, columns["kind"])).lower()
        type_label = _text(cell(values, columns["contract_type"])).lower()
        if kind_label and kind_label not in KIND_BY_LABEL:
            warnings.append(
                f"строка {excel_row} ({number}): вид «{kind_label}» неизвестен — записан как РиУ"
            )
        if type_label and type_label not in TYPE_BY_LABEL:
            warnings.append(
                f"строка {excel_row} ({number}): тип «{type_label}» неизвестен — записан как стандартный"
            )

        raw_amount = cell(values, columns["amount"])
        has_amount = raw_amount is not None and _text(raw_amount) != ""

        parsed.append(RegistryRow(
            excel_row=excel_row,
            administrator=_text(cell(values, columns["administrator"])),
            program_code=_text(cell(values, columns["program_code"])),
            program_name=_text(cell(values, columns["program_name"])),
            number=number,
            name=_text(cell(values, columns["name"])),
            counterparty=_text(cell(values, columns["counterparty"])),
            bin_iin=bin_iin,
            amount=_money(raw_amount) if has_amount else ZERO,
            has_amount=has_amount,
            advance_share=advance_share,
            signed_date=signed_date,
            kind=KIND_BY_LABEL.get(kind_label, AgreementKind.WORKS_SERVICES),
            contract_type=TYPE_BY_LABEL.get(type_label, AgreementType.STANDARD),
            external_id=external_id,
        ))

    return parsed, warnings


# ── Отображение в модели ────────────────────────────────────────────────

def derive_payment_type(advance_share: Decimal) -> str:
    """Доля аванса → ``PaymentType``.

    Полной предоплате и полной постоплате соответствуют края диапазона; всё
    между ними — «поэтапно»: часть вперёд, часть по факту. Это ВЫВОД, а не
    перенос: отдельной колонки с типом оплаты в книге нет, а три ветки
    логики модулю нужны.
    """
    if advance_share <= 0:
        return PaymentType.POSTPAYMENT
    if advance_share >= 1:
        return PaymentType.PREPAYMENT
    return PaymentType.STAGED


def _strip_dots(number: str) -> str:
    return number.rstrip(".")


class _NumberAllocator:
    """Выдаёт незанятый номер договора, дописывая точки к повторам.

    ``Agreement.number`` уникален, а в реестре один номер носят до трёх
    разных договоров. Занятыми считаются и номера уже лежащие в базе — иначе
    импорт в непустую базу падал бы на ``IntegrityError`` вместо понятного
    отчёта.

    Договор, у которого уже есть строка в базе (нашли по ``external_id``),
    СВОЙ номер сохраняет: точки, выданные прошлым прогоном, должны пережить
    следующий, иначе ссылка на договор меняется от запуска к запуску.
    """

    def __init__(self, taken: set[str]):
        self._taken = set(taken)

    def reserve(self, number: str) -> None:
        self._taken.add(number)

    def allocate(self, base: str) -> tuple[str, bool]:
        candidate = base
        while candidate in self._taken:
            candidate += "."
        self._taken.add(candidate)
        return candidate, candidate != base


# ── Загрузка ────────────────────────────────────────────────────────────

@dataclass
class _References:
    """Справочники, разложенные по ключам, которыми к ним обращается реестр."""

    administrators: dict[str, Administrator] = field(default_factory=dict)
    programs: dict[str, Program] = field(default_factory=dict)
    budgets: dict[tuple[int, str], Budget] = field(default_factory=dict)
    lines: dict[tuple[str, str], BudgetLine] = field(default_factory=dict)


def _load_references(budget_rows: list[BudgetRow], registry_rows: list[RegistryRow],
                     *, year: int, country: Country,
                     report: ImportReport) -> _References:
    """Справочники и бюджет. Обязан отработать до договоров.

    Программы собираются из ОБОИХ листов: длинное название есть только в
    «Бюджете», короткое (статья расходов) — только в реестре, а часть кодов
    встречается лишь в одном из листов.
    """
    refs = _References()

    # Программы: код → (длинное название, короткое название).
    names: dict[str, str] = {}
    items: dict[str, str] = {}
    for row in budget_rows:
        if row.program_code:
            names.setdefault(row.program_code, row.program_name)
        elif row.program_name:
            report.warn(
                f"«{SHEET_BUDGET}» строка {row.excel_row}: "
                f"«{row.program_name}» без кода программы — строка бюджета пропущена"
            )
    for row in registry_rows:
        if row.program_code:
            items.setdefault(row.program_code, row.program_name)

    for code in sorted(set(names) | set(items)):
        # Название — из «Бюджета» (там оно полное), статья — из реестра.
        # Когда есть только одно из двух, оно идёт в оба поля: пустое
        # название программе запрещено, а пустая статья ничего не сообщает.
        name = names.get(code) or items.get(code, "")
        expense_item = items.get(code) or names.get(code, "")
        program, created = Program.objects.update_or_create(
            code=code, defaults={"name": name, "expense_item": expense_item},
        )
        refs.programs[code] = program
        report.bump("Program", created)

    # Администраторы: и из «Бюджета», и из реестра — часть проектов ведёт
    # договоры, не имея строки лимитов.
    admin_names = {row.administrator for row in budget_rows if row.administrator}
    admin_names |= {row.administrator for row in registry_rows if row.administrator}
    for project_name in sorted(admin_names):
        administrator, created = Administrator.objects.get_or_create(
            country=country, project_name=project_name,
        )
        refs.administrators[project_name] = administrator
        report.bump("Administrator", created)

    # Бюджеты-контейнеры: один на «администратор × год × валюта».
    #
    # Заводятся ПО ТРЕБОВАНИЮ, а не заранее по списку администраторов: валюта
    # входит в ключ, и проект, у которого на листе лимитов оказались строки в
    # двух валютах, должен получить два контейнера, а не уронить импорт на
    # отсутствующем ключе. Валюта договоров того же проекта берётся из его
    # строк бюджета (в реестре колонки валюты нет).
    currencies = {row.administrator: row.currency for row in budget_rows}

    def budget_for(project_name: str, currency: str) -> Budget:
        administrator = refs.administrators[project_name]
        key = (administrator.pk, currency)
        if key not in refs.budgets:
            budget, created = Budget.objects.get_or_create(
                administrator=administrator, period_year=year, currency=currency,
            )
            refs.budgets[key] = budget
            report.bump("Budget", created)
        return refs.budgets[key]

    # Строки бюджета из листа лимитов.
    for row in budget_rows:
        if not row.program_code or not row.administrator:
            continue
        line, created = BudgetLine.objects.update_or_create(
            budget=budget_for(row.administrator, row.currency),
            program=refs.programs[row.program_code],
            defaults={"amount": row.limit},
        )
        refs.lines[(row.administrator, row.program_code)] = line
        report.bump("BudgetLine", created)

    # Строки, на которые ссылается реестр, но которых нет в «Бюджете».
    # Договор без строки не сохранить, поэтому строка заводится с нулевым
    # лимитом — и это ровно тот случай, который обязан увидеть человек:
    # ноль означает, что весь договор лежит за пределами бюджета.
    for row in registry_rows:
        key = (row.administrator, row.program_code)
        if key in refs.lines or not row.program_code:
            continue
        currency = currencies.get(row.administrator, DEFAULT_CURRENCY)
        line, created = BudgetLine.objects.get_or_create(
            budget=budget_for(row.administrator, currency),
            program=refs.programs[row.program_code],
            defaults={
                "amount": ZERO,
                "note": f"Заведена импортом реестра договоров: лимит на листе «{SHEET_BUDGET}» отсутствует",
            },
        )
        refs.lines[key] = line
        report.bump("BudgetLine", created)
        if created:
            report.warn(
                f"нет лимита для «{row.administrator}» × программа {row.program_code} — "
                f"строка бюджета заведена с нулевым лимитом"
            )
    return refs


def _load_counterparties(registry_rows: list[RegistryRow], *, country: Country,
                         report: ImportReport) -> dict[str, Counterparty]:
    """Контрагенты, опознанные по БИН.

    Название ключом быть не может: одна организация приходит в разных
    написаниях. Побеждает первое встреченное, остальные — в отчёт; выбирать
    правильное написание за финансистов импорт не должен, а перезаписывать
    имя на каждой строке значило бы, что итог зависит от порядка строк.
    """
    by_bin: dict[str, Counterparty] = {}
    variants: dict[str, set[str]] = {}

    for row in registry_rows:
        variants.setdefault(row.bin_iin, set()).add(row.counterparty)
        if row.bin_iin in by_bin:
            continue
        counterparty, created = Counterparty.objects.get_or_create(
            bin_iin=row.bin_iin,
            defaults={"name": row.counterparty, "country": country},
        )
        by_bin[row.bin_iin] = counterparty
        report.bump("Counterparty", created)

    for bin_iin, names in sorted(variants.items()):
        if len(names) > 1:
            report.warn(
                f"БИН {bin_iin}: в реестре несколько написаний "
                f"({', '.join(sorted(names))}) — сохранено «{by_bin[bin_iin].name}»"
            )
    return by_bin


def _load_agreements(registry_rows: list[RegistryRow], refs: _References,
                     counterparties: dict[str, Counterparty], *,
                     status: str, report: ImportReport) -> None:
    external_ids = [row.external_id for row in registry_rows if row.external_id]
    existing = {
        agreement.external_id: agreement
        for agreement in Agreement.objects.filter(external_id__in=external_ids)
    }

    # Занятыми считаются номера ВСЕХ договоров базы, кроме тех, которые этот
    # прогон и так перезапишет — иначе договор конфликтовал бы сам с собой.
    reserved_ids = {agreement.pk for agreement in existing.values()}
    taken = set(
        Agreement.objects.exclude(pk__in=reserved_ids).values_list("number", flat=True)
    )
    allocator = _NumberAllocator(taken)

    # Номера, уже выданные прошлым прогоном, закрепляются за своими
    # договорами до раздачи новых: иначе точки переехали бы на другие строки.
    for row in registry_rows:
        agreement = existing.get(row.external_id)
        if agreement is not None and _strip_dots(agreement.number) == row.number:
            allocator.reserve(agreement.number)

    for row in registry_rows:
        line = refs.lines.get((row.administrator, row.program_code))
        if line is None:
            report.warn(
                f"строка {row.excel_row} ({row.number}): не найдена строка бюджета "
                f"«{row.administrator}» × {row.program_code} — договор пропущен"
            )
            continue

        counterparty = counterparties.get(row.bin_iin)
        if counterparty is None:
            report.warn(
                f"строка {row.excel_row} ({row.number}): контрагент {row.bin_iin} "
                f"не заведён — договор пропущен"
            )
            continue

        agreement = existing.get(row.external_id)
        if agreement is not None and _strip_dots(agreement.number) == row.number:
            number = agreement.number
        else:
            number, suffixed = allocator.allocate(row.number)
            if suffixed:
                report.warn(
                    f"строка {row.excel_row}: номер «{row.number}» уже занят "
                    f"(«{row.name}», {row.counterparty}) — сохранён как «{number}»"
                )

        if not row.has_amount and row.contract_type != AgreementType.FRAMEWORK:
            report.warn(
                f"строка {row.excel_row} («{number}»): суммы нет, "
                f"но договор не помечен открытым — записан нулём"
            )

        agreement, created = Agreement.objects.update_or_create(
            external_id=row.external_id,
            defaults={
                "number": number,
                "name": row.name,
                "budget_line": line,
                "counterparty": counterparty,
                "amount": row.amount,
                "advance_share": row.advance_share,
                "payment_type": derive_payment_type(row.advance_share),
                "kind": row.kind,
                "contract_type": row.contract_type,
                # Валюта снимается с бюджета, а не принимается из книги: в
                # реестре её колонки нет, а договор всегда в валюте того
                # бюджета, из которого он оплачивается (так же поступает и
                # Invoice — см. его докстринг).
                "currency": line.budget.currency,
                "signed_date": row.signed_date,
                "status": status,
                # ``approval_state`` НЕ передаётся: колонку ведёт signoff.
            },
        )
        report.bump("Agreement", created)


def _report_overruns(refs: _References, report: ImportReport) -> None:
    """Посчитать, где загруженные договоры вышли за лимит строки.

    Импорт перерасход не запрещает (переносится уже случившийся факт), но
    молчать о нём нельзя: строка с отрицательным остатком выглядит в
    интерфейсе как ошибка расчёта, пока не знаешь, что так пришло из книги.
    """
    from apps.contracts.services import budget_calc

    lines = list(refs.lines.values())
    committed = budget_calc.committed_map([line.pk for line in lines])
    for key, line in sorted(refs.lines.items()):
        used = committed.get(line.pk, ZERO)
        if used > line.amount:
            report.overruns.append(
                f"«{key[0]}» × программа {key[1]}: договоров на {used}, "
                f"лимит {line.amount} (перерасход {used - line.amount})"
            )


class _Rollback(Exception):
    """Внутренний сигнал отката для ``--dry-run``."""


def load_workbook_file(path):
    """Открыть книгу. Отдельной функцией — чтобы тесты подменяли источник."""
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover — зависимость объявлена
        raise CashflowImportError(
            "не установлен openpyxl (см. backend/requirements.txt)"
        ) from exc
    # ``data_only``: нужны значения формул, а не сами формулы — часть сумм в
    # книге посчитана выражениями.
    return load_workbook(path, read_only=True, data_only=True)


def run_import(path, *, year: int | None = None, country_name: str = DEFAULT_COUNTRY,
               status: str = AgreementStatus.SIGNED,
               dry_run: bool = False) -> ImportReport:
    """Прочитать книгу и загрузить её. Единственная точка входа модуля.

    ``year`` — год бюджетов-контейнеров. По умолчанию берётся из самой
    поздней даты подписания в реестре: в книге года нет, а выдумывать
    текущий нельзя — файл прошлого года завёл бы бюджеты не того периода.
    """
    workbook = load_workbook_file(path)
    try:
        budget_rows = read_budget_sheet(workbook)
        registry_rows, parse_warnings = read_registry_sheet(workbook)
    finally:
        workbook.close()

    report = ImportReport(dry_run=dry_run)
    report.rows_read = len(registry_rows)
    for warning in parse_warnings:
        report.warn(warning)

    if not registry_rows:
        raise CashflowImportError(f"на листе «{SHEET_REGISTRY}» нет ни одной строки данных")

    if year is None:
        dates = [row.signed_date for row in registry_rows if row.signed_date]
        if not dates:
            raise CashflowImportError(
                "не удалось определить год бюджета: в реестре нет ни одной "
                "даты подписания — укажите --year явно"
            )
        year = max(dates).year

    try:
        with transaction.atomic():
            country, created = Country.objects.get_or_create(name=country_name)
            report.bump("Country", created)

            refs = _load_references(budget_rows, registry_rows, year=year,
                                    country=country, report=report)
            counterparties = _load_counterparties(registry_rows, country=country,
                                                  report=report)
            _load_agreements(registry_rows, refs, counterparties,
                             status=status, report=report)
            _report_overruns(refs, report)

            if dry_run:
                raise _Rollback
    except _Rollback:
        pass

    return report

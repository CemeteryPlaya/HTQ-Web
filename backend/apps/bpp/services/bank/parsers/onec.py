"""Выписка 1С — формат обмена 1CClientBankExchange (ТЗ §11.2, §11.3 п.1–2,
E-IMP-01; план этапа 3 A, задача 3, решение D-S3-3).

Файл текстовый, строки ``Ключ=Значение``, обычно в кодировке Windows-1251
(``Кодировка=Windows``) и с переводами строк CRLF; ``Кодировка=DOS`` —
cp866. Первая строка — ``1CClientBankExchange``, без неё файл не выписка
1С (E-IMP-01, текст ТЗ §26.1 дословно). Документы — между
``СекцияДокумент=…`` и ``КонецДокумента``; секции ``СекцияРасчСчет`` …
``КонецРасчСчет`` и строки заголовка несут период (``ДатаНачала``/
``ДатаКонца``) и счёт выписки (``РасчСчет``).

Примеров выписок казахстанских банков ещё нет (В-13, Q-B26), поэтому поля
читаются по стандарту формата с синонимами казахстанского варианта:
первое непустое из списка ``FIELDS``. Когда примеры появятся, правка — в
этом словаре.

Списание (п.2) — документ, где счёт плательщика = IBAN счёта организации;
остальные (поступления и чужие платежи) в файле считаются, но не
загружаются. Нераспознанная дата или сумма списания — в список ошибок
«Строка N: …», где N — номер строки файла с этим полем; остальные
документы читаются дальше. Поступления и чужие платежи не проверяются:
ошибка в том, что не загружается, исправлять некому. Документ без
плательщика не загружается, но проверяется — чей он, не понять.
"""

from __future__ import annotations

import codecs
from datetime import datetime

from htqweb.errors import DomainError

from .. import templates
from . import MAX_ROWS, ParsedStatement, line, too_many_rows

__all__ = ["FIELDS", "HEADER", "NO_PAYER", "normalize_iban", "parse", "precheck"]

HEADER = "1CClientBankExchange"
NO_PAYER = ("В выписке нет счёта плательщика — списания не определены. Ни у одного "
            "документа нет поля ПлательщикСчет (ПлательщикИИК): проверьте выгрузку из "
            "банк-клиента.")
DATE_PATTERN = "%d.%m.%Y"

#: Поле → ключи 1С по порядку предпочтения (D-S3-3). ``ДатаСписано`` —
#: дата списания со счёта, у списания она точнее даты документа.
FIELDS: dict[str, tuple[str, ...]] = {
    "date": ("ДатаСписано", "Дата"),
    "doc_number": ("Номер",),
    "amount": ("Сумма",),
    "currency": ("Валюта", "КодВалюты"),
    "payer_account": ("ПлательщикСчет", "ПлательщикИИК", "ПлательщикРасчСчет"),
    "recipient_account": ("ПолучательСчет", "ПолучательИИК", "ПолучательРасчСчет"),
    "recipient_bin": ("ПолучательИНН", "ПолучательБИН", "ПолучательИИН"),
    "recipient_name": ("Получатель1", "Получатель"),
    "purpose": ("НазначениеПлатежа",),
}
_PURPOSE_PARTS = tuple(f"НазначениеПлатежа{n}" for n in range(1, 7))


def _format_error() -> DomainError:
    # ТЗ §26.1, E-IMP-01 — дословно.
    message = ("Файл не распознан как выписка формата 1С: нет строки „1CClientBankExchange“. "
               "Выберите другой формат или файл.")
    return DomainError("E-IMP-01", message, fields=[{"field": "file", "message": message}])


def _decode(content: bytes, encoding: str) -> list[str]:
    """Строки файла. Заголовок проверяется до декодирования: он ASCII в
    любой из кодировок формата. BOM UTF-8 — признак UTF-8."""
    raw = content
    if raw.startswith(codecs.BOM_UTF8):
        raw, encoding = raw[len(codecs.BOM_UTF8):], "utf-8"
    first = raw.lstrip().split(b"\n", 1)[0].strip()
    if first != HEADER.encode("ascii"):
        raise _format_error()
    head = raw[:4096]
    if any("Кодировка=DOS".encode(enc) in head for enc in ("cp866", "cp1251", "utf-8")):
        encoding = "cp866"
    try:
        text = raw.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            message = (f"Выписку 1С не удалось прочитать в кодировке {encoding}. Выгрузите "
                       f"её из банк-клиента заново (кодировка Windows) или выберите "
                       f"другой файл.")
            raise DomainError("E-IMP-01", message,
                              fields=[{"field": "file", "message": message}]) from exc
    return text.splitlines()  # CRLF, LF и CR — одинаково


def _date_or_none(value: str | None):
    try:
        return datetime.strptime((value or "").strip(), DATE_PATTERN).date()
    except ValueError:
        return None


def _pick(doc: dict, field: str) -> tuple[str, int | None]:
    """Первое непустое значение поля по синонимам и номер его строки."""
    for key in FIELDS[field]:
        value, line_no = doc.get(key, ("", None))
        if value:
            return value, line_no
    return "", None


def _purpose(doc: dict) -> str:
    value, _ = _pick(doc, "purpose")
    if value:
        return value
    return " ".join(doc[key][0] for key in _PURPOSE_PARTS if doc.get(key, ("",))[0])


def _read_sections(lines: list[str]) -> tuple[dict, set[str], list[dict]]:
    """Заголовок (ключ → значение), счета выписки и документы — словари
    «ключ → (значение, номер строки)» с ``__line`` — строкой начала."""
    header: dict[str, str] = {}
    accounts: set[str] = set()
    docs: list[dict] = []
    current: dict | None = None
    for line_no, raw in enumerate(lines, start=1):
        text = raw.strip()
        if not text:
            continue
        if text.startswith("СекцияДокумент"):
            if current is not None:  # не закрытый предыдущий документ
                docs.append(current)
            current = {"__line": line_no}
            if len(docs) >= MAX_ROWS:
                raise too_many_rows()
            continue
        if text == "КонецДокумента":
            if current is not None:
                docs.append(current)
            current = None
            continue
        if text == "КонецФайла":
            break
        key, sep, value = text.partition("=")
        if not sep:
            continue  # СекцияРасчСчет, КонецРасчСчет и прочие маркеры
        key, value = key.strip(), value.strip()
        if current is not None:
            current.setdefault(key, (value, line_no))
        elif key == "РасчСчет":
            if value:
                accounts.add(normalize_iban(value))
        else:
            header.setdefault(key, value)
    if current is not None:
        docs.append(current)
    if len(docs) > MAX_ROWS:
        raise too_many_rows()
    return header, accounts, docs


def normalize_iban(value: str) -> str:
    """IBAN для сравнения: без пробелов, в верхнем регистре."""
    return "".join((value or "").split()).upper()


def _read(content: bytes, encoding: str) -> tuple[dict, set[str], list[dict]]:
    return _read_sections(_decode(content, encoding or "cp1251"))


def _check_account(accounts: set[str], account) -> str:
    """IBAN счёта организации; выписка по другому счёту (``РасчСчет``
    заголовка не совпал) — ``E-VAL-01``: загрузить её в чужой счёт значило
    бы молча не найти ни одного списания."""
    own = normalize_iban(account.iban)
    if accounts and own not in accounts:
        message = (f"Выписка выгружена по счёту {', '.join(sorted(accounts))}, а выбран "
                   f"счёт {own}. Выберите счёт организации, по которому выгружена выписка.")
        raise DomainError("E-VAL-01", message,
                          fields=[{"field": "account_id", "message": message}])
    return own


def precheck(content: bytes, *, account, encoding: str = "cp1251") -> dict:
    """Быстрая проверка при загрузке — до сохранения файла и постановки
    разбора в очередь: это выписка 1С (E-IMP-01), документов не больше
    ``MAX_ROWS`` (E-IMP-03), счёт тот (E-VAL-01). Ответ — период из
    заголовка файла (``period_from``/``period_to``, ``None`` — нет) и число
    документов (``documents``)."""
    header, accounts, docs = _read(content, encoding)
    _check_account(accounts, account)
    return {"period_from": _date_or_none(header.get("ДатаНачала")),
            "period_to": _date_or_none(header.get("ДатаКонца")),
            "documents": len(docs)}


def parse(content: bytes, *, account, encoding: str = "cp1251") -> ParsedStatement:
    """Разобрать выписку 1С по счёту организации ``account``."""
    header, accounts, docs = _read(content, encoding)
    own = _check_account(accounts, account)

    result = ParsedStatement(rows_total=len(docs),
                             period_from=_date_or_none(header.get("ДатаНачала")),
                             period_to=_date_or_none(header.get("ДатаКонца")))
    for doc in docs:
        row_no = doc["__line"]
        # Сначала — чей документ: поступление и платёж чужого счёта не
        # загружаются, и их дата или сумма ошибкой строки не считаются —
        # иначе карточка звала бы исправлять то, что в базу не попало бы
        # всё равно. Плательщика нет — списание ли это, не понять: ошибки
        # такого документа показываются (как и ``NO_PAYER`` ниже).
        payer, _ = _pick(doc, "payer_account")
        if payer and normalize_iban(payer) != own:
            continue  # поступление или чужой платёж — не списание этого счёта
        raw_date, date_line = _pick(doc, "date")
        try:
            doc_date = templates.parse_date(raw_date, DATE_PATTERN)
        except ValueError:
            result.errors.append(
                f"Строка {date_line or row_no}: не распознана дата „{raw_date}“")
            continue
        raw_amount, amount_line = _pick(doc, "amount")
        try:
            amount = templates.parse_amount(raw_amount)
        except ValueError as exc:
            result.errors.append(templates.amount_error(amount_line or row_no, raw_amount, exc))
            continue
        if not amount or amount <= 0:
            result.errors.append(templates.amount_error(amount_line or row_no, raw_amount))
            continue
        doc_number, _ = _pick(doc, "doc_number")
        if not doc_number:
            result.errors.append(f"Строка {row_no}: нет номера документа")
            continue
        if not payer:
            continue  # списание ли это, не понять — не загружается
        currency, _ = _pick(doc, "currency")
        recipient_bin, _ = _pick(doc, "recipient_bin")
        recipient_iban, _ = _pick(doc, "recipient_account")
        recipient_name, _ = _pick(doc, "recipient_name")
        result.lines.append(line(
            row_no=row_no, doc_date=doc_date, doc_number=doc_number, amount=amount,
            currency=currency if len(currency) == 3 and currency.isalpha() else account.currency,
            recipient_name=recipient_name, recipient_bin="".join(recipient_bin.split()),
            recipient_iban=normalize_iban(recipient_iban), purpose=_purpose(doc)))
    if docs and not any(_pick(doc, "payer_account")[0] for doc in docs):
        # Без плательщика списание не отличить от поступления: не «0
        # списаний» молча, а строка ошибки в карточке загрузки.
        result.errors.insert(0, NO_PAYER)
    return result

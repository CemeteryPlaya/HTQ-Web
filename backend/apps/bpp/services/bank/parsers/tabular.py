"""Выписка Excel и CSV — только по шаблону банка (ТЗ §11.3 п.1–2; план
этапа 3 A, задача 3, решение D-S3-3: код не знает ни одного банка).

Чтение строк, поиск заголовка, разбор даты и суммы — ``services/bank/
templates.py`` (задача 2, им же пользуется предпросмотр шаблона): здесь
только отбор списаний своего счёта и итоги.

- Строка данных — любая строка после заголовка, кроме пустых и «подвалов»
  без даты, номера и суммы (``templates.read_row`` отдаёт ``None``).
  Нераспознанная строка — в ``errors`` «Строка N: …» и в ``rows_total``:
  она в файле есть, просто не прочитана.
- Списание — ``direction == "debit"`` (отрицательная сумма в режиме
  ``signed``, непустой дебет в ``split``). Поступления считаются, но не
  загружаются.
- Колонка «Счёт плательщика» в шаблоне необязательна: выписка банк-клиента
  выгружается по одному счёту, и строка без плательщика — операция этого
  счёта. Непустой плательщик, не равный IBAN счёта организации, — чужой
  платёж, не загружается.
- Строк данных больше ``MAX_ROWS`` — ``E-IMP-03`` целиком; счёт идёт по
  ходу чтения, дальше предела файл не читается.
"""

from __future__ import annotations

from .. import templates
from . import MAX_ROWS, ParsedStatement, line, too_many_rows
from .onec import normalize_iban

__all__ = ["parse", "precheck"]


def _data_rows(content: bytes, name: str, template):
    """(номер строки, строка) после заголовка — лениво; заголовок не
    найден — ``E-IMP-02``, файл не того формата — ``E-IMP-01``."""
    rows = templates.table_rows(content, name, template)
    try:
        _header_row, columns = templates.find_header(rows, template)
        yield columns
        yield from rows
    finally:
        rows.close()


def precheck(content: bytes, *, name: str, template) -> dict:
    """Быстрая проверка при загрузке — до сохранения файла: формат
    (E-IMP-01), заголовок шаблона (E-IMP-02) и предел строк (E-IMP-03).
    Строки не разбираются — только считаются непустые после заголовка.
    Периода файл Excel/CSV не несёт: ``period_from``/``period_to`` — ``None``."""
    documents = 0
    reader = _data_rows(content, name, template)
    try:
        next(reader)  # колонки
        for _row_no, row in reader:
            if all(value is None or (isinstance(value, str) and not value.strip())
                   for value in row):
                continue
            documents += 1
            if documents > MAX_ROWS:
                raise too_many_rows()
    finally:
        reader.close()
    return {"period_from": None, "period_to": None, "documents": documents}


def parse(content: bytes, *, name: str, template, account) -> ParsedStatement:
    """Разобрать выписку Excel/CSV по шаблону ``template`` счёта ``account``."""
    own = normalize_iban(account.iban)
    pattern = templates.date_pattern(template.date_format)
    result = ParsedStatement()
    reader = _data_rows(content, name, template)
    try:
        columns = next(reader)
        for row_no, row in reader:
            try:
                values = templates.read_row(row, columns, template, pattern, row_no)
            except ValueError as exc:
                values, error = None, str(exc)
            else:
                error = None
                if values is None:
                    continue
            result.rows_total += 1
            if result.rows_total > MAX_ROWS:
                raise too_many_rows()
            if error is not None:
                result.errors.append(error)
                continue
            if values["direction"] != "debit":
                continue  # поступление
            payer = normalize_iban(values.get("payer_account") or "")
            if payer and payer != own:
                continue  # чужой платёж
            currency = (values.get("currency") or "").strip().upper()
            result.lines.append(line(
                row_no=row_no, doc_date=values["date"], doc_number=values["doc_number"],
                amount=values["amount"],
                currency=currency if len(currency) == 3 and currency.isalpha()
                else account.currency,
                recipient_name=values.get("recipient_name") or "",
                recipient_bin="".join((values.get("recipient_bin") or "").split()),
                recipient_iban=normalize_iban(values.get("recipient_iban") or ""),
                purpose=values.get("purpose") or ""))
    finally:
        reader.close()
    return result

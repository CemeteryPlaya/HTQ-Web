"""Помощники тестов счетов организации и шаблонов выписок (A3.1).

Файлы образцов собираются в тесте (openpyxl, csv) — бинарных фикстур в
репозитории нет. IBAN — с верной контрольной суммой, по той же независимой
записи ISO 13616, что у тестов контрагентов.
"""

from __future__ import annotations

import csv
import io
import zipfile

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.bpp.models.bank import StatementTemplate
from apps.bpp.tests.counterparties.common import kz_iban

__all__ = ["HEADERS", "csv_file", "iban", "template", "truncated_xlsx", "xlsx_file"]

#: Заголовки «как у банка» → поле шаблона.
HEADERS = {
    "date": "Дата операции",
    "doc_number": "№ документа",
    "amount": "Сумма",
    "purpose": "Назначение платежа",
    "recipient_name": "Получатель",
    "recipient_bin": "БИН/ИИН получателя",
}


def iban(n: int = 1) -> str:
    return kz_iban(f"998{n:013d}")


def template(**over) -> StatementTemplate:
    """Несохранённый шаблон Excel — для разбора он и не нужен в базе."""
    data = {"name": "Банк Excel", "format": "xlsx", "encoding": "utf-8",
            "delimiter": ";", "date_format": "ДД.ММ.ГГГГ",
            "columns": dict(HEADERS), "amount_mode": "signed", **over}
    return StatementTemplate(**data)


def xlsx_file(rows, name: str = "vypiska.xlsx") -> SimpleUploadedFile:
    book = openpyxl.Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(list(row))
    out = io.BytesIO()
    book.save(out)
    return SimpleUploadedFile(
        name, out.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def truncated_xlsx(rows, name: str = "vypiska.xlsx") -> SimpleUploadedFile:
    """Книга, у которой XML листа оборван посередине: архив цел и книга
    открывается, а ломается уже чтение строк."""
    whole = zipfile.ZipFile(io.BytesIO(xlsx_file(rows).read()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as broken:
        for info in whole.infolist():
            data = whole.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                data = data[: len(data) // 2]
            broken.writestr(info, data)
    return SimpleUploadedFile(
        name, out.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def csv_file(rows, *, name: str = "vypiska.csv", delimiter: str = ";",
             encoding: str = "cp1251") -> SimpleUploadedFile:
    text = io.StringIO()
    writer = csv.writer(text, delimiter=delimiter, lineterminator="\r\n")
    for row in rows:
        writer.writerow(row)
    return SimpleUploadedFile(name, text.getvalue().encode(encoding), content_type="text/csv")

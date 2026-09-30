"""Помощники тестов счетов организации, шаблонов выписок (A3.1) и загрузки
выписки (A4.1).

Файлы образцов собираются в тесте (openpyxl, csv, текст 1С в cp1251 с
CRLF) — бинарных фикстур в репозитории нет. IBAN — с верной контрольной суммой, по той же независимой
записи ISO 13616, что у тестов контрагентов.
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, timedelta
from decimal import Decimal

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.bpp.models.bank import (
    BankImport,
    BankImportStatus,
    BankStatementLine,
    OrgBankAccount,
    StatementTemplate,
)
from apps.bpp.tests.counterparties.common import kz_iban

__all__ = ["HEADERS", "counterparty", "csv_file", "iban", "loaded_import", "onec_bytes",
           "onec_doc", "onec_file", "orm_invoice", "org_account", "template", "truncated_xlsx",
           "xlsx_file"]

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


# ── выписка 1С (1CClientBankExchange) ──────────────────────────────────

def onec_doc(number: str, day: str, amount: str, payer: str, *,
             recipient_bin: str = "050140000656", recipient: str = "ТОО «Ромашка»",
             recipient_iban: str = "", purpose: str = "Оплата по счёту СЧ-2026-000001",
             payer_key: str = "ПлательщикИИК", bin_key: str = "ПолучательБИН",
             date_key: str = "Дата", extra: tuple[str, ...] = ()) -> list[str]:
    """Строки одного документа ``СекцияДокумент`` … ``КонецДокумента``."""
    return ["СекцияДокумент=Платежное поручение", f"Номер={number}", f"{date_key}={day}",
            f"Сумма={amount}", f"{payer_key}={payer}", f"{bin_key}={recipient_bin}",
            f"Получатель1={recipient}", f"ПолучательИИК={recipient_iban}",
            f"НазначениеПлатежа={purpose}", *extra, "КонецДокумента"]


def onec_lines(account_iban: str, docs, *, header: bool = True,
               period: tuple[str, str] | None = ("01.09.2026", "30.09.2026")) -> list[str]:
    head = ["1CClientBankExchange"] if header else []
    head += ["ВерсияФормата=1.03", "Кодировка=Windows", "Отправитель=Бухгалтерия"]
    if period:
        head += [f"ДатаНачала={period[0]}", f"ДатаКонца={period[1]}"]
    head += ["СекцияРасчСчет", f"РасчСчет={account_iban}", "КонецРасчСчет"]
    body = [text for doc in docs for text in doc]
    return [*head, *body, "КонецФайла"]


def onec_bytes(account_iban: str, docs, **kwargs) -> bytes:
    """Выписка 1С как её отдаёт банк-клиент: cp1251 и CRLF."""
    return "\r\n".join(onec_lines(account_iban, docs, **kwargs)).encode("cp1251") + b"\r\n"


def onec_file(account_iban: str, docs, *, name: str = "kl_to_1c.txt",
              **kwargs) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, onec_bytes(account_iban, docs, **kwargs),
                              content_type="text/plain")


# ── загрузка «Загружена» без разбора файла (сверка, A4.2) ──────────────

def org_account(n: int = 1) -> OrgBankAccount:
    """Счёт организации с шаблоном 1С — прямо в базе, без журнала и прав
    (для тестов сверки, где разбор файла не проверяется)."""
    tpl = StatementTemplate.objects.create(name=f"Шаблон 1С {n}", format="onec", columns={})
    return OrgBankAccount.objects.create(iban=iban(n), bank_name="Halyk Bank", bic="HSBKKZKX",
                                         currency="KZT", template=tpl)


def loaded_import(account: OrgBankAccount, lines, *, author_id: int | None = None
                  ) -> BankImport:
    """Загрузка «Загружена» со строками ``lines`` — словари ``amount``,
    ``purpose`` и (по желанию) ``recipient_bin``, ``currency``, ``doc_number``,
    ``doc_date``. Ключ дубля — как у настоящей загрузки."""
    from apps.bpp.services.bank.imports import dedup_hash

    today = date.today()
    seq = BankImport.objects.count() + 1
    imp = BankImport.objects.create(
        number=f"ВП-2026-{9000 + seq:04d}", account=account, format="onec",
        period_from=today - timedelta(days=7), period_to=today, filename="kl_to_1c.txt",
        author_id=author_id, status=BankImportStatus.LOADED)
    for row_no, item in enumerate(lines, start=1):
        amount = Decimal(str(item["amount"]))
        doc_number = item.get("doc_number") or f"{seq}-{row_no}"
        doc_date = item.get("doc_date") or today
        recipient_bin = item.get("recipient_bin", "")
        BankStatementLine.objects.create(
            bank_import=imp, account=account, row_no=row_no, doc_date=doc_date,
            doc_number=doc_number, amount=amount, currency=item.get("currency", "KZT"),
            recipient_bin=recipient_bin, purpose=item.get("purpose", ""),
            dedup_hash=dedup_hash(account.pk, doc_date=doc_date, doc_number=doc_number,
                                  amount=amount, recipient_bin=recipient_bin))
    return imp


# ── счёт прямо в базе (сверка, A4.2, задача 3) ─────────────────────────

def counterparty(reg: str = "100000000001", **over):
    """Контрагент прямо в базе — как ``test_invoices._counterparty``."""
    from apps.bpp.models import Counterparty

    fields = {"name": f"ТОО «Контрагент {reg[-3:]}»", "kind": "legal", "country_code": "KZ",
              "reg_number": reg, "is_vat_payer": True, "verified_override": True, **over}
    return Counterparty.objects.create(**fields)


def orm_invoice(cp, amount, *, status: str = "to_pay", currency: str = "KZT",
                author_id: int = 904):
    """Счёт в нужном статусе прямо в базе, без потока B: сверке нужны только
    номер, статус, сумма, валюта и контрагент. Номер и номер счёта
    контрагента — уникальные по базе."""
    import uuid

    from apps.bpp.models import Invoice

    seq = Invoice.objects.count() + 1
    return Invoice.objects.create(
        number=f"СЧ-2026-{800000 + seq:06d}", project_id=uuid.uuid4(),
        article_id=uuid.uuid4(), counterparty=cp, ext_number=f"E-{seq}",
        ext_date=date.today(), amount=Decimal(str(amount)), currency_code=currency,
        status=status, author_id=author_id)

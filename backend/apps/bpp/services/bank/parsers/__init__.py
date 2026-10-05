"""Разбор файла выписки (ТЗ §11.3 п.1–2, задача A4.1).

Два разборщика с одним результатом ``ParsedStatement``:

- ``onec`` — 1CClientBankExchange по стандарту формата (D-S3-3: имена полей
  с синонимами казахстанского варианта);
- ``tabular`` — Excel и CSV по шаблону банка (``services/bank/templates.py``).

Оба отдают только списания со счёта организации (п.2), нераспознанные
строки — списком «Строка N: …» (п.1), а файл больше ``MAX_ROWS`` документов
отвергают целиком (``E-IMP-03``, ТЗ §11.2: «до 10 000 строк»). Дубли (п.3)
отсекает запись в базу (``services/bank/imports.py``), не разбор.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from htqweb.errors import DomainError

__all__ = ["MAX_ROWS", "ParsedStatement", "line", "too_many_rows"]

MAX_ROWS = 10_000


@dataclass
class ParsedStatement:
    """Итог разбора.

    ``rows_total`` — документов (строк данных) в файле, ``lines`` — списания
    со счёта организации: ``{row_no, doc_date, doc_number, amount (Decimal >
    0), currency, recipient_name, recipient_bin, recipient_iban, purpose}``;
    ``errors`` — «Строка N: …»; ``period_from``/``period_to`` — период из
    самого файла, если он его несёт (заголовок 1С), иначе ``None``."""

    rows_total: int = 0
    lines: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    period_from: date | None = None
    period_to: date | None = None


def too_many_rows() -> DomainError:
    limit = f"{MAX_ROWS:,}".replace(",", " ")
    message = (f"В файле больше {limit} строк — столько за одну загрузку не принимается. "
               f"Выгрузите выписку за период покороче и загрузите её частями.")
    return DomainError("E-IMP-03", message, fields=[{"field": "file", "message": message}])


def line(*, row_no: int, doc_date: date, doc_number: str, amount: Decimal, currency: str,
         recipient_name: str = "", recipient_bin: str = "", recipient_iban: str = "",
         purpose: str = "") -> dict:
    """Строка списания в единой форме обоих разборщиков."""
    return {"row_no": row_no, "doc_date": doc_date, "doc_number": doc_number[:64],
            "amount": amount, "currency": (currency or "")[:3].upper(),
            "recipient_name": recipient_name[:500], "recipient_bin": recipient_bin[:32],
            "recipient_iban": recipient_iban[:34], "purpose": purpose}

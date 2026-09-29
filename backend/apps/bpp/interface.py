"""Межаппный интерфейс модуля БЗО (для tasks и notifications).

Каждая функция первой строкой зовёт ``require_service("bpp")``.
"""

from __future__ import annotations

from apps.core.services import require_service


def closing_docs_pending_for_user(user_id: int) -> list[dict]:
    """Счета автора в «Ждёт закрывающих документов» — для раздела ежедневной
    сводки (контракт §2.6, A3.2, D-13): ``[{invoice_id, number, title, url,
    since, days}]``. Зовётся в контексте компании."""
    require_service("bpp")
    from apps.bpp.services.invoices import payments

    return payments.closing_docs_pending_for_user(user_id)


def find_by_number(number: str) -> dict | None:
    """Счёт по системному номеру ``СЧ-ГГГГ-NNNNNN`` — для сверки выписки
    (контракт §2.6, A4.2): ``{id, number, status, amount, currency_code,
    counterparty_reg_number, paid_bank_amount, recon_status}`` или ``None``."""
    require_service("bpp")
    from apps.bpp.services.invoices import read

    return read.find_by_number(number)

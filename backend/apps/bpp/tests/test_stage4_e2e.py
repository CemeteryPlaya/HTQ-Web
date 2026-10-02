"""Сквозная проверка этапа 4 (задача 7 плана этапа 4 A, шаг 1).

Одна история на настоящих сервисах: оплата → выписка → автосверка →
дашборд «Оплаты» → отмена загрузки → повторная загрузка.

1. Счёт проходит поток B: отправлен → ФД «Оплатить» → БУХ «Оплачено»
   (отметка оплаты БУХ, ``payments.mark_paid``).
2. Выписка 1С с «грязным» номером счёта в назначении — автосверка (A4.2)
   сопоставляет строку, загрузка «Сверена», счёт «Оплачен полностью». Дашборд:
   ``full`` = 1, ``bank_unconfirmed`` = 0.
3. «Отменить загрузку»: строки и сопоставления отменены, у счёта «Нет данных
   банка», отметка БУХ осталась — через 4 рабочих дня (дата подменена)
   ``bank_unconfirmed`` = 1, ``full`` = 0.
4. Та же выписка грузится снова (ключи дублей освобождены) — строка снова
   «Сопоставлена», счёт «Оплачен полностью».

Всё идёт сервисами внутри ``use_company`` (фикстура ``company_context``):
HTTP-ответ сбросил бы ``search_path``, а тут он не нужен.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.bpp.models import InvoiceStatus
from apps.bpp.models.bank import BankImportStatus, BankStatementLine, LineMatchStatus
from apps.bpp.models.invoices import ReconStatus
from apps.bpp.services.bank import imports, matching
from apps.bpp.services.bank import settings as bank_settings
from apps.bpp.services.dashboard import payments as dashboard
from apps.bpp.services.invoices import decisions, payments
from apps.bpp.services.invoices import read as invoices_read
from apps.bpp.tests import stage2 as s
from apps.bpp.tests import test_invoices as invoice_flow
from apps.bpp.tests.bank import common
from apps.bpp.tests.test_files import memory_storage  # noqa: F401  (фикстура: хранилище в памяти)
from apps.refdata import interface as refdata

pytestmark = pytest.mark.django_db

ADM = 951
AMOUNT = 1000


def _paid_invoice(slug):
    """Шаг 1: счёт на 1000 ₸ проведён до «Оплачено» отметкой БУХ."""
    _, _, inv = invoice_flow._submitted(slug, AMOUNT)
    inv = decisions.decide(invoice_flow._fd(slug), inv.id, decision="pay")
    inv = payments.mark_paid(invoice_flow._buh(slug), inv.id,
                             pay_date=timezone.localdate(), amount=AMOUNT)
    assert inv.status == InvoiceStatus.PAID
    return inv


def _org_account():
    tpl = bank_settings.create_template({"name": "Шаблон 1С", "format": "onec", "columns": {}},
                                        actor_id=ADM)
    return bank_settings.create_account(
        {"iban": common.iban(1), "bank_name": "Halyk Bank", "bic": "HSBKKZKX",
         "currency": "KZT", "template_id": str(tpl.pk)}, actor_id=ADM)


def _dirty(number: str) -> str:
    """«СЧ-2026-000001» → «cч - 2026 - 000001» (латинская «c», пробелы у дефисов)."""
    return "c" + number.lower()[1:].replace("-", " - ")


def _indicators(slug) -> dict:
    payload = dashboard.dashboard(invoice_flow._fd(slug), dashboard.Filters())
    return {row["key"]: row for row in payload["indicators"]}


def _upload(account, inv, purpose):
    today = timezone.localdate()
    doc = common.onec_doc("501", today.strftime("%d.%m.%Y"), f"{AMOUNT}.00", account.iban,
                          recipient_bin=inv.counterparty.reg_number,
                          recipient=inv.counterparty.name, purpose=purpose)
    return common.onec_file(account.iban, [doc], period=(
        (today - timedelta(days=7)).strftime("%d.%m.%Y"), today.strftime("%d.%m.%Y")))


class _FutureClock:
    """``timezone`` с подменённой «сегодняшней» датой — для дашборда, который
    считает рабочие дни ожидания банка от сегодня."""

    def __init__(self, today):
        self._today = today

    def localdate(self, *args, **kwargs):
        return self._today

    def __getattr__(self, name):
        return getattr(timezone, name)


def _after_bank_days(day, days):
    """Та же мера, что у фильтра ``bank_wait_days`` (D-S7-7), а не копия Пн–Пт —
    иначе тест плавает в окне праздников РК."""
    return refdata.add_bank_days(day, days)


def test_pay_reconcile_cancel_and_reload(company_context, monkeypatch,
                                         django_capture_on_commit_callbacks):
    slug = company_context["slug"]
    inv = _paid_invoice(slug)
    s.grant(slug, ADM, "bpp-adm")
    account = _org_account()
    purpose = f"оплата по счёту {_dirty(inv.number)}"
    assert _dirty(inv.number) != inv.number

    def load():
        with django_capture_on_commit_callbacks(execute=True):
            imp, _ = imports.start_import(account_id=account.pk,
                                          upload=_upload(account, inv, purpose),
                                          actor_id=s.FD)
        imp.refresh_from_db()
        return imp

    def matched_line(imp):
        line = BankStatementLine.objects.get(bank_import=imp)
        assert (line.match_status, line.found_numbers) == (
            LineMatchStatus.MATCHED, [inv.number])
        assert list(line.matches.values_list("invoice_id", "amount", "state")) == [
            (inv.pk, Decimal("1000.00"), "active")]
        return line

    # До выписки: БУХ отметил, банка нет, но отметка сегодняшняя — ждать рано.
    rows = _indicators(slug)
    assert (rows["full"]["count"], rows["bank_unconfirmed"]["count"]) == (0, 0)

    # 2. Выписка с «грязным» номером — «Сверена», счёт «Оплачен полностью».
    first = load()
    assert first.status == BankImportStatus.RECONCILED, first.failure
    matched_line(first)
    inv.refresh_from_db()
    assert (inv.status, inv.paid_bank_amount, inv.recon_status) == (
        InvoiceStatus.PAID, Decimal("1000.00"), ReconStatus.FULL)
    rows = _indicators(slug)
    assert (rows["full"]["count"], rows["bank_unconfirmed"]["count"]) == (1, 0)

    # 3. Отмена загрузки: у счёта «Нет данных банка», отметка БУХ на месте.
    cancelled = matching.cancel_import(s.FD, first.pk, "загрузили не ту выписку")
    assert cancelled.status == BankImportStatus.CANCELLED
    inv.refresh_from_db()
    assert (inv.status, inv.paid_bank_amount, inv.recon_status) == (
        InvoiceStatus.PAID, Decimal("0.00"), ReconStatus.NO_DATA)
    assert BankStatementLine.objects.get(bank_import=first).cancelled_at is not None
    rows = _indicators(slug)
    assert (rows["full"]["count"], rows["bank_unconfirmed"]["count"]) == (0, 0)  # сегодня

    # Через 4 рабочих дня банк всё ещё молчит — показатель загорается.
    later = _after_bank_days(timezone.localdate(), 4)
    with monkeypatch.context() as patch:
        patch.setattr(invoices_read, "timezone", _FutureClock(later))
        rows = _indicators(slug)
    assert (rows["full"]["count"], rows["bank_unconfirmed"]["count"]) == (0, 1)
    assert rows["bank_unconfirmed"]["amount"] == Decimal("1000.00")

    # 4. Та же выписка снова — ключи дублей свободны, строка «Сопоставлена».
    second = load()
    assert second.pk != first.pk
    assert second.status == BankImportStatus.RECONCILED, second.failure
    assert (second.debits, second.duplicates, second.errors) == (1, 0, [])
    matched_line(second)
    inv.refresh_from_db()
    assert (inv.paid_bank_amount, inv.recon_status) == (Decimal("1000.00"), ReconStatus.FULL)
    rows = _indicators(slug)
    assert (rows["full"]["count"], rows["bank_unconfirmed"]["count"]) == (1, 0)

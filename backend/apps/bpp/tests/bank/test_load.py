"""Нагрузка выписки: 5 000 списаний 1С разбираются и сверяются в бюджет
времени (мастер-план A4.1, ответ Q-C26: «5 000 строк укладываются в бюджет
времени» — ≤ 60 с; план этапа 8 A, «Дополнение 04.10», задача 9.2).

Путь — боевой: загрузка через сервис (``imports.start_import``: файл в
``apps.files``, журнал, «Обрабатывается»), затем задача разбора
``tasks_bank.run_bank_import`` синхронно — тем вызовом, который на бою
делает воркер Celery (разбор, запись пачками, автосверка). Время меряется
вокруг задачи: от начала разбора до «Сверена».

Автосверке есть что делать: 200 счетов «К оплате» в базе, 200 строк выписки
называют каждая свой счёт в назначении (в «грязном» виде — строчными, как
пишут в банк-клиенте) и платят его целиком, остальные 4 800 — без номера
счёта. Локально разбор и автосверка — около 8 с (вместе с заведением счетов
и созданием тестовой схемы — дольше); метки ``slow`` в проекте нет — тест идёт
в общем прогоне. Что тест ловит регрессию, доказано мутацией (бюджет 1 с —
падает, red-log задачи 9.2).
"""

from __future__ import annotations

import time
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db.models import Count
from django.utils import timezone

from apps.bpp import tasks_bank
from apps.bpp.models import Invoice
from apps.bpp.models.bank import BankImport, BankImportStatus, LineMatchStatus, PaymentMatch
from apps.bpp.models.invoices import ReconStatus
from apps.bpp.services.bank import imports
from apps.bpp.tests import stage2 as s
from apps.bpp.tests.test_files import memory_storage  # noqa: F401  (фикстура)

from . import common

#: Бюджет времени разбора и автосверки (Q-C26) — не поднимать.
BUDGET_SECONDS = 60
LINES = 5_000
INVOICES = 200
CP_BIN = "100000000001"
AMOUNT = Decimal("1000.00")


#: «Сегодня» — один раз на модуль: даты строк и период файла не разойдутся,
#: даже если прогон пересечёт полночь.
TODAY = timezone.localdate()


def _day(n: int) -> str:
    return (TODAY - timedelta(days=n)).strftime("%d.%m.%Y")


def _docs(account_iban: str, invoices) -> list[list[str]]:
    """``LINES`` списаний своего счёта: первые ``len(invoices)`` платят каждая
    свой счёт целиком, прочие — без номера счёта. Номера документов разные —
    дублей (BR-075) в файле нет."""
    docs = []
    for i in range(LINES):
        if i < len(invoices):
            amount, purpose = AMOUNT, f"оплата по сч {invoices[i].number.lower()} за товар"
        else:
            amount = Decimal(1000 + i % 977) + Decimal("0.50")
            purpose = f"Оплата по договору поставки № П-{i} от 01.09.2026, в т.ч. НДС"
        docs.append(common.onec_doc(str(10_000 + i), _day(1 + i % 7), f"{amount:.2f}",
                                    account_iban, recipient_bin=CP_BIN, purpose=purpose))
    return docs


@pytest.mark.django_db
def test_5000_onec_lines_parse_and_reconcile_within_budget(company_context, capsys):
    slug = company_context["slug"]
    account = common.org_account()
    cp = common.counterparty(CP_BIN)
    invoices = [common.orm_invoice(cp, AMOUNT) for _ in range(INVOICES)]
    upload = common.onec_file(account.iban, _docs(account.iban, invoices),
                              period=(_day(7), _day(0)))

    # Приём файла — как ручка: загрузка «Обрабатывается», разбор ещё не поставлен
    # (колбэк фиксации транзакции в тесте не выполняется).
    imp, _ = imports.start_import(account_id=account.pk, upload=upload, actor_id=s.FD)
    assert imp.status == BankImportStatus.PROCESSING

    started = time.monotonic()
    tasks_bank.run_bank_import(company_slug=slug, import_id=str(imp.pk))
    elapsed = time.monotonic() - started

    with capsys.disabled():
        print(f"\nвыписка 1С: {LINES} строк, {INVOICES} счетов — разбор и автосверка "
              f"за {elapsed:.1f} с (бюджет {BUDGET_SECONDS} с)")

    imp = BankImport.objects.get(pk=imp.pk)
    assert imp.status == BankImportStatus.RECONCILED, imp.failure
    assert elapsed < BUDGET_SECONDS, (
        f"разбор и автосверка {LINES} строк — {elapsed:.1f} с, бюджет {BUDGET_SECONDS} с")
    assert (imp.rows_total, imp.debits, imp.duplicates, imp.errors) == (LINES, LINES, 0, [])
    assert imp.lines.count() == LINES

    by_status = dict(imp.lines.order_by().values_list("match_status").annotate(n=Count("pk")))
    assert by_status == {LineMatchStatus.MATCHED: INVOICES,
                         LineMatchStatus.UNMATCHED: LINES - INVOICES}
    assert PaymentMatch.objects.filter(line__bank_import=imp).count() == INVOICES
    recon = {(inv.paid_bank_amount, inv.recon_status)
             for inv in Invoice.objects.filter(pk__in=[i.pk for i in invoices])}
    assert recon == {(AMOUNT, ReconStatus.FULL)}

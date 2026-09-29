"""Сквозная проверка этапа 3 (задача 9 плана этапа 3 A, шаг 1).

Одна история на настоящих сервисах — без сборки строк руками:

1. Счёт проходит поток B (B3.2): отправлен → ФД «Оплатить» → БУХ «Оплачено»
   → запрос закрывающих документов (``decisions.decide``,
   ``payments.mark_paid``, ``payments.request_docs`` — фабрики из
   ``test_invoices.py``).
2. Ежедневная сводка автора счёта (``digest.send()``, источник
   ``bpp.closing_docs`` регистрирует сам ``BppConfig.ready()``) несёт раздел
   «Ждут от вас закрывающих документов» со ссылкой на счёт на поддомене
   компании (задача 8, D-13).
3. Метрика ``bpp_invoices_closing_docs_overdue`` загорается после пяти
   дней ожидания (задача 7, Q-C29).
4. Выписка 1С с номером этого счёта в назначении (в «грязном» виде, как его
   набирают в платёжке) загружается, а строка остаётся «Не сопоставлена»:
   сверка — этап 4 (A4.2). Контракт, на котором она будет стоять, —
   ``bpp.interface.find_by_number`` — счёт находит.

Тесты зовут ``digest.send()`` без контекста компании, как Celery-beat;
остальное идёт внутри ``use_company``.
"""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.bpp import metrics
from apps.bpp.interface import find_by_number
from apps.bpp.models import Invoice, InvoiceStatus
from apps.bpp.models.bank import BankImportStatus, BankStatementLine, LineMatchStatus
from apps.bpp.models.invoices import ReconStatus
from apps.bpp.services.bank import imports
from apps.bpp.services.bank import settings as bank_settings
from apps.bpp.services.invoices import decisions, payments
from apps.bpp.tests import stage2 as s
# Счёт — модель B (B3.2): проводим его его же фабриками, как test_metrics.py.
from apps.bpp.tests import test_invoices as invoice_flow
from apps.bpp.tests.bank import common
from apps.bpp.tests.test_files import memory_storage  # noqa: F401  (фикстура: хранилище в памяти)
from apps.companies.models import Company, CompanyMembership
from apps.notifications.models import Channel, Delivery, Notification
from apps.notifications.services import digest
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db

ADM = 951                     # заводит счёт организации и шаблон выписки
AMOUNT = 1000
HEADING = "Ждут от вас закрывающих документов:"


@pytest.fixture(autouse=True)
def _no_center_side_effects(monkeypatch):
    """Доставка (Celery) и мгновенный показ (Socket.IO) центру не нужны —
    достаточно записей ``Notification``/``Delivery`` (как в
    test_digest_closing_docs.py и test_bpp_signoff_e2e.py)."""
    from apps.notifications.services import center

    monkeypatch.setattr(center, "_enqueue", lambda ids: None)
    monkeypatch.setattr(center, "_realtime", lambda rows: None)


def _awaiting_docs(slug: str) -> Invoice:
    """Шаг 1 истории: счёт без договора на 1000 ₸ проходит весь поток B до
    «Ждёт закрывающих документов». Зовётся в контексте компании."""
    _, _, inv = invoice_flow._submitted(slug, AMOUNT)
    assert inv.status == InvoiceStatus.UNDER_REVIEW
    assert re.fullmatch(r"СЧ-\d{4}-\d{6}", inv.number)

    inv = decisions.decide(invoice_flow._fd(slug), inv.id, decision="pay")
    assert inv.status == InvoiceStatus.TO_PAY

    buh = invoice_flow._buh(slug)
    inv = payments.mark_paid(buh, inv.id, pay_date=timezone.localdate(), amount=AMOUNT)
    assert inv.status == InvoiceStatus.PAID

    inv = payments.request_docs(buh, inv.id)
    assert inv.status == InvoiceStatus.AWAITING_DOCS
    assert inv.author_id == s.SN
    return inv


def _overdue() -> int:
    return metrics.collect()["bpp_invoices_closing_docs_overdue"]["values"][0][1]


# ── 1–2. оплачено → запрос закрывающих → сводка автора ──────────────────

def test_paid_invoice_lands_in_the_authors_digest(settings, company_schema):
    settings.PUBLIC_BASE_URL = "https://htq.group"
    slug = company_schema["slug"]
    with use_company(slug):
        inv = _awaiting_docs(slug)
    # Тенантный источник обходит компании ПОЛЬЗОВАТЕЛЯ — нужна строка членства.
    CompanyMembership.objects.get_or_create(user_id=s.SN,
                                            company=Company.objects.get(slug=slug))

    assert digest.send() >= 1

    note = Notification.objects.get(recipient_id=s.SN, event="digest.daily")
    lines = note.text.splitlines()
    assert HEADING in lines
    item = (f"• {inv.number} — ждёт закрывающих 0 дн. — "
            f"https://{slug}.htq.group/bpp/invoices/{inv.pk}")
    assert lines[lines.index(HEADING) + 1] == item
    # Задач согласования у автора нет — «внимания», а не «решения», и
    # колокольчик ведёт прямо на счёт.
    assert note.title == "Ждут вашего внимания: 1"
    assert note.url == f"/bpp/invoices/{inv.pk}"
    # Сводка — не только колокольчик: письмо заведено (каналы по умолчанию).
    assert Delivery.objects.filter(notification=note, channel=Channel.EMAIL).exists()


# ── 3. метрика «Ждёт закрывающих» дольше 5 дней ─────────────────────────

def test_closing_docs_metric_lights_up_after_five_days(company_context):
    inv = _awaiting_docs(company_context["slug"])
    assert _overdue() == 0                        # только что запрошены

    Invoice.objects.filter(pk=inv.pk).update(
        docs_requested_at=timezone.now() - timedelta(days=6))
    assert _overdue() == 1


# ── 4. выписка с номером счёта — «Не сопоставлена» до сверки A4.2 ────────

def _org_account():
    """Счёт организации с шаблоном 1С — так же, как test_imports.py::_account."""
    tpl = bank_settings.create_template({"name": "Шаблон 1С", "format": "onec", "columns": {}},
                                        actor_id=ADM)
    return bank_settings.create_account(
        {"iban": common.iban(1), "bank_name": "Halyk Bank", "bic": "HSBKKZKX",
         "currency": "KZT", "template_id": str(tpl.pk)}, actor_id=ADM)


def _dirty(number: str) -> str:
    """«СЧ-2026-000001» → «cч - 2026 - 000001»: строчные, латинская «c» вместо
    кириллической «С», пробелы вокруг дефисов — как номер набирают руками."""
    lowered = number.lower()
    assert lowered.startswith("сч")               # кириллица
    return "c" + lowered[1:].replace("-", " - ")


def test_statement_line_with_the_invoice_number_stays_unmatched(
        company_context, django_capture_on_commit_callbacks):
    slug = company_context["slug"]
    inv = _awaiting_docs(slug)
    s.grant(slug, ADM, "bpp-adm")
    account = _org_account()

    dirty = _dirty(inv.number)
    assert dirty != inv.number and "c" in dirty and " - " in dirty
    purpose = f"оплата по счёту {dirty}"
    today = timezone.localdate()
    doc = common.onec_doc("501", today.strftime("%d.%m.%Y"), f"{AMOUNT}.00", account.iban,
                          recipient_bin=inv.counterparty.reg_number,
                          recipient=inv.counterparty.name, purpose=purpose)
    upload = common.onec_file(account.iban, [doc], period=(
        (today - timedelta(days=7)).strftime("%d.%m.%Y"), today.strftime("%d.%m.%Y")))

    # Разбор — Celery-задача на фиксации транзакции (в тестах — сразу).
    with django_capture_on_commit_callbacks(execute=True):
        imp, _ = imports.start_import(account_id=account.pk, upload=upload, actor_id=s.FD)
    imp.refresh_from_db()
    assert imp.status == BankImportStatus.LOADED, imp.failure
    assert (imp.debits, imp.duplicates, imp.errors) == (1, 0, [])

    line = BankStatementLine.objects.get(bank_import=imp)
    assert line.purpose == purpose                # назначение хранится как в банке
    assert line.amount == Decimal("1000.00")
    assert line.recipient_bin == inv.counterparty.reg_number
    # Сверки ещё нет (A4.2): строка не сопоставлена, счёт банком не тронут.
    assert line.match_status == LineMatchStatus.UNMATCHED
    inv.refresh_from_db()
    assert (inv.status, inv.paid_bank_amount, inv.recon_status) == (
        InvoiceStatus.AWAITING_DOCS, Decimal("0"), ReconStatus.NO_DATA)

    # Контракт для A4.2: по чистому номеру счёт находится ...
    found = find_by_number(inv.number)
    assert found is not None
    assert (found["id"], found["number"], found["status"]) == (
        str(inv.pk), inv.number, InvoiceStatus.AWAITING_DOCS)
    assert found["amount"] == Decimal("1000.00")
    assert found["counterparty_reg_number"] == line.recipient_bin
    assert (found["paid_bank_amount"], found["recon_status"]) == (Decimal("0"),
                                                                  ReconStatus.NO_DATA)
    # ... а «грязный» из назначения — нет: find_by_number только обрезает
    # пробелы по краям и поднимает регистр. Выделить номер из назначения и
    # привести его к «СЧ-ГГГГ-NNNNNN» (латиница → кириллица, пробелы у
    # дефисов) — работа сверки A4.2, до вызова контракта.
    assert find_by_number(dirty) is None

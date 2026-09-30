"""Автосверка выписки со счетами и статус сверки счёта (ТЗ §11.3 пп.4–8,
CALC-010, AC-010, AC-011, BR-073; план этапа 4 A, задача 2 — Review Focus
2, 3, 4).

Счета — фабриками B (``test_invoices.py``: отправлен → ФД «Оплатить»),
выписки — настоящей загрузкой (разбор на фиксации транзакции, Celery в
тестах сразу) или строками прямо в базе (``common.loaded_import``), где
разбор файла не проверяется.
"""

from __future__ import annotations

import threading
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.utils import timezone

from apps.bpp.models import AuditLog, Invoice, InvoiceStatus
from apps.bpp.models.bank import (
    BankImport,
    BankImportStatus,
    BankStatementLine,
    LineMatchStatus,
    PaymentMatch,
    PaymentMatchState,
)
from apps.bpp.models.invoices import ReconStatus
from apps.bpp.services.bank import imports, matching
from apps.bpp.services.invoices import decisions
from apps.bpp.services.invoices import invoices as invoice_service
from apps.bpp.tests import stage2 as s
from apps.bpp.tests import test_invoices as invoice_flow
from apps.bpp.tests.test_files import memory_storage  # noqa: F401  (фикстура)

from . import common

D = Decimal
CP_BIN = "100000000001"          # БИН контрагента счетов из ``invoice_flow._counterparty``
FOREIGN_BIN = "990340000123"
ADM = 951


@pytest.fixture
def slug(company_context):
    slug = company_context["slug"]
    s.grant(slug, ADM, "bpp-adm")
    return slug


def _payable(slug, amount, *, cp=None, ext="145", proj=None, sn=None, pay=True):
    """Счёт на ``amount`` в «К оплате» (или, ``pay=False``, «На рассмотрении
    ФД»). Второй и следующие счета одного контрагента — со своим номером
    счёта контрагента (BR-045)."""
    sn, proj, inv = invoice_flow._invoice(slug, amount, counterparty=cp, proj=proj, sn=sn)
    if ext != "145":
        inv, _ = invoice_service.update_draft(sn, inv.id, expected_version=None,
                                              data={"ext_number": ext})
    inv = invoice_service.submit(sn, inv.id, expected_version=None)
    if pay:
        inv = decisions.decide(invoice_flow._fd(slug), inv.id, decision="pay")
    return sn, proj, inv


def _day(n: int = 0) -> str:
    return (timezone.localdate() - timedelta(days=n)).strftime("%d.%m.%Y")


def _upload(capture, account, docs) -> BankImport:
    """Настоящая загрузка выписки 1С: разбор и автосверка — в задаче на
    фиксации транзакции."""
    upload = common.onec_file(account.iban, docs, period=(_day(7), _day(0)))
    with capture(execute=True):
        imp, _ = imports.start_import(account_id=account.pk, upload=upload, actor_id=s.FD)
    imp.refresh_from_db()
    return imp


def _doc(account, number: str, amount: str, purpose: str, recipient_bin: str = CP_BIN):
    return common.onec_doc(number, _day(1), amount, account.iban, recipient_bin=recipient_bin,
                           purpose=purpose)


def _recon(inv) -> tuple[Decimal, str]:
    inv.refresh_from_db()
    return inv.paid_bank_amount, inv.recon_status


# ── AC-010: частично → полностью, повторная выписка ничего не меняет ────

def test_ac010_partial_then_full_and_reupload_changes_nothing(
        slug, django_capture_on_commit_callbacks):
    _, _, inv = _payable(slug, D("1000000"))
    account = common.org_account()
    capture = django_capture_on_commit_callbacks

    first_docs = [_doc(account, "701", "400000.00", f"Оплата по счёту {inv.number}")]
    first = _upload(capture, account, first_docs)
    assert first.status == BankImportStatus.RECONCILED, first.failure
    assert _recon(inv) == (D("400000.00"), ReconStatus.PARTIAL)
    line = first.lines.get()
    assert (line.match_status, line.found_numbers) == (LineMatchStatus.MATCHED, [inv.number])
    match = line.matches.get()
    assert (match.invoice_id, match.amount, match.state, match.manual) == (
        inv.pk, D("400000.00"), PaymentMatchState.ACTIVE, False)

    second = _upload(capture, account,
                     [_doc(account, "702", "600000.00", f"оплата по сч {inv.number.lower()}")])
    assert second.status == BankImportStatus.RECONCILED
    assert _recon(inv) == (D("1000000.00"), ReconStatus.FULL)

    again = _upload(capture, account, first_docs)
    assert (again.status, again.debits, again.duplicates) == (BankImportStatus.RECONCILED, 1, 1)
    assert again.lines.count() == 0
    assert _recon(inv) == (D("1000000.00"), ReconStatus.FULL)
    assert PaymentMatch.objects.filter(invoice=inv).count() == 2
    # Повтор автосверки той же загрузки ничего не удваивает.
    assert matching.auto_match(first.pk)["matched"]["count"] == 1
    assert PaymentMatch.objects.filter(invoice=inv).count() == 2
    assert _recon(inv) == (D("1000000.00"), ReconStatus.FULL)
    # Изменение сверки — в журнале счёта.
    history = AuditLog.objects.filter(object_type="bpp.invoice", object_id=str(inv.pk),
                                      action="updated", changes__has_key="recon_status")
    assert [row.changes["recon_status"] for row in history.order_by("created_at")] == [
        ["no_data", "partial"], ["partial", "full"]]


# ── AC-011, BR-073: чужой БИН — на проверку, статус счёта не меняется ───

def test_ac011_foreign_bin_goes_to_review_and_keeps_status(slug):
    _, _, inv = _payable(slug, D("1000000"))
    imp = common.loaded_import(common.org_account(), [
        {"amount": "400000", "purpose": f"Оплата по счёту {inv.number}",
         "recipient_bin": FOREIGN_BIN}])

    result = matching.auto_match(imp.pk)

    line = imp.lines.get()
    assert (line.match_status, line.review_reason) == (LineMatchStatus.NEEDS_REVIEW,
                                                       "bin_mismatch")
    match = line.matches.get()
    assert (match.invoice_id, match.amount, match.state, match.review_reason) == (
        inv.pk, D("400000.00"), PaymentMatchState.REVIEW, "bin_mismatch")
    assert _recon(inv) == (D("0.00"), ReconStatus.NO_DATA)
    assert result["needs_review"] == {"count": 1, "amount": D("400000.00")}
    assert matching.REVIEW_REASONS["bin_mismatch"] == (
        "БИН получателя не совпадает с БИН контрагента счёта")


def test_currency_mismatch_and_wrong_status_go_to_review(slug):
    sn, proj, paid = _payable(slug, D("1000"))
    _, _, pending = _payable(slug, D("2000"), cp=paid.counterparty, ext="146", proj=proj,
                             sn=sn, pay=False)
    assert pending.status == InvoiceStatus.UNDER_REVIEW
    imp = common.loaded_import(common.org_account(), [
        {"amount": "1000", "purpose": f"Оплата {paid.number}", "recipient_bin": CP_BIN,
         "currency": "USD"},
        {"amount": "2000", "purpose": f"Оплата {pending.number}", "recipient_bin": CP_BIN},
    ])

    matching.auto_match(imp.pk)

    by_row = {line.row_no: line for line in imp.lines.all()}
    assert (by_row[1].match_status, by_row[1].review_reason) == (
        LineMatchStatus.NEEDS_REVIEW, "currency_mismatch")
    assert (by_row[2].match_status, by_row[2].review_reason) == (
        LineMatchStatus.NEEDS_REVIEW, "invoice_status")
    assert set(PaymentMatch.objects.values_list("state", "review_reason")) == {
        (PaymentMatchState.REVIEW, "currency_mismatch"),
        (PaymentMatchState.REVIEW, "invoice_status")}
    assert _recon(paid) == (D("0.00"), ReconStatus.NO_DATA)
    assert _recon(pending) == (D("0.00"), ReconStatus.NO_DATA)
    assert matching.REVIEW_REASONS["invoice_status"] == (
        "Счёт в статусе, отличном от К оплате / Оплачено")
    assert matching.REVIEW_REASONS["currency_mismatch"] == "Валюта платежа ≠ валюте счёта"


# ── несколько номеров (D-S4-4) ──────────────────────────────────────────

def test_several_numbers_exact_split_and_ambiguous_split(slug):
    sn, proj, a = _payable(slug, D("400"))
    cp = a.counterparty
    _, _, b = _payable(slug, D("600"), cp=cp, ext="146", proj=proj, sn=sn)
    _, _, c = _payable(slug, D("400"), cp=cp, ext="147", proj=proj, sn=sn)
    _, _, d = _payable(slug, D("600"), cp=cp, ext="148", proj=proj, sn=sn)
    imp = common.loaded_import(common.org_account(), [
        # Номера — в порядке появления в назначении: сначала B, потом A.
        {"amount": "1000", "purpose": f"Оплата {b.number} и {a.number.lower()}",
         "recipient_bin": CP_BIN},
        # Переплата: 1200 на остатки 400 + 600 — делится неоднозначно.
        {"amount": "1200", "purpose": f"Оплата {c.number}, {d.number}", "recipient_bin": CP_BIN},
    ])

    result = matching.auto_match(imp.pk)

    exact, ambiguous = imp.lines.order_by("row_no")
    assert exact.match_status == LineMatchStatus.MATCHED
    assert exact.found_numbers == [b.number, a.number]
    assert {(m.invoice_id, m.amount, m.state) for m in exact.matches.all()} == {
        (b.pk, D("600.00"), PaymentMatchState.ACTIVE),
        (a.pk, D("400.00"), PaymentMatchState.ACTIVE)}
    assert _recon(a) == (D("400.00"), ReconStatus.FULL)
    assert _recon(b) == (D("600.00"), ReconStatus.FULL)

    assert (ambiguous.match_status, ambiguous.review_reason) == (
        LineMatchStatus.NEEDS_REVIEW, "several_numbers")
    assert {(m.invoice_id, m.amount, m.state, m.review_reason)
            for m in ambiguous.matches.all()} == {
        (c.pk, D("400.00"), PaymentMatchState.REVIEW, "several_numbers"),
        (d.pk, D("600.00"), PaymentMatchState.REVIEW, "several_numbers")}
    assert _recon(c) == (D("0.00"), ReconStatus.NO_DATA)
    assert _recon(d) == (D("0.00"), ReconStatus.NO_DATA)
    # Переплата не распределена и видна в итогах и у строки.
    assert result["unallocated"] == D("200.00")
    row = next(item for item in imports.lines(imp)["items"] if item["row_no"] == 2)
    assert (row["allocated"], row["unallocated"]) == (D("1000.00"), D("200.00"))
    assert row["review_reason_label"] == (
        "В назначении несколько номеров, сумма не делится однозначно")
    assert sorted(m["invoice_number"] for m in row["matches"]) == sorted([c.number, d.number])


def test_unknown_number_and_no_number_stay_unmatched(slug):
    imp = common.loaded_import(common.org_account(), [
        {"amount": "500", "purpose": "Оплата по счёту СЧ-2000-000001", "recipient_bin": CP_BIN},
        {"amount": "700", "purpose": "Оплата за металл по договору 15", "recipient_bin": CP_BIN},
    ])

    result = matching.auto_match(imp.pk)

    unknown, bare = imp.lines.order_by("row_no")
    assert (unknown.match_status, unknown.found_numbers) == (LineMatchStatus.UNMATCHED,
                                                             ["СЧ-2000-000001"])
    assert (bare.match_status, bare.found_numbers) == (LineMatchStatus.UNMATCHED, [])
    assert not PaymentMatch.objects.exists()
    assert result["unmatched"] == {"count": 2, "amount": D("1200.00")}
    imp.refresh_from_db()
    assert imp.status == BankImportStatus.RECONCILED


# ── итоги и статус загрузки ────────────────────────────────────────────

def test_import_becomes_reconciled_with_totals(slug, django_capture_on_commit_callbacks):
    _, _, inv = _payable(slug, D("1000000"))
    account = common.org_account()
    imp = _upload(django_capture_on_commit_callbacks, account, [
        _doc(account, "801", "250000.00", f"Оплата {inv.number}"),
        _doc(account, "802", "100000.00", f"Оплата {inv.number}", recipient_bin=FOREIGN_BIN),
        _doc(account, "803", "70000.50", "Хозяйственные расходы"),
    ])
    assert imp.status == BankImportStatus.RECONCILED, imp.failure

    card = imports.card(imports.get_import(imp.pk))
    assert (card["status"], card["status_label"]) == ("reconciled", "Сверена")
    assert card["totals"] == {
        "matched": {"count": 1, "amount": D("250000.00")},
        "needs_review": {"count": 1, "amount": D("100000.00")},
        "unmatched": {"count": 1, "amount": D("70000.50")},
        "excluded": {"count": 0, "amount": D("0.00")},
        "unallocated": D("0.00"),
    }
    assert (card["lines"], card["matched"], card["needs_review"], card["unmatched"],
            card["excluded"]) == (3, 1, 1, 1, 0)
    assert _recon(inv) == (D("250000.00"), ReconStatus.PARTIAL)
    actions = set(AuditLog.objects.filter(object_type="bpp.bankimport", object_id=str(imp.pk))
                  .values_list("action", flat=True))
    assert {"loaded", "reconciled"} <= actions
    # Пересечение периода с уже сверенной загрузкой по-прежнему предупреждается.
    assert imports._overlaps(account, imp.period_from, imp.period_to)


def test_failed_auto_match_leaves_the_import_loaded(slug, django_capture_on_commit_callbacks,
                                                    monkeypatch):
    """Автосверка упала — строки загружены, загрузка «Загружена» (не
    «Ошибка»), повтор ``auto_match`` доводит её до «Сверена»."""
    _, _, inv = _payable(slug, D("1000"))
    account = common.org_account()

    real = matching.auto_match

    def broken(import_id):
        raise RuntimeError("сбой сверки")

    monkeypatch.setattr(matching, "auto_match", broken)
    imp = _upload(django_capture_on_commit_callbacks, account,
                  [_doc(account, "901", "1000.00", f"Оплата {inv.number}")])
    assert imp.status == BankImportStatus.LOADED
    assert imp.lines.get().match_status == LineMatchStatus.UNMATCHED

    monkeypatch.setattr(matching, "auto_match", real)
    matching.auto_match(imp.pk)
    imp.refresh_from_db()
    assert imp.status == BankImportStatus.RECONCILED
    assert _recon(inv) == (D("1000.00"), ReconStatus.FULL)


# ── гонка двух загрузок по одному счёту (Review Focus 4) ───────────────

@pytest.mark.django_db(transaction=True)
def test_two_imports_race_for_one_invoice(monkeypatch):
    """Две загрузки из разных выписок сверяются одновременно и платят один
    счёт; обе дошли до блокировки счетов (барьер) — итог «Оплачено по банку»
    равен сумме обоих платежей. Каждый поток — в своём соединении; таблицы
    модуля в тестовой базе есть и в ``public``."""
    cp = invoice_flow._counterparty(CP_BIN)
    inv = Invoice.objects.create(
        number="СЧ-2026-000777", project_id=uuid.uuid4(), article_id=uuid.uuid4(),
        counterparty=cp, ext_number="777", ext_date=timezone.localdate(),
        amount=D("1000000.00"), status=InvoiceStatus.TO_PAY, author_id=s.SN)
    account = common.org_account()
    ids = [common.loaded_import(account, [
        {"amount": amount, "purpose": f"Оплата по счёту {inv.number}", "recipient_bin": CP_BIN,
         "doc_number": f"R-{amount}"}]).pk for amount in ("400000", "600000")]

    barrier = threading.Barrier(2)
    real_lock = matching._lock_invoices

    def wait_then_lock(keys):
        keys = list(keys)
        if keys:
            barrier.wait(timeout=10)
        return real_lock(keys)

    monkeypatch.setattr(matching, "_lock_invoices", wait_then_lock)
    crashes: list[str] = []
    guard = threading.Lock()

    def worker(import_id):
        try:
            matching.auto_match(import_id)
        except Exception as exc:  # noqa: BLE001 — любой исход, кроме штатного, — провал
            with guard:
                crashes.append(repr(exc))
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(pk,)) for pk in ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert crashes == []
    inv.refresh_from_db()
    assert (inv.paid_bank_amount, inv.recon_status) == (D("1000000.00"), ReconStatus.FULL)
    assert PaymentMatch.objects.filter(invoice=inv, state=PaymentMatchState.ACTIVE).count() == 2
    assert set(BankImport.objects.filter(pk__in=ids).values_list("status", flat=True)) == {
        BankImportStatus.RECONCILED}
    assert set(BankStatementLine.objects.values_list("match_status", flat=True)) == {
        LineMatchStatus.MATCHED}

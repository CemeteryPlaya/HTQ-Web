"""Автосверка выписки со счетами и статус сверки счёта (ТЗ §11.3 пп.4–8,
CALC-010, AC-010, AC-011, BR-073; A4.2, план этапа 4 A, задача 2).

``auto_match(import_id)`` сопоставляет строки загрузки со счетами по номеру
``СЧ-ГГГГ-NNNNNN`` в назначении платежа (``recon.find_numbers``) и
возвращает итоги по вкладкам (``totals``):

- номеров нет или ни один счёт не найден — строка «Не сопоставлена»;
- один номер — сопоставление на всю сумму строки. На проверку оно уходит
  (``review``), если БИН получателя ≠ БИН контрагента счёта, статус счёта
  не из ``PAYABLE_STATUSES`` (D-S4-3) или валюта платежа ≠ валюте счёта —
  причина в строке и в сопоставлении (коды ``REVIEW_REASONS``, D-S4-2);
- несколько номеров — ``recon.distribute`` по неоплаченным остаткам в
  порядке появления номеров в назначении (D-S4-4). Сумма делится однозначно
  и все номера — существующие счета — каждое сопоставление ``active``;
  иначе всё распределение ``review`` с причиной «несколько номеров». Части
  с нулевым остатком не записываются; переплата по строке с несколькими
  номерами в распределение не кладётся и видна как «не распределено»
  (``totals["unallocated"]``, ``unallocated`` у строки). Все счета строки
  уже оплачены полностью (делить нечего) — строка «Не сопоставлена», её
  ФД сопоставляет вручную;
- проблема хоть у одного счёта строки — на проверку уходит вся строка:
  строку ФД решает целиком, а сопоставления получают каждое свою причину
  (или причину строки, если у счёта замечаний нет).

Идемпотентность: берутся только строки «Не сопоставлена» без исключения и
без действующих сопоставлений — повтор автосверки ничего не удваивает;
«Не сопоставлена» проверяется заново (счёт с этим номером мог появиться).

**Блокировки** — один порядок у всех, кто меняет сопоставления: загрузка →
её строки → счета по ``id`` (``_lock_invoices``). Строки обрабатываются
пачками по ``CHUNK``, каждая пачка — своя транзакция: блокировка загрузки
(и проверка, что её не отменили), строк пачки, затем всех их счетов разом.
Две загрузки с платежами по одному счёту поэтому идут друг за другом, и
остаток, от которого считается распределение, — всегда зафиксированный.
Ручные действия сверки (подтверждение, отмена, ручное сопоставление,
отмена загрузки) обязаны брать блокировки в том же порядке. Подтверждение
сопоставления «на проверке» меняет его ``state`` на месте (уникальность
«строка + счёт» — среди неотменённых, ``review`` и ``active`` в ней оба).

**CALC-010** — ``recalc_invoice``: «Оплачено по банку» = Σ ``active``
сопоставлений (D-S4-1, «на проверке» не входит), статус сверки — по нему.
Единственная точка записи ``Invoice.paid_bank_amount`` / ``recon_status``
(контракт мастер-плана §2.6 называет её ``recon.recalc_invoice``; живёт
здесь, рядом с записью сопоставлений).
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Count, DecimalField, Exists, F, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.bpp import interface as bpp_interface
from apps.bpp.models import (
    BankImport,
    BankImportStatus,
    BankStatementLine,
    Invoice,
    InvoiceStatus,
    LineMatchStatus,
    PaymentMatch,
    PaymentMatchState,
    ReconStatus,
)
from apps.bpp.services.core import audit
from apps.bpp.services.money import money

from . import recon

__all__ = [
    "CHUNK",
    "PAYABLE_STATUSES",
    "REVIEW_REASONS",
    "allocated_subquery",
    "auto_match",
    "recalc_invoice",
    "totals",
]

#: Строк выписки за одну транзакцию автосверки.
CHUNK = 200
ZERO = Decimal("0.00")

#: D-S4-3: статусы счёта, которые сверка принимает без проверки — «К оплате»
#: и «Оплачено» с любым шагом закрывающих документов (D-13).
PAYABLE_STATUSES = frozenset({
    InvoiceStatus.TO_PAY, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.PAID,
    InvoiceStatus.AWAITING_DOCS, InvoiceStatus.DOCS_PROVIDED, InvoiceStatus.CLOSED,
})

#: D-S4-2: код причины «Требует проверки» → текст ТЗ §11.2 дословно. Код
#: хранится в строке и в сопоставлении, текст показывает экран.
BIN_MISMATCH = "bin_mismatch"
SEVERAL_NUMBERS = "several_numbers"
INVOICE_STATUS = "invoice_status"
CURRENCY_MISMATCH = "currency_mismatch"
REVIEW_REASONS = {
    BIN_MISMATCH: "БИН получателя не совпадает с БИН контрагента счёта",
    SEVERAL_NUMBERS: "В назначении несколько номеров, сумма не делится однозначно",
    INVOICE_STATUS: "Счёт в статусе, отличном от К оплате / Оплачено",
    CURRENCY_MISMATCH: "Валюта платежа ≠ валюте счёта",
}

_LIVE_IMPORT = (BankImportStatus.LOADED, BankImportStatus.RECONCILED)


# ── CALC-010 ────────────────────────────────────────────────────────────

def _recon_status(paid: Decimal, amount: Decimal) -> str:
    if paid == 0:
        return ReconStatus.NO_DATA
    if paid < amount:
        return ReconStatus.PARTIAL
    if paid == amount:
        return ReconStatus.FULL
    return ReconStatus.OVERPAID


def recalc_invoice(invoice_id, *, actor_id: int | None = None) -> None:
    """P = Σ подтверждённых (``active``) сопоставлений (D-S4-1).
    P = 0 → «Нет данных банка»; 0 < P < Сумма → «Оплачен частично»;
    P = Сумма → «Оплачен полностью»; P > Сумма → «Переплата».

    Зовётся в транзакции изменения сопоставлений. Строка счёта блокируется
    ДО подсчёта суммы: иначе две транзакции посчитали бы Σ каждая без
    чужого, ещё не зафиксированного сопоставления, и одна сумма потерялась
    бы. Изменение пишется в журнал счёта (``updated``: поля
    ``paid_bank_amount``, ``recon_status``); ``version`` счёта не растёт —
    поля сверки автор не правит, и его открытая форма не должна получать
    E-CON-01 из-за банка."""
    inv = (Invoice.objects.select_for_update()
           .only("amount", "paid_bank_amount", "recon_status").filter(pk=invoice_id).first())
    if inv is None:
        return
    paid = (PaymentMatch.objects.filter(invoice_id=invoice_id, state=PaymentMatchState.ACTIVE)
            .aggregate(total=Sum("amount"))["total"]) or ZERO
    paid = money(paid)
    status = _recon_status(paid, inv.amount)
    if (paid, status) == (inv.paid_bank_amount, inv.recon_status):
        return
    Invoice.objects.filter(pk=invoice_id).update(paid_bank_amount=paid, recon_status=status)
    audit.record_for(Invoice.SIGNOFF_SUBJECT_TYPE, str(invoice_id), "updated",
                     actor_id=actor_id, changes={
                         "paid_bank_amount": [str(inv.paid_bank_amount), str(paid)],
                         "recon_status": [inv.recon_status, status]})


# ── блокировки ──────────────────────────────────────────────────────────

def _lock_invoices(ids) -> dict:
    """Счета ``ids`` под ``select_for_update`` в порядке ``id`` — один порядок
    блокировок у всех, кто меняет сопоставления, поэтому взаимной блокировки
    нет. Вместе с БИН контрагента (для проверки BR-073). Счёт, удалённый,
    пока ждали блокировку (черновик), в ответ не попадает."""
    keys = sorted({str(key) for key in ids})
    if not keys:
        return {}
    rows = (Invoice.objects.select_for_update(of=("self",))
            .select_related("counterparty")
            .filter(pk__in=keys).order_by("pk"))
    return {str(inv.pk): inv for inv in rows}


# ── правила сопоставления ───────────────────────────────────────────────

def _plain(value: str) -> str:
    return "".join((value or "").split()).upper()


def _problem(line: BankStatementLine, inv: Invoice) -> str:
    """Причина проверки по одному счёту — первая по порядку ТЗ §11.2; пусто —
    замечаний нет."""
    reg = inv.counterparty.reg_number if inv.counterparty_id else ""
    if not _plain(reg) or _plain(line.recipient_bin) != _plain(reg):
        return BIN_MISMATCH
    if inv.status not in PAYABLE_STATUSES:
        return INVOICE_STATUS
    if _plain(line.currency) != _plain(inv.currency_code):
        return CURRENCY_MISMATCH
    return ""


def _decide(line: BankStatementLine, numbers: list[str], by_number: dict[str, Invoice],
            paid: dict[str, Decimal]) -> tuple[str, str, list[tuple[Invoice, Decimal, str]]]:
    """Решение по строке: ``(статус строки, причина строки, [(счёт, сумма,
    причина счёта)])``. Состояние сопоставлений — по статусу строки."""
    known = [(number, by_number[number]) for number in numbers if number in by_number]
    if not known or line.amount <= 0:
        return LineMatchStatus.UNMATCHED, "", []
    if len(numbers) == 1:
        inv = known[0][1]
        reason = _problem(line, inv)
        return ((LineMatchStatus.NEEDS_REVIEW, reason, [(inv, line.amount, reason)]) if reason
                else (LineMatchStatus.MATCHED, "", [(inv, line.amount, "")]))

    remainders = [(str(inv.pk), inv.amount - paid[str(inv.pk)]) for _, inv in known]
    parts, exact = recon.distribute(line.amount, remainders)
    invoices = {str(inv.pk): inv for _, inv in known}
    planned = [(invoices[key], amount, _problem(line, invoices[key]))
               for key, amount in parts if amount > 0]
    if not planned:
        # Все счета уже оплачены полностью — делить нечего: строку ФД
        # сопоставляет вручную (вкладка «Не сопоставлена»).
        return LineMatchStatus.UNMATCHED, "", []
    if not exact or len(known) < len(numbers):
        reason = SEVERAL_NUMBERS
    else:
        reason = next((problem for _, _, problem in planned if problem), "")
    if not reason:
        return LineMatchStatus.MATCHED, "", planned
    return (LineMatchStatus.NEEDS_REVIEW, reason,
            [(inv, amount, problem or reason) for inv, amount, problem in planned])


# ── автосверка ──────────────────────────────────────────────────────────

def _pending(import_id):
    """Строки загрузки, которые автосверка берёт: действующие, «Не
    сопоставлена», не исключённые, без действующих сопоставлений."""
    live_match = PaymentMatch.objects.filter(line=OuterRef("pk")).exclude(
        state=PaymentMatchState.CANCELLED)
    return (BankStatementLine.objects
            .filter(bank_import_id=import_id, cancelled_at__isnull=True,
                    match_status=LineMatchStatus.UNMATCHED, excluded_at__isnull=True)
            .exclude(Exists(live_match)))


def _match_chunk(import_id, after: tuple[int, str] | None) -> tuple[int, str] | None:
    """Одна пачка строк — одна транзакция. Ответ — курсор последней взятой
    строки (``row_no``, ``pk``) или ``None``, если строк больше нет либо
    загрузка уже не сверяется (отменена)."""
    with transaction.atomic():
        imp = (BankImport.objects.select_for_update().only("id", "status")
               .filter(pk=import_id).first())
        if imp is None or imp.status not in _LIVE_IMPORT:
            return None
        rows = _pending(import_id)
        if after is not None:
            rows = rows.filter(Q(row_no__gt=after[0]) | Q(row_no=after[0], pk__gt=after[1]))
        lines = list(rows.select_for_update(of=("self",)).order_by("row_no", "pk")[:CHUNK])
        if not lines:
            return None

        found = {line.pk: recon.find_numbers(line.purpose) for line in lines}
        ids_by_number: dict[str, str] = {}
        for number in dict.fromkeys(n for numbers in found.values() for n in numbers):
            invoice = bpp_interface.find_by_number(number)
            if invoice is not None:
                ids_by_number[number] = invoice["id"]
        locked = _lock_invoices(ids_by_number.values())
        by_number = {number: locked[key] for number, key in ids_by_number.items()
                     if key in locked}
        # Остатки для распределения — от зафиксированной суммы под блокировкой,
        # с учётом сопоставлений, сделанных этой же пачкой.
        paid = {key: inv.paid_bank_amount for key, inv in locked.items()}

        now = timezone.now()
        matches: list[PaymentMatch] = []
        touched: set[str] = set()
        for line in lines:
            status, reason, planned = _decide(line, found[line.pk], by_number, paid)
            state = (PaymentMatchState.ACTIVE if status == LineMatchStatus.MATCHED
                     else PaymentMatchState.REVIEW)
            for inv, amount, problem in planned:
                matches.append(PaymentMatch(
                    line=line, invoice=inv, amount=amount, manual=False, state=state,
                    review_reason="" if state == PaymentMatchState.ACTIVE else problem))
                if state == PaymentMatchState.ACTIVE:
                    paid[str(inv.pk)] += amount
                    touched.add(str(inv.pk))
            line.match_status, line.review_reason = status, reason
            line.found_numbers, line.updated_at = found[line.pk], now
        PaymentMatch.objects.bulk_create(matches)
        BankStatementLine.objects.bulk_update(
            lines, ["match_status", "review_reason", "found_numbers", "updated_at"])
        for key in sorted(touched):
            recalc_invoice(key)
        return lines[-1].row_no, lines[-1].pk


def auto_match(import_id) -> dict:
    """Автосверка загрузки ``import_id`` (в контексте её компании). Загрузка
    «Загружена» после неё — «Сверена»; повтор на «Сверена» доводит только
    то, что осталось «Не сопоставлена». Загрузка в ином статусе
    (разбирается, ошибка, отменена) не сверяется. Ответ — ``totals``."""
    after = None
    while True:
        after = _match_chunk(import_id, after)
        if after is None:
            break
    result = totals(import_id)
    now = timezone.now()
    reconciled = BankImport.objects.filter(pk=import_id, status=BankImportStatus.LOADED).update(
        status=BankImportStatus.RECONCILED, updated_at=now)
    if reconciled:
        audit.record_for("bpp.bankimport", str(import_id), "reconciled", actor_id=None,
                         changes={tab: result[tab]["count"] for tab in LineMatchStatus.values})
    return result


# ── итоги по вкладкам ───────────────────────────────────────────────────

def allocated_subquery(line_ref: str = "pk") -> Coalesce:
    """Σ действующих и «на проверке» сопоставлений строки — для аннотации
    ``allocated`` (``OuterRef(line_ref)`` — ключ строки выписки)."""
    rows = (PaymentMatch.objects.filter(line=OuterRef(line_ref))
            .exclude(state=PaymentMatchState.CANCELLED)
            .order_by().values("line").annotate(total=Sum("amount")).values("total"))
    field = DecimalField(max_digits=18, decimal_places=2)
    return Coalesce(Subquery(rows, output_field=field), ZERO, output_field=field)


def totals(import_id) -> dict:
    """Итоги загрузки по вкладкам — ``{matched, needs_review, unmatched,
    excluded: {count, amount}, unallocated}``: число действующих строк и Σ
    их сумм; ``unallocated`` — Σ частей строк «Сопоставлена» и «Требует
    проверки», не разложенных ни на один счёт (переплата по строке с
    несколькими номерами)."""
    live = BankStatementLine.objects.filter(bank_import_id=import_id, cancelled_at__isnull=True)
    by_tab = {row["match_status"]: row for row in
              live.order_by().values("match_status").annotate(count=Count("pk"),
                                                              amount=Sum("amount"))}
    result = {tab: {"count": by_tab.get(tab, {}).get("count", 0),
                    "amount": money(by_tab.get(tab, {}).get("amount") or ZERO)}
              for tab in LineMatchStatus.values}
    rest = (live.filter(match_status__in=(LineMatchStatus.MATCHED, LineMatchStatus.NEEDS_REVIEW))
            .annotate(allocated=allocated_subquery())
            .filter(allocated__lt=F("amount"))
            .aggregate(total=Sum(F("amount") - F("allocated")))["total"])
    result["unallocated"] = money(rest or ZERO)
    return result

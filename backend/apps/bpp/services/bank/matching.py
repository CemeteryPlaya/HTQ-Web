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
без единого сопоставления — даже отменённого: сопоставление, которое ФД
отменил, автосверка не создаёт снова (его решение важнее номера в
назначении). Повтор автосверки ничего не удваивает; строка без
сопоставлений проверяется заново (счёт с этим номером мог появиться).

**Ручные действия ФД** (ТЗ §11.4, задача 3) — ниже, после автосверки:
кандидаты ``candidates``, ручное сопоставление ``match_line`` (сразу
``active``, ``manual=True``), подтверждение ``confirm`` (``review`` →
``active`` на месте), отмена ``cancel_match``, исключение ``exclude``,
отмена загрузки ``cancel_import`` (мягкая) и её охват ``impact``, «Сверить»
``reconcile`` (автосверка загрузки «Загружена», если она упала после
разбора). Каждое — одна транзакция: запись в журнал загрузки и
``recalc_invoice`` затронутых счетов в ней же. Комментарий подтверждения,
отмены сопоставления и исключения обязателен (BR-060: «Отменить» — среди
отказных действий), ручного сопоставления и отмены загрузки — нет.

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
(контракт мастер-плана §2.6 — ``matching.recalc_invoice``: живёт здесь,
рядом с записью сопоставлений; в ``recon`` её не перенести — ``recon``
импортируется отсюда, реэкспорт дал бы цикл).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.db import transaction
from django.db.models import (
    Case,
    Count,
    DecimalField,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Abs, Coalesce
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
from apps.bpp.services.money import fmt, money
from htqweb.errors import DomainError

from . import recon

__all__ = [
    "AUDIT_TYPE",
    "CANDIDATES_LIMIT",
    "CHUNK",
    "COMMENT_MIN",
    "FORBIDDEN_STATUSES",
    "PAYABLE_STATUSES",
    "REVIEW_REASONS",
    "allocated_subquery",
    "auto_match",
    "cancel_import",
    "cancel_match",
    "candidates",
    "confirm",
    "exclude",
    "impact",
    "match_line",
    "recalc_invoice",
    "reconcile",
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

#: ТЗ §11.4: с «Отменён» и «Не к оплате» платёж не сопоставляется вручную;
#: «Заменён альтернативой» — такой же финал счёта. Эти же статусы не
#: подтверждаются из «Требует проверки» (подтверждение — то же ручное
#: сопоставление) и не предлагаются кандидатами.
FORBIDDEN_STATUSES = frozenset({
    InvoiceStatus.CANCELLED, InvoiceStatus.NOT_PAYABLE, InvoiceStatus.REPLACED,
})
#: BR-060: комментарий подтверждения, отмены сопоставления и исключения — не короче.
COMMENT_MIN = 10
#: Кандидатов для ручного сопоставления — не больше (ТЗ §11.2).
CANDIDATES_LIMIT = 5
#: «Близкая сумма» кандидата — ±10 % суммы строки (мастер-план A4.2).
CANDIDATE_SPREAD = Decimal("0.10")

_LIVE_IMPORT = (BankImportStatus.LOADED, BankImportStatus.RECONCILED)
#: Журнал загрузки выписки — тип объекта = ``app_label.model``.
AUDIT_TYPE = BankImport._meta.label_lower


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
    """P = Σ подтверждённых сопоставлений (``recon.active_matches``, D-S4-1).
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
    # Одно определение «подтверждённого» сопоставления на всех читателей
    # суммы (дашборд, «Оплачено факт», фильтр реестра) — ``recon.active_matches``.
    paid = (recon.active_matches().filter(invoice_id=invoice_id)
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
    return recon.plain_reg(value)


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
    сопоставлена», не исключённые и без единого сопоставления — отменённое
    ФД сопоставление автосверка не возвращает."""
    any_match = PaymentMatch.objects.filter(line=OuterRef("pk"))
    return (BankStatementLine.objects
            .filter(bank_import_id=import_id, cancelled_at__isnull=True,
                    match_status=LineMatchStatus.UNMATCHED, excluded_at__isnull=True)
            .exclude(Exists(any_match)))


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


def auto_match(import_id, *, actor_id: int | None = None) -> dict:
    """Автосверка загрузки ``import_id`` (в контексте её компании). Загрузка
    «Загружена» после неё — «Сверена»; повтор на «Сверена» доводит только
    то, что осталось «Не сопоставлена». Загрузка в ином статусе
    (разбирается, ошибка, отменена) не сверяется. Ответ — ``totals``.
    ``actor_id`` — кто нажал «Сверить» (пусто — автосверка после разбора)."""
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
        audit.record_for(AUDIT_TYPE, str(import_id), "reconciled", actor_id=actor_id,
                         changes={tab: result[tab]["count"] for tab in LineMatchStatus.values})
    return result


def reconcile(actor_id: int, import_id) -> dict:
    """«Сверить» (ФД): автосверка загрузки, оставшейся «Загружена», — после
    разбора она идёт сама, и ручка нужна, только если та упала (M-2 ревью
    задачи 2). Только для «Загружена» — иначе ``E-STATE-01``; уже
    сопоставленные, исключённые и отменённые ФД строки автосверка не трогает
    (``_pending``), поэтому повтор ничего не удваивает. Две одновременные
    «Сверить» безопасны: пачки автосверки блокируют загрузку. Ответ —
    ``totals``."""
    key = _as_uuid(import_id)
    imp = (BankImport.objects.only("id", "number", "status").filter(pk=key).first()
           if key else None)
    if imp is None:
        raise _not_found("Загрузка выписки")
    if imp.status != BankImportStatus.LOADED:
        raise _state(f"Загрузка {imp.number} — «{imp.get_status_display()}»: сверить можно "
                     f"только загрузку «Загружена».")
    return auto_match(imp.pk, actor_id=actor_id)


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


# ── ручные действия ФД (ТЗ §11.4, задача 3) ────────────────────────────

def _invalid(field: str, message: str) -> DomainError:
    return DomainError("E-VAL-01", message, fields=[{"field": field, "message": message}])


def _state(message: str) -> DomainError:
    return DomainError("E-STATE-01", message, status=409)


def _not_found(what: str) -> DomainError:
    return DomainError("E-NOT-FOUND", f"{what} не найдена.", status=404)


def _as_uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _comment(comment, *, required: bool) -> str:
    """BR-060: обязательный комментарий — не короче ``COMMENT_MIN``;
    необязательный хранится как есть."""
    text = str(comment or "").strip()
    if required and len(text) < COMMENT_MIN:
        raise DomainError(
            "BR-060", "Опишите причину: комментарий не короче 10 символов.",
            fields=[{"field": "comment", "message": f"Минимум {COMMENT_MIN} символов"}])
    return text


_IMPORT_STATE_TEXT = {
    BankImportStatus.PROCESSING: "ещё разбирается",
    BankImportStatus.FAILED: "не загрузилась",
    BankImportStatus.CANCELLED: "отменена",
}


def _lock_import(import_id) -> BankImport:
    key = _as_uuid(import_id)
    imp = (BankImport.objects.select_for_update().defer("source").filter(pk=key).first()
           if key else None)
    if imp is None:
        raise _not_found("Загрузка выписки")
    return imp


def _locked_line(line_id) -> tuple[BankImport, BankStatementLine]:
    """Строка под блокировкой в общем порядке: сначала её загрузка, потом
    строка. Загрузка должна быть «Загружена» или «Сверена», строка — не
    отменена."""
    key = _as_uuid(line_id)
    import_id = (BankStatementLine.objects.filter(pk=key)
                 .values_list("bank_import_id", flat=True).first() if key else None)
    if import_id is None:
        raise _not_found("Строка выписки")
    imp = _lock_import(import_id)
    line = BankStatementLine.objects.select_for_update().get(pk=key)
    if imp.status not in _LIVE_IMPORT or line.cancelled_at is not None:
        state = _IMPORT_STATE_TEXT.get(imp.status, "отменена")
        raise _state(f"Загрузка {imp.number} {state} — строки её выписки не меняются.")
    return imp, line


def _record(imp: BankImport, action: str, *, actor_id: int, line: BankStatementLine | None = None,
            changes: dict | None = None, comment: str = "") -> None:
    data = dict(changes or {})
    if line is not None:
        data = {"line_id": str(line.pk), "row_no": line.row_no, "doc_number": line.doc_number,
                "amount": str(line.amount), **data}
    audit.record_for(AUDIT_TYPE, str(imp.pk), action, actor_id=actor_id, changes=data,
                     comment=comment)


def _recalc_all(invoice_ids, actor_id: int | None) -> None:
    for key in sorted({str(key) for key in invoice_ids}):
        recalc_invoice(key, actor_id=actor_id)


def _refuse_invoice(inv: Invoice | None, line: BankStatementLine, action: str) -> None:
    """ТЗ §11.4 и M-4: счёт существует, не в финальном статусе отказа, в
    валюте платежа — иначе ``E-VAL-01`` на ``invoice_id``."""
    if inv is None:
        raise _invalid("invoice_id", "Счёт не найден. Выберите счёт из списка.")
    if inv.status in FORBIDDEN_STATUSES:
        raise _invalid("invoice_id", f"Счёт {inv.number} в статусе «{inv.get_status_display()}» "
                                     f"— {action} с ним нельзя.")
    if _plain(line.currency) != _plain(inv.currency_code):
        raise _invalid("invoice_id", REVIEW_REASONS[CURRENCY_MISMATCH])


def _amount(value) -> Decimal:
    try:
        amount = money(Decimal(str(value).replace(" ", "").replace(",", ".")))
    except (ArithmeticError, ValueError, TypeError):
        raise _invalid("amount", "Укажите сумму сопоставления числом.") from None
    if not amount.is_finite():
        raise _invalid("amount", "Укажите сумму сопоставления числом.")
    if amount <= 0:
        raise _invalid("amount", "Сумма сопоставления должна быть больше нуля.")
    return amount


# ── кандидаты ────────────────────────────────────────────────────────────

def _query_filter(text: str) -> Q:
    """Поиск кандидата по номеру счёта (часть номера или полный номер в
    «грязном» виде — как в назначении платежа), контрагенту (название, БИН)
    и сумме."""
    number = recon.normalize_purpose(text).replace(" ", "")
    condition = (Q(number__icontains=number) | Q(counterparty__name__icontains=text)
                 | Q(counterparty__short_name__icontains=text)
                 | Q(counterparty__reg_number__icontains=text.replace(" ", "")))
    numbers = recon.find_numbers(text)
    if numbers:  # «сч 2026 000123» — тот же разбор, что у автосверки
        condition |= Q(number__in=numbers)
    try:
        amount = money(Decimal(text.replace(" ", "").replace("\u00a0", "").replace(",", ".")))
    except (ArithmeticError, ValueError):
        return condition
    return condition | Q(amount=amount) if amount.is_finite() else condition


def candidates(line_id, query: str = "") -> list[dict]:
    """До 5 счетов для «Сопоставить вручную» (ТЗ §11.2, §11.4).

    Без ``query`` — счета с тем же БИН контрагента, что у получателя
    платежа, и суммой в пределах ±10 % суммы строки. С ``query`` — поиск по
    номеру, контрагенту (название, БИН) и сумме, где счета «тот же БИН и
    близкая сумма» идут первыми. В обоих случаях — только счета в валюте
    платежа и не «Отменён» / «Не к оплате» / «Заменён альтернативой»;
    ближе по сумме — выше."""
    key = _as_uuid(line_id)
    line = BankStatementLine.objects.filter(pk=key).first() if key else None
    if line is None:
        raise _not_found("Строка выписки")
    rows = (Invoice.objects.select_related("counterparty")
            .exclude(status__in=FORBIDDEN_STATUSES)
            .filter(currency_code__iexact=_plain(line.currency)))
    reg = _plain(line.recipient_bin)
    spread = money(line.amount * CANDIDATE_SPREAD)
    close = (Q(counterparty__reg_number=reg, amount__gte=line.amount - spread,
               amount__lte=line.amount + spread) if reg else None)
    text = " ".join(str(query or "").split())
    if text:
        rows = rows.filter(_query_filter(text))
    elif close is None:
        return []
    else:
        rows = rows.filter(close)
    rank = (Case(When(close, then=Value(0)), default=Value(1), output_field=IntegerField())
            if close is not None else Value(1, output_field=IntegerField()))
    rows = (rows.annotate(rank=rank, diff=Abs(F("amount") - line.amount))
            .order_by("rank", "diff", "number")[:CANDIDATES_LIMIT])
    return [_candidate(inv, reg) for inv in rows]


def _candidate(inv: Invoice, reg: str) -> dict:
    cp = inv.counterparty
    return {
        "id": str(inv.pk), "number": inv.number, "status": inv.status,
        "status_label": inv.get_status_display(), "amount": inv.amount,
        "currency_code": inv.currency_code, "paid_bank_amount": inv.paid_bank_amount,
        "remainder": max(inv.amount - inv.paid_bank_amount, ZERO),
        "recon_status": inv.recon_status, "recon_status_label": inv.get_recon_status_display(),
        "counterparty": ({"id": str(cp.pk), "name": cp.short_name or cp.name,
                          "reg_number": cp.reg_number} if cp else None),
        "same_bin": bool(cp and reg and _plain(cp.reg_number) == reg),
        "ext_number": inv.ext_number, "ext_date": inv.ext_date,
    }


# ── сопоставить, подтвердить, отменить, исключить ──────────────────────

@transaction.atomic
def match_line(actor_id: int, line_id, allocations: list[dict], comment: str = ""
               ) -> BankStatementLine:
    """«Сопоставить вручную» (ТЗ §11.4): строка «Не сопоставлена» →
    «Сопоставлена», сопоставления ``manual=True`` сразу ``active``.
    ``allocations`` — ``[{invoice_id, amount}]``; у единственного счёта
    сумму можно не указывать — вся строка. Σ распределения ≤ суммы строки
    (остаток строки остаётся «не распределено»)."""
    comment = _comment(comment, required=False)
    imp, line = _locked_line(line_id)
    if line.match_status != LineMatchStatus.UNMATCHED:
        raise _state("Сопоставить вручную можно только строку «Не сопоставлена». Сначала "
                     "отмените её сопоставление.")
    items = list(allocations or [])
    if not items:
        raise _invalid("invoice_id", "Выберите счёт для сопоставления.")
    plan: list[tuple[str, Decimal]] = []
    for item in items:
        key = _as_uuid((item or {}).get("invoice_id"))
        if key is None:
            raise _invalid("invoice_id", "Счёт не найден. Выберите счёт из списка.")
        raw = (item or {}).get("amount")
        if raw in (None, "") and len(items) == 1:
            amount = line.amount
        elif raw in (None, ""):
            raise _invalid("amount", "Укажите сумму для каждого счёта распределения.")
        else:
            amount = _amount(raw)
        if str(key) in {k for k, _ in plan}:
            raise _invalid("invoice_id", "Один счёт указан в распределении дважды.")
        plan.append((str(key), amount))
    total = sum((amount for _, amount in plan), ZERO)
    if total > line.amount:
        raise _invalid("amount", f"Сумма распределения {fmt(total, line.currency)} больше суммы "
                                 f"строки выписки {fmt(line.amount, line.currency)}.")
    locked = _lock_invoices(key for key, _ in plan)
    for key, _ in plan:
        _refuse_invoice(locked.get(key), line, "сопоставить платёж")
    now = timezone.now()
    PaymentMatch.objects.bulk_create([
        PaymentMatch(line=line, invoice=locked[key], amount=amount, manual=True,
                     state=PaymentMatchState.ACTIVE, comment=comment, created_by=actor_id,
                     updated_by=actor_id)
        for key, amount in plan])
    line.match_status, line.review_reason, line.updated_at = LineMatchStatus.MATCHED, "", now
    line.updated_by = actor_id
    line.save(update_fields=["match_status", "review_reason", "updated_at", "updated_by"])
    _recalc_all(locked, actor_id)
    _record(imp, "line_matched", actor_id=actor_id, line=line, comment=comment, changes={
        "allocations": [{"invoice": locked[key].number, "amount": str(amount)}
                        for key, amount in plan]})
    return line


@transaction.atomic
def confirm(actor_id: int, line_id, comment: str) -> BankStatementLine:
    """«Подтвердить сопоставление» строки «Требует проверки» (ТЗ §11.2,
    BR-073): комментарий обязателен (BR-060), сопоставления ``review`` →
    ``active`` на месте, статус сверки счетов пересчитывается. Счёт в
    «Отменён» / «Не к оплате» / «Заменён альтернативой» и платёж в другой
    валюте не подтверждаются — ``E-VAL-01`` на ``invoice_id``."""
    comment = _comment(comment, required=True)
    imp, line = _locked_line(line_id)
    if line.match_status != LineMatchStatus.NEEDS_REVIEW:
        raise _state("Подтвердить можно только строку «Требует проверки».")
    matches = list(line.matches.filter(state=PaymentMatchState.REVIEW)
                   .select_for_update().order_by("created_at", "pk"))
    if not matches:
        raise _state("У строки нет сопоставлений на проверке — сопоставьте её вручную.")
    locked = _lock_invoices(m.invoice_id for m in matches)
    for match in matches:
        _refuse_invoice(locked.get(str(match.invoice_id)), line, "подтвердить сопоставление")
    now = timezone.now()
    PaymentMatch.objects.filter(pk__in=[m.pk for m in matches]).update(
        state=PaymentMatchState.ACTIVE, confirmed_by_id=actor_id, confirmed_at=now,
        comment=comment, updated_at=now, updated_by=actor_id)
    reason = line.review_reason
    line.match_status, line.review_reason, line.updated_at = LineMatchStatus.MATCHED, "", now
    line.updated_by = actor_id
    line.save(update_fields=["match_status", "review_reason", "updated_at", "updated_by"])
    _recalc_all(locked, actor_id)
    _record(imp, "match_confirmed", actor_id=actor_id, line=line, comment=comment, changes={
        "review_reason": reason,
        "invoices": [locked[str(m.invoice_id)].number for m in matches]})
    return line


@transaction.atomic
def cancel_match(actor_id: int, line_id, comment: str) -> BankStatementLine:
    """«Отменить сопоставление» (вкладки «Сопоставлены» и «Требуют
    проверки»): все неотменённые сопоставления строки — ``cancelled`` (в
    истории остаются), строка — «Не сопоставлена», счета пересчитываются.
    Комментарий обязателен (BR-060 — «Отменить»). Автосверка эту строку
    больше не трогает — дальше только вручную. У строки «Исключена» то же
    действие снимает исключение."""
    comment = _comment(comment, required=True)
    imp, line = _locked_line(line_id)
    now = timezone.now()
    if line.match_status == LineMatchStatus.EXCLUDED:
        changes = {"excluded_comment": line.excluded_comment}
        line.match_status, line.updated_at, line.updated_by = (LineMatchStatus.UNMATCHED, now,
                                                                actor_id)
        line.excluded_comment, line.excluded_by_id, line.excluded_at = "", None, None
        line.save(update_fields=["match_status", "excluded_comment", "excluded_by_id",
                                 "excluded_at", "updated_at", "updated_by"])
        _record(imp, "exclusion_cancelled", actor_id=actor_id, line=line, comment=comment,
                changes=changes)
        return line
    if line.match_status not in (LineMatchStatus.MATCHED, LineMatchStatus.NEEDS_REVIEW):
        raise _state("Строка не сопоставлена — отменять нечего.")
    matches = list(line.matches.exclude(state=PaymentMatchState.CANCELLED)
                   .select_for_update().order_by("created_at", "pk"))
    locked = _lock_invoices(m.invoice_id for m in matches)
    PaymentMatch.objects.filter(pk__in=[m.pk for m in matches]).update(
        state=PaymentMatchState.CANCELLED, cancelled_by_id=actor_id, cancelled_at=now,
        updated_at=now, updated_by=actor_id)
    previous = line.match_status
    line.match_status, line.review_reason, line.updated_at = LineMatchStatus.UNMATCHED, "", now
    line.updated_by = actor_id
    line.save(update_fields=["match_status", "review_reason", "updated_at", "updated_by"])
    _recalc_all(locked, actor_id)
    _record(imp, "match_cancelled", actor_id=actor_id, line=line, comment=comment, changes={
        "match_status": previous,
        "matches": [{"invoice": locked[str(m.invoice_id)].number, "amount": str(m.amount),
                     "state": m.state} for m in matches]})
    return line


@transaction.atomic
def exclude(actor_id: int, line_id, comment: str) -> BankStatementLine:
    """«Исключить — не относится к закупкам» (ТЗ §11.4): строка «Не
    сопоставлена» → «Исключена», комментарий обязателен (BR-060). Счета не
    затрагиваются; в показатель дашборда «Не сопоставлено» строка больше не
    входит (ТЗ §11.4 называет её «Прочие списания»; отдельного показателя в
    таблице D-01 §11.5 нет)."""
    comment = _comment(comment, required=True)
    imp, line = _locked_line(line_id)
    if line.match_status != LineMatchStatus.UNMATCHED:
        raise _state("Исключить можно только строку «Не сопоставлена». Сначала отмените её "
                     "сопоставление.")
    now = timezone.now()
    line.match_status, line.review_reason = LineMatchStatus.EXCLUDED, ""
    line.excluded_comment, line.excluded_by_id, line.excluded_at = comment, actor_id, now
    line.updated_at, line.updated_by = now, actor_id
    line.save(update_fields=["match_status", "review_reason", "excluded_comment",
                             "excluded_by_id", "excluded_at", "updated_at", "updated_by"])
    _record(imp, "line_excluded", actor_id=actor_id, line=line, comment=comment)
    return line


# ── отмена загрузки ─────────────────────────────────────────────────────

def _impact_matches(import_id):
    return PaymentMatch.objects.filter(line__bank_import_id=import_id,
                                       line__cancelled_at__isnull=True).exclude(
        state=PaymentMatchState.CANCELLED)


def impact(import_id) -> dict:
    """Для диалога «Отменить загрузку» (ТЗ §11.4): ``invoices`` — сколько
    счетов затронет отмена (у них есть действующие или проверяемые
    сопоставления строк загрузки), ``lines`` — действующих строк."""
    key = _as_uuid(import_id)
    if key is None or not BankImport.objects.filter(pk=key).exists():
        raise _not_found("Загрузка выписки")
    invoices = _impact_matches(key).order_by().values("invoice_id").distinct().count()
    lines = BankStatementLine.objects.filter(bank_import_id=key,
                                             cancelled_at__isnull=True).count()
    return {"invoices": invoices, "lines": lines}


@transaction.atomic
def cancel_import(actor_id: int, import_id, comment: str = "") -> BankImport:
    """«Отменить загрузку» (ТЗ §11.4, мягко): строки загрузки и их
    сопоставления получают ``cancelled_at`` (сопоставления — ещё и
    ``cancelled``), статусы сверки затронутых счетов пересчитываются,
    загрузка — «Отменена». Ключи дублей строк освобождаются (индекс BR-075
    — среди неотменённых строк), поэтому та же выписка потом грузится и
    сверяется заново. Отметка оплаты БУХ, которую держала сверка
    (``PaymentMark`` не отменяется при ``paid_bank_amount > 0``), снова
    отменяема."""
    comment = _comment(comment, required=False)
    imp = _lock_import(import_id)
    if imp.status not in _LIVE_IMPORT:
        state = _IMPORT_STATE_TEXT.get(imp.status, "отменена")
        raise _state(f"Загрузка {imp.number} {state} — отменить можно загрузку «Сверена» "
                     f"или «Загружена».")
    lines = list(imp.lines.filter(cancelled_at__isnull=True).select_for_update()
                 .order_by("row_no", "pk").values_list("pk", flat=True))
    matches = list(_impact_matches(imp.pk).values_list("pk", "invoice_id"))
    invoice_ids = {str(invoice_id) for _, invoice_id in matches}
    _lock_invoices(invoice_ids)
    now = timezone.now()
    PaymentMatch.objects.filter(pk__in=[pk for pk, _ in matches]).update(
        state=PaymentMatchState.CANCELLED, cancelled_by_id=actor_id, cancelled_at=now,
        updated_at=now, updated_by=actor_id)
    BankStatementLine.objects.filter(pk__in=lines).update(cancelled_at=now, updated_at=now,
                                                          updated_by=actor_id)
    previous = imp.status
    BankImport.objects.filter(pk=imp.pk).update(status=BankImportStatus.CANCELLED,
                                                updated_at=now, updated_by=actor_id)
    _recalc_all(invoice_ids, actor_id)
    _record(imp, "cancelled", actor_id=actor_id, comment=comment, changes={
        "status": [previous, BankImportStatus.CANCELLED], "lines": len(lines),
        "matches": len(matches), "invoices": len(invoice_ids)})
    imp.refresh_from_db()
    return imp

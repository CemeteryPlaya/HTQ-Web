"""Бизнес-метрики договорного контура.

Собирается по расписанию через ``apps.core.metrics`` — см. докстринг там.
Обращается только к своим моделям (правило изоляции аппок).

Домен денежный, и ломается он не отказом, а расхождением: договор согласован,
а статус не переведён; строка бюджета ушла в минус; оплата второй месяц висит
в «ожидает бухгалтерию». Ни одно из этих состояний не даёт ни 5xx, ни строки
в логе — снаружи система выглядит работающей, поэтому единственный способ их
увидеть — считать.

Три метрики здесь ОБЯЗАНЫ быть тождественно нулевыми: ``signoff_desync`` и
``budget_lines_overspent`` описывают нарушенный инвариант, а не нагрузку.
Остальные — справочные, у них порога нет и быть не должно.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone

# Единственная разрешённая форма обращения к соседу — его interface; он
# реэкспортирует ApprovalState специально для таких случаев (models.py этой
# же аппки берёт оттуда же примесь Approvable).
from apps.signoff.interface import ApprovalState

from .models import (
    AccountableFundsRequest,
    AccountableFundsRequestStatus,
    AdvancePayment,
    AdvancePaymentStatus,
    Agreement,
    AgreementStatus,
    BudgetLine,
    CompletionAct,
    ContractPayment,
    GoodsInvoice,
    Invoice,
)
from .services.budget_calc import (
    ACCOUNTABLE_FUNDS_COMMITTING_STATUSES,
    COMMITTING_STATUSES,
    INVOICE_COMMITTING_STATUSES,
    ZERO,
)

# Сколько дней в «ожидает оформления бухгалтерией» считается застреванием.
# Не константа домена, а порог наблюдения: бухгалтерия оформляет за 2–3 дня,
# неделя — это уже забыли.
STALE_ACCOUNTING_DAYS = 7


def _overspent_budget_lines() -> int:
    """Строки бюджета, где занято больше, чем выделено.

    Считается тем же правилом, что и в интерфейсе: ``budget_calc`` — это
    ЕДИНСТВЕННОЕ место, где записано решение «с какого момента документ
    занимает бюджет», поэтому статусы импортируются оттуда, а не
    переписываются здесь. Вторая копия этого списка означала бы вторую
    правду о деньгах.

    ``committed_map()`` не используется намеренно: он собирает
    ``budget_line_id__in=[...]`` со всеми идентификаторами, а раз в минуту
    гонять IN-список на тысячу элементов незачем — здесь тот же расчёт
    одним GROUP BY по всей таблице.
    """
    committed: dict[int, Decimal] = {}
    for queryset in (
        Agreement.objects.filter(status__in=COMMITTING_STATUSES),
        Invoice.objects.filter(status__in=INVOICE_COMMITTING_STATUSES),
        AccountableFundsRequest.objects.filter(
            status__in=ACCOUNTABLE_FUNDS_COMMITTING_STATUSES),
    ):
        rows = queryset.values("budget_line_id").annotate(total=Sum("amount"))
        for row in rows:
            line_id = row["budget_line_id"]
            # У заявки под отчёт строка бюджета необязательна (legacy-строки
            # ссылались на администратора и программу напрямую).
            if line_id is None:
                continue
            committed[line_id] = committed.get(line_id, ZERO) + (row["total"] or ZERO)

    return sum(1 for pk, amount in BudgetLine.objects.values_list("pk", "amount")
               if committed.get(pk, ZERO) > amount)


def collect() -> dict:
    now = timezone.now()
    stale_before = now - timezone.timedelta(days=STALE_ACCOUNTING_DAYS)

    # ── Договоры по статусам ───────────────────────────────────────────────
    agreements = [((row["status"],), row["n"]) for row in
                  Agreement.objects.values("status").annotate(n=Count("id"))]

    # ── Расхождение согласования и статуса ─────────────────────────────────
    # approval_state ставит signoff, status переводит apps/contracts/
    # approval_hooks.py. Если первое «approved», а второе застряло раньше —
    # хук не отработал, и договор согласован только на бумаге.
    desync = (Agreement.objects
              .filter(approval_state=ApprovalState.APPROVED)
              .exclude(status__in=[AgreementStatus.APPROVED,
                                   AgreementStatus.SIGNED,
                                   AgreementStatus.EXECUTED,
                                   AgreementStatus.TERMINATED])
              .count())

    # ── Деньги, застрявшие на оформлении ───────────────────────────────────
    # Четыре модели с одинаковым смыслом: документ согласован, деньги ждут
    # бухгалтерию. Считаем и штуки, и сумму — одним запросом на модель:
    # штуки говорят «сколько забыли», сумма — «насколько это дорого».
    awaiting_counts: list[tuple[tuple[str, ...], float]] = []
    awaiting_amounts: list[tuple[tuple[str, ...], float]] = []
    payment_like = (
        ("payment", ContractPayment),
        ("completion_act", CompletionAct),
        ("goods_invoice", GoodsInvoice),
        ("advance_payment", AdvancePayment),
    )
    for label, model in payment_like:
        row = (model.objects
               .filter(status=AdvancePaymentStatus.AWAITING_ACCOUNTING,
                       paid_at__isnull=True, updated_at__lt=stale_before)
               .aggregate(n=Count("id"), total=Sum("amount")))
        awaiting_counts.append(((label,), row["n"]))
        awaiting_amounts.append(((label,), float(row["total"] or ZERO)))

    # У заявки под отчёт нет paid_at — факт оплаты отмечен своим флагом.
    funds_row = (AccountableFundsRequest.objects
                 .filter(status=AccountableFundsRequestStatus.AWAITING_ACCOUNTING,
                         accounting_paid=False, updated_at__lt=stale_before)
                 .aggregate(n=Count("id"), total=Sum("amount")))
    awaiting_counts.append((("accountable_funds",), funds_row["n"]))
    awaiting_amounts.append((("accountable_funds",),
                             float(funds_row["total"] or ZERO)))

    # ── Наличные на руках ──────────────────────────────────────────────────
    # Деньги выданы, авансовый отчёт не сдан. Это не поломка, а величина,
    # которую руководитель хочет видеть каждое утро.
    outstanding = (AccountableFundsRequest.objects
                   .filter(status=AccountableFundsRequestStatus.AWAITING_ADVANCE_REPORT)
                   .aggregate(total=Sum("amount"))["total"]) or ZERO

    return {
        "contracts_agreements": {
            "help": "Договоры по статусам",
            "labels": ["status"],
            "values": agreements,
        },
        "contracts_signoff_desync": {
            "help": "Договоры, согласованные в signoff, но не переведённые по статусу",
            "values": [((), desync)],
        },
        "contracts_awaiting_accounting": {
            "help": (
                "Документы в «ожидает бухгалтерию» дольше %d дней"
                % STALE_ACCOUNTING_DAYS
            ),
            "labels": ["kind"],
            "values": awaiting_counts,
        },
        "contracts_awaiting_accounting_amount": {
            "help": "Сумма документов, ожидающих бухгалтерию",
            "labels": ["kind"],
            "values": awaiting_amounts,
        },
        "contracts_accountable_funds_outstanding": {
            "help": "Сумма выданных подотчётных средств без авансового отчёта",
            "values": [((), float(outstanding))],
        },
        "contracts_budget_lines_overspent": {
            "help": "Строки бюджета, где занятая сумма превысила выделенную",
            "values": [((), _overspent_budget_lines())],
        },
    }

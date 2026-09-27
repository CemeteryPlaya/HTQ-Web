"""«Задействовано» по статье бюджета проекта — CALC-002 (D-08, задача B2.4).

Считается на лету, не хранится. Сумма по позициям заявок на статью проекта
в статусах заявки «На согласовании», «Утверждена», «Закрыта»:

- открытая или частично закрытая позиция — ``max(план; Σ позиций договоров
  «На согласовании»/«Действует»; Σ строк счетов от «На рассмотрении ФД»,
  кроме «Отменён» и «Не к оплате»)``;
- закрытая или аннулированная позиция — ``Σ строк счетов``.

К позициям прибавляется подотчёт (B4.1) — суммы заявок на подотчётные
средства от «На согласовании» и дальше. Договоров и счетов ещё нет: их
слагаемые позиции приходят в B3.3. Поэтому формула собрана из списков слагаемых
(``_OPEN_ITEM_TERMS``, ``_CLOSED_ITEM_TERMS``): добавить слагаемое — одна
строка в списке, сам агрегат и эталон не меняются.

Две реализации намеренно:

- ``committed_by_article`` — один SQL-агрегат для реестров, остатков и
  проверок под блокировкой;
- ``committed_reference`` — независимый пересчёт по позициям в Python для
  ночной сверки и тестов. Расхождение двух значит, что сломана одна из них.
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Case, DecimalField, F, Sum, Value, When
from django.db.models.functions import Coalesce, Greatest

from apps.bpp.models import (
    AccountableFundsRequest,
    AccountableStatus,
    ItemStatus,
    PurchaseRequestItem,
    RequestStatus,
)

ZERO = Decimal("0.00")

#: Статусы заявки, в которых её позиции занимают бюджет (BR-012).
COMMITTING_REQUEST_STATUSES = (RequestStatus.IN_APPROVAL, RequestStatus.APPROVED,
                               RequestStatus.CLOSED)
OPEN_ITEM_STATUSES = (ItemStatus.OPEN, ItemStatus.PARTIALLY_CLOSED)
#: Подотчёт занимает сумму заявки с отправки на согласование и дальше; выданные
#: деньги в бюджет не возвращаются и после закрытия (B4.1, как в contracts).
COMMITTING_ACCOUNTABLE_STATUSES = (AccountableStatus.ON_REVIEW,
                                   AccountableStatus.AWAITING_ACCOUNTING,
                                   AccountableStatus.AWAITING_REPORT,
                                   AccountableStatus.CLOSED)

_MONEY = DecimalField(max_digits=18, decimal_places=2)

#: Слагаемые открытой позиции сверх плана: Σ договоров, Σ счетов (B3.3).
#: Каждое — выражение над строкой ``PurchaseRequestItem``.
_OPEN_ITEM_TERMS: list = []
#: Слагаемые закрытой или аннулированной позиции: Σ строк счетов (B3.3).
_CLOSED_ITEM_TERMS: list = []


def _open_expr():
    plan = F("amount")
    return Greatest(plan, *_OPEN_ITEM_TERMS) if _OPEN_ITEM_TERMS else plan


def _closed_expr():
    if not _CLOSED_ITEM_TERMS:
        return Value(ZERO, output_field=_MONEY)
    total = _CLOSED_ITEM_TERMS[0]
    for term in _CLOSED_ITEM_TERMS[1:]:
        total = total + term
    return total


def _items(project_id, article_ids=None, *, exclude_request_id=None):
    rows = PurchaseRequestItem.objects.filter(
        request__project_id=project_id,
        request__status__in=COMMITTING_REQUEST_STATUSES)
    if article_ids is not None:
        rows = rows.filter(request__article_id__in=list(article_ids))
    if exclude_request_id is not None:
        rows = rows.exclude(request_id=exclude_request_id)
    return rows


def _accountable(project_id, article_ids=None, *, exclude_accountable_id=None):
    rows = AccountableFundsRequest.objects.filter(
        project_id=project_id, status__in=COMMITTING_ACCOUNTABLE_STATUSES)
    if article_ids is not None:
        rows = rows.filter(article_id__in=list(article_ids))
    if exclude_accountable_id is not None:
        rows = rows.exclude(pk=exclude_accountable_id)
    return rows


def committed_by_article(project_id, article_ids=None, *, exclude_request_id=None,
                         exclude_accountable_id=None) -> dict[str, Decimal]:
    """``{article_id: задействовано}`` по проекту; статьи без позиций — не в ответе.

    ``exclude_request_id`` / ``exclude_accountable_id`` — документ, который
    сравнивают с остатком: при повторной отправке после возврата его
    собственная сумма не должна съедать его же остаток.
    """
    per_item = Case(When(status__in=OPEN_ITEM_STATUSES, then=_open_expr()),
                    default=_closed_expr(), output_field=_MONEY)
    rows = (_items(project_id, article_ids, exclude_request_id=exclude_request_id)
            .values("request__article_id")
            .annotate(total=Coalesce(Sum(per_item), Value(ZERO, output_field=_MONEY))))
    totals = {str(row["request__article_id"]): row["total"] for row in rows}
    accountable = (_accountable(project_id, article_ids,
                                exclude_accountable_id=exclude_accountable_id)
                   .values("article_id").annotate(total=Sum("amount")))
    for row in accountable:
        key = str(row["article_id"])
        totals[key] = totals.get(key, ZERO) + row["total"]
    return totals


def committed_for(project_id, article_id, *, exclude_request_id=None,
                  exclude_accountable_id=None) -> Decimal:
    return committed_by_article(
        project_id, [article_id], exclude_request_id=exclude_request_id,
        exclude_accountable_id=exclude_accountable_id).get(str(article_id), ZERO)


# ── эталон для сверки ───────────────────────────────────────────────────

def _item_reference(item) -> Decimal:
    """Задействовано одной позицией — по тексту CALC-002, без SQL."""
    if item.status in OPEN_ITEM_STATUSES:
        return max([item.amount])  # + Σ договоров, Σ счетов (B3.3)
    return ZERO  # Σ счетов (B3.3)


def committed_reference(project_id, article_id) -> Decimal:
    total = ZERO
    for item in _items(project_id, [article_id]).select_related("request"):
        total += _item_reference(item)
    for accountable in _accountable(project_id, [article_id]):
        total += accountable.amount
    return total

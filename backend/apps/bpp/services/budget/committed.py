"""«Задействовано» по статье бюджета проекта — CALC-002 (D-08, задача B2.4).

Считается на лету, не хранится. Сумма по позициям заявок на статью проекта
в статусах заявки «На согласовании», «Утверждена», «Закрыта»:

- открытая или частично закрытая позиция — ``max(план; Σ позиций договоров
  «На согласовании»/«Действует»; Σ строк счетов от «На рассмотрении ФД»,
  кроме «Отменён» и «Не к оплате»)``;
- закрытая или аннулированная позиция — ``Σ строк счетов``.

К позициям прибавляется подотчёт (B4.1) — суммы заявок на подотчётные
средства от «На согласовании» и дальше, — и прирост допсоглашений (D-18): у
них нет своих позиций, поэтому они тоже считаются на уровне статьи.
Договоры — слагаемое открытой позиции (B3.1), строки счетов — открытой и
закрытой (B3.2). Формула собрана из списков слагаемых
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

from django.db.models import Case, DecimalField, F, OuterRef, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce, Greatest

from apps.bpp.models import (
    AccountableFundsRequest,
    AccountableStatus,
    Agreement,
    AgreementItem,
    AgreementStatus,
    InvoiceLine,
    InvoiceStatus,
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

#: Договоры, позиции которых занимают бюджет: «На согласовании» и «Действует»,
#: только закрытые — открытый договор бюджет не занимает, его занимают счета
#: (D-09). Расторгнутый и исполненный отпускают неосвоенное (Q-D02).
COMMITTING_AGREEMENT_STATUSES = (AgreementStatus.ON_REVIEW, AgreementStatus.ACTIVE)


def _agreements_term():
    """Σ сумм позиций закрытых договоров «На согласовании»/«Действует» по
    позиции заявки (с допсоглашениями — их позиции тоже здесь)."""
    rows = (AgreementItem.objects
            .filter(request_item=OuterRef("pk"), agreement__is_open=False,
                    agreement__status__in=COMMITTING_AGREEMENT_STATUSES,
                    amount__isnull=False)
            .values("request_item").annotate(total=Sum("amount")).values("total"))
    return Coalesce(Subquery(rows, output_field=_MONEY), Value(ZERO, output_field=_MONEY))


#: Счета, строки которых занимают бюджет: от «На рассмотрении ФД», кроме
#: «Отменён», «Не к оплате» и «Заменён» (CALC-002). Возвращённый на доработку
#: резерв отпускает, как заявка на доработке (ТЗ §7.7 [Л]).
COMMITTING_INVOICE_STATUSES = (InvoiceStatus.UNDER_REVIEW, InvoiceStatus.TO_PAY,
                               InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.PAID,
                               InvoiceStatus.AWAITING_DOCS, InvoiceStatus.DOCS_PROVIDED,
                               InvoiceStatus.CLOSED)


def _invoices_term():
    """Σ строк счетов по позиции заявки (B3.2)."""
    rows = (InvoiceLine.objects
            .filter(request_item=OuterRef("pk"), invoice__status__in=COMMITTING_INVOICE_STATUSES)
            .values("request_item").annotate(total=Sum("amount")).values("total"))
    return Coalesce(Subquery(rows, output_field=_MONEY), Value(ZERO, output_field=_MONEY))


#: Слагаемые открытой позиции сверх плана: Σ договоров (B3.1), Σ счетов (B3.2).
#: Каждое — выражение над строкой ``PurchaseRequestItem``.
_OPEN_ITEM_TERMS: list = [_agreements_term(), _invoices_term()]
#: Слагаемые закрытой или аннулированной позиции: Σ строк счетов (B3.2).
_CLOSED_ITEM_TERMS: list = [_invoices_term()]


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


def _supplements(project_id, article_ids=None):
    """Допсоглашения закрытых договоров «На согласовании»/«Действует» — их
    сумма есть прирост к родителю без своих позиций (D-18), поэтому считается
    на уровне статьи, как подотчёт: лимиты идут на общие суммы договоров."""
    rows = Agreement.objects.filter(
        project_id=project_id, parent_agreement__isnull=False, is_open=False,
        amount__isnull=False, status__in=COMMITTING_AGREEMENT_STATUSES)
    if article_ids is not None:
        rows = rows.filter(article_id__in=list(article_ids))
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
    for row in (_supplements(project_id, article_ids)
                .values("article_id").annotate(total=Sum("amount"))):
        key = str(row["article_id"])
        totals[key] = totals.get(key, ZERO) + row["total"]
    return totals


def committed_for(project_id, article_id, *, exclude_request_id=None,
                  exclude_accountable_id=None) -> Decimal:
    return committed_by_article(
        project_id, [article_id], exclude_request_id=exclude_request_id,
        exclude_accountable_id=exclude_accountable_id).get(str(article_id), ZERO)


# ── эталон для сверки ───────────────────────────────────────────────────

def _agreements_reference(item) -> Decimal:
    total = ZERO
    for row in AgreementItem.objects.filter(request_item=item).select_related("agreement"):
        agreement = row.agreement
        if (not agreement.is_open and row.amount is not None
                and agreement.status in COMMITTING_AGREEMENT_STATUSES):
            total += row.amount
    return total


def _invoices_reference(item, exclude_invoice_id=None) -> Decimal:
    total = ZERO
    for row in InvoiceLine.objects.filter(request_item=item).select_related("invoice"):
        if row.invoice_id == exclude_invoice_id:
            continue
        if row.invoice.status in COMMITTING_INVOICE_STATUSES:
            total += row.amount
    return total


def invoiced_for_item(item, *, exclude_invoice_id=None) -> Decimal:
    """Σ строк счетов, занимающих бюджет, по позиции — для BR-043 счёта."""
    return _invoices_reference(item, exclude_invoice_id)


def agreements_for_item(item) -> Decimal:
    """Σ позиций закрытых договоров по позиции — для BR-043 счёта."""
    return _agreements_reference(item)


def _item_reference(item) -> Decimal:
    """Задействовано одной позицией — по тексту CALC-002, без SQL."""
    if item.status in OPEN_ITEM_STATUSES:
        return max([item.amount, _agreements_reference(item), _invoices_reference(item)])
    return _invoices_reference(item)


def committed_reference(project_id, article_id) -> Decimal:
    total = ZERO
    for item in _items(project_id, [article_id]).select_related("request"):
        total += _item_reference(item)
    for accountable in _accountable(project_id, [article_id]):
        total += accountable.amount
    for supplement in _supplements(project_id, [article_id]):
        total += supplement.amount
    return total

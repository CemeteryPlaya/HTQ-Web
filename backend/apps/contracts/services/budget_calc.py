"""Расчёт занятости бюджета — единственное место, где считаются
«занято» и «остаток».

Остаток НЕ хранится в БД и не декрементируется отдельной операцией. Он
всегда выводится из живых договоров и согласованных счетов:

    committed = SUM(agreement.amount) по СТАНДАРТНЫМ договорам этой СТРОКИ
                бюджета в статусах COMMITTING_STATUSES
              + SUM(оплат) по ОТКРЫТЫМ договорам этой строки
              + SUM(invoice.amount) по согласованным/оплаченным счетам
    remaining = line.amount − committed

Открытый (рамочный) договор суммы не имеет, и бюджет его сумма не занимает.
Тратятся по нему деньги оплатами — поэтому для открытого договора расходом
считаются ОНИ, а не сумма договора. У стандартного — наоборот: сумма
договора уже занимает бюджет целиком, и прибавить к ней оплаты по нему
значило бы посчитать одни и те же деньги дважды.

Каждый договор считается РОВНО одним из двух способов, и решает это тип, а
не то, ноль ли в ``amount``. В реестре заказчика бывает открытый договор с
проставленной суммой (оценка, потолок); посчитай его и суммой, и оплатами —
одни и те же деньги легли бы в расход дважды. Отсюда и
``agreement_commitment`` для проверок лимита: проверять договор надо на то,
что он действительно займёт.

Единица счёта — ``BudgetLine``, а не ``Budget``: договор ссылается на
строку, деньги выделены программе. Итоги по бюджету целиком
(``totals_for_budget``) складываются из его строк — отдельного источника
правды для них нет.

Почему так, а не хранимое поле, которое уменьшают на сумму договора:
хранимый баланс расходится с реальностью при первом же редактировании
суммы договора, его удалении, расторжении или частично прошедшей записи —
и после этого нет способа узнать, какая из двух цифр верна. Вычисляемый
остаток корректен по построению. В API он отдаётся обычным полем, так что
для фронтенда выглядит ровно так же, как хранимый.

Если когда-нибудь понадобится история («почему бюджет просел на 400 000 ₸
12 марта?») — правильный ответ не «завести хранимый баланс», а добавить
журнал движений (``BudgetTransaction``: +выделено / −законтрактовано /
+возврат) и считать остаток как ``SUM`` по журналу. Тот же принцип: баланс
выводится, а не редактируется.
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum

from apps.contracts.models import (
    Agreement,
    AgreementDirection,
    AgreementStatus,
    AgreementType,
    AccountableFundsRequest,
    AccountableFundsRequestStatus,
    AdvancePayment,
    AdvancePaymentStatus,
    BudgetLine,
    CompletionAct,
    ContractPayment,
    Invoice,
    InvoiceStatus,
)

# ⚠️ ОТКРЫТЫЙ ВОПРОС К ЗАКАЗЧИКУ (единственный, влияющий на цифры).
#
# С какого момента договор занимает бюджет? Заказчик сказал «когда договор
# сделан», что допускает три прочтения: с создания, с согласования, с
# подписания. Принято среднее: черновик бюджет не занимает (иначе брошенные
# черновики молча съедают лимит), расторгнутый договор бюджет освобождает,
# всё между ними — занимает.
#
# Это ЕДИНСТВЕННОЕ место, где зафиксировано решение. Меняется правкой этого
# множества — ни модели, ни схемы, ни вьюхи трогать не придётся.
COMMITTING_STATUSES = frozenset({
    AgreementStatus.ON_REVIEW,
    AgreementStatus.APPROVED,
    AgreementStatus.SIGNED,
    AgreementStatus.EXECUTED,
})

# Счёт становится расходом только после положительного решения signoff.
# ``paid`` остаётся в множестве, чтобы оплата не освободила уже потраченные
# деньги. Черновики и счета на согласовании пока не уменьшают остаток.
INVOICE_COMMITTING_STATUSES = frozenset({
    InvoiceStatus.APPROVED,
    InvoiceStatus.PAID,
})

# Подотчётная заявка начинает резервировать средства с отправки на
# согласование. После выдачи она остаётся здесь до будущего авансового отчёта.
ACCOUNTABLE_FUNDS_COMMITTING_STATUSES = frozenset({
    AccountableFundsRequestStatus.ON_REVIEW,
    AccountableFundsRequestStatus.AWAITING_ACCOUNTING,
    AccountableFundsRequestStatus.AWAITING_ADVANCE_REPORT,
    # Closing the accountability workflow does not return paid funds to the
    # budget: they are evidenced by the approved advance reports instead.
    AccountableFundsRequestStatus.CLOSED,
})

# Оплата по ОТКРЫТОМУ договору становится расходом с того же момента, что и
# счёт без договора, — после положительного решения signoff
# (``awaiting_accounting``) и дальше, после проведения (``closed``). Черновик
# и оплата на согласовании бюджет не занимают, как не занимает его черновик
# счёта.
#
# Статус самого договора здесь роли не играет: расторгнутый открытый договор
# уже потраченных денег не возвращает.
OPEN_AGREEMENT_SPENDING_STATUSES = frozenset({
    AdvancePaymentStatus.AWAITING_ACCOUNTING,
    AdvancePaymentStatus.CLOSED,
})

# Через что уходят деньги по договору. Тот же набор, что складывает
# ``contract_payment_service.paid_amount_for_agreement``: предоплата, оплата
# по счёту и оплата по акту — три отдельных платёжных документа.
_OPEN_AGREEMENT_SPENDING_MODELS = (AdvancePayment, ContractPayment, CompletionAct)

ZERO = Decimal("0.00")


class BudgetExceeded(Exception):
    """Сумма расхода не помещается в остаток строки бюджета."""

    def __init__(self, budget_line_id: int, requested: Decimal, remaining: Decimal):
        self.budget_line_id = budget_line_id
        self.requested = requested
        self.remaining = remaining
        super().__init__(
            f"Сумма {requested} превышает остаток бюджетной строки "
            f"#{budget_line_id}: доступно {remaining}"
        )


def committed_map(line_ids, *, exclude_agreement_id: int | None = None,
                  exclude_invoice_id: int | None = None) -> dict[int, Decimal]:
    """{budget_line_id: занятая сумма} для набора строк двумя агрегатами.

    Строки без единого учитываемого договора в результат не попадают —
    вызывающий берёт их через ``.get(id, ZERO)``. Так сделано намеренно:
    ``GROUP BY`` не обязан возвращать нулевые группы, и подмешивать их
    здесь значило бы платить лишним проходом по списку ради удобства,
    которое ``dict.get`` даёт бесплатно.

    ``exclude_agreement_id`` / ``exclude_invoice_id`` исключают собственный
    расход из агрегата при проверке его новой суммы, чтобы старая сумма не
    считалась чужой занятостью.
    """
    ids = list(line_ids)
    if not ids:
        return {}

    # Открытые договоры — мимо: их расход — оплаты, они сложены ниже (см.
    # докстринг модуля). Сумму открытого договора не считать нельзя даже
    # «на всякий случай»: вместе с оплатами это двойной счёт.
    # Два независимых отсева, и нужны оба: договор-ПОСТУПЛЕНИЕ бюджет не
    # занимает по определению (деньги приходят, а не уходят), рамочный — не
    # занимает своей суммой (её нет).
    agreement_query = Agreement.objects.filter(
        budget_line_id__in=ids,
        status__in=COMMITTING_STATUSES,
        direction=AgreementDirection.EXPENSE,
    ).exclude(contract_type=AgreementType.FRAMEWORK)
    if exclude_agreement_id is not None:
        agreement_query = agreement_query.exclude(pk=exclude_agreement_id)

    invoice_query = Invoice.objects.filter(
        budget_line_id__in=ids, status__in=INVOICE_COMMITTING_STATUSES,
    )
    if exclude_invoice_id is not None:
        invoice_query = invoice_query.exclude(pk=exclude_invoice_id)

    totals: dict[int, Decimal] = {}
    accountable_query = AccountableFundsRequest.objects.filter(
        budget_line_id__in=ids, status__in=ACCOUNTABLE_FUNDS_COMMITTING_STATUSES,
    )

    for query in (agreement_query, invoice_query, accountable_query):
        rows = query.values("budget_line_id").annotate(total=Sum("amount"))
        for row in rows:
            line_id = row["budget_line_id"]
            totals[line_id] = totals.get(line_id, ZERO) + (row["total"] or ZERO)

    # Расход по открытым договорам — их оплатами (см. докстринг модуля).
    # ``exclude_agreement_id`` к ним не применяется: он исключает СУММУ
    # договора при проверке её новой величины, а у открытого договора
    # суммы, которую занимала бы строка, нет.
    for model in _OPEN_AGREEMENT_SPENDING_MODELS:
        rows = (model.objects
                .filter(agreement__budget_line_id__in=ids,
                        agreement__contract_type=AgreementType.FRAMEWORK,
                        status__in=OPEN_AGREEMENT_SPENDING_STATUSES)
                .values("agreement__budget_line_id")
                .annotate(total=Sum("amount")))
        for row in rows:
            line_id = row["agreement__budget_line_id"]
            totals[line_id] = totals.get(line_id, ZERO) + (row["total"] or ZERO)
    return totals


def agreement_commitment(contract_type: str | None, amount: Decimal) -> Decimal:
    """Сколько строки бюджета займёт САМА СУММА договора — то, с чем её
    сравнивает ``check_capacity``.

    У открытого договора — ничего: его расход приходит оплатами, и они
    проверяются каждая в свой момент. Проверять открытый договор на его
    ``amount`` значило бы не пустить его в строку из-за денег, которые
    ``committed_map`` не посчитает никогда. ``None`` — тип не задан, то есть
    дефолт модели, стандартный.
    """
    return ZERO if contract_type == AgreementType.FRAMEWORK else amount


def open_payment_overrun(payment) -> Decimal | None:
    """На сколько строка бюджета выходит за лимит с учётом ЭТОЙ оплаты по
    открытому договору. ``None`` — не выходит, или договор не открытый.

    ``payment`` — предоплата, оплата по договору или акт: у всех трёх есть
    ``agreement``, ``amount`` и ``status`` из одной машины статусов.

    Лимит здесь только ПРЕДУПРЕЖДАЕТ, а не запрещает (так решил заказчик):
    у стандартного договора бюджет охраняет цепочка «оплата ≤ остаток
    договора ≤ остаток строки», а у открытого второго звена нет — суммы нет.
    Без этого предупреждения оплата на любую сумму уходила бы в строку молча.
    Стандартного договора это не касается: его оплаты свою строку не
    занимают вовсе (см. докстринг модуля).

    Оплата, уже вошедшая в расход (``OPEN_AGREEMENT_SPENDING_STATUSES``), в
    остатке строки уже учтена, и второй раз её не вычитаем: иначе после
    одобрения предупреждение показывало бы перерасход на её сумму больше.
    """
    agreement = payment.agreement
    if agreement.has_fixed_amount:
        return None
    remaining = remaining_for(agreement.budget_line)
    if payment.status not in OPEN_AGREEMENT_SPENDING_STATUSES:
        remaining -= payment.amount
    return -remaining if remaining < 0 else None


def committed_for(budget_line_id: int, *, exclude_agreement_id: int | None = None,
                  exclude_invoice_id: int | None = None) -> Decimal:
    """Занятая сумма одной строки бюджета."""
    return committed_map([budget_line_id],
                         exclude_agreement_id=exclude_agreement_id,
                         exclude_invoice_id=exclude_invoice_id).get(budget_line_id, ZERO)


def totals_for(line: BudgetLine, *, committed: Decimal | None = None) -> dict:
    """``{allocated, committed, remaining}`` одной строки бюджета.

    ``committed`` можно передать снаружи, если он уже посчитан пачкой через
    ``committed_map`` — чтобы список строк не делал N+1 запросов.
    """
    if committed is None:
        committed = committed_for(line.pk)
    return {
        "allocated": line.amount,
        "committed": committed,
        "remaining": line.amount - committed,
    }


def totals_for_budget(lines, *, committed: dict[int, Decimal] | None = None) -> dict:
    """``{allocated, committed, remaining}`` бюджета целиком — суммой строк.

    Принимает уже загруженные строки, а не ``Budget``: карточка бюджета всё
    равно показывает их таблицей, и второй запрос за теми же строками ради
    итога был бы лишним. ``committed`` — результат ``committed_map`` по этим
    же строкам, тоже переиспользуется, а не считается заново.

    Отдельного хранимого итога у бюджета нет и быть не должно — он
    разъезжался бы с суммами строк при первой же их правке.
    """
    lines = list(lines)
    if committed is None:
        committed = committed_map([line.pk for line in lines])

    allocated = sum((line.amount for line in lines), ZERO)
    used = sum((committed.get(line.pk, ZERO) for line in lines), ZERO)
    return {"allocated": allocated, "committed": used, "remaining": allocated - used}


def remaining_for(line: BudgetLine, *, exclude_agreement_id: int | None = None,
                  exclude_invoice_id: int | None = None) -> Decimal:
    return line.amount - committed_for(line.pk,
                                       exclude_agreement_id=exclude_agreement_id,
                                       exclude_invoice_id=exclude_invoice_id)


def check_capacity(line: BudgetLine, amount: Decimal, *,
                   exclude_agreement_id: int | None = None,
                   exclude_invoice_id: int | None = None) -> None:
    """Поднять ``BudgetExceeded``, если ``amount`` не помещается в остаток СТРОКИ.

    Лимит проверяется по строке, а не по бюджету целиком: деньги выделены
    программе, и договор на 5 млн по программе с лимитом 1 млн не становится
    допустимым оттого, что у соседней программы в том же бюджете есть
    свободные 10 млн. Перебрасывать деньги между программами — это правка
    сумм строк, отдельное и видимое действие.

    Договор проверяется при входе в занимающий статус. Счёт дополнительно
    проверяется при создании и повторно перед одобрением: до одобрения он не
    уменьшает остаток, но заведомо не должен быть больше доступной суммы.

    ⚠️ Открытый вопрос: заказчик не сказал, должно ли превышение бюджета
    БЛОКИРОВАТЬ сохранение или лишь предупреждать. Здесь блокирует (жёстче
    и безопаснее: превышение, которое молча прошло, обнаруживается на
    сверке). Смягчение до предупреждения — это перевод вызывающей стороны
    (``agreement_service``) с исключения на возврат флага, модель не
    затрагивается.
    """
    remaining = remaining_for(line, exclude_agreement_id=exclude_agreement_id,
                              exclude_invoice_id=exclude_invoice_id)
    if amount > remaining:
        raise BudgetExceeded(line.pk, amount, remaining)

"""Расчёт занятости бюджета — единственное место, где считаются
«законтрактовано» и «остаток».

Остаток НЕ хранится в БД и не декрементируется при создании договора. Он
всегда выводится из живых строк ``Agreement``:

    committed = SUM(agreement.amount) по договорам этой бюджетной строки
                в статусах COMMITTING_STATUSES
    remaining = budget.amount − committed

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

from apps.contracts.models import Agreement, AgreementStatus, Budget

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

ZERO = Decimal("0.00")


class BudgetExceeded(Exception):
    """Сумма договора не помещается в остаток бюджетной строки."""

    def __init__(self, budget_id: int, requested: Decimal, remaining: Decimal):
        self.budget_id = budget_id
        self.requested = requested
        self.remaining = remaining
        super().__init__(
            f"Сумма договора {requested} превышает остаток бюджета "
            f"#{budget_id}: доступно {remaining}"
        )


def committed_map(budget_ids, *, exclude_agreement_id: int | None = None) -> dict[int, Decimal]:
    """{budget_id: законтрактованная сумма} одним запросом для набора строк.

    Бюджеты без единого учитываемого договора в результат не попадают —
    вызывающий берёт их через ``.get(id, ZERO)``. Так сделано намеренно:
    ``GROUP BY`` не обязан возвращать нулевые группы, и подмешивать их
    здесь значило бы платить лишним проходом по списку ради удобства,
    которое ``dict.get`` даёт бесплатно.

    ``exclude_agreement_id`` исключает конкретный договор из агрегата —
    нужно при РЕДАКТИРОВАНИИ договора, чтобы его собственная старая сумма
    не считалась занятой при проверке новой (иначе увеличение суммы на 1 ₸
    сравнивалось бы с остатком, из которого уже вычтена вся старая сумма).
    """
    ids = list(budget_ids)
    if not ids:
        return {}

    query = Agreement.objects.filter(
        budget_id__in=ids, status__in=COMMITTING_STATUSES,
    )
    if exclude_agreement_id is not None:
        query = query.exclude(pk=exclude_agreement_id)

    rows = query.values("budget_id").annotate(total=Sum("amount"))
    return {row["budget_id"]: row["total"] or ZERO for row in rows}


def committed_for(budget_id: int, *, exclude_agreement_id: int | None = None) -> Decimal:
    """Законтрактованная сумма одной бюджетной строки."""
    return committed_map([budget_id],
                         exclude_agreement_id=exclude_agreement_id).get(budget_id, ZERO)


def totals_for(budget: Budget, *, committed: Decimal | None = None) -> dict:
    """``{allocated, committed, remaining}`` одной бюджетной строки.

    ``committed`` можно передать снаружи, если он уже посчитан пачкой через
    ``committed_map`` — чтобы список бюджетов не делал N+1 запросов.
    """
    if committed is None:
        committed = committed_for(budget.pk)
    return {
        "allocated": budget.amount,
        "committed": committed,
        "remaining": budget.amount - committed,
    }


def remaining_for(budget: Budget, *, exclude_agreement_id: int | None = None) -> Decimal:
    return budget.amount - committed_for(budget.pk,
                                         exclude_agreement_id=exclude_agreement_id)


def check_capacity(budget: Budget, amount: Decimal, *,
                   exclude_agreement_id: int | None = None) -> None:
    """Поднять ``BudgetExceeded``, если ``amount`` не помещается в остаток.

    Вызывается только для договоров в занимающих бюджет статусах — черновик
    лимит не проверяет (он его и не занимает, см. ``COMMITTING_STATUSES``).

    ⚠️ Открытый вопрос: заказчик не сказал, должно ли превышение бюджета
    БЛОКИРОВАТЬ сохранение или лишь предупреждать. Здесь блокирует (жёстче
    и безопаснее: превышение, которое молча прошло, обнаруживается на
    сверке). Смягчение до предупреждения — это перевод вызывающей стороны
    (``agreement_service``) с исключения на возврат флага, модель не
    затрагивается.
    """
    remaining = remaining_for(budget, exclude_agreement_id=exclude_agreement_id)
    if amount > remaining:
        raise BudgetExceeded(budget.pk, amount, remaining)

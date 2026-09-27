"""Ночная сверка «Задействовано» (CALC-002, Q-B05, задача B2.4).

По каждой строке действующих бюджетов компании SQL-агрегат
``committed_by_article`` сравнивается с независимым пересчётом
``committed_reference``. Расхождение значит, что одна из реализаций
сломана, а остатки, по которым пропускаются заявки и счета, неверны.

Расхождение идёт через ``fallback`` (``expected=False``) — это алерт
``htqweb-fallback-*``: в строгом режиме (разработка, тесты) сверка падает,
на бою пишет строку ``FALLBACK`` и счётчик. Своя метрика
``htqweb_bpp_committed_mismatch_total`` появится вместе с панелью дашборда
БЗО (A3.2): сторож ``test_metrics_are_observed`` не пропускает метрику без
панели.
"""

from __future__ import annotations

from apps.bpp.models import Budget, BudgetStatus
from htqweb.fallback import fallback

from . import committed as calc


def mismatches() -> list[dict]:
    found = []
    budgets = Budget.objects.filter(status__in=(BudgetStatus.APPROVED, BudgetStatus.CLOSED),
                                    active_version__isnull=False)
    for budget in budgets.select_related("active_version"):
        aggregate = calc.committed_by_article(budget.project_id)
        for line in budget.active_version.lines.all():
            article_id = str(line.article_id)
            fast = aggregate.get(article_id, calc.ZERO)
            slow = calc.committed_reference(budget.project_id, article_id)
            if fast != slow:
                found.append({"budget": budget.number, "article_id": article_id,
                              "aggregate": str(fast), "reference": str(slow)})
    return found


def run() -> dict:
    found = mismatches()
    for row in found:
        fallback("bpp.committed.mismatch", None,
                 reason="«Задействовано»: агрегат не совпал с пересчётом по позициям",
                 budget=row["budget"], article_id=row["article_id"],
                 aggregate=row["aggregate"], reference=row["reference"])
    return {"mismatches": len(found)}

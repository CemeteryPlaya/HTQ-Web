"""Ночная сверка «Задействовано» (CALC-002, Q-B05, задача B2.4).

По каждой строке действующих бюджетов компании SQL-агрегат
``committed_by_article`` сравнивается с независимым пересчётом
``committed_reference``. Расхождение значит, что одна из реализаций
сломана, а остатки, по которым пропускаются заявки и счета, неверны.

Расхождение идёт через ``fallback`` (``expected=False``) — это алерт
``htqweb-fallback-*``: в строгом режиме (разработка, тесты) сверка падает,
на бою пишет строку ``FALLBACK`` и счётчик.

Итог прогона (число расхождений и время) пишется в настройку модуля
``committed_check_last`` — его читает ``apps/bpp/metrics.py`` (метрики
``htqweb_bpp_committed_mismatches`` и ``htqweb_bpp_committed_check_age_seconds``,
A3.2, D-S3-4): пересчитывать сверку при каждом сборе метрик (раз в 60 с)
слишком дорого.
"""

from __future__ import annotations

from django.utils import timezone

from apps.bpp.models import Budget, BudgetStatus
from apps.bpp.models.settings import ModuleSetting
from htqweb.fallback import fallback

from . import committed as calc

#: Ключ ``ModuleSetting`` с итогом последней сверки: ``{count, at}``.
RESULT_KEY = "committed_check_last"


def _record(count: int) -> None:
    """Итог сверки — строкой настройки, минуя ``set_setting``: это запись
    ночной задачи, а не правка настройки человеком, и журнал изменений
    (неизменяемый, ТЗ §25.2) не должен получать строку на каждую компанию
    каждую ночь."""
    ModuleSetting.objects.update_or_create(
        key=RESULT_KEY,
        defaults={"value": {"count": count, "at": timezone.now().isoformat()},
                  "updated_by": None})


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
    # До ``fallback``: в строгом режиме он поднимет исключение на первом же
    # расхождении, а итог с расхождением метрика видеть обязана.
    _record(len(found))
    for row in found:
        fallback("bpp.committed.mismatch", None,
                 reason="«Задействовано»: агрегат не совпал с пересчётом по позициям",
                 budget=row["budget"], article_id=row["article_id"],
                 aggregate=row["aggregate"], reference=row["reference"])
    return {"mismatches": len(found)}

"""Остаток статьи бюджета и блокировка строки (контракт мастер-плана §2.6).

``balance`` — CALC-001 − CALC-002 = CALC-003 по ДЕЙСТВУЮЩЕЙ версии: черновик
корректировки на остатки не влияет (D-06, ТЗ §13.1 п.18).

``lock_line`` — ``SELECT … FOR UPDATE`` строки действующей версии: под ней
идут все проверки остатка (BR-011, BR-034, BR-043, «Оплатить»). Две заявки,
одновременно выбирающие остаток, встают в очередь на этой строке: вторая
пересчитывает «Задействовано» уже с первой (AC-004).
"""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from apps.bpp.models import Budget, BudgetLine, BudgetStatus
from apps.project import interface as projects
from apps.refdata import interface as refdata
from htqweb.errors import DomainError

from . import committed as calc

#: Сколько раз ``lock_line`` перечитывает строку, если пока он ждал
#: блокировку, ФД утвердил корректировку и действующей стала другая версия.
_LOCK_ATTEMPTS = 3


def project_code(project_id) -> str:
    brief = projects.project_brief([str(project_id)]).get(str(project_id))
    return brief["code"] if brief else str(project_id)


def article_name(article_id) -> str:
    brief = refdata.article_brief([str(article_id)]).get(str(article_id))
    return brief["name"] if brief else str(article_id)


def no_approved_budget(project_id) -> DomainError:
    """E-BUD-02 — текст ТЗ §26.1."""
    return DomainError(
        "E-BUD-02",
        f"По проекту {project_code(project_id)} нет утверждённого бюджета. Создать заявку "
        f"можно после утверждения бюджета финансовым директором.",
        fields=[{"field": "project_id", "message": "Бюджет не утверждён"}])


def not_in_budget(project_id, article_id) -> DomainError:
    return DomainError(
        "E-BUD-03",
        f"Статьи «{article_name(article_id)}» нет в бюджете проекта "
        f"{project_code(project_id)}. Выберите статью из утверждённых лимитов или "
        f"обратитесь к финансовому директору.",
        fields=[{"field": "article_id", "message": "Статьи нет в бюджете"}])


def approved_budget(project_id) -> Budget:
    """Утверждённый бюджет проекта или E-BUD-02 (BR-003)."""
    budget = Budget.objects.filter(project_id=project_id).first()
    if budget is None or budget.status != BudgetStatus.APPROVED or not budget.active_version_id:
        raise no_approved_budget(project_id)
    return budget


def active_line(project_id, article_id) -> BudgetLine:
    budget = approved_budget(project_id)
    line = BudgetLine.objects.filter(version_id=budget.active_version_id,
                                     article_id=article_id).first()
    if line is None:
        raise not_in_budget(project_id, article_id)
    return line


def lock_line(project_id, article_id) -> BudgetLine:
    """Заблокировать строку действующей версии до конца транзакции.

    После захвата блокировки версия перепроверяется: пока запрос ждал, ФД мог
    утвердить корректировку (она держит блокировки строк старой версии до
    коммита), и тогда блокировать надо строку новой действующей версии.
    """
    for _ in range(_LOCK_ATTEMPTS):
        budget = approved_budget(project_id)
        line = (BudgetLine.objects.select_for_update()
                .filter(version_id=budget.active_version_id, article_id=article_id).first())
        if line is None:
            raise not_in_budget(project_id, article_id)
        current = Budget.objects.filter(pk=budget.pk).values_list(
            "active_version_id", "status").first()
        if current == (line.version_id, BudgetStatus.APPROVED):
            return line
    raise no_approved_budget(project_id)


def figures(line: BudgetLine, committed: Decimal) -> dict:
    return {"limit": line.limit_amount, "committed": committed,
            "available": line.limit_amount - committed}


def balance(project_id, article_id, *, exclude_request_id=None) -> dict:
    """``{limit, committed, available, as_of}`` — контракт §2.6 (GetBudgetBalance)."""
    line = active_line(project_id, article_id)
    committed = calc.committed_for(project_id, article_id,
                                   exclude_request_id=exclude_request_id)
    return {**figures(line, committed), "as_of": timezone.now()}

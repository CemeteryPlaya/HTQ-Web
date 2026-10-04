"""Уведомление «бюджет утверждён» — ТЗ §16.2 п.1 (остаток B этапа 2, B-5).

ФД утвердил бюджет → статьи открыты для заявок → СН и ПМ узнают об этом.
Получатели:

- снабженцы компании — у них все проекты (``project.all``, ``access/0015``);
- ПМ — только участники этого проекта (BR-014: чужие проекты ПМ не видит);
- автор утверждения — никогда.

«СН» и «ПМ» — не названия ролей, а права: создавать заявки (``bpp.requests``
+ ``create``) и видеть статьи своей группы (``bpp.articles.supply`` /
``bpp.articles.pm``) — то же правило, по которому ``Actor.initiator_roles``
выводит роль инициатора. Директор без права создавать заявки не получает
уведомления, хотя статьи обеих групп ему открыты.

Запись — в транзакции утверждения под своей точкой сохранения, как у
движка согласования (``signoff.engine._notify_center``): откатилось
утверждение — нет и уведомления, а сбой центра утверждение не роняет.
Доставку (e-mail, Telegram) центр ставит сам после коммита. Пропуск
уведомления — подмена, поэтому через ``htqweb.fallback``: выключенный центр
— штатная деградация (``expected``), любой другой сбой в strict падает.
"""

from __future__ import annotations

from django.db import transaction

from apps.access import interface as access
from apps.bpp.models import Budget
from apps.core.services import ServiceDisabled
from apps.notifications import interface as notifications
from apps.project import interface as projects
from htqweb.fallback import fallback
from htqweb.tenancy import current_company_or_none

EVENT = "bpp.budget_approved"


def recipients(budget: Budget, *, actor_id: int, company: str) -> list[int]:
    initiators = set(access.holders_of("bpp.requests", "create", company))
    supply = initiators & set(access.holders_of("bpp.articles.supply", "view", company))
    pm = (initiators & set(access.holders_of("bpp.articles.pm", "view", company))
          & set(projects.member_user_ids(str(budget.project_id))))
    return sorted((supply | pm) - {actor_id})


def budget_approved(budget: Budget, *, actor_id: int, correction: bool = False) -> None:
    company = current_company_or_none()
    if company is None:
        # Без компании (стенд до переноса в схемы, транзакционные тесты в
        # public) не у кого проверить членство — получателей нет.
        fallback("bpp.budget.approved_notify_no_company", None, expected=True,
                 reason="нет контекста компании — СН и ПМ не уведомлены",
                 budget=str(budget.pk))
        return
    try:
        users = recipients(budget, actor_id=actor_id, company=company)
        if not users:
            return
        project = projects.project_brief([str(budget.project_id)]).get(
            str(budget.project_id)) or {}
        code = project.get("code") or budget.number
        title = (f"Корректировка бюджета проекта {code} утверждена. Лимиты статей обновлены"
                 if correction else
                 f"Бюджет проекта {code} утверждён. Статьи открыты для заявок")
        with transaction.atomic():
            notifications.notify(
                recipients=users, event=EVENT, title=title, url=f"/bpp/budgets/{budget.pk}",
                company_slug=company, target_type="bpp.budget", target_id=str(budget.pk),
                actor_id=actor_id, deliver=True)
    except ServiceDisabled as exc:
        fallback("bpp.budget.approved_notify_disabled", None, expected=True, exc=exc,
                 reason="центр уведомлений выключен — СН и ПМ не уведомлены",
                 budget=str(budget.pk))
    except Exception as exc:
        fallback("bpp.budget.approved_notify_failed", None, exc=exc,
                 reason="центр уведомлений не принял уведомление об утверждении бюджета",
                 budget=str(budget.pk))

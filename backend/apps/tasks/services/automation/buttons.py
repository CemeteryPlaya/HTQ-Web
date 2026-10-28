"""Кнопки автоматизации (решения K-36, K-39; этап S4).

Кнопку на карточке нажимает тот, кто вправе вести задачу
(``require_soft_edit``), — её видят кнопки домашних досок задачи. Кнопку на
доске — тот, кто вправе создавать задачи на этой доске; без колонки карточек
она работает на уровне доски, с колонкой — над карточками колонки, видными
нажавшему. Действия — от имени нажавшего, без проверки его прав; события
правок продолжают цепочку правил доски. Не сработала — ответ с причиной, а
запуск уже в журнале.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.http import Http404

from htqweb.errors import DomainError

from ...models import AutomationKind, AutomationRule, AutomationRunStatus
from .. import board_fields
from .. import board_service
from .. import task_scope
from .. import task_service
from . import context
from . import engine
from . import scheduled
from .context import Event


def card_buttons(task) -> dict[tuple[str, int], list[dict]]:
    """Кнопки домашних досок задачи — для её карточки."""
    out: dict[tuple[str, int], list[dict]] = {}
    for rule in engine.rules_of(board_fields.home_board_keys(task),
                                kinds=(AutomationKind.CARD_BUTTON,)):
        out.setdefault((rule.board_kind, rule.board_id), []).append(
            {"id": rule.pk, "name": rule.name, "icon": rule.icon or None})
    return out


def _raise_for(status: str, rule: AutomationRule) -> None:
    if status == AutomationRunStatus.FAILED:
        raise DomainError("automation_failed",
                          engine.last_error(rule) or "Кнопка не сработала", status=422)
    if status == AutomationRunStatus.NO_MATCH:
        raise DomainError("automation_not_applicable",
                          "Условия кнопки для этой карточки не выполнены", status=409)
    if status == AutomationRunStatus.LIMITED:
        raise DomainError("automation_limited",
                          "Автоматизация упёрлась в предел — смотрите журнал запусков доски",
                          status=409)


def press_card(request, task_id: int, rule_id: int) -> dict:
    task = task_service.load_for_action(task_id, request)
    task_service.require_soft_edit(task, request)
    rule = AutomationRule.objects.filter(pk=rule_id, kind=AutomationKind.CARD_BUTTON,
                                         enabled=True).first()
    if rule is None or (rule.board_kind, rule.board_id) not in board_fields.home_board_keys(task):
        raise Http404("Button not found")
    user_id = task_scope.for_request(request).user_id
    with context.chain(user_id) as (chain, _fresh):
        status = engine.execute(chain, rule, task, Event("card_button", task.pk, user_id),
                                actor_id=user_id, event_name="card_button")
        engine.drain(chain)
    _raise_for(status, rule)
    return {"status": status}


def press_board(request, board, rule_id: int) -> dict:
    if not board_service.can_create(request, board):
        raise PermissionDenied("Кнопки доски нажимает тот, кто создаёт задачи на ней")
    rule = AutomationRule.objects.filter(
        pk=rule_id, kind=AutomationKind.BOARD_BUTTON, enabled=True,
        board_kind=board.kind, board_id=board.id).first()
    if rule is None:
        raise Http404("Button not found")
    user_id = task_scope.for_request(request).user_id
    if rule.trigger.get("cards") is None:
        status = scheduled.run_board(rule, actor_id=user_id, event_type="board_button")
        _raise_for(status, rule)
        return {"status": status, "cards": 0, "done": 0}
    tasks = scheduled.column_tasks(rule, board, task_scope.for_request(request))
    done = scheduled.run_cards(rule, tasks, actor_id=user_id, event_type="board_button")
    return {"status": AutomationRunStatus.OK, "cards": len(tasks), "done": done}

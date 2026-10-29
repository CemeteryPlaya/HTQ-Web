"""Кнопки автоматизации (решения K-36, K-39; этап S4, уточнено в S4b).

Спецификация — docs/plans/2026-10-28-kanban-automation-logic.md, §7.

Кнопку на карточке видит и нажимает тот, кто вправе вести задачу
(``can_progress``), — кнопки домашних досок задачи; у каждой признак
«доступна сейчас» (условия кнопки сошлись на этой карточке). Кнопку на доске
без колонки карточек нажимает тот, кто вправе создавать задачи на доске; с
колонкой — она обрабатывает только карточки, которые нажавший вправе вести,
остальные пропускаются. Действия — от имени нажавшего, без проверки его прав
на каждое действие; события правок продолжают цепочку правил доски. Не
сработала — ответ с ошибкой этого запуска, а запуск уже в журнале.
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

NOT_APPLICABLE = "Условия кнопки для этой карточки не выполнены"


def _available(rule: AutomationRule, task, user_id: int | None) -> tuple[bool, str | None]:
    """Сошлись ли условия кнопки на карточке сейчас — без записи в журнал."""
    if not rule.conditions:
        return True, None
    try:
        if engine.conditions_hold(rule, task, Event("card_button", task.pk, user_id)):
            return True, None
    except DomainError as exc:
        return False, exc.message
    return False, NOT_APPLICABLE


def card_buttons(task, scope=None) -> dict[tuple[str, int], list[dict]]:
    """Кнопки домашних досок задачи — для её карточки. ``scope`` — кто
    смотрит: не вправе вести задачу — кнопок нет; ``None`` — внутренний вызов."""
    if scope is not None and not task_service.can_progress(task, scope):
        return {}
    user_id = scope.user_id if scope is not None else None
    out: dict[tuple[str, int], list[dict]] = {}
    for rule in engine.rules_of(board_fields.home_board_keys(task),
                                kinds=(AutomationKind.CARD_BUTTON,)):
        available, reason = _available(rule, task, user_id)
        out.setdefault((rule.board_kind, rule.board_id), []).append(
            {"id": rule.pk, "name": rule.name, "icon": rule.icon or None,
             "available": available, "reason": reason})
    return out


def _raise_for(status: str, error: str | None) -> None:
    if status == AutomationRunStatus.FAILED:
        raise DomainError("automation_failed", error or "Кнопка не сработала", status=422)
    if status == AutomationRunStatus.NO_MATCH:
        raise DomainError("automation_not_applicable", NOT_APPLICABLE, status=409)
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
        error = chain.last_error
        engine.drain(chain)
    _raise_for(status, error)
    return {"status": status}


def press_board(request, board, rule_id: int) -> dict:
    rule = AutomationRule.objects.filter(
        pk=rule_id, kind=AutomationKind.BOARD_BUTTON, enabled=True,
        board_kind=board.kind, board_id=board.id).first()
    if rule is None:
        raise Http404("Button not found")
    scope = task_scope.for_request(request)
    if rule.trigger.get("cards") is None:
        if not board_service.can_create(request, board):
            raise PermissionDenied("Кнопки доски нажимает тот, кто создаёт задачи на ней")
        status, error = scheduled.run_board(rule, actor_id=scope.user_id,
                                            event_type="board_button")
        _raise_for(status, error)
        return {"status": status, "cards": 0, "done": 0, "skipped": 0}
    # Над карточками — только те, что нажавший вправе вести (спецификация §7).
    tasks = scheduled.column_tasks(rule)
    allowed = [task for task in tasks if task_service.can_progress(task, scope)]
    done = scheduled.run_cards(rule, allowed, actor_id=scope.user_id, event_type="board_button")
    return {"status": AutomationRunStatus.OK, "cards": len(allowed), "done": done,
            "skipped": len(tasks) - len(allowed)}

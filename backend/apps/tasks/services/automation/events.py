"""События задач для автоматизации и запрет ручного переноса (K-37, K-38).

Сервисы задач отдают события в конце своей правки — ``emit``. Вне цепочки
открывается новая и сразу обрабатывается движком; внутри исполняемой
автоматизации событие копится до конца её правила; между правилами — встаёт
в очередь.

``precheck_move`` — до ручной смены колонки: правило «Запретить перенос» с
подходящим триггером и условиями отвечает 409 ``automation_blocked`` с текстом
правила. Переносы самой автоматизации не проверяются. Правка откатывается
вместе с исключением, поэтому запрет пишется в журнал запусков уже после
отката — обёрткой ``records_blocks`` у ручек ручного переноса.
"""

from __future__ import annotations

import functools

from htqweb.errors import DomainError

from . import context
from .context import Event


class Blocked(DomainError):
    """Ручной перенос запрещён правилом доски (K-38)."""

    def __init__(self, rule, task_id: int, actor_id: int | None, event: Event):
        message = next((action.get("message") for action in rule.actions
                        if action.get("type") == "block"), "") or "Перенос запрещён правилом доски"
        super().__init__("automation_blocked", message, status=409,
                         details={"rule_id": rule.id, "rule_name": rule.name or None})
        self.rule = rule
        self.task_id = task_id
        self.actor_id = actor_id
        self.event = event


def emit(*events: Event) -> None:
    """Отдать события движку (сервисы задач — в конце своей правки)."""
    events = [event for event in events if event is not None]
    if not events:
        return
    from . import engine

    initiator = next((event.actor_id for event in events if event.actor_id is not None), None)
    with context.chain(initiator) as (chain, fresh):
        now = chain.running
        if now is not None:
            for event in events:
                event.depth = now.depth + 1
                event.by_automation = True
                now.produced.append(event)
            return
        chain.queue.extend(events)
        if fresh:
            engine.drain(chain)


def precheck_move(task, from_status: str, to_status: str, actor_id: int | None) -> None:
    """Ручная смена колонки: правило-запрет с подходящими условиями — 409."""
    if from_status == to_status or context.in_automation():
        return
    from . import engine

    event = Event(type="moved", task_id=task.pk, actor_id=actor_id,
                  data={"from": from_status, "to": to_status})
    rule = engine.blocking_rule(task, event)
    if rule is not None:
        raise Blocked(rule, task.pk, actor_id, event)


def records_blocks(view):
    """Ручка ручного переноса: запрет — в журнал запусков после отката правки."""

    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except Blocked as blocked:
            from . import engine

            engine.record_blocked(blocked)
            raise

    return wrapper

"""Автоматизации доски: список, сохранение, порядок, копия, удаление, журнал
запусков (этап S4).

Видит список тот, кто видит доску; правит и читает журнал запусков —
администратор доски (K-39): в журнале названия задач доски и поддерева, а их
видимость у смотрящих разная. У личной доски автоматизации нет. Всё
проверяет ``catalog.validate``; создание и правка пишут в журнал запусков
строку ``changed`` («было → стало»). Копия рождается выключенной: две
одинаковые включённые автоматизации делали бы всё дважды. Название
обязательно у всех видов: по нему автоматизацию узнают журнал и лента.
Сломанную (``broken_reason``, спецификация логики §10) включает только
правка, прошедшая проверку, — она же снимает поломку. Порядок меняется
внутри своего вида: раздел конструктора показывает один вид.
"""

from __future__ import annotations

from django.db import connection, transaction
from django.http import Http404
from django.utils import timezone

from htqweb.errors import DomainError

from ... import schemas
from ...models import AutomationKind, AutomationRule, AutomationRun, AutomationRunStatus, BoardKind
from .. import board_rank
from .. import board_service
from .. import ranked
from . import catalog
from . import engine
from . import scheduled

AUTOMATION_LIMIT = catalog.AUTOMATION_LIMIT
RUNS_PAGE = 50


def require_shared(board) -> None:
    if board.kind == BoardKind.PERSONAL:
        raise DomainError("board_automation_personal",
                          "У личной доски нет автоматизации", status=422)


def _lock(board) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                       [f"tasks.board_automation:{board.kind}:{board.id}"])


def snapshot(rule: AutomationRule) -> dict:
    return {"kind": rule.kind, "name": rule.name, "icon": rule.icon, "trigger": rule.trigger,
            "conditions": rule.conditions, "actions": rule.actions, "enabled": rule.enabled}


def payload(rule: AutomationRule) -> dict:
    return {
        "id": rule.pk,
        "board_kind": rule.board_kind,
        "board_id": rule.board_id,
        **snapshot(rule),
        "position": rule.position,
        "preset_key": rule.preset_key or None,
        "next_run_at": rule.next_run_at,
        "broken_reason": rule.broken_reason or None,
        "activated_at": rule.activated_at,
        "created_by": rule.created_by,
        "updated_by": rule.updated_by,
        "created_at": rule.created_at,
        "updated_at": rule.updated_at,
    }


def _board_rules(board) -> list[AutomationRule]:
    return list(AutomationRule.objects.filter(board_kind=board.kind, board_id=board.id)
                .order_by("position", "id"))


def list_rules(board, kind: str | None = None) -> list[dict]:
    require_shared(board)
    rows = _board_rules(board)
    if kind:
        rows = [rule for rule in rows if rule.kind == kind]
    return [payload(rule) for rule in rows]


def _check_name(kind: str, name: str) -> None:
    if not name.strip():
        what = ("кнопку" if kind in (AutomationKind.CARD_BUTTON, AutomationKind.BOARD_BUTTON)
                else "автоматизацию")
        raise DomainError("automation_invalid", f"Назовите {what}", status=422,
                          details={"path": "name"})


def _schedule_next(rule: AutomationRule) -> None:
    rule.next_run_at = (scheduled.next_run(rule.trigger)
                        if rule.kind == AutomationKind.SCHEDULE else None)


def save_new(board, data: schemas.AutomationIn, actor_id: int | None, *,
             preset_key: str = "") -> AutomationRule:
    """Новая автоматизация в конец доски — без проверки прав (ими занят
    вызывающий: ручка или шаблон доски)."""
    _lock(board)
    existing = _board_rules(board)
    if len(existing) >= AUTOMATION_LIMIT:
        raise DomainError("automation_limit",
                          f"На доске не больше {AUTOMATION_LIMIT} автоматизаций", status=422)
    _check_name(data.kind, data.name)
    trigger, conditions, actions = catalog.validate(board, data.kind, data.trigger,
                                                    data.conditions, data.actions)
    rule = AutomationRule(
        board_kind=board.kind, board_id=board.id, kind=data.kind, name=data.name.strip(),
        icon=data.icon, trigger=trigger, conditions=conditions, actions=actions,
        enabled=data.enabled, preset_key=preset_key,
        position=ranked.position_between(existing, None, None, None,
                                         code="automation_order_stale", what="автоматизации"),
        activated_at=timezone.now() if data.enabled else None,
        created_by=actor_id, updated_by=actor_id)
    _schedule_next(rule)
    rule.save()
    engine.log_run(rule, status=AutomationRunStatus.CHANGED, event="created", actor_id=actor_id,
                   details={"after": snapshot(rule)})
    return rule


@transaction.atomic
def create(request, board, data: schemas.AutomationIn) -> dict:
    require_shared(board)
    board_service.require_admin(request, board)
    return payload(save_new(board, data, request.token.user_id))


def _rule(rule_id: int) -> AutomationRule:
    rule = AutomationRule.objects.filter(pk=rule_id).first()
    if rule is None:
        raise Http404("Automation not found")
    return rule


def admin_board(request, rule: AutomationRule):
    """Доска автоматизации — если видна (404) и вызывающий её администратор (403)."""
    board = board_service.resolve(request, rule.board_kind, rule.board_id)
    board_service.require_admin(request, board)
    return board


def apply_patch(board, rule: AutomationRule, data: schemas.AutomationPatch,
                actor_id: int | None) -> AutomationRule:
    before = snapshot(rule)
    fields = data.model_fields_set
    if "name" in fields and data.name is not None:
        rule.name = data.name.strip()
    if "icon" in fields and data.icon is not None:
        rule.icon = data.icon
    _check_name(rule.kind, rule.name)
    revalidated = bool({"trigger", "conditions", "actions"} & fields)
    if revalidated:
        old_trigger = rule.trigger
        rule.trigger, rule.conditions, rule.actions = catalog.validate(
            board, rule.kind,
            data.trigger if data.trigger is not None else rule.trigger,
            data.conditions if data.conditions is not None else rule.conditions,
            data.actions if data.actions is not None else rule.actions)
        _schedule_next(rule)
        # Прошла проверку — ссылки снова целы: поломка снята.
        rule.broken_reason = ""
        if rule.trigger != old_trigger:
            rule.activated_at = timezone.now()
    if "enabled" in fields and data.enabled is not None:
        if data.enabled and rule.broken_reason:
            raise DomainError(
                "automation_broken",
                f"Автоматизация сломана: {rule.broken_reason} — поправьте её, затем включите",
                status=422)
        if data.enabled and not rule.enabled:
            _schedule_next(rule)
            rule.activated_at = timezone.now()
        rule.enabled = data.enabled
    if data.move:
        rule.position = ranked.position_between(
            [row for row in _board_rules(board) if row.kind == rule.kind], rule.pk,
            data.before_id, data.after_id,
            code="automation_order_stale", what="автоматизации")
    rule.updated_by = actor_id
    rule.save()
    if board_rank.needs_rebalance(rule.position):
        ranked.respread(_board_rules(board))
        rule.refresh_from_db()
    after = snapshot(rule)
    if after != before:
        engine.log_run(rule, status=AutomationRunStatus.CHANGED, event="updated",
                       actor_id=actor_id, details={"before": before, "after": after})
    return rule


@transaction.atomic
def update(request, rule_id: int, data: schemas.AutomationPatch) -> dict:
    board = admin_board(request, _rule(rule_id))
    _lock(board)
    rule = AutomationRule.objects.select_for_update().filter(pk=rule_id).first()
    if rule is None:
        raise Http404("Automation not found")
    return payload(apply_patch(board, rule, data, request.token.user_id))


@transaction.atomic
def copy(request, rule_id: int) -> dict:
    source = _rule(rule_id)
    board = admin_board(request, source)
    data = schemas.AutomationIn(kind=source.kind, name=f"{source.name} (копия)".strip()[:200]
                                if source.name else "", icon=source.icon,
                                trigger=source.trigger, conditions=source.conditions,
                                actions=source.actions, enabled=False)
    return payload(save_new(board, data, request.token.user_id))


@transaction.atomic
def delete(request, rule_id: int) -> None:
    rule = _rule(rule_id)
    admin_board(request, rule)
    engine.log_run(rule, status=AutomationRunStatus.CHANGED, event="deleted",
                   actor_id=request.token.user_id, details={"before": snapshot(rule)})
    rule.delete()


def _run_payload(run: AutomationRun, tasks: dict) -> dict:
    task = tasks.get(run.task_id)
    return {
        "id": run.pk,
        "rule_id": run.rule_id,
        "rule_name": run.rule_name or None,
        "task": ({"id": task.pk, "key": task.key, "summary": task.summary}
                 if task is not None else None),
        "event": run.event,
        "status": run.status,
        "actor_id": run.actor_id,
        "details": run.details,
        "created_at": run.created_at,
    }


def runs(request, board, *, rule_id: int | None = None, problems: bool = False,
         before: int | None = None, limit: int | None = None) -> dict:
    """Журнал запусков доски (администратор доски): новые сверху, страницами
    по ``id``; ``problems`` — только сбои, запреты и упоры в пределы."""
    require_shared(board)
    board_service.require_admin(request, board)
    limit = max(1, min(int(limit or RUNS_PAGE), 200))
    rows = AutomationRun.objects.filter(board_kind=board.kind, board_id=board.id)
    if rule_id is not None:
        rows = rows.filter(rule_id=rule_id)
    if problems:
        rows = rows.filter(status__in=[AutomationRunStatus.FAILED, AutomationRunStatus.BLOCKED,
                                       AutomationRunStatus.LIMITED, AutomationRunStatus.SKIPPED])
    if before is not None:
        rows = rows.filter(pk__lt=before)
    page = list(rows.order_by("-pk")[:limit + 1])
    more = len(page) > limit
    page = page[:limit]
    from ...models import Task

    tasks = {task.pk: task for task in Task.objects.filter(
        pk__in={run.task_id for run in page if run.task_id})}
    return {"items": [_run_payload(run, tasks) for run in page],
            "next_before": page[-1].pk if more else None}

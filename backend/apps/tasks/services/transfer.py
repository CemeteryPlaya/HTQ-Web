"""«Отправить в отдел» — перенос задачи в другой отдел (канбан-доски, K1.6).

Мастер-план K-08, спека этапа 1 §K1.5. Переносит глава отдела задачи
(основной отдел — в поддереве управляемых им отделов), глава с полной правкой
задачи без отдела, администратор. У получателя задача появляется без
исполнителя и в «К выполнению»; отдел-отправитель остаётся связью ``origin`` —
видит ход работ, прав не получает; глава получателя получает уведомление.
Автор, руководитель, делегаты и наблюдатели остаются (S1-16).
"""

from __future__ import annotations

from django.db import transaction

from apps.core.services import ServiceDisabled
from apps.hr import interface as hr
from htqweb.errors import DomainError
from htqweb.fallback import fallback

from ..models import (DepartmentLinkKind, Status, TERMINAL_STATUSES, Task, TaskAssignee,
                      TaskDepartmentLink)
from . import board_fields
from . import board_service
from . import department_rules
from . import hydration
from . import task_notify
from . import task_scope
from . import task_service
from .automation import events as automation
from .automation.context import Event


def can_transfer(task: Task, scope) -> bool:
    """Вправе ли вызывающий перенести эту задачу (без проверки цели)."""
    if scope is None or scope.elevated:
        return True
    if task.department_id is not None:
        return task.department_id in scope.managed_subtree
    return bool(scope.managed_ids) and task_service.can_edit(task, scope)


def _sender(task: Task, scope, sender_department_id: int | None) -> int | None:
    """Отдел-отправитель: прежний основной отдел, у задачи без отдела —
    выбранный (из управляемых вызывающим) или первый управляемый."""
    if task.department_id is not None:
        return task.department_id
    if sender_department_id is not None:
        if sender_department_id not in scope.managed_ids:
            raise DomainError("task_transfer_sender",
                              "Отправителем может быть только отдел, которым вы руководите",
                              status=422)
        return sender_department_id
    return min(scope.managed_ids) if scope.managed_ids else None


def _notify_transfer(task: Task, department_id: int, actor_id: int) -> None:
    try:
        heads = hr.department_manager_user_ids([department_id])
    except ServiceDisabled as exc:
        heads = fallback("tasks.transfer.manager_lookup", {},
                         reason="hr выключен — глава отдела-получателя не найден",
                         expected=True, exc=exc)
    name = hydration.department_name(hydration.department_briefs([department_id]),
                                     department_id)
    task_notify.transferred(task, actor_id, name, heads.get(department_id))


@transaction.atomic
def transfer(task_id: int, target_department_id: int, request, *,
             sender_department_id: int | None = None) -> Task:
    scope = task_scope.for_request(request)
    task_service.load_for_action(task_id, request)                  # невидимая — 404
    if not scope.elevated:
        # Цель — до права: выключенный hr даёт 503, а не 403 (S1-05).
        department_rules._require_active([target_department_id])
    # Блокировка отдельным запросом: выборка видимости — DISTINCT, а с ним
    # FOR UPDATE Postgres не принимает. Право — по ЗАБЛОКИРОВАННОЙ строке
    # (ревью K1.6): параллельный перенос мог сменить отдел между чтениями.
    task = Task.objects.select_for_update().get(pk=task_id, is_deleted=False)
    if not can_transfer(task, scope):
        raise DomainError("task_transfer_forbidden",
                          "Переносит задачу глава её отдела", status=403)
    if task.status in TERMINAL_STATUSES:
        raise DomainError("task_transfer_terminal",
                          "Завершённую или отменённую задачу не переносят", status=409)
    if target_department_id == task.department_id:
        raise DomainError("task_transfer_same", "Задача уже в этом отделе", status=422)
    sender = _sender(task, scope, sender_department_id)
    actor = scope.user_id
    old_department = task.department_id

    if sender is not None and sender != target_department_id:
        TaskDepartmentLink.objects.update_or_create(
            task=task, department_id=sender, defaults={"kind": DepartmentLinkKind.ORIGIN})
    TaskDepartmentLink.objects.update_or_create(
        task=task, department_id=target_department_id,
        defaults={"kind": DepartmentLinkKind.MEMBER})

    old_assignee = task.assignee_id
    old_crew = task_service._crew_ids(task)
    old_boards = set(board_fields.home_board_keys(task))
    TaskAssignee.objects.filter(task=task).delete()
    task.assignee_id = None
    old_status = task.status
    # «К выполнению» прямым присваиванием (S1-06): из «На проверке» FSM в
    # «К выполнению» не пускает, а у получателя задача начинается заново.
    # Терминальные сюда не доходят — ``completed_at`` не трогается.
    task.status = Status.TODO
    task.department_id = target_department_id
    task.save()

    task_service._log(task, actor, "transfer", sender, target_department_id)
    task_service._log(task, actor, "department_id", old_department, target_department_id)
    if old_assignee is not None:
        task_service._log(task, actor, "assignee_id", old_assignee, None)
    if old_status != Status.TODO:
        task_service._log(task, actor, "status", old_status, Status.TODO)
    # Места на досках прежних отделов больше не действуют; на доске цели —
    # в конец «К выполнению» (мастер-план §5.5, шаг 7).
    board_service.forget_department_ranks(task.id)
    board_service.place_on_department(target_department_id, task)
    _notify_transfer(task, target_department_id, actor)
    # События автоматизации (спецификация логики §3): статус, снятые
    # исполнители, «пришла на доску» нового отдела — его правила, а не
    # повтор «создана» на доске проекта.
    events = []
    if old_status != task.status:
        events.append(Event("moved", task.pk, actor, {"from": old_status, "to": task.status}))
    events += task_service._crew_events(task, actor, old_crew, set())
    events += task_service.arrived_events(task, actor, old_boards)
    automation.emit(*events)
    return task

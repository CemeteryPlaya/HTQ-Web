"""Уведомления о задаче — одна точка вместо разрозненных ``_notify``
(решения K-29, K-30, K-33; мастер-план канбана §3.4, этап S2).

Получают только УЧАСТНИКИ задачи (исполнители, руководитель, автор,
делегаты, наблюдатели) — кто просто видит доску, не получает ничего. Из них
убираются автор события и те, кто выключил уведомления хотя бы одной доски,
где лежит задача (доска отдела действует на поддерево). Адресные события —
«вас назначили», «вам делегировали», запросы доступа и решения по ним —
доходят всегда, выключатель их не гасит.

Заголовок — готовая фраза: колокольчик показывает его как есть. Код события
(``event=…``) лежит в ссылке — по нему различит события будущий
Telegram-бот, не разбирая текст. Пишется в транзакции изменения под своей
точкой сохранения: откат правки уносит и уведомление, а сбой записи
уведомления правку не ломает.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.db.models import Q

from apps.core.services import ServiceDisabled
from apps.hr import interface as hr
from apps.notifications import interface as notifications
from htqweb.fallback import fallback
from htqweb.tenancy.context import current_company_or_none

from ..models import BoardKind, BoardNotificationMute, DepartmentLinkKind, Task, TaskAssignee
from . import hydration

logger = logging.getLogger(__name__)

#: Только колокольчик (K-33). Будущий бот для сотрудников включит доставку
#: здесь, не трогая мест, откуда события шлются.
DELIVER = False

STATUS_LABELS = {
    "backlog": "Бэклог", "todo": "К выполнению", "in_progress": "В работе",
    "in_review": "На ревью", "blocked": "Заблокирована", "done": "Готова",
    "cancelled": "Отменена",
}

ACCESS_KIND_LABELS = {"execute": "на исполнение", "own": "на владение"}


# ── кто получает ────────────────────────────────────────────────────────

def participants(task: Task) -> set[int]:
    """Участники задачи (K-29) — по данным в базе на момент события."""
    ids = {task.assignee_id, task.supervisor_id, task.reporter_id}
    ids.update(TaskAssignee.objects.filter(task=task).values_list("user_id", flat=True))
    ids.update(task.delegates.values_list("user_id", flat=True))
    ids.update(task.watchers.values_list("user_id", flat=True))
    ids.discard(None)
    return ids


def _department_boards(task: Task) -> set[int]:
    """Доски отделов, где лежит задача: её отделы (основной, участники,
    отправитель) и их предки — выключенная доска отдела действует на
    поддерево. ``hr`` выключен — только сами отделы."""
    departments = {task.department_id}
    departments.update(link.department_id for link in task.department_links.all()
                       if link.kind in (DepartmentLinkKind.MEMBER, DepartmentLinkKind.ORIGIN))
    departments.discard(None)
    boards = set(departments)
    for department_id in departments:
        try:
            boards.update(row["id"] for row in hr.org_ancestors(department_id))
        except ServiceDisabled as exc:
            fallback("tasks.task_notify.ancestors_unavailable", None,
                     reason="hr выключен — выключатель доски проверяется без отделов-предков",
                     expected=True, exc=exc)
            break
    return boards


def muted(task: Task, user_ids: set[int]) -> set[int]:
    """Кто из ``user_ids`` выключил уведомления хотя бы одной доски задачи."""
    if not user_ids:
        return set()
    condition = Q()
    if boards := _department_boards(task):
        condition |= Q(board_kind=BoardKind.DEPARTMENT, board_id__in=boards)
    if task.project_id:
        condition |= Q(board_kind=BoardKind.PROJECT, board_id=task.project_id)
    if not condition:
        return set()
    return set(BoardNotificationMute.objects.filter(condition, user_id__in=user_ids)
               .values_list("user_id", flat=True))


# ── запись ──────────────────────────────────────────────────────────────

def _ref(task: Task) -> str:
    summary = task.summary if len(task.summary) <= 80 else f"{task.summary[:79]}…"
    return f"{task.key} «{summary}»"


def _url(task: Task, event: str, *, panel: bool = False) -> str:
    url = f"/tasks/board?card={task.id}&event={event}"
    return f"{url}&panel=requests" if panel else url


def _send(task: Task, event: str, actor_id: int | None, recipients, title: str, *,
          text: str = "", panel: bool = False) -> None:
    recipients = sorted({uid for uid in recipients if uid and uid != actor_id})
    if not recipients:
        return
    try:
        with transaction.atomic():
            notifications.notify(
                recipients=recipients, event="tasks.task", title=title, text=text,
                url=_url(task, event, panel=panel), company_slug=current_company_or_none(),
                target_type="task", target_id=str(task.id), actor_id=actor_id,
                deliver=DELIVER, dedupe_window_seconds=60)
    except ServiceDisabled as exc:
        # Центр уведомлений выключен на платформе — штатная деградация.
        fallback("tasks.task_notify.center_disabled", None,
                 reason="центр уведомлений выключен — уведомление о задаче не записано",
                 expected=True, exc=exc)
    except Exception:  # noqa: BLE001 — уведомление не должно ломать правку задачи
        logger.exception("tasks: notification %s for task %s failed", event, task.id)


def to_participants(task: Task, event: str, actor_id: int | None, title: str, *,
                    exclude=(), text: str = "") -> None:
    """Событие для участников (K-29) — минус выключившие доску (K-30)."""
    people = participants(task) - set(exclude) - {actor_id}
    _send(task, event, actor_id, people - muted(task, people), title, text=text)


def to_people(task: Task, event: str, actor_id: int | None, recipients, title: str, *,
              panel: bool = False) -> None:
    """Адресное событие — доходит всегда."""
    _send(task, event, actor_id, recipients, title, panel=panel)


# ── события ─────────────────────────────────────────────────────────────

def _name(user_id: int | None) -> str:
    return hydration.user_name(hydration.user_briefs([user_id]), user_id) or f"#{user_id}"


def assignees_added(task: Task, actor_id: int | None, user_ids, *, primary_id=None) -> None:
    """Добавлены исполнители: им — адресно, остальным участникам — одной фразой."""
    added = [uid for uid in dict.fromkeys(user_ids) if uid]
    if not added:
        return
    for uid in added:
        title = (f"Вас назначили основным исполнителем: {_ref(task)}" if uid == primary_id
                 else f"Вас назначили исполнителем: {_ref(task)}")
        to_people(task, "assignee_added", actor_id, [uid], title)
    names = ", ".join(_name(uid) for uid in added)
    to_participants(task, "assignee_added", actor_id,
                    f"Новые исполнители — {names}: {_ref(task)}" if len(added) > 1
                    else f"Новый исполнитель — {names}: {_ref(task)}",
                    exclude=added)


def primary_changed(task: Task, actor_id: int | None, user_id: int | None) -> None:
    if user_id:
        to_people(task, "assignee_changed", actor_id, [user_id],
                  f"Вас назначили основным исполнителем: {_ref(task)}")
        to_participants(task, "assignee_changed", actor_id,
                        f"Основной исполнитель — {_name(user_id)}: {_ref(task)}",
                        exclude=[user_id])
    else:
        to_participants(task, "assignee_changed", actor_id,
                        f"Снят основной исполнитель: {_ref(task)}")


def claimed(task: Task, actor_id: int) -> None:
    to_participants(task, "assignee_changed", actor_id,
                    f"Взята в работу — {_name(actor_id)}: {_ref(task)}")


def status_changed(task: Task, actor_id: int | None, status: str) -> None:
    to_participants(task, "status", actor_id,
                    f"Статус «{STATUS_LABELS.get(status, status)}»: {_ref(task)}")


def commented(task: Task, actor_id: int | None, body: str) -> None:
    text = body if len(body) <= 300 else f"{body[:299]}…"
    to_participants(task, "comment", actor_id, f"Новый комментарий: {_ref(task)}", text=text)


def transferred(task: Task, actor_id: int | None, department_name: str | None,
                head_id: int | None) -> None:
    where = f"«{department_name}»" if department_name else "другой отдел"
    to_participants(task, "transfer", actor_id, f"Передана в отдел {where}: {_ref(task)}",
                    exclude=[head_id] if head_id else ())
    if head_id:
        to_people(task, "transfer", actor_id, [head_id],
                  f"В ваш отдел передана задача: {_ref(task)}")


def supervisor_set(task: Task, actor_id: int | None, user_id: int | None) -> None:
    if user_id:
        to_people(task, "supervisor_set", actor_id, [user_id],
                  f"Вас назначили руководителем задачи: {_ref(task)}")


def delegated(task: Task, actor_id: int | None, user_id: int) -> None:
    to_people(task, "delegated", actor_id, [user_id],
              f"Вам делегирована задача: {_ref(task)}")


def access_requested(task: Task, requester_id: int, kind: str, deciders) -> None:
    to_people(task, "access_requested", requester_id, deciders,
              f"{_name(requester_id)} просит доступ {ACCESS_KIND_LABELS.get(kind, kind)}: "
              f"{_ref(task)}", panel=True)


def access_decided(task: Task, actor_id: int, access_request, *, approved: bool,
                   other_deciders=(), replaced_user_id: int | None = None) -> None:
    kind = ACCESS_KIND_LABELS.get(access_request.kind, access_request.kind)
    verdict = "одобрен" if approved else "отклонён"
    requester = access_request.requester_id
    to_people(task, "access_decided", actor_id, [requester],
              f"Ваш запрос доступа {kind} {verdict}: {_ref(task)}", panel=True)
    to_people(task, "access_decided", actor_id,
              [uid for uid in other_deciders if uid != requester],
              f"Запрос доступа {kind} от {_name(requester)} {verdict}, "
              f"решение — {_name(actor_id)}: {_ref(task)}", panel=True)
    if replaced_user_id and replaced_user_id != requester:
        to_people(task, "access_decided", actor_id, [replaced_user_id],
                  f"Замена в задаче: вместо вас — {_name(requester)}: {_ref(task)}")

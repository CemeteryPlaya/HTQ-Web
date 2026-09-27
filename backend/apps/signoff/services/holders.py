"""«Сейчас у» и очередь пользователя (мастер-план БЗО, B1.3; ТЗ §16.2).

«Сейчас у» — колонка реестров документов: у кого документ ждёт решения, на
каком этапе и с какого времени. Очередь пользователя — для ежедневной сводки
ожидающих решения (D-23): те же задачи, что «Ждёт меня», без полей экрана.
Обе функции работают в контексте ТЕКУЩЕЙ компании, как весь signoff.
"""

from __future__ import annotations

from apps.hr import interface as hr
from apps.signoff.models import (
    ApprovalProcess,
    ProcessState,
    StageState,
    TaskState,
)
from apps.signoff.services import presentation, registry
from apps.signoff.services.registry import BadSubjectId

_OPEN = (StageState.ACTIVE, StageState.NO_EXECUTOR)


def current_holders(subject_type: str, subject_ids) -> dict[str, dict]:
    """``{subject_id: {stage, users: [{id, name}], position, since, no_executor}}``.

    Ключ — каноническая строка ключа объекта (как в ``ApprovalProcess``).
    Объекты без идущего согласования в ответ не попадают; ключ, которого у
    типа не бывает, — тоже (реестр не должен падать из-за одной строки).
    """
    keys = []
    for subject_id in subject_ids:
        try:
            keys.append(registry.storage_key(subject_type, subject_id))
        except BadSubjectId:
            continue
    if not keys:
        return {}

    processes = list(ApprovalProcess.objects
                     .filter(subject_type=subject_type, subject_id__in=keys,
                             state=ProcessState.PENDING)
                     .prefetch_related("stages__tasks"))
    open_stages = {
        process.pk: [stage for stage in process.stages.all()
                     if stage.order == process.current_order and stage.state in _OPEN]
        for process in processes
    }
    pending = {
        process.pk: [task for stage in open_stages[process.pk]
                     if stage.state == StageState.ACTIVE
                     for task in stage.tasks.all() if task.state == TaskState.PENDING]
        for process in processes
    }
    names = presentation._name_map(
        task.user_id for tasks in pending.values() for task in tasks)
    position_ids = [tasks[0].position_id for tasks in pending.values()
                    if tasks and tasks[0].position_id is not None]
    titles = ({row["id"]: row.get("title", "") for row in hr.get_positions_brief(position_ids)}
              if position_ids else {})

    out: dict[str, dict] = {}
    for process in processes:
        stages = open_stages[process.pk]
        tasks = pending[process.pk]
        no_executor = any(stage.state == StageState.NO_EXECUTOR for stage in stages)
        users = [{"id": task.user_id,
                  "name": names.get(task.user_id, {}).get("full_name", "")}
                 for task in _unique_users(tasks)]
        first_position = tasks[0].position_id if tasks else None
        since = min((stage.activated_at for stage in stages if stage.activated_at),
                    default=process.created_at)
        out[process.subject_id] = {
            "stage": " / ".join(stage.name for stage in stages),
            "users": users,
            "position": titles.get(first_position) if first_position is not None else None,
            "since": since,
            "no_executor": no_executor,
        }
    return out


def pending_for_user(user_id: int) -> list[dict]:
    """``[{task_id, subject_type, subject_id, title, url, since}]`` — решения,
    которых этот человек ждёт прямо сейчас (та же выборка, что «Ждёт меня»)."""
    rows = presentation.list_inbox(user_id)
    if not rows:
        return []
    from apps.signoff.models import ApprovalTask

    activated = dict(ApprovalTask.objects
                     .filter(pk__in=[row["task_id"] for row in rows])
                     .values_list("pk", "stage__activated_at"))
    return [{
        "task_id": row["task_id"],
        "subject_type": row["subject_type"],
        "subject_id": row["subject_id"],
        "title": row["subject_title"],
        "url": row["subject_url"],
        "since": activated.get(row["task_id"]) or row["created_at"],
    } for row in rows]


def digest_items(user_id: int) -> list[dict]:
    """Источник ежедневной сводки центра уведомлений (D-23): ``[{title, url,
    since}]`` по той же выборке, что ``pending_for_user``.

    Заголовок предмета может не прийти (тип без ``describe``), а ссылки на
    документ может не быть вовсе, — тогда строка сводки всё равно читается и
    ведёт на карточку процесса, где стоят кнопки решения.

    Выключенный у компании ``signoff`` — не сбой источника, а «ждать нечего»:
    пустой список, без ``ServiceDisabled`` (сводка записала бы его как упавший
    источник у каждого пользователя каждое утро).
    """
    from apps.core.services import service_enabled
    from apps.signoff.services import registry

    if not service_enabled("signoff"):
        return []
    items = []
    for row in presentation.list_inbox(user_id):
        label = (registry.get_subject(row["subject_type"]).label
                 if registry.is_registered(row["subject_type"]) else row["subject_type"])
        title = row["subject_title"] or f"{label} №{row['subject_id']}"
        items.append({
            "title": f"{title} — {row['stage_name']}",
            "url": row["subject_url"] or f"/signoff/processes/{row['process_id']}",
            "since": row["created_at"],
        })
    return items


def _unique_users(tasks):
    seen = set()
    for task in tasks:
        if task.user_id not in seen:
            seen.add(task.user_id)
            yield task

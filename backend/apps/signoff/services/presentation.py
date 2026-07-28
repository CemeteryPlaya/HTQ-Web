"""Сборка карточек процесса и списка «ждёт моего решения».

Единственная реализация сериализации процесса на весь домен: ею пользуются
и HTTP-слой (с именами согласующих и карточкой предметного объекта), и
``interface.py`` для соседей (без них — соседу нужны данные, а не оформление).
Флаг ``enrich`` разводит эти два случая, чтобы не заводить два сериализатора,
которые однажды разойдутся.

Имена людей и заголовки предметных объектов — из ЧУЖИХ аппок
(``apps.users.interface`` и колбэк ``describe`` предметной аппки), поэтому
они собираются пачками: список из 20 заявок не должен превращаться в 20
походов к соседу.
"""

from __future__ import annotations

import logging

from apps.signoff.models import (
    ApprovalProcess,
    ApprovalTask,
    StageState,
    TaskState,
)
from apps.signoff.services import registry
from apps.users import interface as users

logger = logging.getLogger(__name__)


def serialize_process(process: ApprovalProcess, *, enrich: bool = False) -> dict:
    """Карточка процесса простыми типами. ``enrich`` добавляет имена и
    заголовок предметного объекта."""
    stages = list(process.stages.prefetch_related("tasks"))

    names: dict[int, dict] = {}
    if enrich:
        names = _name_map([task.user_id
                           for stage in stages
                           for task in stage.tasks.all()])

    card = {
        "id": process.pk,
        "subject_type": process.subject_type,
        "subject_id": process.subject_id,
        "state": process.state,
        "initiator_id": process.initiator_id,
        "current_order": process.current_order,
        "created_at": process.created_at,
        "finished_at": process.finished_at,
        "stages": [
            {
                "id": stage.pk,
                "order": stage.order,
                "name": stage.name,
                "quorum": stage.quorum,
                "state": stage.state,
                "decided_at": stage.decided_at,
                "tasks": [
                    {
                        "id": task.pk,
                        "user_id": task.user_id,
                        "full_name": names.get(task.user_id, {}).get("full_name", ""),
                        "state": task.state,
                        "comment": task.comment,
                        "acted_at": task.acted_at,
                    }
                    for task in stage.tasks.all()
                ],
            }
            for stage in stages
        ],
    }

    if enrich:
        described = describe_many([(process.subject_type, process.subject_id)])
        card_info = described.get((process.subject_type, process.subject_id), {})
        card["subject_title"] = card_info.get("title")
        card["subject_url"] = card_info.get("url")

    return card


def list_inbox(user_id: int) -> list[dict]:
    """Что ждёт решения этого пользователя прямо сейчас.

    Только задачи АКТИВНЫХ этапов: запрос на этапе, до которого очередь не
    дошла, существует в БД, но показывать его как «ждёт вас» нельзя — до
    него может и не дойти.
    """
    tasks = list(ApprovalTask.objects
                 .filter(user_id=user_id, state=TaskState.PENDING,
                         stage__state=StageState.ACTIVE)
                 .select_related("stage", "stage__process")
                 .order_by("-stage__process__created_at", "id"))
    if not tasks:
        return []

    described = describe_many([
        (task.stage.process.subject_type, task.stage.process.subject_id)
        for task in tasks
    ])

    rows = []
    for task in tasks:
        process = task.stage.process
        info = described.get((process.subject_type, process.subject_id), {})
        rows.append({
            "task_id": task.pk,
            "process_id": process.pk,
            "subject_type": process.subject_type,
            "subject_id": process.subject_id,
            "subject_title": info.get("title"),
            "subject_url": info.get("url"),
            "stage_name": task.stage.name,
            "quorum": task.stage.quorum,
            "initiator_id": process.initiator_id,
            "created_at": process.created_at,
        })
    return rows


def describe_many(pairs) -> dict[tuple[str, int], dict]:
    """``{(subject_type, subject_id): {title, url}}`` через колбэки аппок.

    ``describe`` предметной аппки принимает по одному id, поэтому пачка
    здесь — только по числу ВЫЗОВОВ (дубликаты схлопываются), а не по
    запросам в БД. Расширять контракт до батч-версии сейчас незачем:
    список «ждёт решения» у человека — это единицы строк, и лишний метод в
    контракте каждой предметной аппки стоил бы дороже.
    """
    out: dict[tuple[str, int], dict] = {}
    for subject_type, subject_id in dict.fromkeys(pairs):
        try:
            subject = registry.get_subject(subject_type)
        except registry.UnknownSubject:
            # Тип перестал регистрироваться (аппку сняли), а процессы от него
            # остались. Карточка не должна ронять список.
            logger.warning("signoff: тип %s больше не зарегистрирован", subject_type)
            out[(subject_type, subject_id)] = {
                "title": f"{subject_type} #{subject_id}", "url": None}
            continue

        if subject.describe is None:
            out[(subject_type, subject_id)] = {
                "title": f"{subject.label} #{subject_id}", "url": None}
            continue

        try:
            info = subject.describe(subject_id) or {}
        except Exception:
            logger.warning("signoff: describe() для %s#%s упал",
                           subject_type, subject_id, exc_info=True)
            info = {}
        out[(subject_type, subject_id)] = {
            "title": info.get("title") or f"{subject.label} #{subject_id}",
            "url": info.get("url"),
        }
    return out


def _name_map(user_ids) -> dict[int, dict]:
    ids = list(dict.fromkeys(user_ids))
    if not ids:
        return {}
    return {row["id"]: row for row in users.get_users_brief(ids)}

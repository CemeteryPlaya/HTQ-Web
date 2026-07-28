"""Публичный API аппки signoff для ДРУГИХ аппок.

Единственный способ, которым сосед имеет право обращаться к signoff.
Прямой импорт ``apps.signoff.models`` / ``apps.signoff.services`` из другой
аппки запрещён и ловится ``apps/core/tests/test_app_isolation.py``.

В отличие от остальных ``interface.py`` в репозитории, этот модуль
экспортирует не только функции, но и КЛАСС — примесь ``Approvable``.
Иначе никак: предметная модель обязана его наследовать, а импортировать
``apps.signoff.models`` предметная аппка не вправе. Поэтому:

    from apps.signoff import interface as signoff

    class Budget(signoff.Approvable, models.Model):
        SIGNOFF_SUBJECT_TYPE = "contracts.budget"

Про ``require_service("signoff")``. Он стоит на функциях ВРЕМЕНИ ВЫПОЛНЕНИЯ
и намеренно отсутствует на ``register_subject``/``Approvable``:
регистрация происходит в ``AppConfig.ready()``, то есть до того, как
существует соединение с БД и таблица ``core_service_status`` (в частности,
на ``migrate`` в пустой базе). Гейт на регистрации ронял бы запуск всего
процесса из-за выключенного сервиса — при том что выключённый signoff
должен запрещать согласование, а не поднятие платформы.
"""

from __future__ import annotations

from apps.core.services import require_service
from apps.signoff.models import (
    Approvable,
    ApprovalProcess,
    ApprovalState,
    ProcessState,
    StageState,
    TaskState,
)
from apps.signoff.services import engine, presentation, registry
from apps.signoff.services.registry import UnknownSubject, register_subject

__all__ = [
    "Approvable",
    "ApprovalState",
    "UnknownSubject",
    "register_subject",
    "start_process",
    "cancel_process",
    "get_process",
    "get_process_for",
    "approval_state_of",
    "count_awaiting",
]


def start_process(*, subject_type: str, subject_id: int,
                  initiator_id: int | None = None) -> dict:
    """Отправить объект на согласование. Возвращает карточку процесса.

    Поднимает ``engine.RouteNotConfigured`` / ``AlreadyInApproval`` /
    ``RouteUnusable`` — все они наследуют ``engine.SignoffError``, и вьюха
    вызывающей аппки переводит их в 409 с текстом.
    """
    require_service("signoff")

    process = engine.start(subject_type=subject_type, subject_id=subject_id,
                           initiator_id=initiator_id)
    return serialize_process(process)


def cancel_process(*, process_id: int, actor_id: int | None = None) -> dict:
    """Отозвать идущее согласование; объект возвращается в черновик."""
    require_service("signoff")

    return serialize_process(engine.cancel(process_id=process_id,
                                           actor_id=actor_id))


def get_process(process_id: int) -> dict | None:
    require_service("signoff")

    process = ApprovalProcess.objects.filter(pk=process_id).first()
    return None if process is None else serialize_process(process)


def get_process_for(subject_type: str, subject_id: int) -> dict | None:
    """Последний процесс согласования объекта или ``None``."""
    require_service("signoff")

    process = (ApprovalProcess.objects
               .filter(subject_type=subject_type, subject_id=subject_id)
               .order_by("-created_at", "-id").first())
    return None if process is None else serialize_process(process)


def approval_state_of(subject_type: str, subject_id: int) -> str:
    """Состояние согласования объекта, выведенное из процессов.

    Нужно редко: у самого объекта есть денормализованное поле
    ``approval_state`` (примесь ``Approvable``), и читать надо его. Эта
    функция — для сверки и для случаев, когда объекта под рукой нет.
    """
    require_service("signoff")

    process = (ApprovalProcess.objects
               .filter(subject_type=subject_type, subject_id=subject_id)
               .order_by("-created_at", "-id").first())
    if process is None:
        return ApprovalState.DRAFT
    return {
        ProcessState.PENDING: ApprovalState.PENDING,
        ProcessState.APPROVED: ApprovalState.APPROVED,
        ProcessState.REJECTED: ApprovalState.REJECTED,
        ProcessState.CANCELLED: ApprovalState.DRAFT,
    }[process.state]


def count_awaiting(user_id: int) -> int:
    """Сколько согласований ждёт решения этого пользователя (для бейджа)."""
    require_service("signoff")

    from apps.signoff.models import ApprovalTask

    return ApprovalTask.objects.filter(
        user_id=user_id, state=TaskState.PENDING,
        stage__state=StageState.ACTIVE,
    ).count()


def serialize_process(process: ApprovalProcess) -> dict:
    """Карточка процесса простыми типами — ORM-объекты наружу не отдаются.

    Без ``enrich``: соседу нужны данные, а не оформление, и разворачивать
    для него имена согласующих значило бы тянуть ``apps.users`` в каждый
    межаппный вызов. HTTP-слой зовёт тот же сериализатор с ``enrich=True``.
    """
    return presentation.serialize_process(process, enrich=False)


def registered_subjects() -> list[dict]:
    """Какие типы объектов вообще согласуемы — для настройки маршрутов."""
    return [{"subject_type": s.subject_type, "label": s.label}
            for s in registry.registered_subjects()]

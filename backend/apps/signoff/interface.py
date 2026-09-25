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
    ApprovalRoute,
    ApprovalState,
    ProcessState,
    StageState,
    TaskState,
)
from apps.signoff.services import attachments, engine, presentation, registry
from apps.signoff.services.engine import (
    AlreadyInApproval,
    ProcessStillRunning,
    RouteNotConfigured,
    RouteUnusable,
    SignoffError,
    SubjectLocked,
)
from apps.signoff.services import route_service
from apps.signoff.services.registry import UnknownSubject, register_subject
from apps.signoff.services.route_service import RouteConflict

__all__ = [
    "Approvable",
    "ApprovalState",
    # Исключения экспортируются наравне с функциями: вьюха предметной аппки
    # обязана уметь перевести их в 409, а импортировать
    # apps.signoff.services.engine она не вправе.
    "SignoffError",
    "RouteNotConfigured",
    "AlreadyInApproval",
    "RouteUnusable",
    # Поднимает не функция этого модуля, а метод примеси
    # (``Approvable.assert_editable``) — но ловит его вьюха предметной
    # аппки, и брать его ей больше неоткуда.
    "SubjectLocked",
    "ProcessStillRunning",
    "UnknownSubject",
    "RouteConflict",
    "configure_route",
    "register_subject",
    "start_process",
    "cancel_process",
    "rework_process",
    "get_process",
    "get_process_for",
    "approval_state_of",
    "count_awaiting",
    "has_active_route",
    "registered_subjects",
    "list_awaiting_subject_ids",
    "list_decided_subject_ids",
    "pending_requirement_keys",
    "pending_step",
    "decision_stats",
    "is_participant",
]


def has_active_route(subject_type: str, scope: str = "") -> bool:
    """Настроено ли согласование для этого типа объектов (и области).

    Нужно предметной аппке, чтобы включать проверку «объект согласован?»
    только там, где согласование вообще заведено. Без этого установка,
    в которой маршрутов нет, немедленно перестала бы работать: все
    существующие записи имеют ``approval_state = draft``, и жёсткая проверка
    запретила бы всё разом — на ровном месте, без единого настроенного
    маршрута.

    ``require_service`` здесь НЕ ставится, и ``ServiceDisabled`` не
    поднимается: вопрос «действует ли гейт согласования» при выключённом
    signoff имеет ответ «нет», а не «ошибка». Выключенный модуль
    согласования должен переставать ТРЕБОВАТЬ согласования, а не ронять
    предметные аппки, которые его подключили.
    """
    from apps.core.services import service_enabled

    if not service_enabled("signoff"):
        return False
    return ApprovalRoute.objects.filter(subject_type=subject_type, scope=scope,
                                        is_active=True).exists()


def start_process(*, subject_type: str, subject_id: int,
                  initiator_id: int | None = None,
                  enrich: bool = False, scope: str | None = None) -> dict:
    """Отправить объект на согласование. Возвращает карточку процесса.

    Поднимает ``engine.RouteNotConfigured`` / ``AlreadyInApproval`` /
    ``RouteUnusable`` — все они наследуют ``engine.SignoffError``, и вьюха
    вызывающей аппки переводит их в 409 с текстом.

    ``scope`` обычно не передаётся: область объекта движок спрашивает у
    самой аппки (``Subject.scope_of``), и явный аргумент нужен только там,
    где аппка хочет запустить объект по чужой области.
    """
    require_service("signoff")

    process = engine.start(subject_type=subject_type, subject_id=subject_id,
                           initiator_id=initiator_id, scope=scope)
    return serialize_process(process, enrich=enrich)


def cancel_process(*, process_id: int, actor_id: int | None = None,
                   enrich: bool = False) -> dict:
    """Отозвать идущее согласование; объект возвращается в черновик."""
    require_service("signoff")

    return serialize_process(engine.cancel(process_id=process_id,
                                           actor_id=actor_id), enrich=enrich)


def rework_process(*, process_id: int, actor_id: int | None = None,
                   comment: str = "", enrich: bool = False) -> dict:
    """Вернуть на доработку объект по УЖЕ ЗАКРЫТОМУ кругу согласования.

    Единственный способ отпереть согласованный или отклонённый объект для
    правки (``Approvable.assert_editable``). Пока круг идёт, это делает
    согласующий своим решением ``rework``, а не эта функция — она поднимет
    ``engine.ProcessStillRunning``.

    Права не проверяет: кому это позволено, знает вызывающий
    (``views.ProcessReworkView`` — администратор или согласующий этого
    процесса), ровно как у ``cancel_process``.
    """
    require_service("signoff")

    return serialize_process(
        engine.reopen(process_id=process_id, actor_id=actor_id,
                      comment=comment), enrich=enrich)


def get_process(process_id: int, *, enrich: bool = False) -> dict | None:
    require_service("signoff")

    process = ApprovalProcess.objects.filter(pk=process_id).first()
    return None if process is None else serialize_process(process, enrich=enrich)


def get_process_for(subject_type: str, subject_id: int, *,
                    enrich: bool = False) -> dict | None:
    """Последний процесс согласования объекта или ``None``."""
    require_service("signoff")

    process = (ApprovalProcess.objects
               .filter(subject_type=subject_type, subject_id=subject_id)
               .order_by("-created_at", "-id").first())
    return None if process is None else serialize_process(process, enrich=enrich)


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
        ProcessState.REWORK: ApprovalState.REWORK,
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


def configure_route(*, subject_type: str, name: str, stages: list[dict],
                    scope: str = "") -> int:
    """Создать активный маршрут с этапами одной транзакцией; вернуть его id.

    Для предметной аппки, которая заводит маршрут программно — команда
    переезда «Запросов» со старого движка. Каждый этап — словарь в терминах
    ``route_service.add_stage`` (``order``, ``name``, ``quorum``,
    ``approver_kind``, ``position_ids``/``user_ids``/``approver_key``,
    ``condition``, ``is_fallback``, ``requires_attachment``,
    ``requires_comment``, ``requirement_key``). Любая ошибка настройки —
    ``RouteConflict``
    (экспортируется отсюда же), и ничего не записано.
    """
    require_service("signoff")

    from django.db import transaction

    with transaction.atomic():
        route = route_service.create_route(subject_type=subject_type, name=name,
                                           scope=scope)
        for spec in stages:
            route_service.add_stage(
                route.pk,
                order=spec.get("order", 1), name=spec["name"],
                quorum=spec.get("quorum", "all"),
                position_ids=list(spec.get("position_ids") or []),
                condition=spec.get("condition") or [],
                is_fallback=bool(spec.get("is_fallback", False)),
                approver_kind=spec.get("approver_kind", "position"),
                user_ids=list(spec.get("user_ids") or []),
                approver_key=spec.get("approver_key", ""),
                requires_attachment=bool(spec.get("requires_attachment", False)),
                requires_comment=bool(spec.get("requires_comment", False)),
                requirement_key=spec.get("requirement_key", ""),
            )
    return route.pk


def pending_step(*, user_id: int, subject_type: str,
                 subject_id: int) -> dict | None:
    """Рабочий шаг этого пользователя по объекту ПРЯМО СЕЙЧАС — или ``None``.

    Задача на активном этапе идущего процесса, где решение за ним, вместе с
    тем, чего этот этап требует: ``requirement_key`` (что должно быть
    сделано на объекте), ``requires_attachment`` / ``requires_comment`` и
    уже приложенный ``file_id``. Нужно предметной аппке, чтобы её экран мог
    показать блок «ваш шаг» — поля, документ, пояснение — и закрыть шаг
    одним действием через ``POST tasks/<id>/attachment`` + ``/decision``.
    Гейты этапа при этом проверяет движок, аппка их только показывает.

    Параллельные этапы одного человека по одному объекту — редкость; берётся
    первый по порядку.
    """
    require_service("signoff")

    from apps.signoff.models import ApprovalTask

    task = (ApprovalTask.objects
            .select_related("stage")
            .filter(user_id=user_id, state=TaskState.PENDING,
                    stage__state=StageState.ACTIVE,
                    stage__process__state=ProcessState.PENDING,
                    stage__process__subject_type=subject_type,
                    stage__process__subject_id=subject_id)
            .order_by("stage__order", "id")
            .first())
    if task is None:
        return None
    stage = task.stage
    return {
        "task_id": task.pk,
        "stage_name": stage.name,
        "requirement_key": stage.requirement_key or "",
        "requires_attachment": stage.requires_attachment,
        "requires_comment": stage.requires_comment,
        "file_id": task.file_id or None,
        # Не только id: чтобы человек мог ОТКРЫТЬ приложенное и убедиться,
        # что это тот счёт, — до того, как шаг закроется и документ уйдёт
        # к следующему согласующему.
        "file": attachments.file_brief(task.file_id),
    }


def pending_requirement_keys(*, user_id: int, subject_type: str,
                             subject_id: int) -> list[str]:
    """Требования к объекту активного шага пользователя (см. ``pending_step``)."""
    step = pending_step(user_id=user_id, subject_type=subject_type,
                        subject_id=subject_id)
    return [step["requirement_key"]] if step and step["requirement_key"] else []


def list_awaiting_subject_ids(user_id: int, subject_type: str) -> list[int]:
    """Объекты этого типа, по которым пользователь должен принять решение
    ПРЯМО СЕЙЧАС — для вкладки «Список дел» реестра предметной аппки,
    которой к ``ApprovalTask`` доступа нет. Порядок — свежие процессы первыми."""
    require_service("signoff")

    from apps.signoff.models import ApprovalTask

    rows = (ApprovalTask.objects
            .filter(user_id=user_id, state=TaskState.PENDING,
                    stage__state=StageState.ACTIVE,
                    stage__process__subject_type=subject_type)
            .order_by("-stage__process__created_at")
            .values_list("stage__process__subject_id", flat=True))
    return list(dict.fromkeys(rows))


def list_decided_subject_ids(user_id: int, subject_type: str) -> list[int]:
    """Объекты, по которым пользователь УЖЕ принимал решение — вкладка
    «Готово». Только состоявшиеся решения: пропущенные кворумом запросы
    (``skipped``) решением не были."""
    require_service("signoff")

    from apps.signoff.models import ApprovalTask

    rows = (ApprovalTask.objects
            .filter(user_id=user_id, acted_at__isnull=False,
                    stage__process__subject_type=subject_type)
            .exclude(state__in=(TaskState.PENDING, TaskState.SKIPPED))
            .order_by("-acted_at")
            .values_list("stage__process__subject_id", flat=True))
    return list(dict.fromkeys(rows))


def is_participant(user_id: int, subject_type: str, subject_id: int) -> bool:
    """Был ли человек согласующим этого объекта — в любом круге и в любом
    состоянии задачи.

    Нужно предметной аппке, чтобы решить, показывать ли ему карточку: тот,
    кого спрашивали, вправе видеть, что он согласовывал, даже когда круг
    давно закрыт, а его задача погашена кворумом. Ровно то же правило, по
    которому сам signoff показывает процессы (``views._visible_processes``).
    """
    require_service("signoff")

    from apps.signoff.models import ApprovalTask

    return ApprovalTask.objects.filter(
        user_id=user_id,
        stage__process__subject_type=subject_type,
        stage__process__subject_id=subject_id,
    ).exists()


def decision_stats(subject_type: str, *, limit: int = 20) -> list[dict]:
    """Кто сколько решал по объектам этого типа — ``[{user_id, count,
    approved}]``, самые активные первыми. Для статистики предметной аппки
    «по согласующим»; пропущенные кворумом запросы решением не считаются."""
    require_service("signoff")

    from django.db.models import Case, Count, IntegerField, Sum, Value, When

    from apps.signoff.models import ApprovalTask

    rows = (ApprovalTask.objects
            .filter(stage__process__subject_type=subject_type,
                    acted_at__isnull=False)
            .exclude(state__in=(TaskState.PENDING, TaskState.SKIPPED))
            .values("user_id")
            .annotate(count=Count("id"),
                      approved=Sum(Case(When(state=TaskState.APPROVED, then=Value(1)),
                                        default=Value(0),
                                        output_field=IntegerField())))
            .order_by("-count")[:limit])
    return [{"user_id": int(row["user_id"]), "count": int(row["count"]),
             "approved": int(row["approved"] or 0)} for row in rows]


def serialize_process(process: ApprovalProcess, *, enrich: bool = False) -> dict:
    """Карточка процесса простыми типами — ORM-объекты наружу не отдаются.

    ``enrich=False`` по умолчанию: обычному соседу нужны данные, а не
    оформление, и разворачивать для него имена согласующих значило бы тянуть
    ``apps.users`` в каждый межаппный вызов.

    Просить ``enrich=True`` осмысленно ровно в одном случае: сосед сам отдаёт
    эту карточку в HTTP-ответе (эндпоинты «отправить на согласование» в
    предметных аппках), и тогда фронтенду нужны имена согласующих и заголовок
    объекта — ровно то же, что отдаёт собственный HTTP-слой signoff.
    """
    return presentation.serialize_process(process, enrich=enrich)


def registered_subjects() -> list[dict]:
    """Какие типы объектов вообще согласуемы — для настройки маршрутов."""
    return [{"subject_type": s.subject_type, "label": s.label}
            for s in registry.registered_subjects()]

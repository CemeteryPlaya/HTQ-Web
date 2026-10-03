"""Решение задачи дочерней компании прямо из очереди холдинга (БЗО, B8.1).

По умолчанию задача дочерней решается на её адресе: очередь холдинга
показывает задачу, «Открыть» переводит в дочернюю (``switchCompany``), и
дальше работают обычная карточка и решение. Переключатель маршрута
``allow_direct_decisions`` (решение Руслана 02.10) разрешает решить её, не
уходя из холдинга: запрос приходит на адрес холдинга, а движок выполняется в
схеме дочерней — ``use_company(дочерняя)`` снаружи, транзакция
``engine.act`` внутри, поэтому и её ``on_commit`` (события, уведомления)
отрабатывают в схеме дочерней. Колбэки предметных аппок берут компанию из
контекста, а не из запроса (это и обещает ``cross_company_decisions``), —
статус документа, KPI и уведомления пишутся в дочернюю.

Проверки, по порядку:

1. компания строго НИЖЕ текущей по дереву владения — иначе 404, как
   несуществующая: решать из дочерней за холдинг, из соседней — за соседа
   нельзя;
2. задача — своя (иначе 404);
3. ``signoff`` и подмодуль предмета включены у дочерней — иначе 503, как
   ответил бы HTTP-гейт на её адресе;
4. тип документа это допускает (``cross_company_decisions``) и флаг
   маршрута включён — иначе 403 (``DirectForbidden``);
5. этап не требует того, что из холдинга не сделать, — вложения
   согласующего и выбора варианта (``DirectBlocked``, 409).

4 и 5 перепроверяются под замком процесса (``engine.act(guard=…)``): флаг
маршрута живой, и выключенный секунду назад переключатель должен
остановить решение.
"""

from __future__ import annotations

from django.http import Http404

from apps.companies import interface as companies
from apps.core.services import require_service
from apps.signoff.models import (
    ApprovalProcess,
    ApprovalRoute,
    ApprovalTask,
    StageState,
    TaskState,
)
from apps.signoff.services import engine, presentation, registry
from htqweb.tenancy import current_company_or_none
from htqweb.tenancy.db import use_company


class DirectForbidden(engine.SignoffError):
    """Тип документа не решается из вышестоящей компании или флаг маршрута
    выключен — 403."""


class DirectBlocked(engine.SignoffError):
    """Этап требует того, что из вышестоящей компании не сделать, — 409."""


def company_card(slug: str, *, current: str | None) -> dict:
    """Компания строки очереди или карточки. ``subdomain`` — для перехода на
    её адрес (``switchCompany`` на фронте строит хост по псевдониму)."""
    row = companies.get_company(slug) or {}
    return {"slug": slug, "subdomain": row.get("subdomain"), "name": row.get("name") or slug,
            "url": companies.public_url(slug), "current": slug == current}


def target_company(slug: str) -> str:
    """Компания задачи — строго ниже текущей по дереву и со схемой; иначе 404."""
    current = current_company_or_none()
    if (not current or slug == current or slug not in companies.descendant_slugs(current)
            or not companies.schema_exists(slug)):
        raise Http404("Компания не найдена")
    return slug


def route_of(process: ApprovalProcess) -> ApprovalRoute | None:
    """Маршрут процесса: по ``route_id`` (справочный, без FK), а если его
    удалили — действующий маршрут типа и области."""
    route = (ApprovalRoute.objects.filter(pk=process.route_id).first()
             if process.route_id else None)
    return route or (ApprovalRoute.objects
                     .filter(subject_type=process.subject_type, scope=process.scope,
                             is_active=True).first())


def forbidden_reason(process: ApprovalProcess) -> str | None:
    """Почему тип документа или маршрут не допускают решения из вышестоящей
    компании. Флаг — ЖИВОЙ, из маршрута, а не из снимка процесса."""
    try:
        subject = registry.get_subject(process.subject_type)
    except registry.UnknownSubject:
        return "Документ этого типа решается на адресе своей компании"
    if not subject.cross_company_decisions:
        return f"«{subject.label}» решается на адресе своей компании"
    route = route_of(process)
    if route is None or not route.allow_direct_decisions:
        return "Решение из вышестоящей компании по этому маршруту не включено"
    return None


def blocked_reason(process: ApprovalProcess, stage) -> str | None:
    """Что этап требует такого, чего из вышестоящей компании не сделать.

    Проверки СОСТОЯНИЯ объекта (бюджет у счёта, ``requirement_key``) сюда не
    входят: у типов с ``cross_company_decisions`` это проверки, а не работа
    согласующего, и движок выполнит их как обычно, ответив 409 с причиной.
    """
    if stage.requires_attachment:
        return (f"Этап «{stage.name}» требует приложить документ — решите на адресе "
                f"компании")
    if (engine.stage_votes(process, stage)
            and len(registry.options_for(process.subject_type, process.subject_id)) > 1):
        return ("Нужно выбрать вариант — исходный документ или альтернативу; решите на "
                "адресе компании, там есть сравнение")
    return None


def blocker(task: ApprovalTask) -> str | None:
    """Почему эту задачу нельзя решить прямо из вышестоящей компании; ``None``
    — можно. Для строки очереди — без деления на 403 и 409."""
    process = task.stage.process
    return forbidden_reason(process) or blocked_reason(process, task.stage)


def _own_pending_task(process: ApprovalProcess, user_id: int) -> ApprovalTask | None:
    return (ApprovalTask.objects.select_related("stage", "stage__process")
            .filter(stage__process=process, user_id=user_id, state=TaskState.PENDING,
                    stage__state=StageState.ACTIVE)
            .order_by("stage__order", "id").first())


def process_card(slug: str, process_id: int, *, user_id: int) -> dict:
    """Карточка процесса дочерней для решения из холдинга: процесс, сводка
    документа (``Subject.summary``) и своя задача с признаком «можно решить
    отсюда». Только для участника процесса — иначе 404."""
    current = current_company_or_none()
    target = target_company(slug)
    with use_company(target):
        require_service("signoff")
        process = (ApprovalProcess.objects
                   .filter(pk=process_id, stages__tasks__user_id=user_id)
                   .distinct().first())
        if process is None:
            raise Http404("Процесс согласования не найден")
        card = presentation.serialize_process(process, enrich=True)
        # Тип сняли с регистрации, а процессы остались — карточка без сводки,
        # а не 500 (как ``presentation.describe_many``).
        card["summary"] = (registry.summary_for(process.subject_type, process.subject_id)
                           if registry.is_registered(process.subject_type) else None)
        task = _own_pending_task(process, user_id)
        reason = blocker(task) if task is not None else None
        card["my_task_id"] = task.pk if task is not None else None
        card["direct_allowed"] = task is not None and reason is None
        card["direct_blocker"] = reason
    card["company"] = company_card(target, current=current)
    # Можно ли перейти на адрес компании документа — есть членство (A8.1).
    card["can_enter"] = companies.user_may_enter_company(user_id, target)
    return card


def decide(slug: str, task_id: int, *, user_id: int, decision: str,
           comment: str = "", option_key: str = "") -> dict:
    """Решение по своей задаче дочерней компании — из холдинга."""
    current = current_company_or_none()
    target = target_company(slug)
    with use_company(target):
        require_service("signoff")
        task = (ApprovalTask.objects.select_related("stage", "stage__process")
                .filter(pk=task_id, user_id=user_id).first())
        if task is None:
            raise Http404("Запрос на согласование не найден")
        if registry.is_registered(task.stage.process.subject_type):
            service = registry.get_subject(task.stage.process.subject_type).service
            if service:
                require_service(service)

        def guard(process, stage, _task) -> None:
            reason = forbidden_reason(process)
            if reason:
                raise DirectForbidden(reason)
            reason = blocked_reason(process, stage)
            if reason:
                raise DirectBlocked(reason)

        process = engine.act(task_id=task.pk, actor_id=user_id, decision=decision,
                             comment=comment, option_key=option_key, guard=guard,
                             decided_from=current)
        card = presentation.serialize_process(process, enrich=True)
    card["company"] = company_card(target, current=current)
    return card

"""Операции над проектами. Руководитель — участник автоматически и не
снимается, пока он руководитель (Q-E26)."""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.db.models import Q

from apps.project.models import Project, ProjectMember, ProjectStatus
from htqweb import date_rules


class ProjectError(Exception):
    pass


class ProjectChangeRejected(ProjectError):
    """Подписчик отказал в правке «Проекта» (текст — для человека). Правка
    откатывается целиком — данные связанных сущностей не расходятся с
    «Проектом». Доска задач правку принимает всегда (D-02, решение 01.10:
    «Проект» главный — подстраивается доска); механизм — для соседа, которому
    подстроиться нечем."""


class ProjectDatesError(ProjectError):
    """Дата окончания раньше даты начала. Сроки «Проекта» проверяет он сам:
    доска задач их повторяет и не спорит с ними (D-02)."""


def _check_dates(date_start, date_end) -> None:
    if date_rules.out_of_order(date_start, date_end):
        raise ProjectDatesError("Дата окончания проекта раньше даты начала.")


#: Подписчики на правку «Проекта» — соседи, чьи данные повторяют его поля
#: (доска задач, D-02: «Проект» главный). Приём тот же, что у реестров
#: signoff и files: «Проект» не импортирует соседей, соседи подписываются из
#: своего ``ready()`` через ``project.interface.register_change_listener``.
_LISTENERS: list = []


def add_change_listener(listener) -> None:
    if listener not in _LISTENERS:
        _LISTENERS.append(listener)


def _changed(project: Project) -> None:
    """Сообщить подписчикам о правке — в той же транзакции: отказ подписчика
    (``ProjectChangeRejected``) откатывает и саму правку."""
    snapshot = brief(project)
    for listener in list(_LISTENERS):
        listener(snapshot)


def _ensure_member(project: Project, user_id: int | None, actor_id: int | None) -> None:
    if user_id:
        ProjectMember.objects.get_or_create(project=project, user_id=user_id,
                                            defaults={"added_by": actor_id})


@transaction.atomic
def create(*, code: str, name: str, country_code: str, actor_id: int,
           manager_user_id: int | None = None, **fields) -> Project:
    _check_dates(fields.get("date_start"), fields.get("date_end"))
    try:
        with transaction.atomic():
            project = Project.objects.create(code=code, name=name, country_code=country_code,
                                             manager_user_id=manager_user_id,
                                             created_by=actor_id, **fields)
    except IntegrityError as exc:
        raise ProjectError(f"Проект с кодом «{code}» уже есть") from exc
    _ensure_member(project, manager_user_id, actor_id)
    return project


@transaction.atomic
def update(project: Project, *, actor_id: int, **fields) -> Project:
    _check_dates(fields.get("date_start", project.date_start),
                 fields.get("date_end", project.date_end))
    for key, value in fields.items():
        setattr(project, key, value)
    project.save()
    _ensure_member(project, project.manager_user_id, actor_id)
    _changed(project)
    return project


def add_member(project: Project, user_id: int, *, actor_id: int) -> None:
    _ensure_member(project, user_id, actor_id)


def remove_member(project: Project, user_id: int, *, actor_id: int) -> None:
    if project.manager_user_id == user_id:
        raise ProjectError("Руководитель проекта остаётся участником, пока он руководитель")
    ProjectMember.objects.filter(project=project, user_id=user_id).delete()


def brief(project: Project) -> dict:
    return {"id": str(project.id), "code": project.code, "name": project.name,
            "kind": project.kind, "status": project.status,
            "country_code": project.country_code, "manager_user_id": project.manager_user_id,
            "customer_name": project.customer_name,
            "customer_counterparty_id": project.customer_counterparty_id or None,
            "date_start": project.date_start, "date_end": project.date_end}


def search(query: str, *, user_id: int, only_member: bool, limit: int = 20) -> list[dict]:
    rows = Project.objects.exclude(status=ProjectStatus.ARCHIVED)
    if query:
        rows = rows.filter(Q(code__icontains=query) | Q(name__icontains=query))
    if only_member:
        rows = rows.filter(members__user_id=user_id)
    return [brief(p) for p in rows.order_by("code")[:limit]]

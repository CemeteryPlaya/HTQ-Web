"""Видимость и права вызывающего — один расчёт на запрос (канбан-доски, K1.4).

Мастер-план канбан-досок §5.1–5.2, спека этапа 1 §K1.3. Из ``TaskScope``
считаются и видимость задачи (``task_service.visibility_q``), и права главы
отдела (``task_service.can_edit``), поэтому всё, что видно на доске, открывает
и ``load_for_action``, а флаги кнопок не расходятся с ручками.

Источники — только соседские ``interface``: отдел сотрудника и отделы, которыми
он руководит, — ``hr``; узлы ``tasks.departments.all`` и ``project.board`` —
``access``; проекты-участия ПМ — ``project`` (через ``board_scope``).

Кэш — явный атрибут запроса ``request.task_scope = (company, user_id, scope)``,
приём ``request.access_resolution`` (``htqweb/http.py``): переиспользуется,
только если совпали компания (``current_company_or_none()`` в момент вызова) и
``user_id`` токена.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.access import interface as access
from apps.core.services import ServiceDisabled
from apps.hr import interface as hr
from htqweb.fallback import fallback
from htqweb.tenancy.context import current_company_or_none

from . import board_scope
from . import hydration

#: Узел «Доски всех отделов» (access/0028): ОД и ГД.
ALL_DEPARTMENTS_NODE = "tasks.departments.all"


@dataclass(frozen=True)
class TaskScope:
    user_id: int
    elevated: bool
    #: Отдел, где человек числится (``None`` — нет карточки, уволен, ``hr`` выключен).
    own_department_id: int | None = None
    #: Отделы, которыми он руководит (``Department.manager``).
    managed_ids: frozenset[int] = field(default_factory=frozenset)
    #: Поддеревья своего и управляемых отделов — видимость (K-04).
    department_ids: frozenset[int] = field(default_factory=frozenset)
    #: Поддеревья только управляемых отделов — права главы (K-06).
    managed_subtree: frozenset[int] = field(default_factory=frozenset)
    #: Узел «Доски всех отделов».
    all_departments: bool = False
    #: Доски «Проектов» держателя ``project.board``: ``None``, ``ALL_LINKED`` или ключи.
    board_refs: object = None


def _org(user_id: int) -> tuple[int | None, list[int], dict[int, list[int]]]:
    """Свой отдел, управляемые отделы и их поддеревья — три запроса к ``hr``.

    Уволенный сотрудник отдела не получает (S1-22): раньше он видел только
    неразобранные задачи, с поддеревом увидел бы весь отдел. ``hr`` выключен —
    без отделов: видимость сужается до участия и досок проектов (fail-closed).
    """
    # Свой отдел — тем же путём, что и раньше (``hydration``: деградирует сам,
    # уволенного отсекает), поэтому прежние точки подмены в тестах действуют.
    own = hydration.employee_department_id(user_id)
    try:
        managed = hr.managed_department_ids(user_id)
        roots = ([own] if own is not None else []) + list(managed)
        subtrees = hr.department_subtree_ids(roots) if roots else {}
    except ServiceDisabled as exc:
        return fallback("tasks.task_scope.hr_unavailable", (None, [], {}),
                        reason="hr выключен — видимость задач без отдела",
                        expected=True, exc=exc)
    return own, list(managed), subtrees


__all__ = ["ALL_DEPARTMENTS_NODE", "TaskScope", "build", "for_request"]


def _expand(roots, subtrees: dict[int, list[int]]) -> frozenset[int]:
    """Корни плюс их поддеревья. Корень входит, даже если ``hr`` о нём не
    знает (S1-22): отсутствие строки не должно сужать видимость до пустой."""
    result = set(roots)
    for root in roots:
        result.update(subtrees.get(root, ()))
    return frozenset(result)


def build(token, company: str | None, *, resolution=None) -> TaskScope:
    """Расчёт без кэша — для вызовов вне HTTP-запроса."""
    if token.is_elevated:
        return TaskScope(user_id=token.user_id, elevated=True)
    own, managed, subtrees = _org(token.user_id)
    roots = ([own] if own is not None else []) + managed
    all_departments = "view" in access.flags_for(
        token, ALL_DEPARTMENTS_NODE, company, resolution=resolution)
    return TaskScope(
        user_id=token.user_id,
        elevated=False,
        own_department_id=own,
        managed_ids=frozenset(managed),
        department_ids=_expand(roots, subtrees),
        managed_subtree=_expand(managed, subtrees),
        all_departments=all_departments,
        board_refs=board_scope.board_refs_for(token, company, resolution=resolution),
    )


def for_request(request) -> TaskScope:
    """``TaskScope`` вызывающего, посчитанный один раз на запрос."""
    company = current_company_or_none()
    token = request.token
    cached = getattr(request, "task_scope", None)
    if cached is not None and cached[0] == company and cached[1] == token.user_id:
        return cached[2]
    resolution = None
    held = getattr(request, "access_resolution", None)
    if held is not None and held[0] == company and held[1] == token.user_id:
        resolution = held[2]
    scope = build(token, company, resolution=resolution)
    request.task_scope = (company, token.user_id, scope)
    return scope

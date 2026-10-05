"""Доски задач «Проектов» для держателя «Доски задач проекта» (решение
Руслана 01.10, узел ``project.board`` — ТД, ОД, АДМ, ПМ).

Обычному сотруднику доски видны по отделу (``project_service.scope_for``).
Держатель узла видит ещё и доски тех «Проектов» БЗО, что видит в модуле: с
узлом ``project.all`` — все связанные доски, иначе доски проектов-участия.
Это только чтение — доски, её список задач и дорожных карт; правка доски
(``views._project_for_write``) этим не открывается, а задачи внутри доски
видны по своим правилам (``task_service.scope_for``).
"""

from __future__ import annotations

from django.db.models import Q

from apps.access import interface as access
from apps.project import interface as project

#: «Все связанные доски» — у держателя узла, который видит все «Проекты».
ALL_LINKED = "all-linked"


def board_refs_for(token, company: str | None):
    """``ALL_LINKED``, список ключей «Проектов» или ``None`` — узла нет, а у
    видящих всё (``is_elevated``) правило и так шире."""
    if token.is_elevated or "view" not in access.flags_for(token, "project.board", company):
        return None
    if "view" in access.flags_for(token, "project.all", company):
        return ALL_LINKED
    return project.member_project_ids(token.user_id)


def refs_for_request(request):
    company = (getattr(request, "company", None) or {}).get("slug")
    return board_refs_for(request.token, company)


def board_q(refs, prefix: str = "") -> Q | None:
    """Условие «доска одного из этих «Проектов»» для ``Project`` (``prefix``
    пуст) или для строк со ссылкой на доску (``prefix="project__"``)."""
    if refs == ALL_LINKED:
        # Непустая ссылка: «> ''» — без NOT по джойну, где проекта может не быть.
        return Q(**{f"{prefix}project_ref__gt": ""})
    if refs:
        return Q(**{f"{prefix}project_ref__in": list(refs)})
    return None

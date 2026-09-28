"""Правила статей бюджета — проверка ручки API.

Само правило родителя — в модели (``Article.parent_problem``): родитель из
той же группы (группа открывает статьи по узлу прав, BR-010), не сама
статья и не её потомок, не архивный. Модель проверяет его и в ``clean()``,
то есть в django-admin, где группу и родителя можно сменить и у готовой
статьи. Здесь — тот же вызов с ошибкой API E-REF-05.

Через API группа и родитель после создания не меняются (``ArticlePatch``
их не принимает), поэтому ручка проверяет правило только при создании.
"""

from __future__ import annotations

import uuid

from htqweb.errors import DomainError

from ..models import Article

E_PARENT = "E-REF-05"


def _canonical(value) -> str:
    """UUID строкой в каноническом виде (регистр, дефисы), как у ``str(pk)``."""
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        return str(value)


def check_parent(group_id: str, parent_id: str | None) -> None:
    if not parent_id:
        return
    try:
        key = uuid.UUID(str(parent_id))
    except ValueError:
        key = None
    parent = (Article.objects.select_related("group").filter(pk=key).first()
              if key is not None else None)
    if parent is None:
        raise DomainError(
            E_PARENT, "Родительская статья не найдена. Обновите страницу и выберите её снова.",
            fields=[{"field": "parent_id", "message": "Статья не найдена"}])
    problem = Article(group_id=_canonical(group_id)).parent_problem(parent)
    if problem is not None:
        text, short = problem
        raise DomainError(E_PARENT, text, fields=[{"field": "parent_id", "message": short}])

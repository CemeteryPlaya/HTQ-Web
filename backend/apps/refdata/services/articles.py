"""Правила статей бюджета — проверка ручки API.

Само правило родителя — в модели (``Article.parent_problem``): родитель из
той же группы (группа открывает статьи по узлу прав, BR-010), не сама
статья и не её потомок, не архивный. Модель проверяет его и в ``clean()``,
то есть в django-admin, где группу и родителя можно сменить и у готовой
статьи. Здесь — тот же вызов с ошибкой API E-REF-05.

Через API группа и родитель после создания не меняются (``ArticlePatch``
их не принимает), поэтому ручка проверяет правило только при создании.

Группа проверяется раньше родителя (``check_group``): кривой или
несуществующий ``group_id`` иначе доходил до правила родителя и получал
отказ «родитель из другой группы», а без родителя — нарушение внешнего
ключа при сохранении, которое ручка выдавала за повтор кода. Архивная
группа тоже отвергается — как архивный родитель: новые записи архивные
данные справочника не берут (ТЗ §18).
"""

from __future__ import annotations

import uuid

from htqweb.errors import DomainError

from ..models import Article, ArticleGroup

E_PARENT = "E-REF-05"
E_GROUP = "E-VAL-01"


def _canonical(value) -> str:
    """UUID строкой в каноническом виде (регистр, дефисы), как у ``str(pk)``."""
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        return str(value)


def check_group(group_id: str) -> None:
    """Группа новой статьи существует и действует — иначе 422 с полем
    ``group_id`` (ключ не UUID, группы нет, группа в архиве)."""
    try:
        key = uuid.UUID(str(group_id))
    except ValueError:
        key = None
    group = ArticleGroup.objects.filter(pk=key).first() if key is not None else None
    if group is None:
        raise DomainError(
            E_GROUP, "Группа статей не найдена. Обновите страницу и выберите группу снова.",
            fields=[{"field": "group_id", "message": "Группа не найдена"}])
    if not group.is_active:
        raise DomainError(
            E_GROUP, f"Группа статей „{group.name}“ в архиве — выберите действующую.",
            fields=[{"field": "group_id", "message": "Группа статей в архиве"}])


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

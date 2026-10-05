"""Общие ручки модуля: история изменений документа, «кто я».

Каждая — под гейтом модуля ``bpp`` с явным уровнем.
"""

from django.http import Http404

from htqweb.http import api_view

from .services.actor import Actor
from .services.core import audit


@api_view(methods=("GET",), module="bpp", level="read")
def object_history(request, object_type: str, object_id: str):
    # Отказ — 404, как на несуществующий объект: ручкой нельзя прощупать
    # чужие id (services/core/audit.py — реестр проверок по типам).
    if not audit.can_view_history(request, object_type, object_id):
        raise Http404("История не найдена")
    return audit.history(object_type, object_id)


@api_view(methods=("GET",), module="bpp", level="read")
def me(request):
    """ТЗ §23 GetCurrentUser: группы статей и роли инициатора пользователя —
    одно правило с сервисом заявки (``services.actor.Actor``), иначе подсказка
    «кто я» могла бы разойтись с тем, что реально разрешает подать заявку."""
    actor = Actor(request)
    return {
        "article_groups": actor.group_codes,
        "initiator_roles": [role.value for role in actor.initiator_roles()],
    }

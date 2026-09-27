"""Общие ручки модуля: история изменений документа.

Каждая — под гейтом модуля ``bpp`` с явным уровнем.
"""

from django.http import Http404

from htqweb.http import api_view

from .services.core import audit


@api_view(methods=("GET",), module="bpp", level="read")
def object_history(request, object_type: str, object_id: str):
    # Отказ — 404, как на несуществующий объект: ручкой нельзя прощупать
    # чужие id (services/core/audit.py — реестр проверок по типам).
    if not audit.can_view_history(request, object_type, object_id):
        raise Http404("История не найдена")
    return audit.history(object_type, object_id)

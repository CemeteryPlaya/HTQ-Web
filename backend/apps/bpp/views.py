"""Общие ручки модуля: история изменений документа.

Каждая — под гейтом модуля ``bpp`` с явным уровнем.
"""

from htqweb.http import api_view

from .services.core import audit


@api_view(methods=("GET",), module="bpp", level="read")
def object_history(request, object_type: str, object_id: str):
    return audit.history(object_type, object_id)

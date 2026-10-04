"""Ручка «Обзора» модуля ``GET /api/bpp/v1/overview`` — стартовая страница
раздела по ролям (ТЗ §05, §17; ``services/overview.py``).

Гейт модуля ``bpp`` (``read``); дальше каждый блок решает сам — по праву
своего узла и рубильнику своего подмодуля: недоступного блока в ответе нет.
Подмодуля у самой ручки нет: путь ``overview`` не входит ни в один префикс
``bpp_*`` (``htqweb/middleware/service_gate.py``).
"""

from __future__ import annotations

from htqweb.http import api_view

from .services import overview as service
from .services.actor import Actor


@api_view(methods=("GET",), module="bpp", level="read")
def overview(request):
    return service.overview(Actor(request))

"""Запись в замороженный раздел «Договоры» — 403 (A6.2, D-S6-4).

Одна точка на все ручки: любой метод, кроме ``GET``/``HEAD``/``OPTIONS``,
под ``/api/contracts/`` замороженной компании отвечает 403
``contracts_frozen`` — до разбора токена и до вьюхи. Пометодные проверки во
вьюхах забылись бы на первой же новой ручке; префикс URL не забудется.
Приём тот же, что у архива компании (``htqweb/tenancy/archive.py``): там
запись закрыта всем, включая суперпользователя, — здесь тоже.

Стоит в ``settings.MIDDLEWARE`` после ``CompanyContextMiddleware`` (нужен
``search_path`` компании — признак лежит в её схеме) и после
``ServiceGateMiddleware``: выключенный у компании модуль ``contracts``
отвечает своим 503 раньше, и признак не читается из схемы, где таблиц
раздела может не быть.

Без компании запроса (голый домен, ``search_path`` = ``public``) признак не
спрашивается: заморозка — свойство компании, а в ``public`` после
``tenancy_bootstrap`` тенантных таблиц нет.
"""

from __future__ import annotations

from django.http import JsonResponse

from apps.contracts.services import freeze

PREFIX = "/api/contracts/"
SAFE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})


def frozen_response() -> JsonResponse:
    return JsonResponse({"detail": freeze.FROZEN_DETAIL, "code": freeze.FROZEN_CODE},
                        status=403)


class ContractsFreezeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (request.method not in SAFE_METHODS
                and request.path.startswith(PREFIX)
                and getattr(request, "company", None) is not None
                and freeze.is_frozen()):
            return frozen_response()
        return self.get_response(request)

"""Архивная компания — только чтение.

Спека: docs/plans/2026-09-25-archive-read-only-spec.md. Одно правило, две
точки применения, и ни одна не справится одна:

- ``CompanyContextMiddleware`` отклоняет ЗАПИСЬ — любой метод вне
  ``SAFE_METHODS`` — до аутентификации. Не знает, кто пришёл, и знать не
  должен: запись в архив закрыта всем, включая суперпользователя. Видит
  каждый путь, в том числе мимо ``api_view`` (django-admin, SSE).
- ``api_view`` отклоняет ЧТЕНИЕ всем, кроме суперпользователя (решение
  заказчика 25.09): только он разбирает токен.

``TOKEN_PATHS`` открыты в обеих точках: без выдачи токена суперпользователь
архив не прочтёт вовсе, а кого пускать, решает сама ручка —
``apps.companies.interface.user_may_enter_company``.

403, а не 404, на запись — намеренно (спека §13 п. 1): суперпользователю,
нажавшему кнопку на открытой перед ним компании, «Компания не найдена»
была бы ложью. Цена — анонимный POST узнаёт, что компания есть и в архиве.
"""

from __future__ import annotations

from django.http import JsonResponse

SAFE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})

TOKEN_PATHS: frozenset[str] = frozenset({
    "/api/users/v1/token/",
    "/api/users/v1/token/refresh/",
})

ARCHIVED_CODE = "company_archived"


def is_archived(company: dict | None) -> bool:
    """Компания запроса (словарь реестра из ``request.company``) — в архиве."""
    return company is not None and not company["is_active"]


def archived_response() -> JsonResponse:
    return JsonResponse(
        {"detail": "Компания в архиве — только чтение", "code": ARCHIVED_CODE},
        status=403,
    )


def not_found_response() -> JsonResponse:
    # Тот же текст, что middleware отдаёт неизвестной метке: для всех, кроме
    # суперпользователя, архив по-прежнему неотличим от «компании нет».
    return JsonResponse({"detail": "Компания не найдена"}, status=404)

"""Архивная компания — только чтение.

Спека: docs/plans/2026-09-25-archive-read-only-spec.md. Одно правило, две
точки применения, и ни одна не справится одна:

- ``CompanyContextMiddleware`` отклоняет ЗАПИСЬ — любой метод вне
  ``SAFE_METHODS`` — до аутентификации. Не знает, кто пришёл, и знать не
  должен: запись в архив закрыта всем, включая суперпользователя. Видит и
  пути мимо ``api_view`` (django-admin, SSE ``approvals/stream``), но не
  все: ``/django-admin/login`` освобождён middleware раньше ветки архива
  (сессия пишется в ``public``, а остальной django-admin на хосте архива
  отвечает 404 — воспользоваться ею там нечем), а Socket.IO мессенджера
  смонтирован в ``htqweb/asgi.py`` мимо Django-middleware вовсе (спека §11).
- ``api_view`` отклоняет ЧТЕНИЕ всем, кроме суперпользователя (решение
  заказчика 25.09): только он разбирает токен. Анонимные ручки
  (``auth=None``) — только у тенантных аппок, см. ``anonymous_blocked``.

``TOKEN_PATHS`` открыты в обеих точках: без выдачи токена суперпользователь
архив не прочтёт вовсе, а кого пускать, решает сама ручка —
``apps.companies.interface.user_may_enter_company``.

403, а не 404, на запись — намеренно (спека §13 п. 1): суперпользователю,
нажавшему кнопку на открытой перед ним компании, «Компания не найдена»
была бы ложью. Цена — анонимный POST узнаёт, что компания есть и в архиве.
"""

from __future__ import annotations

from django.conf import settings
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


def anonymous_blocked(view_module: str) -> bool:
    """Анонимная ручка из этого модуля закрыта на поддомене архива.

    ``True`` только для модулей тенантных аппок — ``apps.<label>.…`` с
    ``<label>`` из ``settings.TENANT_APPS``. Такие ручки (кадровые
    share-ссылки) читают схему компании, а кто пришёл без токена, не
    узнать — значит, и отличить суперпользователя нельзя.

    Анонимные ручки общих аппок (подписанные файлы ``media_files``,
    вложения мессенджера, аватары, записи конференций, публичный ``cms``)
    на архиве открыты (решение по финальному ревью 25.09): они читают
    ``public``, а не схему компании, защищены подписью или своей проверкой
    и те же ссылки отвечают на голом домене и на хосте любой действующей
    компании. Закрыть их на хосте архива значило ничего не защитить, но
    отнять у суперпользователя документы и аватары на экранах архива.

    Считается по имени модуля один раз, при декорировании: ``api_view`` не
    знает, какой аппке принадлежит ручка, а ``fn.__module__`` знает.
    """
    parts = view_module.split(".")
    return (len(parts) >= 2 and parts[0] == "apps"
            and parts[1] in settings.TENANT_APPS)


def archived_response() -> JsonResponse:
    return JsonResponse(
        {"detail": "Компания в архиве — только чтение", "code": ARCHIVED_CODE},
        status=403,
    )


def not_found_response() -> JsonResponse:
    # Тот же текст, что middleware отдаёт неизвестной метке: для всех, кроме
    # суперпользователя, архив по-прежнему неотличим от «компании нет».
    return JsonResponse({"detail": "Компания не найдена"}, status=404)

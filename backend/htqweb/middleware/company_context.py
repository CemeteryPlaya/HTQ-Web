"""Резолв компании запроса и перевод соединения в её схему.

Регистрируется ПЕРЕД ServiceGateMiddleware: тот гасит домены по URL-префиксу
и должен уже знать компанию, чтобы спросить не только глобальный рубильник
(ServiceStatus), но и компанейский (CompanyModule).

Middleware, а не api_view: контекст нужен также /django-admin/, который
через api_view не проходит.

⚠️ WebSocket-пути этим middleware НЕ покрыты. Socket.IO мессенджера
смонтирован в htqweb/asgi.py как `socketio.ASGIApp(sio, other_asgi_app=...,
socketio_path="ws/messenger/socket.io")` и перехватывает такие запросы ДО
передачи в django_asgi_app — то есть до применения settings.MIDDLEWARE
вообще (тот же файл прямо говорит, что ServiceGateMiddleware по той же
причине не покрывает WS-scope). `/ws/sfu/` обслуживается отдельным
Node-контейнером вне Django и Python не касается. Контекст компании для
WS-путей — отдельная, ещё не решённая задача.

Сброс в finally безусловен. CONN_MAX_AGE=0 уже гарантирует, что соединение
не переживёт запрос, но contextvar под ASGI переживает — и утёкшее значение
означало бы чтение чужой схемы следующим запросом в том же процессе.
"""

from __future__ import annotations

from django.http import JsonResponse

from apps.companies.interface import get_company
from htqweb.tenancy.context import reset_company, set_company
from htqweb.tenancy.db import apply_search_path

COMPANY_HEADER = "X-HTQ-Company"

# Пути, которым компания не нужна и которые обязаны отвечать при пустом
# реестре: без них нельзя ни поднять стек с нуля, ни снять метрики.
_EXEMPT_PREFIXES = ("/health", "/metrics", "/static/", "/django-admin/login")


class CompanyContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(_EXEMPT_PREFIXES):
            request.company = None
            return self.get_response(request)

        slug = request.headers.get(COMPANY_HEADER, "").strip().lower()
        if not slug:
            # Компания не указана — запрос обслуживается в public. Это режим
            # общих доменов (users/cms/media) и переходный период до полного
            # перевода фронта на поддомены.
            request.company = None
            return self.get_response(request)

        company = get_company(slug)
        if company is None or not company["is_active"]:
            # 404, а не 403: существование компании — само по себе сведение,
            # которое незачем подтверждать анонимному запросу.
            return JsonResponse({"detail": "Компания не найдена"}, status=404)

        request.company = company
        token = set_company(slug)
        try:
            apply_search_path(slug)
            return self.get_response(request)
        finally:
            reset_company(token)
            apply_search_path(None)

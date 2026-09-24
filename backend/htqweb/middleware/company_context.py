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

Архивная компания (спека docs/plans/2026-09-25-archive-read-only-spec.md)
НЕ отбивается целиком: чтение идёт дальше в её схему, запись и django-admin
отклоняются здесь — правило целиком в htqweb/tenancy/archive.py, вторая его
половина (чтение — только суперпользователю) в htqweb.http.api_view.
"""

from __future__ import annotations

from django.db import connection

from apps.companies.interface import resolve_host_label
from htqweb.tenancy import archive
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

        label = request.headers.get(COMPANY_HEADER, "").strip().lower()
        if not label:
            # Компания не указана — запрос обслуживается в public. Это режим
            # общих доменов (users/cms/media) и страниц голого домена: вход,
            # регистрация, выбор компании, /join/<token>.
            request.company = None
            return self.get_response(request)

        # Метка хоста — это псевдоним ИЛИ слаг (apps.companies.interface.
        # resolve_host_label), а дальше по коду везде идёт слаг: он и имя
        # схемы (co_<slug>), и claim токена, и company_slug в ролях.
        company = resolve_host_label(label)
        if company is None:
            # 404, а не 403: существование компании — само по себе сведение,
            # которое незачем подтверждать анонимному запросу.
            return archive.not_found_response()
        if archive.is_archived(company):
            # Архив — только чтение (htqweb/tenancy/archive.py). Здесь —
            # половина правила, которой не нужно знать, кто пришёл: запись
            # закрыта всем. Чтение пропускается дальше, отсекать
            # не-суперпользователей будет api_view.
            if request.path.startswith("/django-admin/"):
                # Сессии на этом шаге ещё нет (SessionMiddleware ниже по
                # списку) — не узнать, суперпользователь ли пришёл.
                return archive.not_found_response()
            if (request.method not in archive.SAFE_METHODS
                    and request.path not in archive.TOKEN_PATHS):
                return archive.archived_response()

        slug = company["slug"]
        request.company = company
        token = set_company(slug)
        try:
            apply_search_path(slug)
            return self.get_response(request)
        finally:
            reset_company(token)
            # Внешняя транзакция сломана (IntegrityError внутри atomic — в
            # тестах это вся транзакция теста; ATOMIC_REQUESTS у нас нет):
            # до ROLLBACK запрещён любой SQL, и SET подменил бы уже готовый
            # ответ TransactionManagementError'ом. SET этой же транзакции
            # откатится вместе с ней — сбрасывать нечего. Тот же приём, что у
            # автофикстуры conftest.py. Всплыло с блоком L: ручки почты
            # получили заголовок компании, а их тест на 500 от IntegrityError
            # — этот путь.
            if not connection.needs_rollback:
                apply_search_path(None)

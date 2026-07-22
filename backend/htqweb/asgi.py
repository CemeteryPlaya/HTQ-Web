"""ASGI config for htqweb project.

Базовое приложение — обычный Django ASGI (WSGI обслуживает почти весь трафик,
PLAN.md §3). ASGI нужен точечно для двух async-поверхностей, которые приходят
в разных потоках миграции:

  * Socket.IO мессенджера — ``/ws/messenger/`` (Поток A, фаза 8, PLAN.md §6.5);
  * SSE согласований — ``/api/requests/v1/stream`` (Поток B, фаза 5, §6.2).

Каждая монтируется в СВОЮ размеченную якорями секцию ниже, чтобы правки двух
потоков в этом общем файле не пересекались построчно и мердж шёл без конфликта
(PLAN.md §4.1, §8.2). НЕ удаляйте комментарии-якоря ``>>>``/``<<<``.

It exposes the ASGI callable as a module-level variable named ``application``.
See https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "htqweb.settings.dev")

# Базовое Django ASGI-приложение. Доменные секции ниже могут ОБОРАЧИВАТЬ его
# (например, socketio.ASGIApp(sio, other_asgi_app=application, ...)).
django_asgi_app = get_asgi_application()
application = django_asgi_app

# ─────────────────────────────────────────────────────────────────────────
# >>> messenger:socketio  (Поток A · фаза 8 · PLAN.md §6.5)
#     python-socketio поверх `application` — сервер (`sio`, все @sio.event
#     хендлеры, выбор client_manager) целиком в apps/messenger/socket.py;
#     здесь только финальная обёртка ASGIApp вокруг django_asgi_app.
#     Обработчик `connect` (apps/messenger/socket.py) ПЕРВЫМ делом зовёт
#     require_service("messenger") и отклоняет коннект при выключенном
#     сервисе (ServiceGateMiddleware не покрывает WS-scope). Правьте ТОЛЬКО
#     эту секцию.
import socketio

from apps.messenger.socket import sio as messenger_sio

application = socketio.ASGIApp(
    messenger_sio, other_asgi_app=application, socketio_path="ws/messenger/socket.io",
)
# <<< messenger:socketio
# ─────────────────────────────────────────────────────────────────────────
# >>> approvals:sse  (Поток B · фаза 5 · PLAN.md §6.2)
#     SSE /api/requests/v1/stream реализуется обычным async-view Django
#     (StreamingHttpResponse) через apps/approvals/urls.py — обёртка asgi.py,
#     как правило, НЕ нужна. Якорь оставлен для симметрии: если понадобится
#     сырой ASGI-маршрут, монтируйте его здесь поверх `application`. Правьте
#     ТОЛЬКО эту секцию.
# <<< approvals:sse
# ─────────────────────────────────────────────────────────────────────────

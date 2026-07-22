"""Роуты домена messenger под ``/api/messenger/v1/`` (монтируется
автодискавери, см. ``htqweb/urls.py``, ``MessengerConfig.API_PREFIX``).

Порт ``services/messenger/app/api/v1/{rooms,messages,read}.py``
(messenger-core под-задача) — 8 реально достижимых роутов (не 9: см.
``apps/messenger/views.py`` докстринг про ``read.py``-дубликат, поглощённый
в ``mark_message_read``).

Реальные вызовы фронта (frontend/src/features/messenger/api/messengerApi.ts):
``rooms/`` (GET/POST, СО слешем), ``rooms/{id}`` (GET/PATCH, БЕЗ слеша),
``messages/`` (POST, СО слешем), ``messages/room/{id}`` (GET, БЕЗ слеша),
``messages/room/{id}/read/{messageId}`` (POST, БЕЗ слеша). ``.../typing``
фронтом по REST не вызывается (только через Socket.IO ``emit('typing', …)``,
см. ``frontend/src/features/messenger/hooks/useMessengerSocket.ts``) —
регистрируется защитно, по конвенции остальных аппок (оба написания).

``APPEND_SLASH=False`` — каждое написание пути регистрируется явно (как
``apps/hr/urls.py``/``apps/mail/urls.py``). Более специфичные литеральные
роуты (``read/<uuid:...>``, ``typing``) — ДО общего
``messages/room/<int:room_id>`` (список): порядок не критичен для
корректности (регекспы не пересекаются — разное число сегментов), но
соблюдает конвенцию репозитория «специфичное прежде общего».
"""
from django.urls import path

from . import views

urlpatterns = [
    # ── /rooms/ (rooms.py, 4 эндпойнта) ─────────────────────────────────────
    path("rooms/", views.rooms_collection),
    path("rooms", views.rooms_collection),

    path("rooms/<int:room_id>/", views.room_detail),
    path("rooms/<int:room_id>", views.room_detail),

    # ── /messages/* (messages.py, 4 эндпойнта — 4-й, mark_message_read,
    # поглощает read.py::mark_read, см. apps/messenger/views.py) ────────────
    path("messages/", views.send_message),
    path("messages", views.send_message),

    path("messages/room/<int:room_id>/read/<uuid:message_id>/", views.mark_message_read),
    path("messages/room/<int:room_id>/read/<uuid:message_id>", views.mark_message_read),

    path("messages/room/<int:room_id>/typing/", views.publish_typing),
    path("messages/room/<int:room_id>/typing", views.publish_typing),

    path("messages/room/<int:room_id>/", views.list_messages),
    path("messages/room/<int:room_id>", views.list_messages),
]

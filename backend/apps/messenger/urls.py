"""Роуты домена messenger под ``/api/messenger/v1/`` (монтируется
автодискавери, см. ``htqweb/urls.py``, ``MessengerConfig.API_PREFIX``).

Порт ``services/messenger/app/api/v1/{rooms,messages,read}.py``
(messenger-core под-задача) — 8 реально достижимых роутов (не 9: см.
``apps/messenger/views.py`` докстринг про ``read.py``-дубликат, поглощённый
в ``mark_message_read``) + ``{attachments,keys}.py`` (attachments-под-задача,
PLAN.md §6.5) — 5 роутов (attachments 3, keys 2).

Реальные вызовы фронта (frontend/src/features/messenger/api/messengerApi.ts):
``rooms/`` (GET/POST, СО слешем), ``rooms/{id}`` (GET/PATCH, БЕЗ слеша),
``messages/`` (POST, СО слешем), ``messages/room/{id}`` (GET, БЕЗ слеша),
``messages/room/{id}/read/{messageId}`` (POST, БЕЗ слеша),
``attachments/upload/`` (POST, СО слешем), ``keys/`` (POST, СО слешем),
``keys/{userId}`` (GET, БЕЗ слеша). ``.../typing`` фронтом по REST не
вызывается (только через Socket.IO ``emit('typing', …)``, см.
``frontend/src/features/messenger/hooks/useMessengerSocket.ts``) —
регистрируется защитно, по конвенции остальных аппок (оба написания).

``APPEND_SLASH=False`` — каждое написание пути регистрируется явно (как
``apps/hr/urls.py``/``apps/mail/urls.py``). Более специфичные литеральные
роуты (``read/<uuid:...>``, ``typing``, ``attachments/file/<uuid:...>/thumb``)
— ДО более общих (``messages/room/<int:room_id>``,
``attachments/file/<uuid:...>``): порядок не критичен для корректности
(регекспы не пересекаются — разное число сегментов), но соблюдает конвенцию
репозитория «специфичное прежде общего».
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

    # ── /attachments/* (attachments.py, 3 эндпойнта, attachments-под-задача) ─
    path("attachments/upload/", views.upload_attachment),
    path("attachments/upload", views.upload_attachment),

    path("attachments/file/<uuid:attachment_id>/thumb/", views.serve_attachment_thumb),
    path("attachments/file/<uuid:attachment_id>/thumb", views.serve_attachment_thumb),

    path("attachments/file/<uuid:attachment_id>/", views.serve_attachment),
    path("attachments/file/<uuid:attachment_id>", views.serve_attachment),

    # ── /keys/* (keys.py, 2 эндпойнта, attachments-под-задача) ──────────────
    path("keys/", views.upload_keys),
    path("keys", views.upload_keys),

    path("keys/<int:user_id>/", views.get_user_keys),
    path("keys/<int:user_id>", views.get_user_keys),

    # ── /admin/* (admin.py, 3 эндпойнта, require_admin — workers/admin
    # под-задача, PLAN.md §6.5, последняя под-задача messenger) ─────────────
    path("admin/rooms/", views.admin_list_rooms),
    path("admin/rooms", views.admin_list_rooms),

    path("admin/rooms/<int:room_id>/messages/", views.admin_list_room_messages),
    path("admin/rooms/<int:room_id>/messages", views.admin_list_room_messages),

    path("admin/history/archive/", views.admin_trigger_history_archive),
    path("admin/history/archive", views.admin_trigger_history_archive),

    # ── /users/* (users.py, 4 регистрации: me×2 + search×2 — ingest снесён,
    # P1.2 2026-07-22 audit-спека: ChatUserReplica в Django нет, приёмник без
    # цели) ───────────────────────────────────────────────────────────────
    path("users/me/", views.me),
    path("users/me", views.me),

    path("users/search/", views.search_users),
    path("users/search", views.search_users),
]

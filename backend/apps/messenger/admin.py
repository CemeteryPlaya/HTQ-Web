"""Django-админка домена messenger — вся под ServiceGatedAdminMixin (см.
``apps/mail/admin.py`` докстринг для полного объяснения гейта: при
выключенном сервисе ``messenger`` админские экраны должны отдавать
Django-native 403/redirect, а не показывать данные выключенного домена;
проверяется рефлексивно ``apps/core/tests/test_invariants.py`` Test 2).

``RoomParticipant``/``UserKey`` НЕ регистрируются здесь (ни напрямую, ни как
inline) — ``models.CompositePrimaryKey`` модели Django-admin регистрировать
нельзя (``AdminSite.register`` безусловно поднимает ``ImproperlyConfigured``
для любой модели с ``_meta.is_composite_pk``, до какого-либо участия
``ModelAdmin``); см. ``apps/messenger/models.py::RoomParticipant``/``UserKey``
докстринги и прецедент ``apps/hr/admin.py`` (PMODepartment/PMOPosition).
Test 2 этого не требует поимённо — только чтобы у аппки с ≥1 моделью было
≥1 зарегистрированное gated-админ (Room/Message/AuditLog/ChatAttachment
ниже уже покрывают)."""
from django.contrib import admin

from htqweb.admin_gate import ServiceGatedAdminMixin

from .models import AuditLog, ChatAttachment, Message, Room


@admin.register(Room)
class RoomAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "name", "room_type", "is_e2ee", "created_at")
    list_filter = ("room_type", "is_e2ee")
    search_fields = ("name",)
    readonly_fields = ("storage_key", "created_at", "updated_at")


@admin.register(Message)
class MessageAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "room", "sender_id", "is_encrypted", "is_edited", "created_at")
    list_filter = ("is_encrypted", "is_edited")
    search_fields = ("content",)
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(AuditLog)
class AuditLogAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "user_id", "action", "resource_type", "resource_id", "created_at")
    list_filter = ("action", "resource_type")
    search_fields = ("resource_id", "correlation_id")
    readonly_fields = ("created_at",)


@admin.register(ChatAttachment)
class ChatAttachmentAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "room", "message", "filename", "data_type", "uploaded_by", "created_at")
    list_filter = ("data_type",)
    search_fields = ("filename",)
    readonly_fields = ("id", "created_at", "updated_at")

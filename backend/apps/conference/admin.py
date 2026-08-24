"""Django-админка конференций — вся под ServiceGatedAdminMixin.

Гейт обязателен: при выключенном сервисе `conference` админские экраны
домена должны отдавать 503-native, а не показывать данные выключенного
домена. Мета-тест apps/core/tests/test_invariants.py проверяет это
рефлексивно.

Записи и протокол здесь только для чтения. Админка нужна, чтобы посмотреть,
почему встреча не собралась или когда её медиа истечёт, а не чтобы править
журнал: и участники, и реплики — это факты, присланные SFU и распознавателем,
и правка их руками сделала бы историю недостоверной.
"""

from django.contrib import admin

from htqweb.admin_gate import ServiceGatedAdminMixin

from .models import (
    ConferenceEvent,
    ConferenceParticipant,
    ConferenceRecording,
    ConferenceSession,
    ConferenceTranscriptSegment,
)


class ParticipantInline(admin.TabularInline):
    model = ConferenceParticipant
    extra = 0
    can_delete = False
    fields = ("display_name", "user_id", "is_guest", "joined_at", "left_at",
              "joined_offset_ms")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


class RecordingInline(admin.TabularInline):
    model = ConferenceRecording
    extra = 0
    can_delete = False
    fields = ("kind", "storage_path", "size", "duration_sec", "mime",
              "started_offset_ms")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ConferenceSession)
class ConferenceSessionAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "title", "room_id", "created_by_name", "started_at",
                    "duration_sec", "peak_participants", "recording_state",
                    "transcript_state", "expires_at")
    list_filter = ("recording_state", "transcript_state", "started_at")
    search_fields = ("room_id", "title", "created_by_name")
    date_hierarchy = "started_at"
    readonly_fields = ("room_id", "created_by_id", "created_by_name", "started_at",
                       "ended_at", "duration_sec", "peak_participants",
                       "purged_at", "error", "created_at", "updated_at")
    inlines = (ParticipantInline, RecordingInline)

    def has_add_permission(self, request):
        # Встречу заводит SFU по факту звонка. Созданная руками строка не
        # соответствует ничему на диске и только сломает сборку.
        return False


@admin.register(ConferenceTranscriptSegment)
class ConferenceTranscriptSegmentAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "session", "speaker_name", "start_ms", "text")
    list_filter = ("session",)
    search_fields = ("text", "speaker_name")
    readonly_fields = ("session", "participant", "speaker_name", "start_ms",
                       "end_ms", "text", "confidence")

    def has_add_permission(self, request):
        return False


@admin.register(ConferenceEvent)
class ConferenceEventAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "session", "kind", "at_ms", "participant")
    list_filter = ("kind",)
    readonly_fields = ("session", "participant", "kind", "at_ms", "payload",
                       "created_at")

    def has_add_permission(self, request):
        return False

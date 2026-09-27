from django.contrib import admin

from htqweb.admin_gate import ServiceGatedAdminMixin

from .models import ChannelPrefs, Delivery, Notification, TelegramLink


class DeliveryInline(admin.TabularInline):
    model = Delivery
    extra = 0
    readonly_fields = ("channel", "state", "attempts", "last_error", "sent_at")


@admin.register(Notification)
class NotificationAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("created_at", "recipient_id", "company_slug", "event", "title", "is_read")
    list_filter = ("event", "is_read")
    search_fields = ("title",)
    inlines = (DeliveryInline,)


@admin.register(Delivery)
class DeliveryAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("notification", "channel", "state", "attempts", "sent_at")
    list_filter = ("channel", "state")


@admin.register(ChannelPrefs)
class ChannelPrefsAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("user_id", "bell", "email", "telegram")


@admin.register(TelegramLink)
class TelegramLinkAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("user_id", "chat_id", "linked_at")
    exclude = ("link_code",)

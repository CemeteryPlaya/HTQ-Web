from django.contrib import admin

from htqweb.admin_gate import ServiceGatedAdminMixin

from .models import (
    AuditLog,
    Invitation,
    NumberSequence,
    PaymentStage,
    SupplierContact,
    SupplierProspect,
    Tender,
    TenderRequest,
    TenderRequestItem,
    TenderRequestPart,
)


@admin.register(NumberSequence)
class NumberSequenceAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("prefix", "year", "last")
    readonly_fields = ("prefix", "year", "last")


@admin.register(AuditLog)
class AuditLogAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("created_at", "object_type", "object_id", "action", "actor_id")
    list_filter = ("object_type", "action")

    # Журнал «только для записи» пишет только код модуля (services/core/audit):
    # строка, дописанная руками, была бы подделкой с произвольным actor_id.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class _ReadOnly:
    """Заявку правит только сервис (версия, журнал, права автора): правка из
    django-admin обошла бы и замок статуса, и запись в журнал."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class TenderRequestPartInline(_ReadOnly, admin.TabularInline):
    model = TenderRequestPart
    extra = 0
    fields = ("kind", "article_id", "purchase_type", "bpp_number", "bpp_status",
              "excluded_at")


class TenderRequestItemInline(_ReadOnly, admin.TabularInline):
    model = TenderRequestItem
    extra = 0
    fields = ("line_no", "name", "uom_id", "qty", "plan_price", "need_date", "article_id")


@admin.register(TenderRequest)
class TenderRequestAdmin(_ReadOnly, ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("number", "status", "project_id", "author_id", "created_at")
    list_filter = ("status", "purchase_type")
    search_fields = ("number",)
    inlines = (TenderRequestPartInline, TenderRequestItemInline)


# ── тендеры и участники (T2.1, T2.2) ───────────────────────────────────────
# Только чтение: тендер, приглашения и справочники ведут сервисы (версия,
# журнал, права автора). Хэши токенов и секретов устройств не показываются
# вовсе (T-26): поля перечислены явно, без ``token_hash``/``secret_hash``.

class InvitationInline(_ReadOnly, admin.TabularInline):
    model = Invitation
    extra = 0
    fields = ("name", "email", "counterparty_id", "prospect", "status", "sent_at",
              "first_opened_at", "revoked_at", "max_devices")
    readonly_fields = fields


@admin.register(Tender)
class TenderAdmin(_ReadOnly, ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("number", "status", "request", "author_id", "deadline_at", "created_at")
    list_filter = ("status",)
    search_fields = ("number",)
    inlines = (InvitationInline,)


@admin.register(PaymentStage)
class PaymentStageAdmin(_ReadOnly, ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("scheme", "order", "trigger", "pct", "days")


@admin.register(SupplierContact)
class SupplierContactAdmin(_ReadOnly, ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("email", "name", "counterparty_id", "is_primary", "is_active")
    search_fields = ("email", "name")


@admin.register(SupplierProspect)
class SupplierProspectAdmin(_ReadOnly, ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "email", "reg_number", "country_code", "counterparty_id")
    search_fields = ("name", "email", "reg_number")

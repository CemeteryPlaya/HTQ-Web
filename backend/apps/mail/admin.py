"""Django-админка домена mail — вся под ServiceGatedAdminMixin.

Гейт обязателен: при выключенном сервисе `mail` админские экраны домена
должны отдавать 503-native (решение Р5, как и в apps.hr), а не показывать
данные выключенного домена. Мета-тест apps/core/tests/test_invariants.py
(Test 2) проверяет это рефлексивно.
"""
from django.contrib import admin

from htqweb.admin_gate import ServiceGatedAdminMixin

from .models import AuditLog, EmailAccount, OAuthToken


@admin.register(EmailAccount)
class EmailAccountAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "user_id", "type", "provider", "address",
                    "is_default", "is_active", "connected_at")
    list_filter = ("type", "provider", "is_active", "is_default")
    search_fields = ("address",)
    readonly_fields = ("connected_at", "created_at", "updated_at")


@admin.register(OAuthToken)
class OAuthTokenAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "user_id", "provider", "provider_account_id",
                    "is_active", "expires_at")
    list_filter = ("provider", "is_active")
    search_fields = ("provider_account_id",)
    readonly_fields = ("created_at", "updated_at")
    # encrypted_access_token/encrypted_refresh_token остаются видимыми в форме
    # намеренно — это уже AES-256-GCM-шифртекст (apps/mail/services/crypto.py),
    # не plaintext, показывать больше нечего скрывать.


@admin.register(AuditLog)
class AuditLogAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "user_id", "action", "resource_type", "resource_id", "created_at")
    list_filter = ("action", "resource_type")
    search_fields = ("resource_id", "correlation_id")
    readonly_fields = ("created_at",)

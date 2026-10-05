"""Справочники в django-admin. Удаления нет — запись уходит в архив
(``is_active``) и остаётся в старых документах (ТЗ §18)."""

from django.contrib import admin

from htqweb.admin_gate import ServiceGatedAdminMixin

from .models import Article, ArticleGroup, Country, Currency, ExchangeRate, MrpValue, Uom, VatRate


class _NoDeleteAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Country)
class CountryAdmin(_NoDeleteAdmin):
    list_display = ("code", "name", "is_active")


@admin.register(Currency)
class CurrencyAdmin(_NoDeleteAdmin):
    list_display = ("code", "name", "symbol", "is_active")


@admin.register(ExchangeRate)
class ExchangeRateAdmin(_NoDeleteAdmin):
    list_display = ("currency_code", "on_date", "rate", "source")
    list_filter = ("currency_code", "source")


@admin.register(VatRate)
class VatRateAdmin(_NoDeleteAdmin):
    list_display = ("country_code", "rate", "date_from", "date_to")


@admin.register(MrpValue)
class MrpValueAdmin(_NoDeleteAdmin):
    list_display = ("date_from", "value")


@admin.register(Uom)
class UomAdmin(_NoDeleteAdmin):
    list_display = ("code", "short_name", "name", "is_active")


@admin.register(ArticleGroup)
class ArticleGroupAdmin(_NoDeleteAdmin):
    list_display = ("code", "name", "node_key", "is_active")


@admin.register(Article)
class ArticleAdmin(_NoDeleteAdmin):
    list_display = ("code", "name", "group", "is_active")
    list_filter = ("group", "is_active")

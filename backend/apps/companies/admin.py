"""Django-админка мультикомпанийного реестра — вся под ServiceGatedAdminMixin.

Гейт обязателен по тому же образцу, что и в apps.conference.admin: при
выключенном сервисе `companies` админские экраны домена должны отдавать
Django-нативный отказ, а не показывать данные выключенного домена.
Мета-тест apps/core/tests/test_invariants.py проверяет это рефлексивно —
как то, что каждая зарегистрированная ModelAdmin несёт этот миксин, так и
то, что у аппки вообще есть хотя бы одна зарегистрированная админка.

Анти-локаут-исключение (`_ANTI_LOCKOUT_EXEMPT` в test_invariants.py) сюда
НЕ подходит: оно существует только для ServiceStatus — самого рубильника,
потому что, выключив аппку, которая ЕСТЬ рубильник, оператор спрятал бы
переключатель и лишился бы способа вернуть его обратно. Выключение
`companies` прячет реестр компаний, но админка ServiceStatus (аппка core)
остаётся видимой и включаемой обратно — путь восстановления есть, значит
это обычная доменная аппка.
"""

from django.contrib import admin

from htqweb.admin_gate import ServiceGatedAdminMixin

from .models import (
    Company,
    CompanyMembership,
    CompanyModule,
    CompanySchemaVersion,
    CompanyServiceLink,
)


@admin.register(Company)
class CompanyAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "slug", "kind", "status", "parent", "country")
    list_filter = ("kind", "status")
    search_fields = ("name", "slug")
    # slug задаёт имя схемы Postgres (co_<slug>, дефис заменяется на
    # подчёркивание — htqweb.tenancy.context.schema_for). Смена slug в этой
    # форме означала бы переименование уже существующей схемы, а эта форма
    # такого переименования не делает — поэтому поле только для чтения.
    #
    # status — тоже только для чтения, и это правка, а не всегда так было:
    # правка status здесь была ЕДИНСТВЕННЫМ способом заархивировать
    # компанию, но пересборку сводок холдинга (rebuild_holding_views) она не
    # вызывала — вызывающих ровно три (company_create, migrate_companies,
    # tenancy_bootstrap), и правка через админку среди них не значилась.
    # Итог: компания архивируется, трафик мгновенно 404-ится, а её строки
    # остаются в сводках холдинга до следующего migrate_companies — цифры у
    # директоров молча включают архивную компанию. Единственный путь теперь —
    # `manage.py company_archive`/`company_restore` (см. их докстринги),
    # которые меняют статус И пересобирают сводки одной операцией.
    readonly_fields = ("slug", "status")


@admin.register(CompanyServiceLink)
class CompanyServiceLinkAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("provider", "consumer", "created_at")
    list_filter = ("provider", "consumer")
    search_fields = ("provider__name", "consumer__name")


@admin.register(CompanyMembership)
class CompanyMembershipAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("user_id", "company", "is_default", "created_at")
    # user_id — обычный IntegerField, а не ForeignKey (межаппные FK на
    # платформе запрещены), поэтому list_filter по нему бессмыслен, а вот
    # найти членство по конкретному пользователю через поиск — обычная
    # задача оператора.
    list_filter = ("company", "is_default")
    search_fields = ("user_id",)


@admin.register(CompanyModule)
class CompanyModuleAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("company", "app_label", "enabled", "updated_at")
    list_filter = ("company", "app_label", "enabled")
    search_fields = ("app_label",)


@admin.register(CompanySchemaVersion)
class CompanySchemaVersionAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    """Полностью только для чтения.

    Версия схемы компании обновляется прогоном `manage.py migrate_companies`,
    а не руками оператора. Правка её через админку сделала бы таблицу
    лживой — а таблица существует ровно затем, чтобы отставание схемы
    компании от целевой миграции было видно ДО того, как оно проявится
    500-й ошибкой в рантайме, а не после.
    """

    list_display = ("company", "app_label", "applied_migration",
                     "target_migration", "last_run_at")
    list_filter = ("app_label",)
    search_fields = ("company__name", "app_label")
    readonly_fields = ("company", "app_label", "applied_migration",
                        "target_migration", "last_run_at", "last_error")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

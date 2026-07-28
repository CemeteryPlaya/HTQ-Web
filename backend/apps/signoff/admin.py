"""Регистрация домена signoff в django-admin.

Каждый ``ModelAdmin`` подмешивает ``ServiceGatedAdminMixin`` — рефлексивный
мета-тест ``apps/core/tests/test_invariants.py`` (Test 2) роняет сборку, если
появится незагейченный.

Разделение экранов ровно по слоям домена:

* **Маршруты** — настройка, её ведут руками. Этапы и согласующие правятся
  инлайнами прямо в карточке маршрута: разносить связку «маршрут → этап →
  согласующий» по трём отдельным экранам значило бы заставить
  администратора собирать её по кускам, ни разу не видя целиком.
* **Процессы** — исполнение, оно read-only. Править живое согласование
  руками в админке нельзя: переходы обязаны идти через
  ``services/engine.py``, который держит блокировку, ведёт журнал и
  дёргает колбэк предметной аппки. Прямая правка поля ``state`` обошла бы
  всё это и оставила бы согласованный процесс при несогласованном объекте.
"""

from django.contrib import admin

from htqweb.admin_gate import ServiceGatedAdminMixin

from .models import (
    ApprovalEvent,
    ApprovalProcess,
    ApprovalProcessStage,
    ApprovalRoute,
    ApprovalRouteStage,
    ApprovalRouteStageApprover,
    ApprovalTask,
)


# ═══════════════════════════════════════════════════════════════════════
# Маршруты — настройка
# ═══════════════════════════════════════════════════════════════════════

class ApproverInline(admin.TabularInline):
    model = ApprovalRouteStageApprover
    extra = 1
    verbose_name = "Согласующий"
    verbose_name_plural = "Согласующие"


@admin.register(ApprovalRouteStage)
class ApprovalRouteStageAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    """Этап отдельным экраном — ради инлайна согласующих.

    django-admin не умеет вкладывать инлайн в инлайн, поэтому список
    согласующих не помещается в карточку маршрута. Порядок работы:
    завести этапы в маршруте, затем открыть каждый и назначить людей.
    """

    list_display = ("id", "route", "order", "name", "quorum", "approver_count")
    list_filter = ("route", "quorum")
    search_fields = ("name",)
    inlines = [ApproverInline]

    @admin.display(description="Согласующих")
    def approver_count(self, obj) -> int:
        return obj.approvers.count()


class StageInline(admin.TabularInline):
    model = ApprovalRouteStage
    extra = 1
    fields = ("order", "name", "quorum")
    show_change_link = True  # отсюда — в карточку этапа за согласующими
    verbose_name = "Этап"
    verbose_name_plural = "Этапы (одинаковая очередь = параллельно)"


@admin.register(ApprovalRoute)
class ApprovalRouteAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("id", "name", "subject_type", "is_active", "stage_count",
                    "updated_at")
    list_filter = ("subject_type", "is_active")
    search_fields = ("name", "subject_type")
    readonly_fields = ("created_at", "updated_at")
    inlines = [StageInline]

    @admin.display(description="Этапов")
    def stage_count(self, obj) -> int:
        return obj.stages.count()


# ═══════════════════════════════════════════════════════════════════════
# Процессы — исполнение (только чтение)
# ═══════════════════════════════════════════════════════════════════════

class ReadOnlyAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    """Экран наблюдения: смотреть можно, менять — нет.

    Удаление тоже закрыто: журнал согласования — то, чем объясняют принятое
    решение, и стирать его из админки быть не должно.
    """

    def has_add_permission(self, request, obj=None) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


class ProcessStageInline(admin.TabularInline):
    model = ApprovalProcessStage
    extra = 0
    fields = ("order", "name", "quorum", "state", "decided_at")
    readonly_fields = fields
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None) -> bool:
        return False


class EventInline(admin.TabularInline):
    model = ApprovalEvent
    extra = 0
    fields = ("created_at", "kind", "actor_id", "payload")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None) -> bool:
        return False


@admin.register(ApprovalProcess)
class ApprovalProcessAdmin(ReadOnlyAdmin):
    list_display = ("id", "subject_type", "subject_id", "state",
                    "current_order", "initiator_id", "created_at", "finished_at")
    list_filter = ("state", "subject_type")
    search_fields = ("subject_type", "subject_id")
    inlines = [ProcessStageInline, EventInline]


class TaskInline(admin.TabularInline):
    model = ApprovalTask
    extra = 0
    fields = ("user_id", "state", "comment", "acted_at")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None) -> bool:
        return False


@admin.register(ApprovalProcessStage)
class ApprovalProcessStageAdmin(ReadOnlyAdmin):
    list_display = ("id", "process", "order", "name", "quorum", "state",
                    "decided_at")
    list_filter = ("state", "quorum")
    inlines = [TaskInline]


@admin.register(ApprovalTask)
class ApprovalTaskAdmin(ReadOnlyAdmin):
    list_display = ("id", "stage", "user_id", "state", "acted_at")
    list_filter = ("state",)
    search_fields = ("user_id",)


@admin.register(ApprovalEvent)
class ApprovalEventAdmin(ReadOnlyAdmin):
    list_display = ("id", "process", "kind", "actor_id", "created_at")
    list_filter = ("kind",)

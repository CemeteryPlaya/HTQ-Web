from django.contrib import admin

from htqweb.admin_gate import ServiceGatedAdminMixin

from .models import Project, ProjectMember


class ProjectMemberInline(admin.TabularInline):
    model = ProjectMember
    extra = 0


@admin.register(Project)
class ProjectAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("code", "name", "kind", "status", "country_code", "manager_user_id")
    list_filter = ("kind", "status")
    search_fields = ("code", "name")
    inlines = (ProjectMemberInline,)


@admin.register(ProjectMember)
class ProjectMemberAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("project", "user_id", "added_by", "added_at")

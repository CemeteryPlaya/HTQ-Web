"""Маршруты проектной структуры (docs/plans/2026-10-06-project-structure-spec.md §4)
под /api/project/v1/ — подключаются из ``urls.py``."""

from django.urls import path

from . import views_structure as views

urlpatterns = [
    path("project-roles", views.project_roles),
    path("project-roles/", views.project_roles),
    path("project-roles/<int:role_id>", views.project_role),
    path("project-roles/<int:role_id>/", views.project_role),
    path("projects/<str:project_id>/structure", views.project_structure),
    path("projects/<str:project_id>/structure/", views.project_structure),
    path("projects/<str:project_id>/slots", views.project_slots),
    path("projects/<str:project_id>/slots/", views.project_slots),
    path("slots/<str:slot_id>", views.slot_item),
    path("slots/<str:slot_id>/", views.slot_item),
    path("slots/<str:slot_id>/assignments", views.slot_assignments),
    path("slots/<str:slot_id>/assignments/", views.slot_assignments),
    path("assignments/<str:assignment_id>", views.assignment_item),
    path("assignments/<str:assignment_id>/", views.assignment_item),
    path("employees", views.employees),
    path("employees/", views.employees),
]

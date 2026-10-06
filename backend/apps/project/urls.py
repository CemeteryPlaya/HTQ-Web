"""Маршруты /api/project/v1/."""

from django.urls import include, path

from . import views

urlpatterns = [
    path("user-names", views.user_names),
    path("user-names/", views.user_names),
    path("projects", views.project_collection),
    path("projects/", views.project_collection),
    path("projects/<str:project_id>", views.project_item),
    path("projects/<str:project_id>/", views.project_item),
    path("projects/<str:project_id>/members", views.project_members),
    path("projects/<str:project_id>/members/", views.project_members),
    path("projects/<str:project_id>/members/<int:user_id>", views.project_member),
    path("projects/<str:project_id>/members/<int:user_id>/", views.project_member),
    # Проектная структура — своя пара urls_structure.py ↔ views_structure.py
    # (сторож test_gate.py проверяет модуль маршрутов вместе с его вьюхами).
    path("", include(f"{__package__}.urls_structure")),
]

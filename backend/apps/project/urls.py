"""Маршруты /api/project/v1/."""

from django.urls import path

from . import views

urlpatterns = [
    path("projects", views.project_collection),
    path("projects/", views.project_collection),
    path("projects/<str:project_id>", views.project_item),
    path("projects/<str:project_id>/", views.project_item),
    path("projects/<str:project_id>/members", views.project_members),
    path("projects/<str:project_id>/members/", views.project_members),
    path("projects/<str:project_id>/members/<int:user_id>", views.project_member),
    path("projects/<str:project_id>/members/<int:user_id>/", views.project_member),
]

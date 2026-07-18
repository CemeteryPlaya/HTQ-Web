from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health),
    path("health/ready/", views.ready),
    path("api/core/v1/services/", views.services_status),
]

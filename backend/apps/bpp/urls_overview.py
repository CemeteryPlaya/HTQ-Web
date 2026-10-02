"""Маршруты «Обзора» модуля — ``/api/bpp/v1/overview``.

Подключается сам: ``bpp/urls.py`` собирает все ``urls_*.py`` подмодулей.
``APPEND_SLASH = False``: путь в обоих написаниях.
"""

from django.urls import path

from . import views_overview as views

urlpatterns = [
    path("overview", views.overview),
    path("overview/", views.overview),
]

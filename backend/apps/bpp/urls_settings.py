"""Маршруты «Параметры модуля» — ``/api/bpp/v1/settings…``.

Подключается сам: ``bpp/urls.py`` собирает все ``urls_*.py`` подмодулей.
``APPEND_SLASH = False``: путь в обоих написаниях, как у остальных
``urls_*.py`` модуля.
"""

from django.urls import path

from . import views_settings as views

urlpatterns = [
    path("settings", views.settings_list),
    path("settings/", views.settings_list),
    path("settings/<str:key>", views.setting_patch),
    path("settings/<str:key>/", views.setting_patch),
]

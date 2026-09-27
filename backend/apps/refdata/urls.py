"""Маршруты /api/refdata/v1/.

Явный список, а не цикл: сторож гейта (``apps/access/tests/test_gate.py``)
читает маршрут как ``views.<имя>`` и выражение-переменную не засчитывает.
Удаления нет — у записи только PATCH (архив через ``is_active``).
"""

from django.urls import path

from . import views

urlpatterns = [
    path("countries", views.countries),
    path("countries/", views.countries),
    path("countries/<str:obj_id>", views.country_item),
    path("countries/<str:obj_id>/", views.country_item),
    path("currencies", views.currencies),
    path("currencies/", views.currencies),
    path("currencies/<str:obj_id>", views.currency_item),
    path("currencies/<str:obj_id>/", views.currency_item),
    path("uoms", views.uoms),
    path("uoms/", views.uoms),
    path("uoms/<str:obj_id>", views.uom_item),
    path("uoms/<str:obj_id>/", views.uom_item),
    path("article-groups", views.article_groups),
    path("article-groups/", views.article_groups),
    path("article-groups/<str:obj_id>", views.article_group_item),
    path("article-groups/<str:obj_id>/", views.article_group_item),
    path("articles", views.articles),
    path("articles/", views.articles),
    path("articles/<str:obj_id>", views.article_item),
    path("articles/<str:obj_id>/", views.article_item),
    path("rates", views.rates),
    path("rates/", views.rates),
    path("vat", views.vat),
    path("vat/", views.vat),
    path("mrp", views.mrp),
    path("mrp/", views.mrp),
]

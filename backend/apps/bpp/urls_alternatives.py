"""Маршруты альтернативных предложений ``/api/bpp/v1/alternatives/…`` (A5.1, задачи 2 и 4) —
подмодуль ``bpp_alternatives`` (рубильник по префиксу
``/api/bpp/v1/alternatives``).

``APPEND_SLASH = False``: каждый путь — в обоих написаниях. Строки явные:
сторож прав (``test_gate.py``) читает ``path(…, views.<имя>)``. Ключи в
адресе — ``str``: неверный UUID вьюха превращает в 404 (``uuid_or_404``).
"""

from django.urls import path

from . import views_alternatives as views

O = "alternatives/offers/<str:offer_id>"
S = "alternatives/sources/<str:source_type>/<str:source_id>"

urlpatterns = [
    path("alternatives/feed", views.feed),
    path("alternatives/feed/", views.feed),
    path("alternatives/offers", views.offers_collection),
    path("alternatives/offers/", views.offers_collection),
    path(O, views.offer_detail),
    path(f"{O}/", views.offer_detail),
    path(f"{O}/submit", views.offer_submit),
    path(f"{O}/submit/", views.offer_submit),
    path(f"{O}/withdraw", views.offer_withdraw),
    path(f"{O}/withdraw/", views.offer_withdraw),
    path(f"{S}/limit", views.source_limit),
    path(f"{S}/limit/", views.source_limit),
    path(f"{S}/comparison", views.source_comparison),
    path(f"{S}/comparison/", views.source_comparison),
]

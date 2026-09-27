"""Маршруты плана закупок ``/api/bpp/v1/plan…`` — подмодуль ``bpp_requests``.

``APPEND_SLASH = False``: каждый путь — в обоих написаниях. Строки явные:
сторож прав (``test_gate.py``) читает ``path(…, views.<имя>)``.
"""

from django.urls import path

from . import views_plan as views

urlpatterns = [
    path("plan", views.plan_list),
    path("plan/", views.plan_list),
    path("plan/validate", views.plan_validate),
    path("plan/validate/", views.plan_validate),
    path("plan/reassign", views.plan_reassign),
    path("plan/reassign/", views.plan_reassign),
]

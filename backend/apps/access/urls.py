"""Маршруты ``/api/access/v1/*`` (контракт — спека стадии 2, §4).

Монтируются автоматически по ``AccessConfig.API_PREFIX`` — ``htqweb/urls.py``
не правится.

``APPEND_SLASH = False``: Django сам не редиректит ``/foo`` → ``/foo/``, и
такой редирект на части клиентов теряет заголовок ``Authorization``. Поэтому
каждый путь зарегистрирован в обоих написаниях — со слэшем и без.
"""

from django.urls import path

from . import views

urlpatterns = [
    path("roles", views.RoleCollectionView.as_view()),
    path("roles/", views.RoleCollectionView.as_view()),
]

"""Маршруты ``/api/access/v1/*`` (контракт — спека стадии 2, §4).

Монтируются автоматически по ``AccessConfig.API_PREFIX`` — ``htqweb/urls.py``
не правится.

``APPEND_SLASH = False``: Django сам не редиректит ``/foo`` → ``/foo/``, и
такой редирект на части клиентов теряет заголовок ``Authorization``. Поэтому
каждый путь зарегистрирован в обоих написаниях — со слэшем и без.

Вложенные пути (``roles/<id>/permissions``) стоят ВЫШЕ одиночных: шаблоны
перебираются сверху вниз, и хотя эти два не пересекаются (разное число
сегментов), более специфичный путь выше — порядок, который не сломается при
добавлении соседних вложенных маршрутов.
"""

from django.urls import path

from . import views

urlpatterns = [
    # ── Права текущего пользователя ──
    path("me", views.MeView.as_view()),
    path("me/", views.MeView.as_view()),

    # ── Реестр функций ──
    path("functions", views.FunctionsView.as_view()),
    path("functions/", views.FunctionsView.as_view()),

    # ── Каталог ролей ──
    path("roles/<int:role_id>/holders", views.RoleHoldersView.as_view()),
    path("roles/<int:role_id>/holders/", views.RoleHoldersView.as_view()),
    path("roles/<int:role_id>/copy", views.RoleCopyView.as_view()),
    path("roles/<int:role_id>/copy/", views.RoleCopyView.as_view()),
    path("roles/<int:role_id>/permissions", views.RolePermissionsView.as_view()),
    path("roles/<int:role_id>/permissions/", views.RolePermissionsView.as_view()),
    path("roles/<int:role_id>", views.RoleItemView.as_view()),
    path("roles/<int:role_id>/", views.RoleItemView.as_view()),
    path("roles", views.RoleCollectionView.as_view()),
    path("roles/", views.RoleCollectionView.as_view()),

    # ── Роли должности ──
    path("positions/<int:position_id>/roles", views.PositionRolesView.as_view()),
    path("positions/<int:position_id>/roles/", views.PositionRolesView.as_view()),

    # ── Личные назначения ──
    path("assignments/<int:user_id>", views.UserAssignmentsView.as_view()),
    path("assignments/<int:user_id>/", views.UserAssignmentsView.as_view()),
]

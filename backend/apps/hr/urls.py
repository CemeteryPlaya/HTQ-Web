"""Роуты домена hr под ``/api/hr/v1/`` (монтируется автодискавери по
``HrConfig.API_PREFIX``, см. htqweb/urls.py).

``APPEND_SLASH=False`` — Django сам не редиректит на вариант со слешем, а
307-редирект терял бы заголовок Authorization. Поэтому каждое написание пути
регистрируется явно, ровно как в apps/cms/urls.py.

Реальные вызовы фронта (frontend/src/api/hr.ts, frontend/src/pages/hr/*):
``departments/`` (list, create) и ``departments/{id}/`` (update, delete) —
все СО слешем; ``positions/``, ``positions/{id}/``, ``positions/levels/``,
``positions/permissions-catalog/`` — тоже со слешем; ``positions/{id}/weight``,
``positions/{id}/move``, ``positions/rebalance`` — БЕЗ слеша (ровно как в
роутере исходника). Варианты без явного использования во фронте
регистрируются защитно, по конвенции остальных аппок.

Порядок positions/* важен буквально: литеральные сегменты (``levels/``,
``permissions-catalog/``, ``rebalance``) объявлены ДО ``positions/<int:id>/``
— хотя конвертер ``int`` и так не матчит слова, порядок сохраняем для
ясности и на случай будущей смены конвертера (ровно как в роутере исходника:
"literal-segment routes MUST precede /{id}/").
"""
from django.urls import path

from . import views

urlpatterns = [
    path("departments/", views.departments_collection),
    path("departments", views.departments_collection),

    path("departments/tree", views.department_tree),
    path("departments/tree/", views.department_tree),

    path("departments/<int:department_id>/children", views.department_children),
    path("departments/<int:department_id>/children/", views.department_children),

    path("departments/<int:department_id>/employees", views.department_employees),
    path("departments/<int:department_id>/employees/", views.department_employees),

    path("departments/<int:department_id>/", views.department_detail),
    path("departments/<int:department_id>", views.department_detail),

    # ── positions ─────────────────────────────────────────────────────────
    path("positions/", views.positions_collection),
    path("positions", views.positions_collection),

    path("positions/levels/", views.level_thresholds_collection),
    path("positions/levels", views.level_thresholds_collection),

    path("positions/levels/<int:level_number>", views.level_threshold_detail),
    path("positions/levels/<int:level_number>/", views.level_threshold_detail),

    path("positions/permissions-catalog/", views.get_permissions_catalog),
    path("positions/permissions-catalog", views.get_permissions_catalog),

    path("positions/rebalance", views.rebalance_positions),
    path("positions/rebalance/", views.rebalance_positions),

    path("positions/<int:id>/weight", views.update_position_weight),
    path("positions/<int:id>/weight/", views.update_position_weight),

    path("positions/<int:id>/move", views.move_position),
    path("positions/<int:id>/move/", views.move_position),

    path("positions/<int:id>/", views.position_detail),
    path("positions/<int:id>", views.position_detail),
]

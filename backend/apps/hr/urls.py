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

``vacancies/`` (list GET/create POST), ``vacancies/{id}/`` (PATCH/DELETE) —
СО слешем (frontend/src/api/hr.ts); фронт шлёт PATCH — регистрируем и PUT, и
PATCH аддитивно, как и везде. ``applications/`` (list GET/create POST),
``applications/{id}/`` (PATCH/DELETE) — тоже со слешем.

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

    # ── employees ─────────────────────────────────────────────────────────
    # Литеральные роуты (hr-level/, me/) — ДО /<int:id>/, ровно как в
    # роутере исходника (users/ тоже был бы здесь, но эндпойнт отложен —
    # см. tests/test_employees_api.py растяжку).
    path("employees/hr-level/", views.employee_hr_level),
    path("employees/hr-level", views.employee_hr_level),

    path("employees/me/", views.my_employee),
    path("employees/me", views.my_employee),

    path("employees/", views.employees_collection),
    path("employees", views.employees_collection),

    path("employees/<int:id>/transfer", views.transfer_employee),
    path("employees/<int:id>/transfer/", views.transfer_employee),

    path("employees/<int:id>/history", views.employee_history),
    path("employees/<int:id>/history/", views.employee_history),

    path("employees/<int:id>/", views.employee_detail),
    path("employees/<int:id>", views.employee_detail),

    # ── org ───────────────────────────────────────────────────────────────
    # Литеральные сегменты (``tree``, ``subordination-matrix``, ``relations``,
    # ``settings/deletion-strategy``) — порядок роутера исходника; конфликтов
    # с ``<int:relation_id>`` нет (int-конвертер слова не матчит), но порядок
    # сохраняем для ясности, как и в departments/positions.
    path("org/tree", views.org_tree),
    path("org/tree/", views.org_tree),

    path("org/subordination-matrix", views.org_subordination_matrix),
    path("org/subordination-matrix/", views.org_subordination_matrix),

    path("org/relations", views.add_reporting_relation),
    path("org/relations/", views.add_reporting_relation),

    path("org/relations/<int:relation_id>", views.remove_reporting_relation),
    path("org/relations/<int:relation_id>/", views.remove_reporting_relation),

    path("org/settings/deletion-strategy", views.org_deletion_strategy),
    path("org/settings/deletion-strategy/", views.org_deletion_strategy),

    # ── vacancies ─────────────────────────────────────────────────────────
    path("vacancies/", views.vacancies_collection),
    path("vacancies", views.vacancies_collection),

    path("vacancies/<int:id>/applications", views.vacancy_applications),
    path("vacancies/<int:id>/applications/", views.vacancy_applications),

    path("vacancies/<int:id>/", views.vacancy_detail),
    path("vacancies/<int:id>", views.vacancy_detail),

    # ── applications ──────────────────────────────────────────────────────
    # Литеральный ``archive/`` — ДО ``/<int:id>/`` (ровно как в роутере
    # исходника: комментарий там явно объясняет, что иначе FastAPI попытался
    # бы распарсить "archive" как int и отдал 422).
    path("applications/archive/", views.applications_archive),
    path("applications/archive", views.applications_archive),

    path("applications/", views.applications_collection),
    path("applications", views.applications_collection),

    path("applications/<int:id>/status", views.change_application_status),
    path("applications/<int:id>/status/", views.change_application_status),

    path("applications/<int:id>/", views.application_detail),
    path("applications/<int:id>", views.application_detail),
]

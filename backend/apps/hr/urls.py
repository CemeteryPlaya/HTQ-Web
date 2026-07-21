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

    path("employees/<int:id>/documents", views.employee_documents),
    path("employees/<int:id>/documents/", views.employee_documents),

    # ── calendar (employee_calendar_router исходника, prefix "/employees") ──
    # Литеральные ``calendar-template``/``shift`` — независимые последние
    # сегменты, не конфликтуют с ``calendar``/``calendar/<str:day>`` (разная
    # длина пути). ``calendar/<str:day>`` — ДО ``calendar-template``/``shift``
    # не требуется (разные литералы), но объявлен после голого ``calendar``
    # для читаемости (главное — не после ``employees/<int:id>/``).
    path("employees/<int:employee_id>/calendar-template", views.employee_calendar_template),
    path("employees/<int:employee_id>/calendar-template/", views.employee_calendar_template),

    path("employees/<int:employee_id>/shift", views.employee_shift_detail),
    path("employees/<int:employee_id>/shift/", views.employee_shift_detail),

    path("employees/<int:employee_id>/calendar/<str:day>", views.employee_day_override_detail),
    path("employees/<int:employee_id>/calendar/<str:day>/", views.employee_day_override_detail),

    path("employees/<int:employee_id>/calendar", views.employee_calendar),
    path("employees/<int:employee_id>/calendar/", views.employee_calendar),

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

    # ── time-tracking ─────────────────────────────────────────────────────
    # Литеральные ``entries/`` и ``reports/{daily,weekly,monthly}`` — порядок
    # роутера исходника (не критично для int-конвертера, но сохраняем для
    # ясности, как и везде в этой аппке).
    path("time-tracking/", views.time_tracking_root),
    path("time-tracking", views.time_tracking_root),

    path("time-tracking/entries/", views.time_entries_collection),
    path("time-tracking/entries", views.time_entries_collection),

    path("time-tracking/entries/<int:id>/", views.time_entry_detail),
    path("time-tracking/entries/<int:id>", views.time_entry_detail),

    path("time-tracking/reports/daily", views.time_daily_report),
    path("time-tracking/reports/daily/", views.time_daily_report),

    path("time-tracking/reports/weekly", views.time_weekly_report),
    path("time-tracking/reports/weekly/", views.time_weekly_report),

    path("time-tracking/reports/monthly", views.time_monthly_report),
    path("time-tracking/reports/monthly/", views.time_monthly_report),

    # ── staffing ──────────────────────────────────────────────────────────
    # Литеральные ``occupancy``/``summary`` — ДО ``<int:line_id>`` (порядок
    # роутера исходника).
    path("staffing/occupancy", views.staffing_occupancy),
    path("staffing/occupancy/", views.staffing_occupancy),

    path("staffing/summary", views.staffing_summary),
    path("staffing/summary/", views.staffing_summary),

    path("staffing/", views.staffing_lines_collection),
    path("staffing", views.staffing_lines_collection),

    path("staffing/<int:line_id>", views.staffing_line_detail),
    path("staffing/<int:line_id>/", views.staffing_line_detail),

    # ── personnel-history ────────────────────────────────────────────────
    path("personnel-history/", views.personnel_history_collection),
    path("personnel-history", views.personnel_history_collection),

    path("personnel-history/<int:id>/", views.personnel_history_detail),
    path("personnel-history/<int:id>", views.personnel_history_detail),

    # ── calendar ──────────────────────────────────────────────────────────
    # Порт services/hr/app/api/v1/calendar.py (router prefix "/calendar",
    # 14 эндпойнтов). Литеральные сегменты (``templates``, ``working-days``,
    # ``import``, ``shift-patterns``) объявлены ДО ``<str:day>`` — решение
    # брифа: путь-параметр ``day`` использует ПРОСТОЙ строковый конвертер
    # (Django не имеет встроенного date-конвертера), который матчит ЛЮБОЙ
    # непустой сегмент без слеша — включая слова "templates"/"import"/etc,
    # поэтому порядок объявления здесь КРИТИЧЕН (не просто ради ясности, как
    # в остальных блоках этого файла): будь ``<str:day>`` объявлен раньше,
    # он перехватил бы "templates"/"working-days"/"import"/"shift-patterns".
    path("calendar/templates/", views.calendar_templates_collection),
    path("calendar/templates", views.calendar_templates_collection),

    path("calendar/templates/<int:template_id>/default", views.calendar_template_set_default),
    path("calendar/templates/<int:template_id>/default/", views.calendar_template_set_default),

    path("calendar/templates/<int:template_id>/", views.calendar_template_detail),
    path("calendar/templates/<int:template_id>", views.calendar_template_detail),

    path("calendar/working-days", views.calendar_working_days),
    path("calendar/working-days/", views.calendar_working_days),

    path("calendar/import", views.calendar_import_year),
    path("calendar/import/", views.calendar_import_year),

    path("calendar/shift-patterns/", views.shift_patterns_collection),
    path("calendar/shift-patterns", views.shift_patterns_collection),

    path("calendar/shift-patterns/<int:pattern_id>/", views.shift_pattern_detail),
    path("calendar/shift-patterns/<int:pattern_id>", views.shift_pattern_detail),

    # GET /calendar/ (год целиком) — bare "" под prefix "/calendar" в исходнике.
    path("calendar/", views.calendar_year),
    path("calendar", views.calendar_year),

    # Generic <str:day> — ПОСЛЕДНИЙ (см. комментарий выше).
    path("calendar/<str:day>/", views.calendar_day_override_detail),
    path("calendar/<str:day>", views.calendar_day_override_detail),

    # ── documents ─────────────────────────────────────────────────────────
    # Порт services/hr/app/api/v1/documents.py (4 эндпойнта, hr_document).
    path("documents/", views.documents_collection),
    path("documents", views.documents_collection),

    path("documents/<int:id>/", views.document_detail),
    path("documents/<int:id>", views.document_detail),

    # ── mongo-documents ──────────────────────────────────────────────────
    # Порт services/hr/app/api/v1/mongo_documents.py (5 эндпойнтов,
    # ex-Mongo -> EmployeeDocumentBlob JSONB, решение D6). ``<str:doc_id>``
    # (не ``<int:...>``) — вьюха сама парсит id и отдаёт 400 "Invalid document
    # ID format" на не-числовой ввод (тот же смысл, что ObjectId-парсинг
    # исходника), а не молчаливый 404 от резолвера.
    path("mongo-documents/", views.mongo_documents_collection),
    path("mongo-documents", views.mongo_documents_collection),

    path("mongo-documents/<str:doc_id>/", views.mongo_document_detail),
    path("mongo-documents/<str:doc_id>", views.mongo_document_detail),
]

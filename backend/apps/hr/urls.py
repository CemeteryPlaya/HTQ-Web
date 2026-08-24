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

    path("positions/levels/<int:level_number>/next-weight", views.next_weight_for_level),
    path("positions/levels/<int:level_number>/next-weight/", views.next_weight_for_level),

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

    path("employees/me/pmos", views.my_pmos),
    path("employees/me/pmos/", views.my_pmos),

    path("employees/me/card", views.my_employee_card),
    path("employees/me/card/", views.my_employee_card),

    path("employees/users/", views.employees_users_collection),
    path("employees/users", views.employees_users_collection),

    path("employees/", views.employees_collection),
    path("employees", views.employees_collection),

    path("employees/<int:id>/transfer", views.transfer_employee),
    path("employees/<int:id>/transfer/", views.transfer_employee),

    path("employees/<int:id>/history", views.employee_history),
    path("employees/<int:id>/history/", views.employee_history),

    path("employees/<int:id>/documents", views.employee_documents),
    path("employees/<int:id>/documents/", views.employee_documents),

    path("employees/<int:id>/pmos", views.employee_pmos),
    path("employees/<int:id>/pmos/", views.employee_pmos),

    path("employees/<int:id>/card", views.employee_card),
    path("employees/<int:id>/card/", views.employee_card),

    # ── employee_card — порт services/hr/app/api/v1/employee_card.py (роутер
    # исходника отдельный от employees.py, но тоже под prefix "/employees") ─
    path("employees/<int:employee_id>/card/t2", views.card_t2_detail),
    path("employees/<int:employee_id>/card/t2/", views.card_t2_detail),

    path("employees/<int:employee_id>/card/groups", views.card_groups_detail),
    path("employees/<int:employee_id>/card/groups/", views.card_groups_detail),

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

    # ``superior`` — литерал, поэтому СТРОГО до <int:relation_id>: int-конвертер
    # слово не матчит, но порядок сохраняем как и везде в этом файле.
    path("org/relations/superior", views.org_relation_superior),
    path("org/relations/superior/", views.org_relation_superior),

    path("org/relations/<int:relation_id>", views.org_relation_detail),
    path("org/relations/<int:relation_id>/", views.org_relation_detail),

    # ── org/employee-relations, org/departments/{id}/manager — не порт,
    # ручная правка руководителей/подчинённых на уровне сотрудников. Тот же
    # порядок: литералы (``employee-relations``) до ``<int:...>``.
    path("org/employee-relations", views.org_employee_relations_collection),
    path("org/employee-relations/", views.org_employee_relations_collection),

    path("org/employee-relations/superior", views.org_employee_relation_superior),
    path("org/employee-relations/superior/", views.org_employee_relation_superior),

    path("org/employee-relations/<int:relation_id>", views.org_employee_relation_detail),
    path("org/employee-relations/<int:relation_id>/", views.org_employee_relation_detail),

    path("org/departments/<int:department_id>/manager", views.org_department_manager),
    path("org/departments/<int:department_id>/manager/", views.org_department_manager),

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

    # ── mongo-documents: маршруты сняты ──────────────────────────────────
    # Пять эндпойнтов над ex-Mongo коллекцией (решение D6) удалены вместе с
    # вьюхами и схемами — см. комментарий в views.py. Модель
    # EmployeeDocumentBlob осталась (данные cutover'а + django-admin).

    # ── pmo ───────────────────────────────────────────────────────────────
    # Порт services/hr/app/api/v1/pmo.py (10 эндпойнтов). Литеральный
    # ``members``/``org-chart`` — ДО ``<int:id>/`` (порядок роутера
    # исходника, как и везде в этой аппке).
    path("pmo/", views.pmo_collection),
    path("pmo", views.pmo_collection),

    path("pmo/<int:id>/members", views.pmo_members_collection),
    path("pmo/<int:id>/members/", views.pmo_members_collection),

    path("pmo/<int:id>/members/<int:member_id>", views.pmo_member_detail),
    path("pmo/<int:id>/members/<int:member_id>/", views.pmo_member_detail),

    path("pmo/<int:id>/org-chart", views.pmo_org_chart),
    path("pmo/<int:id>/org-chart/", views.pmo_org_chart),

    path("pmo/<int:id>/", views.pmo_detail),
    path("pmo/<int:id>", views.pmo_detail),

    # ── share-links ───────────────────────────────────────────────────────
    # Порт services/hr/app/api/v1/share_links.py (4 эндпойнта). Литеральный
    # ``{id}/audit`` — ДО голого ``<uuid:link_id>`` detail-роута (порядок
    # роутера исходника, как и везде в этой аппке).
    path("share-links/", views.share_links_collection),
    path("share-links", views.share_links_collection),

    path("share-links/<uuid:link_id>/audit", views.share_link_audit),
    path("share-links/<uuid:link_id>/audit/", views.share_link_audit),

    path("share-links/<uuid:link_id>", views.share_link_detail),
    path("share-links/<uuid:link_id>/", views.share_link_detail),

    # ── public (БЕЗ JWT) — порт services/hr/app/api/public/{org,employee}.py ──
    # ``<str:token>`` — raw token (secrets.token_urlsafe), не uuid/int.
    path("public/org/<str:token>", views.public_org_view),
    path("public/org/<str:token>/", views.public_org_view),

    path("public/employee/<str:token>", views.public_employee_view),
    path("public/employee/<str:token>/", views.public_employee_view),

    # ── department-files — порт services/hr/app/api/v1/department_files.py
    # (7 эндпойнтов). Литеральный ``department-files/search/`` — ДО
    # ``department-files/<int:file_id>/`` (порядок роутера исходника).
    path("department-folders/", views.department_folders_list),
    path("department-folders", views.department_folders_list),

    path("department-file-folders/", views.department_file_folders_collection),
    path("department-file-folders", views.department_file_folders_collection),

    path("department-files/search/", views.department_files_search),
    path("department-files/search", views.department_files_search),

    path("department-files/", views.department_files_collection),
    path("department-files", views.department_files_collection),

    path("department-files/<int:file_id>/", views.department_file_detail),
    path("department-files/<int:file_id>", views.department_file_detail),

    # ── audit (логи) — порт services/hr/app/api/v1/audit.py. Роутер
    # исходника смонтирован под prefix="/logs" (комментарий исходника:
    # "Mounted at `/logs` to match the frontend (HRLogs.tsx)").
    path("logs/", views.audit_logs),
    path("logs", views.audit_logs),

    # ── internal/supervisor (S2S, БЕЗ JWT) — снесён P1.3 (2026-07-22 audit
    # spec): S2S-эндпойнт вызывался другим FastAPI-сервисом (requests);
    # теперь все домены — один процесс, потребитель (apps.approvals)
    # резолвит руководителя через apps.hr.interface напрямую
    # (assignee_resolver._supervisor_of), без HTTP. Живых потребителей у
    # роута не было (grep по backend+frontend перед сносом — пусто).
]

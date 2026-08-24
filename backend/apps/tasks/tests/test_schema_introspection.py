"""Schema-introspection tests for the ``tasks`` app.

Two invariants from PLAN.md §3 that only a live-DB check can hold:

* **"не терять индексы"** — phase 1 silently dropped 11 indexes and only
  review caught it. Every ``index=True`` in the SQLAlchemy source is listed
  below and asserted to exist as a real Postgres index.
* **``db_default=``** — a column with an ORM-side ``default=`` but no DB
  DEFAULT breaks any INSERT that bypasses the ORM (a data migration, the
  phase-10 ETL, a psql fix-up). Asserted against
  ``information_schema.columns.column_default``.
"""

import pytest
from django.db import connection


def _fetchall(sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        return cursor.fetchall()


# (table, column) for every ``index=True`` in services/task/app/models/*.py,
# plus the columns Django indexes for a FK. Written as columns rather than
# index names because the names are Django's to choose — what must not
# regress is that the column is indexed at all.
INDEXED_COLUMNS = [
    # tasks
    ("tasks_task", "key"),
    ("tasks_task", "status"),
    ("tasks_task", "reporter_id"),
    ("tasks_task", "assignee_id"),
    ("tasks_task", "supervisor_id"),
    ("tasks_task", "department_id"),
    ("tasks_task", "project_id"),
    ("tasks_task", "site_id"),
    ("tasks_task", "contractor_id"),
    ("tasks_task", "contractor_worker_id"),
    ("tasks_task", "parent_id"),
    ("tasks_task", "task_type_id"),
    ("tasks_task", "is_deleted"),
    # projects
    ("tasks_project", "owner_id"),
    ("tasks_project", "department_id"),
    # sites (объекты/площадки)
    ("tasks_site", "status"),
    ("tasks_site", "department_id"),
    ("tasks_site", "manager_id"),
    ("tasks_projectsite", "project_id"),
    ("tasks_projectsite", "site_id"),
    # contractors (партнёры)
    ("tasks_contractor", "status"),
    ("tasks_contractorworker", "contractor_id"),
    ("tasks_contractorworker", "level"),
    ("tasks_contractorworker", "user_id"),
    ("tasks_contractorworker", "is_active"),
    ("tasks_contractorengagement", "contractor_id"),
    ("tasks_contractorengagement", "is_active"),
    ("tasks_equipment", "ownership"),
    # participants
    ("tasks_taskassignee", "task_id"),
    ("tasks_taskassignee", "user_id"),
    ("tasks_taskdelegate", "task_id"),
    ("tasks_taskdelegate", "user_id"),
    ("tasks_taskwatcher", "task_id"),
    ("tasks_taskwatcher", "user_id"),
    # task-attached records
    ("tasks_taskcomment", "task_id"),
    ("tasks_taskattachment", "task_id"),
    ("tasks_taskactivity", "task_id"),
    ("tasks_tasklink", "source_id"),
    ("tasks_tasklink", "target_id"),
    ("tasks_taskdepartmentlink", "task_id"),
    ("tasks_taskdepartmentlink", "department_id"),
    # assignments / equipment
    ("tasks_resourceallocation", "task_id"),
    ("tasks_resourceallocation", "roadmap_id"),
    ("tasks_resourceallocation", "employee_id"),
    ("tasks_resourceallocation", "equipment_id"),
    ("tasks_resourcerequirement", "kind"),
    ("tasks_resourcerequirement", "roadmap_id"),
    ("tasks_resourcerequirement", "task_id"),
    # иерархия работ: роудмап и блоки объекта
    ("tasks_roadmap", "project_id"),
    # site_id тут больше нет: роудмап переехал на блок, а площадка
    # выводится джойном site_block__site (миграция 0012).
    ("tasks_roadmap", "site_block_id"),
    ("tasks_roadmap", "status"),
    ("tasks_siteblock", "site_id"),
    ("tasks_siteblock", "status"),
    ("tasks_taskvolume", "task_id"),
    ("tasks_dailyreport", "task_id"),
    ("tasks_dailyreport", "work_date"),
    ("tasks_dailyreport", "author_id"),
    ("tasks_dailyreport", "is_deleted"),
    # численность персонала по блокам — вторая ось факта
    ("tasks_projectstaffreport", "work_date"),
    ("tasks_projectstaffreport", "author_id"),
    ("tasks_projectstaffreport", "is_deleted"),
    ("tasks_equipment", "is_active"),
    # notifications
    ("tasks_notification", "recipient_id"),
    ("tasks_notification", "is_read"),
    # production calendar
    ("tasks_productionday", "date"),
    ("tasks_productionday", "working_days_since_epoch"),
    # calendar
    ("tasks_calendarevent", "start_at"),
    ("tasks_calendarevent", "end_at"),
    ("tasks_calendarevent", "event_type"),
    ("tasks_calendarevent", "department_id"),
    ("tasks_calendarevent", "creator_id"),
    ("tasks_eventexception", "event_id"),
    ("tasks_calendareventparticipant", "event_id"),
    ("tasks_calendareventparticipant", "user_id"),
]

COLUMNS_REQUIRING_DB_DEFAULT = [
    ("tasks_task", "description"),
    ("tasks_task", "priority"),
    ("tasks_task", "status"),
    ("tasks_task", "progress_percent"),
    ("tasks_task", "is_deleted"),
    ("tasks_task", "created_at"),
    ("tasks_task", "updated_at"),
    ("tasks_tasktype", "color"),
    ("tasks_tasktype", "is_system"),
    ("tasks_label", "color"),
    ("tasks_equipment", "is_active"),
    ("tasks_equipment", "ownership"),
    ("tasks_contractor", "notes"),
    ("tasks_contractor", "status"),
    ("tasks_contractorworker", "level"),
    ("tasks_contractorworker", "is_active"),
    ("tasks_contractorengagement", "scope"),
    ("tasks_contractorengagement", "is_active"),
    ("tasks_site", "description"),
    ("tasks_site", "status"),
    ("tasks_site", "color"),
    ("tasks_projectsite", "is_primary"),
    ("tasks_project", "description"),
    ("tasks_project", "status"),
    ("tasks_project", "color"),
    ("tasks_taskassignee", "role"),
    ("tasks_resourceallocation", "allocation"),
    ("tasks_roadmap", "status"),
    ("tasks_roadmap", "color"),
    ("tasks_roadmap", "order"),
    ("tasks_siteblock", "status"),
    ("tasks_siteblock", "order"),
    ("tasks_resourcerequirement", "quantity"),
    ("tasks_dailyreport", "current_revision"),
    ("tasks_dailyreport", "is_deleted"),
    ("tasks_dailyreport", "comment"),
    ("tasks_projectstaffreport", "current_revision"),
    ("tasks_projectstaffreport", "is_deleted"),
    ("tasks_projectstaffreport", "comment"),
    ("tasks_projectstaffreportrevision", "total_headcount"),
    ("tasks_projectstaffreportrevision", "lines"),
    ("tasks_notification", "is_read"),
    ("tasks_tasksequence", "current_value"),
    ("tasks_productionday", "day_type"),
    ("tasks_calendarevent", "is_all_day"),
    ("tasks_calendarevent", "event_type"),
    ("tasks_calendarevent", "is_global"),
    ("tasks_eventexception", "is_cancelled"),
    ("tasks_calendareventparticipant", "rsvp_status"),
]

# Business rules that live in the DB, by the name given in models.py.
EXPECTED_CONSTRAINTS = [
    ("tasks_task", "ck_task_dates"),
    ("tasks_projectsite", "uq_project_site"),
    ("tasks_projectsite", "ck_project_site_dates"),
    ("tasks_equipment", "ck_equipment_contractor_owner"),
    ("tasks_contractorengagement", "uq_contractor_engagement"),
    ("tasks_contractorengagement", "ck_engagement_target"),
    ("tasks_contractorengagement", "ck_engagement_dates"),
    ("tasks_tasklink", "uq_task_link"),
    ("tasks_tasklink", "ck_task_link_not_self"),
    ("tasks_taskassignee", "uq_task_assignee"),
    ("tasks_taskdelegate", "uq_task_delegate"),
    ("tasks_taskwatcher", "uq_task_watcher"),
    ("tasks_taskdepartmentlink", "uq_task_department_link"),
    ("tasks_resourceallocation", "ck_assignment_exactly_one_resource"),
    ("tasks_resourceallocation", "ck_allocation_exactly_one_target"),
    ("tasks_resourceallocation", "uq_task_assignment"),
    ("tasks_resourcerequirement", "ck_requirement_exactly_one_target"),
    ("tasks_resourcerequirement", "ck_requirement_kind_fields"),
    ("tasks_resourcerequirement", "ck_requirement_dates"),
    ("tasks_roadmap", "uq_roadmap_name"),
    ("tasks_roadmap", "ck_roadmap_planned_dates"),
    ("tasks_siteblock", "uq_site_block_name"),
    ("tasks_siteblock", "uq_site_block_code"),
    ("tasks_siteblock", "ck_site_block_dates"),
    ("tasks_siteblockvolume", "uq_site_block_volume"),
    ("tasks_taskvolume", "uq_task_volume"),
    ("tasks_dailyreport", "ck_daily_report_quantity_non_negative"),
    ("tasks_dailyreportrevision", "uq_daily_report_revision"),
    ("tasks_projectstaffreportline", "uq_staff_report_line_role"),
    ("tasks_projectstaffreportline",
     "ck_staff_report_line_headcount_non_negative"),
    ("tasks_projectstaffreportrevision", "uq_staff_report_revision"),
    ("tasks_calendarevent", "ck_calendar_event_type"),
    ("tasks_calendarevent", "ck_calendar_event_range"),
    ("tasks_calendareventparticipant", "uq_calendar_event_participant"),
    ("tasks_calendareventparticipant", "ck_calendar_event_participant_status"),
]


@pytest.mark.django_db
def test_indexed_columns_are_actually_indexed():
    """Every column the FastAPI model marked ``index=True`` still has an
    index. ``pg_index.indkey`` is checked for the column being the FIRST key
    — a composite index that merely mentions the column does not give the
    single-column lookup the original relied on."""
    rows = _fetchall(
        """
        SELECT t.relname, a.attname
        FROM pg_index i
        JOIN pg_class t ON t.oid = i.indrelid
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = i.indkey[0]
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = 'public' AND t.relname LIKE 'tasks_%%'
        """
    )
    indexed = set(rows)
    missing = [pair for pair in INDEXED_COLUMNS if pair not in indexed]
    assert missing == [], f"columns that lost their index: {missing}"


@pytest.mark.django_db
def test_columns_have_db_level_defaults():
    rows = _fetchall(
        """
        SELECT table_name, column_name, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name LIKE 'tasks_%%'
        """
    )
    defaults = {(t, c): d for t, c, d in rows}
    missing = [pair for pair in COLUMNS_REQUIRING_DB_DEFAULT
               if defaults.get(pair) is None]
    assert missing == [], (
        f"columns missing a DB-level default (column_default IS NULL): {missing}"
    )


@pytest.mark.django_db
def test_business_constraints_exist():
    rows = _fetchall(
        """
        SELECT c.conrelid::regclass::text, c.conname
        FROM pg_constraint c
        JOIN pg_namespace n ON n.oid = c.connamespace
        WHERE n.nspname = 'public'
        """
    )
    present = set(rows)
    missing = [pair for pair in EXPECTED_CONSTRAINTS if pair not in present]
    assert missing == [], f"missing DB constraints: {missing}"


@pytest.mark.django_db
def test_staff_report_day_is_unique_per_block_but_only_while_alive():
    """Численность — состояние, а не инкремент.

    Осознанное расхождение с ``tasks_dailyreport``, где ``UNIQUE(task,
    work_date)`` отсутствует намеренно (смены складываются): «12 монтажников»
    от прораба и от бригадира — это одни и те же 12 человек, а не 24.

    Проверяется отдельно от ``EXPECTED_CONSTRAINTS``, потому что партиальный
    ``UniqueConstraint`` Postgres реализует уникальным ИНДЕКСОМ и строки в
    ``pg_constraint`` под него не заводит. Условие ``WHERE NOT is_deleted``
    здесь и стережётся: без него удалённый отчёт держал бы день занятым.
    """
    rows = _fetchall(
        """
        SELECT i.indisunique, pg_get_expr(i.indpred, i.indrelid)
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indexrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relname = 'uq_staff_report_project_block_date'
        """
    )
    assert rows, "партиальный уникальный индекс отчёта по персоналу пропал"
    is_unique, predicate = rows[0]
    assert is_unique
    assert "is_deleted" in (predicate or "")

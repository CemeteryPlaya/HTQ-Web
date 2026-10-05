"""Производственный календарь РК в ``refdata`` (A7.1, D-S7-1).

Чтение — всем сотрудникам; правят только ОД и HR управляющей компании
(узел ``refdata.production_calendar``, строго ``edit``, без наследования от
``refdata``). Импорт строк из схем компаний — команда, не data-миграция.
"""

from __future__ import annotations

import datetime as dt
import io

import pytest
from django.core.management import call_command
from django.db import connection
from django.test import Client

from apps.access.models import Role, RoleAssignment, RolePermission, ScopeKind
from apps.access.tests.helpers import assign, patch_json, token
from apps.companies.models import Company, CompanyKind
from apps.refdata import interface as refdata
from apps.refdata.models import ProductionDay

PROD = "/api/refdata/v1/production-calendar"


def _auth(slug, user_id=7, **claims):
    tok = token(user_id=user_id, sub=str(user_id), company=slug, **claims)
    return {"HTTP_AUTHORIZATION": f"Bearer {tok}", "HTTP_X_HTQ_COMPANY": slug}


@pytest.fixture
def holding(db):
    return Company.objects.create(slug="group-hq", name="Холдинг", kind=CompanyKind.HOLDING)


@pytest.fixture
def subsidiary(db):
    return Company.objects.create(slug="htq-kz", name="ДО", kind=CompanyKind.CONSTRUCTION)


def _system_role(code: str) -> Role:
    """Системная роль с узлом календаря — как её раздаёт миграция access/0022."""
    role, _ = Role.objects.get_or_create(code=code, defaults={"title": code, "is_system": True})
    RolePermission.objects.update_or_create(
        role=role, node="refdata.production_calendar",
        defaults={"can_view": False, "can_create": False, "can_delete": False,
                  "can_edit": code in ("bpp-od", "hr-senior", "hr-lead")})
    return role


def _give(role: Role, slug: str, user_id: int) -> None:
    RoleAssignment.objects.get_or_create(
        company_slug=slug, user_id=user_id, role=role,
        scope_kind=ScopeKind.COMPANY, scope_id=None)


# ── чтение ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_any_employee_reads_the_calendar_without_roles(holding):
    """Сотрудник без ролей БЗО и без модуля refdata читает календарь: 200."""
    resp = Client().get(f"{PROD}/?date__gte=2026-01-01&date__lte=2026-01-08",
                        **_auth(holding.slug, user_id=31))
    assert resp.status_code == 200
    by_date = {row["date"]: row for row in resp.json()}
    assert by_date["2026-01-01"]["day_type"] == "holiday"
    assert by_date["2026-01-01"]["note"] == "Новый год"
    assert by_date["2026-01-03"]["day_type"] == "weekend"
    assert by_date["2026-01-05"]["day_type"] == "working"
    assert set(by_date["2026-01-05"]) == {"date", "day_type", "working_days_since_epoch", "note", "can_edit"}


@pytest.mark.django_db
def test_calendar_read_needs_authentication(holding):
    resp = Client().get(f"{PROD}/?date__gte=2026-01-01&date__lte=2026-01-08",
                        HTTP_X_HTQ_COMPANY=holding.slug)
    assert resp.status_code == 401


@pytest.mark.django_db
def test_calendar_has_holidays_beyond_2026(holding):
    resp = Client().get(f"{PROD}/?date__gte=2027-03-20&date__lte=2027-03-25", **_auth(holding.slug))
    by_date = {row["date"]: row for row in resp.json()}
    assert by_date["2027-03-22"]["note"] == "Наурыз мейрамы"
    assert by_date["2027-03-24"]["note"] == "Наурыз мейрамы (перенос)"


@pytest.mark.django_db
def test_working_day_counter_only_advances_on_working_days(holding):
    resp = Client().get(f"{PROD}/?date__gte=2026-01-01&date__lte=2026-01-09", **_auth(holding.slug))
    counters = {row["date"]: row["working_days_since_epoch"] for row in resp.json()}
    assert counters["2026-01-02"] == 0
    assert counters["2026-01-05"] == 1
    assert counters["2026-01-06"] == 2


@pytest.mark.django_db
def test_calendar_rejects_a_bad_range(holding):
    assert Client().get(f"{PROD}/?date__gte=2026-05-01&date__lte=2026-04-01",
                        **_auth(holding.slug)).status_code == 400
    assert Client().get(f"{PROD}/?date__gte=2026-01-01&date__lte=2028-01-01",
                        **_auth(holding.slug)).status_code == 400
    assert Client().get(f"{PROD}/?date__gte=junk", **_auth(holding.slug)).status_code == 422


@pytest.mark.django_db
def test_response_shape_matches_the_old_contract(holding):
    """Форма строки — та же, что отдавал ``tasks/v1/production-calendar``."""
    from apps.refdata.schemas import ProductionDayResponse

    rows = Client().get(f"{PROD}/?date__gte=2026-01-01&date__lte=2026-01-05",
                        **_auth(holding.slug)).json()
    assert rows
    for row in rows:
        assert set(ProductionDayResponse.model_fields) == set(row)


# ── правка: права ───────────────────────────────────────────────────────

@pytest.mark.django_db
@pytest.mark.parametrize("code", ["bpp-od", "hr-senior"])
def test_od_and_hr_of_the_holding_edit_the_calendar(holding, code):
    _give(_system_role(code), holding.slug, 7)
    resp = patch_json(Client(), f"{PROD}/2026-01-05/",
                      {"day_type": "holiday", "note": "Локальный выходной"}, **_auth(holding.slug))
    assert resp.status_code == 200, resp.content
    assert resp.json()["day_type"] == "holiday"
    assert ProductionDay.objects.filter(date=dt.date(2026, 1, 5)).count() == 1


@pytest.mark.django_db
def test_od_of_a_subsidiary_cannot_edit(subsidiary):
    _give(_system_role("bpp-od"), subsidiary.slug, 7)
    resp = patch_json(Client(), f"{PROD}/2026-01-05/", {"day_type": "holiday"},
                      **_auth(subsidiary.slug))
    assert resp.status_code == 403
    assert not ProductionDay.objects.exists()


@pytest.mark.django_db
def test_module_admin_without_the_node_row_cannot_edit(holding):
    """Узел не наследует глубину от refdata: ``refdata:admin`` без строки — 403."""
    assign(holding.slug, 7, "refdata", "full")
    resp = patch_json(Client(), f"{PROD}/2026-01-05/", {"day_type": "holiday"}, **_auth(holding.slug))
    assert resp.status_code == 403
    assert not ProductionDay.objects.exists()


@pytest.mark.django_db
def test_tasks_write_cannot_edit(holding):
    assign(holding.slug, 7, "tasks", "write")
    resp = patch_json(Client(), f"{PROD}/2026-01-05/", {"day_type": "holiday"}, **_auth(holding.slug))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_node_with_create_only_is_not_enough(holding):
    """Правка — строго ``edit``: ``create`` на узле её не даёт."""
    role = Role.objects.create(code="t-cal-create", title="create only")
    RolePermission.objects.create(role=role, node="refdata.production_calendar", can_create=True)
    _give(role, holding.slug, 7)
    resp = patch_json(Client(), f"{PROD}/2026-01-05/", {"day_type": "holiday"}, **_auth(holding.slug))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_old_tasks_paths_are_gone(holding):
    """Старые пути ``tasks/v1/production-calendar`` в Django больше не отвечают —
    их переписывает nginx (``rewrite``) на новые."""
    resp = Client().get("/api/tasks/v1/production-calendar/?date__gte=2026-01-01&date__lte=2026-01-02",
                        **_auth(holding.slug))
    assert resp.status_code == 404


# ── правка: поведение ───────────────────────────────────────────────────

@pytest.fixture
def editor(holding):
    _give(_system_role("bpp-od"), holding.slug, 7)
    return holding


@pytest.mark.django_db
def test_override_is_stored_and_recounted(editor):
    patch_json(Client(), f"{PROD}/2026-01-05/", {"day_type": "holiday", "note": "x"}, **_auth(editor.slug))
    listing = Client().get(f"{PROD}/?date__gte=2026-01-01&date__lte=2026-01-09",
                           **_auth(editor.slug)).json()
    counters = {row["date"]: row["working_days_since_epoch"] for row in listing}
    assert counters["2026-01-05"] == 0
    assert counters["2026-01-06"] == 1


@pytest.mark.django_db
def test_override_restores_the_holiday_note_when_none_is_given(editor):
    resp = patch_json(Client(), f"{PROD}/2026-01-01/", {"day_type": "working"}, **_auth(editor.slug))
    assert resp.json()["note"] == "Новый год"


@pytest.mark.django_db
def test_bad_date_is_422_and_second_edit_keeps_one_row(editor):
    assert patch_json(Client(), f"{PROD}/not-a-date/", {"day_type": "working"},
                      **_auth(editor.slug)).status_code == 422
    patch_json(Client(), f"{PROD}/2026-01-05/", {"day_type": "holiday"}, **_auth(editor.slug))
    resp = patch_json(Client(), f"{PROD}/2026-01-05/", {"day_type": "short"}, **_auth(editor.slug))
    assert resp.json()["day_type"] == "short"
    assert ProductionDay.objects.filter(date=dt.date(2026, 1, 5)).count() == 1


@pytest.mark.django_db
def test_interface_calculations(editor):
    ProductionDay.objects.create(date=dt.date(2026, 6, 6), day_type="working",
                                 working_days_since_epoch=0)
    assert refdata.is_working_day(dt.date(2026, 6, 6)) is True
    assert refdata.day_type(dt.date(2026, 6, 7)) == "weekend"
    assert refdata.working_days_between(dt.date(2026, 6, 1), dt.date(2026, 6, 7)) == 6
    assert refdata.working_days_between(dt.date(2026, 6, 7), dt.date(2026, 6, 1)) is None
    assert refdata.days_between(dt.date(2026, 6, 1), dt.date(2026, 6, 7), working=False) == 7
    assert refdata.add_working_days(dt.date(2026, 6, 5), 2) == dt.date(2026, 6, 6)
    assert refdata.add_working_days(dt.date(2026, 6, 5), 0) is None
    assert len(refdata.production_days(dt.date(2026, 6, 1), dt.date(2026, 6, 7))) == 7


# ── импорт из схем компаний ─────────────────────────────────────────────

def _put(slug: str, day: str, day_type: str, note: str | None = None) -> None:
    from htqweb.tenancy.context import schema_for

    with connection.cursor() as cur:
        cur.execute(
            f'INSERT INTO "{schema_for(slug)}".tasks_productionday '
            "(date, day_type, note, working_days_since_epoch) VALUES (%s, %s, %s, 0)",
            [day, day_type, note])


def _run(*args) -> str:
    out = io.StringIO()
    call_command("refdata_import_production_days", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_import_merges_equal_rows_reports_conflicts_and_is_idempotent(two_company_schemas):
    a, b = two_company_schemas
    _put(a, "2026-06-06", "working", "рабочая суббота")
    _put(b, "2026-06-06", "working")                 # то же — одна строка
    _put(a, "2026-06-10", "holiday")
    _put(b, "2026-06-10", "short")                   # конфликт между компаниями
    _put(b, "2026-06-12", "holiday", "день компании")

    dry = _run("--dry-run")
    assert "[dry-run]" in dry and "конфликтов: 1" in dry
    assert not ProductionDay.objects.exists()

    out = _run()
    assert "добавлено: 2" in out and "КОНФЛИКТ 2026-06-10" in out
    rows = {row.date: row for row in ProductionDay.objects.all()}
    assert set(rows) == {dt.date(2026, 6, 6), dt.date(2026, 6, 12)}
    assert rows[dt.date(2026, 6, 6)].note == "рабочая суббота"
    assert rows[dt.date(2026, 6, 6)].working_days_since_epoch > 0

    again = _run()
    assert "добавлено: 0" in again and "без изменений: 2" in again
    assert ProductionDay.objects.count() == 2


@pytest.mark.django_db
def test_import_reports_conflict_with_existing_refdata_row(two_company_schemas):
    a, _ = two_company_schemas
    ProductionDay.objects.create(date=dt.date(2026, 6, 6), day_type="holiday",
                                 working_days_since_epoch=0)
    _put(a, "2026-06-06", "working")
    out = _run()
    assert "КОНФЛИКТ 2026-06-06" in out
    assert ProductionDay.objects.get(date=dt.date(2026, 6, 6)).day_type == "holiday"


@pytest.mark.django_db
def test_migration_gives_the_node_to_od_and_hr_only():
    """Миграция access/0022: явная строка у КАЖДОЙ системной роли, ``edit`` —
    только у ``bpp-od``, ``hr-senior``, ``hr-lead``."""
    roles = list(Role.objects.filter(is_system=True).exclude(code="platform-admin"))
    assert roles, "системные роли засеваются миграциями"
    editors = set()
    for role in roles:
        row = RolePermission.objects.filter(role=role, node="refdata.production_calendar").first()
        assert row is not None, f"нет явной строки у {role.code}"
        if row.can_edit:
            editors.add(role.code)
        assert not (row.can_view or row.can_create or row.can_delete)
    assert editors == {"bpp-od", "hr-senior", "hr-lead"}


@pytest.mark.django_db
def test_hr_senior_with_module_write_cannot_write_other_references(holding):
    """access/0022 даёт HR уровень ``refdata:write`` (гейт), но править она может
    только календарь: POST в статьи — 403 (нет права на узлы справочников)."""
    role = _system_role("hr-senior")
    RolePermission.objects.update_or_create(
        role=role, node="refdata.production_calendar",
        defaults={"can_view": False, "can_create": False, "can_delete": False, "can_edit": True})
    _give(role, holding.slug, 7)
    resp = Client().post("/api/refdata/v1/uoms", data='{"code":"x","short_name":"x","name":"X"}',
                         content_type="application/json", **_auth(holding.slug))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_listing_reports_can_edit_per_company(holding, subsidiary):
    _give(_system_role("bpp-od"), holding.slug, 7)
    _give(_system_role("bpp-od"), subsidiary.slug, 7)
    url = f"{PROD}/?date__gte=2026-01-01&date__lte=2026-01-02"
    assert all(r["can_edit"] for r in Client().get(url, **_auth(holding.slug)).json())
    assert not any(r["can_edit"] for r in Client().get(url, **_auth(subsidiary.slug)).json())
    assert not any(r["can_edit"] for r in Client().get(url, **_auth(holding.slug, user_id=99)).json())

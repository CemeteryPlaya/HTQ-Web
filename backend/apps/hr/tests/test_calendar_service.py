"""apps.hr.services.calendar_service — резолюция дня, переключение дефолта,
working-days, назначения шаблона/смены — порт
services/hr/tests/integration/test_calendar_service.py (+ доп. ветки: смены,
holidays_off, взаимная эксклюзивность шаблон/смена, ошибки CRUD).

План: docs/plans/2026-07-20-hr-domain.md
"""
from __future__ import annotations

import datetime

import pytest

from apps.hr.models import Department, Employee, Position, ShiftPattern, WeekTemplate
from apps.hr.services import calendar_service as svc

_FIVE_TWO = {str(i): {"type": "working", "hours": 8} for i in range(5)}
_FIVE_TWO.update({"5": {"type": "weekend", "hours": 0}, "6": {"type": "weekend", "hours": 0}})
_SIX_ONE = {str(i): {"type": "working", "hours": 8} for i in range(6)}
_SIX_ONE["6"] = {"type": "weekend", "hours": 0}


def _default_5_2() -> WeekTemplate:
    return WeekTemplate.objects.create(name="5/2", is_default=True, days=_FIVE_TWO)


def _employee(**kw) -> Employee:
    d = Department.objects.create(name=kw.pop("dep_name", "D"), path=kw.pop("dep_path", "d"))
    p = Position.objects.create(title="Eng", department=d, weight=kw.pop("weight", 50))
    return Employee.objects.create(
        first_name="A", last_name="B", email=kw.pop("email", "a@b.c"),
        department=d, position=p, hire_date=datetime.date(2020, 1, 1), status="active", **kw,
    )


# ── резолюция (day_info/employee_day_info) — порт test_calendar_service.py ──

@pytest.mark.django_db
def test_default_resolution_weekday_vs_weekend():
    _default_5_2()
    mon = svc.day_info(datetime.date(2026, 6, 1))  # понедельник
    sun = svc.day_info(datetime.date(2026, 6, 7))  # воскресенье
    assert mon["type"] == "working" and mon["hours"] == 8
    assert sun["type"] == "weekend" and sun["hours"] == 0


@pytest.mark.django_db
def test_override_wins():
    _default_5_2()
    svc.upsert_day(datetime.date(2026, 6, 1), "holiday", 0, "Holiday")
    info = svc.day_info(datetime.date(2026, 6, 1))
    assert info["type"] == "holiday" and info["hours"] == 0 and info["note"] == "Holiday"


@pytest.mark.django_db
def test_hard_fallback_without_default():
    mon = svc.day_info(datetime.date(2026, 6, 1))  # шаблон не заведён вовсе
    assert mon["type"] == "working" and mon["hours"] == 8
    sat = svc.day_info(datetime.date(2026, 6, 6))
    assert sat["type"] == "weekend" and sat["hours"] == 0


# ── национальные праздники (общий движок apps.core.kz_holidays) ──────────────

@pytest.mark.django_db
def test_national_holiday_beats_the_week_template_without_any_import():
    """Регрессия: единственным источником праздников была таблица CalendarDay,
    которую наполняет только ручной POST /calendar/import, — на живой базе она
    пуста, и 1 января выходило рабочим днём с полной нормой часов."""
    _default_5_2()
    ny = svc.day_info(datetime.date(2026, 1, 1))   # четверг
    assert ny["type"] == "holiday" and ny["hours"] == 0
    assert ny["note"] == "Новый год"


@pytest.mark.django_db
def test_national_holidays_are_not_limited_to_2026():
    for year in (2027, 2031):
        info = svc.day_info(datetime.date(year, 12, 16))
        assert info["type"] == "holiday", year


@pytest.mark.django_db
def test_imported_day_still_wins_over_the_generated_holiday():
    """Постановление правительства может сделать праздничный день рабочим —
    строка в CalendarDay обязана остаться главнее движка."""
    _default_5_2()
    svc.upsert_day(datetime.date(2026, 1, 1), "working", 8, "Отработка")
    info = svc.day_info(datetime.date(2026, 1, 1))
    assert info["type"] == "working" and info["hours"] == 8


@pytest.mark.django_db
def test_working_days_between_skips_national_holidays():
    _default_5_2()
    # 1-9 января 2026: 1 (чт), 2 (пт) и 7 (ср) — праздники, 3-4 — выходные,
    # значит рабочих остаётся четыре: 5, 6, 8, 9.
    res = svc.working_days_between(datetime.date(2026, 1, 1), datetime.date(2026, 1, 9))
    assert res["working_days"] == 4 and float(res["norm_hours"]) == 32.0


@pytest.mark.django_db
def test_shift_with_holidays_off_respects_a_generated_holiday():
    pattern = svc.create_shift_pattern(
        "1/0", [{"type": "work", "hours": 8}], holidays_off=True,
    )
    e = _employee(email="shift-ny@b.c")
    svc.assign_shift(e.id, pattern.id, datetime.date(2026, 1, 1))
    info = svc.employee_day_info(e.id, datetime.date(2026, 1, 1))
    assert info["type"] == "holiday" and info["hours"] == 0


@pytest.mark.django_db
def test_set_default_moves_flag():
    t1 = _default_5_2()
    t2 = svc.create_template("6/1", _SIX_ONE, make_default=False)
    svc.set_default(t2.id)
    t1.refresh_from_db()
    t2.refresh_from_db()
    assert t1.is_default is False and t2.is_default is True


@pytest.mark.django_db
def test_working_days_between_counts_and_sums():
    _default_5_2()
    res = svc.working_days_between(datetime.date(2026, 6, 1), datetime.date(2026, 6, 7))
    assert res["working_days"] == 5 and float(res["norm_hours"]) == 40.0


@pytest.mark.django_db
def test_employee_uses_assigned_template_else_default():
    _default_5_2()
    e = _employee()
    sat = svc.employee_day_info(e.id, datetime.date(2026, 6, 6))
    assert sat["type"] == "weekend"
    t61 = svc.create_template("6/1", _SIX_ONE, make_default=False)
    svc.assign_template(e.id, t61.id)
    sat2 = svc.employee_day_info(e.id, datetime.date(2026, 6, 6))
    assert sat2["type"] == "working" and sat2["hours"] == 8
    svc.assign_template(e.id, None)
    sat3 = svc.employee_day_info(e.id, datetime.date(2026, 6, 6))
    assert sat3["type"] == "weekend"


# ── смены (shift patterns) — ветки, не покрытые исходником напрямую, но
#    вытекающие буквально из его кода (_from_shift/holidays_off) ────────────

@pytest.mark.django_db
def test_shift_pattern_cycle_resolution():
    """2-слотовый цикл work/off, anchor=понедельник -> вторник off."""
    pattern = svc.create_shift_pattern(
        "2/2", [{"type": "work", "hours": 12}, {"type": "off", "hours": 0}],
    )
    e = _employee(email="shift1@b.c")
    svc.assign_shift(e.id, pattern.id, datetime.date(2026, 6, 1))  # Monday anchor, work
    mon = svc.employee_day_info(e.id, datetime.date(2026, 6, 1))
    tue = svc.employee_day_info(e.id, datetime.date(2026, 6, 2))
    wed = svc.employee_day_info(e.id, datetime.date(2026, 6, 3))
    assert mon["type"] == "working" and mon["hours"] == 12
    assert tue["type"] == "weekend" and tue["hours"] == 0
    assert wed["type"] == "working" and wed["hours"] == 12


@pytest.mark.django_db
def test_shift_pattern_holidays_off_overrides_with_national_calendar():
    """holidays_off=True: национальный оверрайд на рабочий по циклу день
    побеждает (buквальный порт CalendarService.employee_day_info п.2)."""
    pattern = svc.create_shift_pattern(
        "1/0", [{"type": "work", "hours": 8}], holidays_off=True,
    )
    e = _employee(email="shift2@b.c")
    svc.assign_shift(e.id, pattern.id, datetime.date(2026, 6, 1))
    svc.upsert_day(datetime.date(2026, 6, 1), "holiday", 0, "Праздник")
    info = svc.employee_day_info(e.id, datetime.date(2026, 6, 1))
    assert info["type"] == "holiday" and info["hours"] == 0


@pytest.mark.django_db
def test_shift_pattern_without_holidays_off_ignores_national_calendar():
    pattern = svc.create_shift_pattern(
        "1/0", [{"type": "work", "hours": 8}], holidays_off=False,
    )
    e = _employee(email="shift3@b.c")
    svc.assign_shift(e.id, pattern.id, datetime.date(2026, 6, 1))
    svc.upsert_day(datetime.date(2026, 6, 1), "holiday", 0, "Праздник")
    info = svc.employee_day_info(e.id, datetime.date(2026, 6, 1))
    assert info["type"] == "working" and info["hours"] == 8


@pytest.mark.django_db
def test_employee_manual_override_wins_over_shift():
    pattern = svc.create_shift_pattern("1/0", [{"type": "work", "hours": 8}])
    e = _employee(email="shift4@b.c")
    svc.assign_shift(e.id, pattern.id, datetime.date(2026, 6, 1))
    svc.set_employee_day_override(e.id, datetime.date(2026, 6, 1), "weekend", 0, "Отгул")
    info = svc.employee_day_info(e.id, datetime.date(2026, 6, 1))
    assert info["type"] == "weekend" and info["hours"] == 0 and info["note"] == "Отгул"


@pytest.mark.django_db
def test_shift_pattern_empty_slots_falls_back():
    pattern = ShiftPattern.objects.create(name="empty", slots=[])
    e = _employee(email="shift5@b.c")
    svc.assign_shift(e.id, pattern.id, datetime.date(2026, 6, 1))
    mon = svc.employee_day_info(e.id, datetime.date(2026, 6, 1))
    sat = svc.employee_day_info(e.id, datetime.date(2026, 6, 6))
    assert mon["type"] == "working" and mon["hours"] == 8.0
    assert sat["type"] == "weekend" and sat["hours"] == 0.0


# ── взаимная эксклюзивность week-template <-> shift ─────────────────────────

@pytest.mark.django_db
def test_assign_shift_clears_week_template_assignment():
    t = _default_5_2()
    pattern = svc.create_shift_pattern("1/0", [{"type": "work", "hours": 8}])
    e = _employee(email="excl1@b.c")
    svc.assign_template(e.id, t.id)
    svc.assign_shift(e.id, pattern.id, datetime.date(2026, 6, 1))
    from apps.hr.models import EmployeeWeekTemplate
    assert not EmployeeWeekTemplate.objects.filter(employee_id=e.id).exists()


@pytest.mark.django_db
def test_assign_template_clears_shift_assignment():
    t = _default_5_2()
    pattern = svc.create_shift_pattern("1/0", [{"type": "work", "hours": 8}])
    e = _employee(email="excl2@b.c")
    svc.assign_shift(e.id, pattern.id, datetime.date(2026, 6, 1))
    svc.assign_template(e.id, t.id)
    from apps.hr.models import EmployeeShiftAssignment
    assert not EmployeeShiftAssignment.objects.filter(employee_id=e.id).exists()


# ── CRUD ошибки — template/shift pattern not found, cannot-delete-default ──

@pytest.mark.django_db
def test_update_template_not_found_raises():
    with pytest.raises(svc.TemplateNotFound):
        svc.update_template(999999, "x", _FIVE_TWO)


@pytest.mark.django_db
def test_delete_default_template_raises():
    t = _default_5_2()
    with pytest.raises(svc.CannotDeleteDefaultTemplate):
        svc.delete_template(t.id)


@pytest.mark.django_db
def test_delete_template_not_found_raises():
    with pytest.raises(svc.TemplateNotFound):
        svc.delete_template(999999)


@pytest.mark.django_db
def test_set_default_not_found_raises():
    with pytest.raises(svc.TemplateNotFound):
        svc.set_default(999999)


@pytest.mark.django_db
def test_assign_template_not_found_raises():
    e = _employee(email="tnf@b.c")
    with pytest.raises(svc.TemplateNotFound):
        svc.assign_template(e.id, 999999)


@pytest.mark.django_db
def test_update_shift_pattern_not_found_raises():
    with pytest.raises(svc.ShiftPatternNotFound):
        svc.update_shift_pattern(999999, "x", [{"type": "work", "hours": 8}], False)


@pytest.mark.django_db
def test_delete_shift_pattern_not_found_raises():
    with pytest.raises(svc.ShiftPatternNotFound):
        svc.delete_shift_pattern(999999)


@pytest.mark.django_db
def test_assign_shift_pattern_not_found_raises():
    e = _employee(email="spnf@b.c")
    with pytest.raises(svc.ShiftPatternNotFound):
        svc.assign_shift(e.id, 999999, datetime.date(2026, 6, 1))


# ── import / delete no-ops ───────────────────────────────────────────────

@pytest.mark.django_db
def test_import_year_upserts_multiple_and_returns_count():
    items = [
        {"day": datetime.date(2026, 1, 1), "day_type": "holiday", "norm_hours": 0, "note": "NY"},
        {"day": datetime.date(2026, 1, 2), "day_type": "holiday", "norm_hours": 0, "note": None},
    ]
    n = svc.import_year(items)
    assert n == 2
    assert svc.day_info(datetime.date(2026, 1, 1))["type"] == "holiday"
    assert svc.day_info(datetime.date(2026, 1, 2))["note"] is None


@pytest.mark.django_db
def test_delete_override_noop_when_missing():
    svc.delete_override(datetime.date(2026, 1, 1))  # не должно падать


@pytest.mark.django_db
def test_unassign_shift_noop_when_missing():
    e = _employee(email="noop1@b.c")
    svc.unassign_shift(e.id)  # не должно падать


@pytest.mark.django_db
def test_employee_day_override_set_then_delete():
    e = _employee(email="ovr@b.c")
    o = svc.set_employee_day_override(e.id, datetime.date(2026, 6, 1), "short", 4, "half day")
    assert o.day_type == "short" and float(o.norm_hours) == 4.0
    svc.delete_employee_day_override(e.id, datetime.date(2026, 6, 1))
    info = svc.employee_day_info(e.id, datetime.date(2026, 6, 1))
    assert info["type"] != "short"


@pytest.mark.django_db
def test_list_templates_and_shift_patterns_ordered_by_id():
    t1 = svc.create_template("A", _FIVE_TWO)
    t2 = svc.create_template("B", _SIX_ONE)
    assert [t.id for t in svc.list_templates()] == [t1.id, t2.id]
    p1 = svc.create_shift_pattern("P1", [{"type": "work", "hours": 8}])
    p2 = svc.create_shift_pattern("P2", [{"type": "off", "hours": 0}])
    assert [p.id for p in svc.list_shift_patterns()] == [p1.id, p2.id]

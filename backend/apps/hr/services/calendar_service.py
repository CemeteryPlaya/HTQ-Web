"""Производственный календарь (рабочие дни/смены) — порт
services/hr/app/services/calendar_service.py.

Резолюция дня — БУКВАЛЬНЫЙ перенос приоритетов исходника (комментарии в
функциях ниже воспроизводят нумерацию исходника, включая её метку "B3a").

Р2: dramatiq-события не портируются (исходник их не шлёт — CalendarService
никаких событий не публикует).
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from apps.core import kz_holidays
from apps.hr.models import (
    CalendarDay,
    EmployeeDayOverride,
    EmployeeShiftAssignment,
    EmployeeWeekTemplate,
    ShiftPattern,
    WeekTemplate,
)

_WORKING = {"working", "short"}


class TemplateNotFound(Exception):
    """404 "Template not found" — порт update_template/delete_template/set_default/assign_template."""


class CannotDeleteDefaultTemplate(Exception):
    """409 "Cannot delete the default template" — порт delete_template."""


class ShiftPatternNotFound(Exception):
    """404 "Shift pattern not found" — порт update_shift_pattern/delete_shift_pattern/assign_shift."""


# ── resolution helpers (buквально _fallback/_from_template/_from_shift) ────

def _fallback(d: date) -> dict:
    wd = d.weekday()
    if wd < 5:
        return {"type": "working", "hours": 8.0, "note": None}
    return {"type": "weekend", "hours": 0.0, "note": None}


def _from_template(tmpl: WeekTemplate, d: date) -> dict | None:
    cfg = (tmpl.days or {}).get(str(d.weekday()))
    if not isinstance(cfg, dict):
        return None
    return {"type": cfg.get("type", "working"), "hours": float(cfg.get("hours", 0)), "note": None}


def _from_shift(pattern: ShiftPattern, anchor: date, d: date) -> dict:
    slots = pattern.slots or []
    if not slots:
        return _fallback(d)
    idx = (d - anchor).days % len(slots)
    slot = slots[idx] if isinstance(slots[idx], dict) else {}
    is_work = slot.get("type") == "work"
    return {"type": "working" if is_work else "weekend", "hours": float(slot.get("hours", 0)), "note": None}


# ── lookups ──

def _override(d: date) -> CalendarDay | None:
    return CalendarDay.objects.filter(day=d).first()


def _default_template() -> WeekTemplate | None:
    return WeekTemplate.objects.filter(is_default=True).first()


def _employee_template(employee_id: int) -> WeekTemplate | None:
    row = EmployeeWeekTemplate.objects.filter(employee_id=employee_id).first()
    if row is None:
        return None
    return WeekTemplate.objects.filter(id=row.week_template_id).first()


def _override_dict(o: CalendarDay) -> dict:
    return {"type": o.day_type, "hours": float(o.norm_hours), "note": o.note}


def _national(d: date) -> dict | None:
    """Национальный день: ручной оверрайд БД, иначе праздник РК из
    ``apps.core.kz_holidays``.

    Раньше здесь стоял голый ``_override``, то есть единственным источником
    праздников была таблица ``CalendarDay`` — а она наполняется только ручным
    ``POST /calendar/import``, и на живой базе пуста. Из-за этого 1 января
    считалось обычным рабочим днём с полной нормой часов. Общий движок
    праздников убирает это молчаливое «календаря нет»; импортированная строка
    по-прежнему главнее — правительство может дать день, которого нет в
    правилах, и наоборот.
    """
    o = _override(d)
    if o is not None:
        return _override_dict(o)
    name = kz_holidays.holiday_note(d)
    if name is not None:
        return {"type": "holiday", "hours": 0.0, "note": name}
    return None


def _employee_override(employee_id: int, d: date) -> EmployeeDayOverride | None:
    return EmployeeDayOverride.objects.filter(employee_id=employee_id, day=d).first()


def _employee_shift(employee_id: int) -> EmployeeShiftAssignment | None:
    return EmployeeShiftAssignment.objects.filter(employee_id=employee_id).first()


# ── resolution ──

def day_info(d: date) -> dict:
    # Праздник обязан бить недельный шаблон: шаблон говорит «пн рабочий», но
    # 1 января рабочим не становится.
    nat = _national(d)
    if nat is not None:
        return nat
    tmpl = _default_template()
    if tmpl is not None:
        r = _from_template(tmpl, d)
        if r is not None:
            return r
    return _fallback(d)


def employee_day_info(employee_id: int, d: date) -> dict:
    # 1. ручной персональный оверрайд побеждает
    eo = _employee_override(employee_id, d)
    if eo is not None:
        return {"type": eo.day_type, "hours": float(eo.norm_hours), "note": eo.note}
    # 2. назначение смены
    shift = _employee_shift(employee_id)
    if shift is not None:
        pattern = ShiftPattern.objects.filter(id=shift.shift_pattern_id).first()
        if pattern is not None:
            nat = _national(d)
            if pattern.holidays_off and nat is not None:
                return nat
            return _from_shift(pattern, shift.anchor_date, d)
    # 3. B3a: национальный оверрайд -> недельный шаблон сотрудника/дефолтный -> fallback
    nat = _national(d)
    if nat is not None:
        return nat
    tmpl = _employee_template(employee_id)
    if tmpl is None:
        tmpl = _default_template()
    if tmpl is not None:
        r = _from_template(tmpl, d)
        if r is not None:
            return r
    return _fallback(d)


# ── ranges ──

def _iter(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def list_year(year: int) -> list[dict]:
    out = []
    for d in _iter(date(year, 1, 1), date(year, 12, 31)):
        info = day_info(d)
        out.append({"day": d.isoformat(), **info})
    return out


def employee_calendar(employee_id: int, start: date, end: date) -> list[dict]:
    return [{"day": d.isoformat(), **employee_day_info(employee_id, d)} for d in _iter(start, end)]


def working_days_between(start: date, end: date) -> dict:
    days = 0
    hours = Decimal("0")
    for d in _iter(start, end):
        info = day_info(d)
        if info["type"] in _WORKING and info["hours"] > 0:
            days += 1
            hours += Decimal(str(info["hours"]))
    return {"working_days": days, "norm_hours": str(hours)}


def employee_working_days_between(employee_id: int, start: date, end: date) -> dict:
    """Порт CalendarService.employee_working_days_between — не вызывается ни
    одним роутом исходника (мёртвый публичный метод сервиса), но переносим
    для паритета модуля целиком."""
    days = 0
    hours = Decimal("0")
    for d in _iter(start, end):
        info = employee_day_info(employee_id, d)
        if info["type"] in _WORKING and info["hours"] > 0:
            days += 1
            hours += Decimal(str(info["hours"]))
    return {"working_days": days, "norm_hours": str(hours)}


# ── templates ──

def list_templates() -> list[WeekTemplate]:
    return list(WeekTemplate.objects.order_by("id"))


def template_out(t: WeekTemplate) -> dict:
    """WeekTemplateOut."""
    return {"id": t.id, "name": t.name, "is_default": t.is_default, "days": t.days}


def create_template(name: str, days: dict, *, make_default: bool = False) -> WeekTemplate:
    if make_default:
        WeekTemplate.objects.update(is_default=False)
    return WeekTemplate.objects.create(name=name, days=days, is_default=make_default)


def update_template(template_id: int, name: str, days: dict) -> WeekTemplate:
    tmpl = WeekTemplate.objects.filter(id=template_id).first()
    if tmpl is None:
        raise TemplateNotFound
    tmpl.name = name
    tmpl.days = days
    tmpl.save()
    return tmpl


def delete_template(template_id: int) -> None:
    tmpl = WeekTemplate.objects.filter(id=template_id).first()
    if tmpl is None:
        raise TemplateNotFound
    if tmpl.is_default:
        raise CannotDeleteDefaultTemplate
    tmpl.delete()


def set_default(template_id: int) -> WeekTemplate:
    tmpl = WeekTemplate.objects.filter(id=template_id).first()
    if tmpl is None:
        raise TemplateNotFound
    WeekTemplate.objects.update(is_default=False)
    tmpl.is_default = True
    tmpl.save()
    return tmpl


# ── overrides (national calendar) ──

def upsert_day(d: date, day_type: str, norm_hours, note: str | None) -> CalendarDay:
    o = _override(d)
    if o is None:
        o = CalendarDay(day=d)
    o.day_type = day_type
    o.norm_hours = Decimal(str(norm_hours))
    o.note = note
    o.save()
    return o


def delete_override(d: date) -> None:
    o = _override(d)
    if o is not None:
        o.delete()


def import_year(items: list[dict]) -> int:
    for it in items:
        upsert_day(it["day"], it["day_type"], it.get("norm_hours", 0), it.get("note"))
    return len(items)


# ── assignment (week template) ──

def assign_template(employee_id: int, template_id: int | None) -> None:
    if template_id is not None:
        shift = _employee_shift(employee_id)
        if shift is not None:
            shift.delete()
    row = EmployeeWeekTemplate.objects.filter(employee_id=employee_id).first()
    if template_id is None:
        if row is not None:
            row.delete()
        return
    if not WeekTemplate.objects.filter(id=template_id).exists():
        raise TemplateNotFound
    if row is None:
        EmployeeWeekTemplate.objects.create(employee_id=employee_id, week_template_id=template_id)
    else:
        row.week_template_id = template_id
        row.save()


# ── shift patterns ──

def list_shift_patterns() -> list[ShiftPattern]:
    return list(ShiftPattern.objects.order_by("id"))


def shift_pattern_out(p: ShiftPattern) -> dict:
    """ShiftPatternOut."""
    return {"id": p.id, "name": p.name, "slots": p.slots, "holidays_off": p.holidays_off}


def create_shift_pattern(name: str, slots: list, *, holidays_off: bool = False) -> ShiftPattern:
    return ShiftPattern.objects.create(name=name, slots=slots, holidays_off=holidays_off)


def update_shift_pattern(pattern_id: int, name: str, slots: list, holidays_off: bool) -> ShiftPattern:
    pat = ShiftPattern.objects.filter(id=pattern_id).first()
    if pat is None:
        raise ShiftPatternNotFound
    pat.name = name
    pat.slots = slots
    pat.holidays_off = holidays_off
    pat.save()
    return pat


def delete_shift_pattern(pattern_id: int) -> None:
    pat = ShiftPattern.objects.filter(id=pattern_id).first()
    if pat is None:
        raise ShiftPatternNotFound
    pat.delete()


# ── shift assignment (взаимоисключающе с недельным шаблоном) ──

def assign_shift(employee_id: int, pattern_id: int, anchor_date: date) -> None:
    if not ShiftPattern.objects.filter(id=pattern_id).exists():
        raise ShiftPatternNotFound
    # снять любое назначение недельного шаблона
    wt = EmployeeWeekTemplate.objects.filter(employee_id=employee_id).first()
    if wt is not None:
        wt.delete()
    row = _employee_shift(employee_id)
    if row is None:
        EmployeeShiftAssignment.objects.create(
            employee_id=employee_id, shift_pattern_id=pattern_id, anchor_date=anchor_date,
        )
    else:
        row.shift_pattern_id = pattern_id
        row.anchor_date = anchor_date
        row.save()


def unassign_shift(employee_id: int) -> None:
    row = _employee_shift(employee_id)
    if row is not None:
        row.delete()


# ── ручной персональный оверрайд дня ──

def set_employee_day_override(
    employee_id: int, day: date, day_type: str, norm_hours, note: str | None,
) -> EmployeeDayOverride:
    row = _employee_override(employee_id, day)
    if row is None:
        row = EmployeeDayOverride(employee_id=employee_id, day=day)
    row.day_type = day_type
    row.norm_hours = Decimal(str(norm_hours))
    row.note = note
    row.save()
    return row


def delete_employee_day_override(employee_id: int, day: date) -> None:
    row = _employee_override(employee_id, day)
    if row is not None:
        row.delete()


def day_override_out(o) -> dict:
    """Порт inline-словаря роутера ``put /{day}`` и ``PUT
    /{employee_id}/calendar/{day}`` — ОДИНАКОВАЯ форма для CalendarDay и
    EmployeeDayOverride."""
    return {"day": o.day.isoformat(), "day_type": o.day_type, "norm_hours": str(o.norm_hours), "note": o.note}

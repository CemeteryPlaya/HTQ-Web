"""Resolve dates to {type, hours} via overrides, week templates, fallback."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calendar import (
    CalendarDay, EmployeeWeekTemplate, WeekTemplate,
    ShiftPattern, EmployeeShiftAssignment, EmployeeDayOverride,
)

_WORKING = {"working", "short"}


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


class CalendarService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── lookups ──
    async def _override(self, d: date) -> CalendarDay | None:
        return (await self.session.execute(
            select(CalendarDay).where(CalendarDay.day == d)
        )).scalar_one_or_none()

    async def _default_template(self) -> WeekTemplate | None:
        return (await self.session.execute(
            select(WeekTemplate).where(WeekTemplate.is_default == True).limit(1)  # noqa: E712
        )).scalar_one_or_none()

    async def _employee_template(self, employee_id: int) -> WeekTemplate | None:
        row = (await self.session.execute(
            select(EmployeeWeekTemplate).where(EmployeeWeekTemplate.employee_id == employee_id)
        )).scalar_one_or_none()
        if row is None:
            return None
        return (await self.session.execute(
            select(WeekTemplate).where(WeekTemplate.id == row.week_template_id)
        )).scalar_one_or_none()

    @staticmethod
    def _override_dict(o: CalendarDay) -> dict:
        return {"type": o.day_type, "hours": float(o.norm_hours), "note": o.note}

    async def _employee_override(self, employee_id: int, d: date) -> EmployeeDayOverride | None:
        return (await self.session.execute(
            select(EmployeeDayOverride).where(
                EmployeeDayOverride.employee_id == employee_id, EmployeeDayOverride.day == d
            )
        )).scalar_one_or_none()

    async def _employee_shift(self, employee_id: int) -> EmployeeShiftAssignment | None:
        return (await self.session.execute(
            select(EmployeeShiftAssignment).where(EmployeeShiftAssignment.employee_id == employee_id)
        )).scalar_one_or_none()

    # ── resolution ──
    async def day_info(self, d: date) -> dict:
        o = await self._override(d)
        if o is not None:
            return self._override_dict(o)
        tmpl = await self._default_template()
        if tmpl is not None:
            r = _from_template(tmpl, d)
            if r is not None:
                return r
        return _fallback(d)

    async def employee_day_info(self, employee_id: int, d: date) -> dict:
        # 1. manual per-employee override wins
        eo = await self._employee_override(employee_id, d)
        if eo is not None:
            return {"type": eo.day_type, "hours": float(eo.norm_hours), "note": eo.note}
        # 2. shift assignment
        shift = await self._employee_shift(employee_id)
        if shift is not None:
            pattern = await self.session.get(ShiftPattern, shift.shift_pattern_id)
            if pattern is not None:
                nat = await self._override(d)
                if pattern.holidays_off and nat is not None:
                    return self._override_dict(nat)
                return _from_shift(pattern, shift.anchor_date, d)
        # 3. B3a: national override → employee week-template / default → fallback
        o = await self._override(d)
        if o is not None:
            return self._override_dict(o)
        tmpl = await self._employee_template(employee_id)
        if tmpl is None:
            tmpl = await self._default_template()
        if tmpl is not None:
            r = _from_template(tmpl, d)
            if r is not None:
                return r
        return _fallback(d)

    # ── ranges ──
    @staticmethod
    def _iter(start: date, end: date):
        cur = start
        while cur <= end:
            yield cur
            cur += timedelta(days=1)

    async def list_year(self, year: int) -> list[dict]:
        out = []
        for d in self._iter(date(year, 1, 1), date(year, 12, 31)):
            info = await self.day_info(d)
            out.append({"day": d.isoformat(), **info})
        return out

    async def employee_calendar(self, employee_id: int, start: date, end: date) -> list[dict]:
        return [{"day": d.isoformat(), **await self.employee_day_info(employee_id, d)}
                for d in self._iter(start, end)]

    async def working_days_between(self, start: date, end: date) -> dict:
        days = 0
        hours = Decimal("0")
        for d in self._iter(start, end):
            info = await self.day_info(d)
            if info["type"] in _WORKING and info["hours"] > 0:
                days += 1
                hours += Decimal(str(info["hours"]))
        return {"working_days": days, "norm_hours": str(hours)}

    async def employee_working_days_between(self, employee_id: int, start: date, end: date) -> dict:
        days = 0
        hours = Decimal("0")
        for d in self._iter(start, end):
            info = await self.employee_day_info(employee_id, d)
            if info["type"] in _WORKING and info["hours"] > 0:
                days += 1
                hours += Decimal(str(info["hours"]))
        return {"working_days": days, "norm_hours": str(hours)}

    # ── templates ──
    async def list_templates(self) -> list[WeekTemplate]:
        return list((await self.session.execute(select(WeekTemplate).order_by(WeekTemplate.id))).scalars().all())

    async def create_template(self, name: str, days: dict, *, make_default: bool = False) -> WeekTemplate:
        if make_default:
            await self.session.execute(update(WeekTemplate).values(is_default=False))
        tmpl = WeekTemplate(name=name, days=days, is_default=make_default)
        self.session.add(tmpl)
        await self.session.commit()
        await self.session.refresh(tmpl)
        return tmpl

    async def update_template(self, template_id: int, name: str, days: dict) -> WeekTemplate:
        tmpl = await self.session.get(WeekTemplate, template_id)
        if tmpl is None:
            raise HTTPException(status_code=404, detail="Template not found")
        tmpl.name = name
        tmpl.days = days
        await self.session.commit()
        await self.session.refresh(tmpl)
        return tmpl

    async def delete_template(self, template_id: int) -> None:
        tmpl = await self.session.get(WeekTemplate, template_id)
        if tmpl is None:
            raise HTTPException(status_code=404, detail="Template not found")
        if tmpl.is_default:
            raise HTTPException(status_code=409, detail="Cannot delete the default template")
        await self.session.delete(tmpl)
        await self.session.commit()

    async def set_default(self, template_id: int) -> WeekTemplate:
        tmpl = await self.session.get(WeekTemplate, template_id)
        if tmpl is None:
            raise HTTPException(status_code=404, detail="Template not found")
        await self.session.execute(update(WeekTemplate).values(is_default=False))
        tmpl.is_default = True
        await self.session.commit()
        await self.session.refresh(tmpl)
        return tmpl

    # ── overrides ──
    async def upsert_day(self, d: date, day_type: str, norm_hours: float, note: str | None) -> CalendarDay:
        o = await self._override(d)
        if o is None:
            o = CalendarDay(day=d)
            self.session.add(o)
        o.day_type = day_type
        o.norm_hours = Decimal(str(norm_hours))
        o.note = note
        await self.session.commit()
        await self.session.refresh(o)
        return o

    async def delete_override(self, d: date) -> None:
        o = await self._override(d)
        if o is not None:
            await self.session.delete(o)
            await self.session.commit()

    async def import_year(self, items: list[dict]) -> int:
        for it in items:
            await self.upsert_day(it["day"], it["day_type"], it.get("norm_hours", 0), it.get("note"))
        return len(items)

    # ── assignment ──
    async def assign_template(self, employee_id: int, template_id: int | None) -> None:
        if template_id is not None:
            shift = await self._employee_shift(employee_id)
            if shift is not None:
                await self.session.delete(shift)
        row = (await self.session.execute(
            select(EmployeeWeekTemplate).where(EmployeeWeekTemplate.employee_id == employee_id)
        )).scalar_one_or_none()
        if template_id is None:
            if row is not None:
                await self.session.delete(row)
                await self.session.commit()
            return
        if await self.session.get(WeekTemplate, template_id) is None:
            raise HTTPException(status_code=404, detail="Template not found")
        if row is None:
            row = EmployeeWeekTemplate(employee_id=employee_id, week_template_id=template_id)
            self.session.add(row)
        else:
            row.week_template_id = template_id
        await self.session.commit()

    # ── shift patterns ──
    async def list_shift_patterns(self) -> list[ShiftPattern]:
        return list((await self.session.execute(select(ShiftPattern).order_by(ShiftPattern.id))).scalars().all())

    async def create_shift_pattern(self, name: str, slots: list, *, holidays_off: bool = False) -> ShiftPattern:
        pat = ShiftPattern(name=name, slots=slots, holidays_off=holidays_off)
        self.session.add(pat)
        await self.session.commit()
        await self.session.refresh(pat)
        return pat

    async def update_shift_pattern(self, pattern_id: int, name: str, slots: list, holidays_off: bool) -> ShiftPattern:
        pat = await self.session.get(ShiftPattern, pattern_id)
        if pat is None:
            raise HTTPException(status_code=404, detail="Shift pattern not found")
        pat.name = name
        pat.slots = slots
        pat.holidays_off = holidays_off
        await self.session.commit()
        await self.session.refresh(pat)
        return pat

    async def delete_shift_pattern(self, pattern_id: int) -> None:
        pat = await self.session.get(ShiftPattern, pattern_id)
        if pat is None:
            raise HTTPException(status_code=404, detail="Shift pattern not found")
        await self.session.delete(pat)
        await self.session.commit()

    # ── shift assignment (mutually exclusive with week template) ──
    async def assign_shift(self, employee_id: int, pattern_id: int, anchor_date: date) -> None:
        if await self.session.get(ShiftPattern, pattern_id) is None:
            raise HTTPException(status_code=404, detail="Shift pattern not found")
        # clear any week-template assignment
        wt = (await self.session.execute(
            select(EmployeeWeekTemplate).where(EmployeeWeekTemplate.employee_id == employee_id)
        )).scalar_one_or_none()
        if wt is not None:
            await self.session.delete(wt)
        row = await self._employee_shift(employee_id)
        if row is None:
            row = EmployeeShiftAssignment(employee_id=employee_id, shift_pattern_id=pattern_id, anchor_date=anchor_date)
            self.session.add(row)
        else:
            row.shift_pattern_id = pattern_id
            row.anchor_date = anchor_date
        await self.session.commit()

    async def unassign_shift(self, employee_id: int) -> None:
        row = await self._employee_shift(employee_id)
        if row is not None:
            await self.session.delete(row)
            await self.session.commit()

    # ── manual per-employee day override ──
    async def set_employee_day_override(self, employee_id: int, day: date, day_type: str, norm_hours: float, note: str | None) -> EmployeeDayOverride:
        row = await self._employee_override(employee_id, day)
        if row is None:
            row = EmployeeDayOverride(employee_id=employee_id, day=day)
            self.session.add(row)
        row.day_type = day_type
        row.norm_hours = Decimal(str(norm_hours))
        row.note = note
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def delete_employee_day_override(self, employee_id: int, day: date) -> None:
        row = await self._employee_override(employee_id, day)
        if row is not None:
            await self.session.delete(row)
            await self.session.commit()

"""Учёт рабочего времени — порт services/hr/app/services/time_service.py
(+ app/repositories/time_repo.py, слитых воедино — как и у остальных
перенесённых сервисов домена, отдельного репозиторного слоя здесь нет).

Р2: dramatiq-события НЕ портируются (исходник их и не шлёт — TimeService
только логирует через structlog; эквивалент здесь не нужен).

Странность исходника (контракт, не баг): ни create_entry, ни update_entry не
проверяют коллизию UniqueConstraint(employee, date, start_time) заранее —
дубликат падает в IntegrityError, необработанный ни сервисом, ни роутером
исходника, поэтому FastAPI отдаёт обычный 500. Здесь — то же самое: ничего не
перехватывается, IntegrityError всплывает до htqweb.http.api_view, которое
заворачивает любое необработанное исключение в 500 (см. test_time_api.py).
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date as date_
from datetime import timedelta

from apps.hr.models import TimeEntry


class TimeEntryNotFound(Exception):
    """404 "Time entry not found" — порт TimeService.get_entry."""


def _minutes(entry: TimeEntry) -> int:
    start = entry.start_time.hour * 60 + entry.start_time.minute
    end = entry.end_time.hour * 60 + entry.end_time.minute
    return max(0, end - start - entry.break_minutes)


def serialize(entry: TimeEntry) -> dict:
    """TimeEntryOut."""
    return {
        "id": entry.id,
        "employee_id": entry.employee_id,
        "date": entry.date.isoformat(),
        "start_time": entry.start_time.isoformat(),
        "end_time": entry.end_time.isoformat(),
        "break_minutes": entry.break_minutes,
        "description": entry.description,
        "project": entry.project,
        "task": entry.task,
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
    }


def get_entry(id: int) -> TimeEntry:
    entry = TimeEntry.objects.filter(id=id).first()
    if entry is None:
        raise TimeEntryNotFound
    return entry


def list_entries(*, page: int = 1, limit: int = 20) -> tuple[list[TimeEntry], int]:
    """Порт TimeService.list_entries — order_by="date", order="desc"."""
    qs = TimeEntry.objects.order_by("-date")
    total = qs.count()
    offset = (page - 1) * limit
    return list(qs[offset:offset + limit]), total


def create_entry(data) -> TimeEntry:
    return TimeEntry.objects.create(**data.model_dump())


def update_entry(id: int, data) -> TimeEntry:
    entry = get_entry(id)
    # by_alias=True: schemas.TimeEntryUpdate.entry_date is aliased "date" on
    # the wire (see schemas.py docstring — self-shadowing workaround); dump
    # by alias so the patch dict key matches the model field name "date".
    patch = data.model_dump(exclude_none=True, by_alias=True)
    for field, value in patch.items():
        setattr(entry, field, value)
    if patch:
        entry.save()
    return entry


def delete_entry(id: int) -> None:
    entry = get_entry(id)
    entry.delete()


def _entries_for_employee(employee_id: int, date_from: date_, date_to: date_) -> list[TimeEntry]:
    """Порт TimeRepository.get_entries_for_employee — order_by(date, start_time)."""
    return list(
        TimeEntry.objects
        .filter(employee_id=employee_id, date__gte=date_from, date__lte=date_to)
        .order_by("date", "start_time")
    )


def daily_report(employee_id: int, day: date_) -> dict:
    entries = _entries_for_employee(employee_id, day, day)
    total = sum(_minutes(e) for e in entries)
    return {
        "date": day.isoformat(),
        "employee_id": employee_id,
        "total_minutes": total,
        "entries": [serialize(e) for e in entries],
    }


def weekly_report(employee_id: int, week_start: date_) -> dict:
    week_end = week_start + timedelta(days=6)
    entries = _entries_for_employee(employee_id, week_start, week_end)

    days_map: dict[date_, list[TimeEntry]] = {}
    for e in entries:
        days_map.setdefault(e.date, []).append(e)

    daily: list[dict] = []
    for i in range(7):
        day = week_start + timedelta(days=i)
        day_entries = days_map.get(day, [])
        total = sum(_minutes(e) for e in day_entries)
        daily.append({
            "date": day.isoformat(),
            "employee_id": employee_id,
            "total_minutes": total,
            "entries": [serialize(e) for e in day_entries],
        })

    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "employee_id": employee_id,
        "total_minutes": sum(d["total_minutes"] for d in daily),
        "daily": daily,
    }


def monthly_report(employee_id: int, year: int, month: int) -> dict:
    _, last_day = monthrange(year, month)
    entries = _entries_for_employee(employee_id, date_(year, month, 1), date_(year, month, last_day))
    total = sum(_minutes(e) for e in entries)

    weeks: dict[date_, list[TimeEntry]] = {}
    for e in entries:
        week_start = e.date - timedelta(days=e.date.weekday())
        weeks.setdefault(week_start, []).append(e)

    weekly_reports: list[dict] = []
    for ws in sorted(weeks):
        week_entries = weeks[ws]
        week_end = ws + timedelta(days=6)
        weekly_reports.append({
            "week_start": ws.isoformat(),
            "week_end": week_end.isoformat(),
            "employee_id": employee_id,
            "total_minutes": sum(_minutes(e) for e in week_entries),
            "daily": [],
        })

    return {
        "year": year,
        "month": month,
        "employee_id": employee_id,
        "total_minutes": total,
        "weekly": weekly_reports,
    }

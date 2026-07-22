"""Read/replace Т-2 repeating groups (education/experience/relatives) — порт
services/hr/app/services/employee_groups_service.py.

Ex-Mongo коллекция ``hr_employee_groups`` -> JSONB (решение D6) — модель
``apps.hr.models.EmployeeGroups`` уже перенесена под-модулем docs (её
докстринг). В отличие от исходника (3 отдельных top-level поля Mongo-
документа: ``education``/``experience``/``relatives``, каждое — своя
Mongo-колонка) здесь единственная колонка ``data`` (JSONField) несёт все три
списка как один JSON-объект ``{"education": [...], "experience": [...],
"relatives": [...]}`` — форма МОДЕЛИ (см. её докстринг), не сервиса; сервис
лишь читает/пишет под этими ключами внутри ``data``.

НЕТ "graceful degrade при недоступном Mongo" исходника (``get_hr_groups_
collection() is None`` -> пустые списки без обращения к хранилищу) — JSONB
всегда доступен вместе с Postgres, отдельного транспорта нет, деградировать
нечему; недостающая строка (сотрудник ещё не заполнял Т-2 группы) даёт те же
пустые списки, что и исходник для отсутствующего Mongo-документа.
"""
from __future__ import annotations

from typing import Any

from apps.hr.models import EmployeeGroups

_LISTS = ("education", "experience", "relatives")


def read(employee_id: int) -> dict[str, list]:
    row = EmployeeGroups.objects.filter(employee_id=employee_id).first()
    if row is None:
        return {k: [] for k in _LISTS}
    data = row.data or {}
    return {k: list(data.get(k) or []) for k in _LISTS}


def replace(employee_id: int, groups: dict[str, Any]) -> dict[str, list]:
    row, _created = EmployeeGroups.objects.get_or_create(employee_id=employee_id)
    data = dict(row.data or {})
    for k in _LISTS:
        if k in groups and groups[k] is not None:
            data[k] = groups[k]
    row.data = data
    row.save()
    return read(employee_id)

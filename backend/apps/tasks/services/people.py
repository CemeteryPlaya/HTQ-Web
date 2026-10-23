"""Поиск людей для окна карточки (участники, этап S2).

Только действующие учётки — участники ТЕКУЩЕЙ компании: исполнителем задачи
компании не может стать человек, у которого нет в неё входа и который её
задачу даже не увидит. Поиск — по имени, логину и почте (``users``); состав
компании — ``companies.interface.active_member_ids``.
"""

from __future__ import annotations

from apps.companies import interface as companies
from apps.users import interface as users
from htqweb.tenancy.context import current_company_or_none

#: Сколько совпадений по всей платформе просматривать до отбора по компании:
#: поиск идёт от двух букв, совпадений единицы-десятки.
SCAN_LIMIT = 200


def search(query: str, limit: int) -> list[dict]:
    query = (query or "").strip()
    if len(query) < 2:
        return []
    rows = [row for row in users.list_users_brief(search=query, limit=SCAN_LIMIT)
            if row.get("is_active", True)]
    slug = current_company_or_none()
    if slug:
        members = set(companies.active_member_ids(slug))
        rows = [row for row in rows if row["id"] in members]
    return [{"id": row["id"],
             "full_name": row.get("full_name") or row.get("username") or "",
             "email": row.get("email") or "",
             "username": row.get("username") or ""}
            for row in rows[:limit]]

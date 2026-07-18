"""Read/replace Т-2 repeating groups in Mongo.

Gracefully degrades to empty lists when Mongo is not configured
(``mongo_uri`` empty) — mirrors the existing hr_documents fallback.
"""

from __future__ import annotations

from typing import Any

from app.mongo import get_hr_groups_collection

_LISTS = ("education", "experience", "relatives")


class EmployeeGroupsService:
    async def read(self, employee_id: int) -> dict[str, list]:
        coll = get_hr_groups_collection()
        if coll is None:
            return {k: [] for k in _LISTS}
        doc = await coll.find_one({"employee_id": employee_id})
        if not doc:
            return {k: [] for k in _LISTS}
        return {k: list(doc.get(k) or []) for k in _LISTS}

    async def replace(self, employee_id: int, groups: dict[str, Any]) -> dict[str, list]:
        coll = get_hr_groups_collection()
        if coll is None:
            return {k: [] for k in _LISTS}
        update: dict[str, Any] = {"employee_id": employee_id}
        for k in _LISTS:
            if k in groups and groups[k] is not None:
                update[k] = groups[k]
        await coll.update_one({"employee_id": employee_id}, {"$set": update}, upsert=True)
        return await self.read(employee_id)

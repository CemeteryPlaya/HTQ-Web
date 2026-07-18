"""Read/UPSERT the Т-2 scalar card with per-section RBAC."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.hr_access import HRAccess
from app.models.employee_card import EmployeeCard

_SECTIONS: dict[str, tuple[tuple[str, ...], str, str]] = {
    "financial": (("salary", "bonus", "bank_account"),
                  "hr.card.financial.view", "hr.card.financial.edit"),
    "personal": (("passport_data", "inn", "birth_date", "birth_place", "citizenship"),
                 "hr.card.personal.view", "hr.card.personal.edit"),
    "certs": (("sro_permit_number", "sro_permit_expiry", "safety_cert_number", "safety_cert_expiry"),
              "hr.card.certs.view", "hr.card.certs.edit"),
}
_MONEY = {"salary", "bonus"}


def _serialize(field: str, value):
    if value is None:
        return None
    if field in _MONEY:
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


class EmployeeCardT2Service:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _get(self, employee_id: int) -> EmployeeCard | None:
        stmt = select(EmployeeCard).where(EmployeeCard.employee_id == employee_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def read_sections(self, employee_id: int, access: HRAccess) -> dict:
        card = await self._get(employee_id)
        out: dict = {}
        for section, (fields, view_key, _edit) in _SECTIONS.items():
            if not access.has(view_key):
                continue
            out[section] = {
                f: _serialize(f, getattr(card, f, None) if card else None) for f in fields
            }
        return out

    async def upsert(self, employee_id: int, patch: dict, access: HRAccess) -> dict:
        card = await self._get(employee_id)
        if card is None:
            card = EmployeeCard(employee_id=employee_id)
            self.session.add(card)
        for section, values in patch.items():
            if values is None:
                continue
            fields, _view, edit_key = _SECTIONS[section]
            if not access.has(edit_key):
                raise PermissionError(f"Missing permission: {edit_key}")
            data = values if isinstance(values, dict) else values.model_dump(exclude_unset=True)
            for f, v in data.items():
                if f not in fields:
                    continue
                if f in _MONEY and v is not None:
                    try:
                        v = Decimal(str(v))
                    except (InvalidOperation, ValueError):
                        raise ValueError(f"Invalid decimal for {f}: {v!r}")
                setattr(card, f, v)
        await self.session.commit()
        await self.session.refresh(card)
        return await self.read_sections(employee_id, access)

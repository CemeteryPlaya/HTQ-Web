"""Read/UPSERT the Т-2 scalar card with per-section RBAC — порт
services/hr/app/services/employee_card_t2_service.py.

Функции, а не класс (та же конвенция порта, что department_service.py/
pmo_service.py/… — исходник был class-based только из-за DI асинхронной
SQLAlchemy-сессии, здесь синхронный Django ORM без сессии).

Гейтинг СЕКЦИОННЫЙ, не по каждому полю отдельно: ``_SECTIONS`` — карта
секция -> (поля, view-ключ, edit-ключ), буквальный порт исходника. Это
единственное место, где решается, какие Т-2 поля видны/редактируемы по
HRAccess — вьюха (``apps/hr/views.py``) не знает о секциях, только зовёт
``read_sections``/``upsert``.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from apps.hr.access import HRAccess
from apps.hr.models import EmployeeCard

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


def _get(employee_id: int) -> EmployeeCard | None:
    return EmployeeCard.objects.filter(employee_id=employee_id).first()


def read_sections(employee_id: int, access: HRAccess) -> dict:
    card = _get(employee_id)
    out: dict = {}
    for section, (fields, view_key, _edit) in _SECTIONS.items():
        if not access.has(view_key):
            continue
        out[section] = {
            f: _serialize(f, getattr(card, f, None) if card else None) for f in fields
        }
    return out


def upsert(employee_id: int, patch: dict, access: HRAccess) -> dict:
    """Порт ``EmployeeCardT2Service.upsert``.

    ``card.save()`` СЛУЧАЕТСЯ ТОЛЬКО ПОСЛЕ успешного прохода всего цикла —
    буквальный паритет с исходником, где ``session.add(card)`` без
    промежуточного ``commit()`` означает, что ``PermissionError``/
    ``ValueError``, поднятые в середине multi-секционного патча, откатывают
    ВСЁ (включая уже применённые setattr на более ранние по порядку секции),
    не только оставшуюся часть. Порядок секций — порядок ``patch.items()``,
    то есть порядок полей ``EmployeeCardT2Patch`` (financial, personal,
    certs), а не порядок ключей JSON-тела запроса.
    """
    card = _get(employee_id)
    if card is None:
        card = EmployeeCard(employee_id=employee_id)

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

    card.save()
    return read_sections(employee_id, access)

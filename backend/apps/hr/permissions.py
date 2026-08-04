"""HR permission keys + level presets — данные, порт services/hr/app/auth/permissions.py.

Ключи — авторитетная единица HR-авторизации (проверяется в HRAccess.has /
require_permission исходника). ``hr_level`` — UI/миграционный пресет: выбор
уровня заполняет ``permissions[]`` должности соответствующим пресетом.

Этот модуль сейчас используется только для статического permissions-catalog
эндпойнта positions (``LEVEL_PRESETS``). ``ALL_KEYS``/``expand_level``
переносятся как данные вместе с остальным файлом по прямому указанию брифа —
их потребитель (``app/auth/hr_access.py``) относится к под-модулю employees
и переносится отдельной задачей.
"""

from __future__ import annotations

from typing import Literal

HRLevel = Literal["junior", "middle", "senior", "lead"]

# ── Канонические ключи прав ─────────────────────────────────────────────────
EMPLOYEES_VIEW = "hr.employees.view"
EMPLOYEES_VIEW_ALL = "hr.employees.view.all"
EMPLOYEES_CREATE = "hr.employees.create"
EMPLOYEES_EDIT = "hr.employees.edit"
EMPLOYEES_DELETE = "hr.employees.delete"
EMPLOYEES_TRANSFER = "hr.employees.transfer"
DEPARTMENTS_VIEW = "hr.departments.view"
DEPARTMENTS_EDIT = "hr.departments.edit"
POSITIONS_VIEW = "hr.positions.view"
POSITIONS_EDIT = "hr.positions.edit"
DOCUMENTS_VIEW = "hr.documents.view"
DOCUMENTS_MANAGE = "hr.documents.manage"
REPORTS_VIEW = "hr.reports.view"
USERS_LIST = "hr.users.list"
USERS_MANAGE = "hr.users.manage"
CARD_FINANCIAL_VIEW = "hr.card.financial.view"
CARD_FINANCIAL_EDIT = "hr.card.financial.edit"
CARD_PERSONAL_VIEW = "hr.card.personal.view"
CARD_PERSONAL_EDIT = "hr.card.personal.edit"
CARD_GROUPS_VIEW = "hr.card.groups.view"
CARD_GROUPS_EDIT = "hr.card.groups.edit"
CALENDAR_VIEW = "hr.calendar.view"
CALENDAR_MANAGE = "hr.calendar.manage"
STAFFING_VIEW = "hr.staffing.view"
STAFFING_MANAGE = "hr.staffing.manage"

ALL_KEYS: frozenset[str] = frozenset({
    EMPLOYEES_VIEW, EMPLOYEES_VIEW_ALL, EMPLOYEES_CREATE, EMPLOYEES_EDIT,
    EMPLOYEES_DELETE, EMPLOYEES_TRANSFER, DEPARTMENTS_VIEW, DEPARTMENTS_EDIT,
    POSITIONS_VIEW, POSITIONS_EDIT, DOCUMENTS_VIEW, DOCUMENTS_MANAGE,
    REPORTS_VIEW, USERS_LIST, USERS_MANAGE,
    CARD_FINANCIAL_VIEW, CARD_FINANCIAL_EDIT, CARD_PERSONAL_VIEW, CARD_PERSONAL_EDIT,
    CARD_GROUPS_VIEW, CARD_GROUPS_EDIT,
    CALENDAR_VIEW, CALENDAR_MANAGE,
    STAFFING_VIEW, STAFFING_MANAGE,
})

_JUNIOR = frozenset({EMPLOYEES_VIEW, DEPARTMENTS_VIEW, POSITIONS_VIEW, DOCUMENTS_VIEW, CALENDAR_VIEW})
_MIDDLE = _JUNIOR | {EMPLOYEES_EDIT, DEPARTMENTS_EDIT, POSITIONS_EDIT, DOCUMENTS_MANAGE,
                     CARD_GROUPS_VIEW, CARD_GROUPS_EDIT}
_SENIOR = _MIDDLE | {EMPLOYEES_VIEW_ALL, EMPLOYEES_CREATE, EMPLOYEES_TRANSFER, USERS_LIST, REPORTS_VIEW,
                     CARD_FINANCIAL_VIEW, CARD_FINANCIAL_EDIT, CARD_PERSONAL_VIEW, CARD_PERSONAL_EDIT,
                     CALENDAR_MANAGE, STAFFING_VIEW, STAFFING_MANAGE}
_LEAD = _SENIOR | {EMPLOYEES_DELETE, USERS_MANAGE}

LEVEL_PRESETS: dict[str, frozenset[str]] = {
    "junior": _JUNIOR,
    "middle": _MIDDLE,
    "senior": _SENIOR,
    "lead": _LEAD,
}


def expand_level(level: str | None) -> frozenset[str]:
    """Пресет ключей для уровня; пустое множество для неизвестного/None."""
    if not level:
        return frozenset()
    return LEVEL_PRESETS.get(level, frozenset())

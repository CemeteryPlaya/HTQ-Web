"""HR permission keys + level presets — данные, порт services/hr/app/auth/permissions.py.

Ключи остаются авторитетной единицей HR-авторизации, но с задачи 9 блока I
«Единая модель прав» проверяются НЕ через них напрямую: вьюхи зовут
``apps.hr.rbac.NodeAccess.has(key)``, который раскрывает ключ в узел реестра
``apps.access`` + набор признаков через ``legacy_roles.KEY_TO_NODE`` и
проверяет их там. ``hr_level``/``LEVEL_PRESETS`` живут дальше как:
UI-пресет позиций (``_PERMISSION_CATALOG`` в ``apps/hr/views.py``) и
единственный источник для эвристики переноса
(``apps.hr.access.classify_hr_level`` → ``access_backfill_positions``,
задача 2 того же блока). ``ALL_KEYS``/``expand_level`` живых читателей
больше не имеют (их звал только снятый резолвер ``resolve_hr_access``) и
остаются как данные без нагрузки — удалять не входит в объём задачи 9.
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
ORG_EDIT = "hr.org.edit"
DOCUMENTS_VIEW = "hr.documents.view"
DOCUMENTS_MANAGE = "hr.documents.manage"
REPORTS_VIEW = "hr.reports.view"
USERS_LIST = "hr.users.list"
USERS_MANAGE = "hr.users.manage"
# Сверка идентичности Сотрудник<->Аккаунт: view — читать очередь заявок,
# manage — назначать подтверждающего. Право РЕШАТЬ сюда не входит вовсе:
# оно не кадровое, а принадлежит подтверждающему (спека 2026-08-25 §9).
IDENTITY_VIEW = "hr.identity.view"
IDENTITY_MANAGE = "hr.identity.manage"
# Право писать идентичность НАПРЯМУЮ, минуя подтверждение владельцем аккаунта.
# Намеренно НЕ входит ни в один уровень (даже в lead): обычный порядок — правка
# уходит заявкой человеку, чьи это имя и телефон, и обходить его должен тот, кому
# это выдали осознанно, а не всякий, кто дорос до уровня. Выдаётся отдельной
# галкой в матрице прав должности.
IDENTITY_FORCE = "hr.identity.force"
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
# Права предметных аппок живут рядом с HR-матрицей: должность «Бухгалтер»
# получает это право в своём ``Position.permissions`` и contracts проверяет
# его только через ``apps.hr.interface``.
CONTRACTS_ADVANCE_PAYMENT_RECORD_PAYMENT = "contracts.advance_payment.record_payment"

ALL_KEYS: frozenset[str] = frozenset({
    EMPLOYEES_VIEW, EMPLOYEES_VIEW_ALL, EMPLOYEES_CREATE, EMPLOYEES_EDIT,
    EMPLOYEES_DELETE, EMPLOYEES_TRANSFER, DEPARTMENTS_VIEW, DEPARTMENTS_EDIT,
    POSITIONS_VIEW, POSITIONS_EDIT, ORG_EDIT, DOCUMENTS_VIEW, DOCUMENTS_MANAGE,
    REPORTS_VIEW, USERS_LIST, USERS_MANAGE, IDENTITY_VIEW, IDENTITY_MANAGE,
    IDENTITY_FORCE,
    CARD_FINANCIAL_VIEW, CARD_FINANCIAL_EDIT, CARD_PERSONAL_VIEW, CARD_PERSONAL_EDIT,
    CARD_GROUPS_VIEW, CARD_GROUPS_EDIT,
    CALENDAR_VIEW, CALENDAR_MANAGE,
    STAFFING_VIEW, STAFFING_MANAGE,
    CONTRACTS_ADVANCE_PAYMENT_RECORD_PAYMENT,
})

_JUNIOR = frozenset({EMPLOYEES_VIEW, DEPARTMENTS_VIEW, POSITIONS_VIEW, DOCUMENTS_VIEW, CALENDAR_VIEW})
_MIDDLE = _JUNIOR | {EMPLOYEES_EDIT, DEPARTMENTS_EDIT, POSITIONS_EDIT, DOCUMENTS_MANAGE,
                     CARD_GROUPS_VIEW, CARD_GROUPS_EDIT}
_SENIOR = _MIDDLE | {EMPLOYEES_VIEW_ALL, EMPLOYEES_CREATE, EMPLOYEES_TRANSFER, USERS_LIST, REPORTS_VIEW,
                     CARD_FINANCIAL_VIEW, CARD_FINANCIAL_EDIT, CARD_PERSONAL_VIEW, CARD_PERSONAL_EDIT,
                     CALENDAR_MANAGE, STAFFING_VIEW, STAFFING_MANAGE, ORG_EDIT,
                     IDENTITY_VIEW}
_LEAD = _SENIOR | {EMPLOYEES_DELETE, USERS_MANAGE, IDENTITY_MANAGE}

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

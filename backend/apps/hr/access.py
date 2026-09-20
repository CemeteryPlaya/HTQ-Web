"""Эвристика ПЕРЕНОСА кадровых уровней — НЕ модель прав.

До задачи 9 блока I «Единая модель прав» этот модуль был параллельной
моделью прав кадрового домена (порт ``services/hr/app/auth/hr_access.py``):
``resolve_hr_access`` угадывал уровень вызывающего по названию его должности
(или брал явный ``Position.permissions["hr_level"]``), раскрывал его в набор
ключей ``apps.hr.permissions``, и вьюхи проверяли ``access.can_*`` в теле —
рядом с модульным гейтом ``api_view(module="hr", …)``, «И-И». Задача 9 сняла
резолвер целиком: права считает ``apps.hr.rbac`` по узлам реестра
``apps.access``, единственным источником.

Что осталось и зачем. ``classify_hr_level`` и ``_level_from_permissions``
нужны ОДНОМУ вызывающему — ``apps.hr.interface.list_positions_hr_levels``,
источнику для команды переноса ``manage.py access_backfill_positions``
(задача 2 того же блока): она переводит вчерашние уровни должностей в
сегодняшние роли ``hr-junior``…``hr-lead``, и угадывать их обязана ТЕМ ЖЕ
порядком, каким их видел живой запрос до переноса, — иначе перенос выдал бы
не те права, что были. Это единственное законное применение угадывания по
названию; сторож ``apps/hr/tests/test_single_rbac_guards.py`` не пускает
никого другого. Когда перенос на всех боевых компаниях выполнен и команда
уходит, уходит и этот файл.
"""
from __future__ import annotations

from typing import Literal

from apps.hr.models import Employee

HRLevel = Literal["junior", "middle", "senior", "lead"]


def _normalize(value: str | None) -> str:
    return (value or "").strip().lower().replace("_", " ").replace("-", " ")


_VALID_LEVELS: set[str] = {"junior", "middle", "senior", "lead"}


def _level_from_permissions(position) -> HRLevel | None:
    """Явный ``permissions.hr_level`` должности приоритетнее эвристики.

    Колонка ``Position.permissions`` с задачи 9 мертва для прав (её не
    пишет ни сид, ни ``participant_service``; читает только этот помощник —
    ради переноса — и ``interface.user_has_permission`` — ради ключей
    ``contracts``), но на боевых данных, заведённых ДО переноса, явный
    уровень там ещё лежит и должен пережить перенос как есть.
    """
    perms = getattr(position, "permissions", None)
    if not isinstance(perms, dict):
        return None
    hr_level = perms.get("hr_level")
    if hr_level in _VALID_LEVELS:
        return hr_level  # type: ignore[return-value]
    return None


def classify_hr_level(employee: Employee | None) -> HRLevel | None:
    """Эвристика по HR-отделу/должности сотрудника — только для переноса.

    Порядок разрешения:
    1. ``position.permissions.hr_level`` — явный оверрайд.
    2. Эвристика по названию/отделу — legacy-фолбэк для системных должностей.

    Строковые маркеры — БУКВАЛЬНЫЙ порт исходника: перенос обязан
    воспроизвести те же уровни, что старая модель выдавала до него.
    """
    if not employee:
        return None

    explicit = _level_from_permissions(getattr(employee, "position", None))
    if explicit is not None:
        return explicit

    position = _normalize(getattr(employee.position, "title", None))
    department = _normalize(getattr(employee.department, "name", None))
    haystack = f"{position} {department}"

    is_hr = any(
        marker in haystack
        for marker in (
            "hr",
            "human resources",
            "people",
            "персонал",
            "кадр",
            "эйчар",
        )
    )
    if not is_hr:
        return None

    if any(
        marker in haystack
        for marker in (
            "co hr",
            "cohr",
            "chief hr",
            "chief human resources",
            "chief people",
            "cpo",
            "hr director",
            "director hr",
            "руководитель hr",
            "директор по персоналу",
        )
    ):
        return "lead"

    if any(marker in haystack for marker in ("senior", "lead", "head", "старш", "ведущ")):
        return "senior"

    if any(marker in haystack for marker in ("middle", "middel", "mid ", "manager", "менеджер", "специалист")):
        return "middle"

    if any(marker in haystack for marker in ("junior", "assistant", "trainee", "младш", "ассист", "стаж")):
        return "junior"

    return "junior"

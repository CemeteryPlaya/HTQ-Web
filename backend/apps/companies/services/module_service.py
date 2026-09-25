"""Модули одной компании — второй, компанейский слой рубильника.

Список модулей — ``KNOWN_SERVICES`` из ``apps.core`` (общий фундамент, его
импортировать можно): второго справочника платформа не заводит, иначе два
списка разъедутся. ``CORE_MODULES`` на уровне компании не выключаются — это
обязательное ядро, которое есть у каждой компании (CLAUDE.md,
«Два независимых рубильника»).

Отсутствие строки ``CompanyModule`` означает «включено» (докстринг модели),
поэтому включение — удаление строки, а не запись ``enabled=True``: иначе
таблица обрастала бы строками, ничего не значащими.
"""

from __future__ import annotations

from apps.companies.models import Company, CompanyModule
from apps.core.models import KNOWN_SERVICES
from apps.core.services import CORE_MODULES


class UnknownModule(Exception):
    def __init__(self, app_label: str) -> None:
        self.detail = f"Модуля {app_label} нет в реестре сервисов платформы."
        super().__init__(self.detail)


class CoreModuleLocked(Exception):
    def __init__(self, app_label: str) -> None:
        self.detail = (f"Модуль {app_label} — ядро платформы и на уровне "
                       "компании не выключается.")
        super().__init__(self.detail)


def _row(app_label: str, stored: CompanyModule | None) -> dict:
    return {
        "app_label": app_label,
        "enabled": True if stored is None else stored.enabled,
        "message": "" if stored is None else stored.message,
        "is_core": app_label in CORE_MODULES,
    }


def list_modules(company: Company) -> list[dict]:
    stored = {m.app_label: m for m in company.modules.all()}
    return [_row(name, stored.get(name)) for name in KNOWN_SERVICES]


def set_module(company: Company, app_label: str, *, enabled: bool,
               message: str | None = None) -> dict:
    if app_label not in KNOWN_SERVICES:
        raise UnknownModule(app_label)
    if app_label in CORE_MODULES:
        raise CoreModuleLocked(app_label)
    if enabled:
        CompanyModule.objects.filter(company=company, app_label=app_label).delete()
        return _row(app_label, None)
    defaults = {"enabled": False}
    if message:
        defaults["message"] = message
    stored, _ = CompanyModule.objects.update_or_create(
        company=company, app_label=app_label, defaults=defaults,
    )
    return _row(app_label, stored)

"""«Проекты» из 1С: идемпотентный upsert одной записи (A7.3, D-38, D-S7-5).

Заготовка без запуска: функция принимает уже прочитанную запись справочника
1С. Сопоставление — по ``ext_1c_ref``, затем по коду проекта (естественный
ключ). Найденный по коду «Проект» без кода 1С связывается (название не
перезаписывается), с ДРУГИМ непустым кодом — ``conflict``. Смена кода уже
связанного проекта через 1С запрещена — ``rejected``. Каждая запись — под
своей точкой сохранения.
"""

from __future__ import annotations

from django.db import DataError, IntegrityError, transaction

from apps.project.models import Project
from apps.refdata import interface as refdata
from htqweb.integrations.onec import (
    CONFLICT,
    CREATED,
    REJECTED,
    UNCHANGED,
    UPDATED,
    Outcome,
    is_guid,
)

from . import projects

#: Отображение полей OData-справочника 1С → «Проект».
#: ⚠️ ПРЕДПОЛОЖЕНИЕ: имена реквизитов — типовые, уточнить у администратора 1С
#: (Q-S7-2).
FIELD_MAP = {
    "ext_1c_ref": "Ref_Key",
    "code": "Code",
    "name": "Description",
    "country_code": "КодСтраны",      # нет в записи — «KZ»
}
DEFAULT_COUNTRY = "KZ"


def _get(record: dict, field: str) -> str:
    return str(record.get(FIELD_MAP[field]) or "").strip()


def upsert_project(record: dict) -> Outcome:
    """Один «Проект» из 1С → ``Outcome``. Зовётся в контексте компании."""
    ref = _get(record, "ext_1c_ref").lower()
    if not is_guid(ref):
        return Outcome(REJECTED, "Нет корректного GUID записи 1С (Ref_Key).")
    code, name = _get(record, "code"), _get(record, "name")
    if not code or not name:
        return Outcome(REJECTED, "У записи 1С нет кода или наименования проекта.")
    try:
        with transaction.atomic():
            return _upsert(ref, code, name, (_get(record, "country_code") or DEFAULT_COUNTRY).upper())
    except (IntegrityError, projects.ProjectError):
        return Outcome(CONFLICT, "Запись 1С конкурирует с другим проектом за уникальный ключ.")
    except DataError:  # обрыв соединения и прочие сбои БД — не «длинное значение», пробрасываются
        return Outcome(REJECTED, "Запись 1С не помещается в поля проекта (слишком длинное значение).")


def _upsert(ref: str, code: str, name: str, country: str) -> Outcome:
    linked = Project.objects.filter(ext_1c_ref=ref).first()  # хранится только нижний регистр (D-S8-4)
    if linked is not None:
        if linked.code != code:
            return Outcome(REJECTED, "Код связанного проекта меняется только в «Проектах», "
                                     "не через 1С.", str(linked.pk))
        if linked.name == name:
            return Outcome(UNCHANGED, object_id=str(linked.pk))
        projects.update(linked, actor_id=None, name=name)
        return Outcome(UPDATED, object_id=str(linked.pk))

    same = Project.objects.filter(code=code).first()
    if same is not None:
        if same.ext_1c_ref and same.ext_1c_ref != ref:
            return Outcome(CONFLICT, "Проект с этим кодом уже связан с другой записью 1С "
                                     f"({same.ext_1c_ref}); данные не тронуты.", str(same.pk))
        projects.update(same, actor_id=None, ext_1c_ref=ref)
        return Outcome(UPDATED, "Проект связан с записью 1С по коду.", str(same.pk))

    country_card = refdata.country_brief([country]).get(country)
    if not country_card or not country_card["is_active"]:
        return Outcome(REJECTED, f"Страна «{country}» не найдена в справочнике или в архиве.")
    created = projects.create(code=code, name=name, country_code=country, actor_id=None,
                              ext_1c_ref=ref)
    return Outcome(CREATED, object_id=str(created.pk))

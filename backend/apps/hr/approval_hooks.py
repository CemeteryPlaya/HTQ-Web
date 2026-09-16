"""Кадровые предметы согласования — блок G, матрица HR-FRM-004.

Здесь домен кадров ОБЪЯВЛЯЕТ свои объекты согласуемыми и отдаёт про них
три вещи: как назвать предмет согласующему (``describe``), какие факты он
несёт (``facts``) и какие из этих фактов можно предлагать в редакторе
маршрута (``fact_fields``). Сам движок, маршруты и виды согласующих — чужая
зона (``apps.signoff``), и этот файл её не касается.

Факты — главное в блоке. По ним маршрут ветвится, и roadmap §6.2 называет
три поимённо: сумма премии, срок отпуска, категория должности. Ключ факта —
часть контракта со вторым разработчиком: переименовать его молча значит
сломать условие в уже настроенном маршруте.

Устройство каждого предмета — тройка функций с общим соглашением:

* ``describe`` возвращает ``None``, если объект удалён: карточка процесса
  просто останется без заголовка, а не упадёт;
* ``facts`` возвращает ПУСТОЙ словарь по той же причине — условный маршрут
  честно откажет «не сошлось ни одно условие», безусловный отработает;
* ``fact_fields`` обязан описывать ровно те ключи, что отдаёт ``facts``:
  поле, которого на запуске не окажется, даст условие, падающее уже в руках
  пользователя (``register_subject`` это частично проверяет сам).

Образец — ``apps/contracts/approval_hooks.py``.
"""

from apps.hr.models import Department, Position, StaffingPosition
from apps.signoff import interface as signoff


# ── строка 2: штатное расписание ─────────────────────────────────────────

def _describe_staffing(subject_id: int) -> dict | None:
    line = (StaffingPosition.objects
            .select_related("position", "department")
            .filter(pk=subject_id).first())
    if line is None:
        return None
    return {
        "title": (f"Штатная единица: {line.position.title} — "
                  f"{line.department.name}, {line.headcount} ед., "
                  f"оклад {line.salary}"),
        "url": f"/hr/staffing/{line.pk}",
    }


def _staffing_facts(subject_id: int) -> dict:
    line = (StaffingPosition.objects
            .select_related("position")
            .filter(pk=subject_id).first())
    if line is None:
        return {}
    return {
        "department_id": line.department_id,
        "position_id": line.position_id,
        # Категория должности (roadmap §6.2) — уровень в иерархии: по нему
        # маршрут отличает специалиста от руководителя блока.
        "position_level": line.position.level,
        "headcount": line.headcount,
        "salary": line.salary,
        # «ФОТ — в пределах бюджета» (примечание документа к строке 2)
        # считается по строке целиком, а не по окладу одного человека.
        "payroll": line.salary * line.headcount,
    }


def _staffing_fact_fields() -> list[dict]:
    return [
        {"key": "department_id", "label": "Подразделение", "type": "choice",
         "options": _department_options()},
        {"key": "position_id", "label": "Должность", "type": "number"},
        {"key": "position_level", "label": "Уровень должности", "type": "number"},
        {"key": "headcount", "label": "Штатных единиц", "type": "number"},
        {"key": "salary", "label": "Оклад", "type": "number"},
        {"key": "payroll", "label": "ФОТ по строке", "type": "number"},
    ]


def _department_options() -> list[dict]:
    """Подразделения текущей компании для редактора условий.

    Читается на КАЖДЫЙ показ редактора, а не кэшируется: список меняется
    реорганизациями, и устаревший выбор здесь означает условие, указывающее
    на несуществующий отдел.
    """
    return [{"value": d.id, "label": d.name}
            for d in Department.objects.filter(is_active=True).order_by("path")]


# ── регистрация ──────────────────────────────────────────────────────────

#: Тип предмета → класс модели. Единственное место соответствия: и
#: register(), и approval_service берут его отсюда.
SUBJECT_MODELS: dict[str, type] = {
    StaffingPosition.SIGNOFF_SUBJECT_TYPE: StaffingPosition,
}

#: Тип предмета → как его показывать и по каким фактам ветвить маршрут.
SUBJECT_SPECS: dict[str, dict] = {
    StaffingPosition.SIGNOFF_SUBJECT_TYPE: {
        "label": "Штатная единица",
        "describe": _describe_staffing,
        "facts": _staffing_facts,
        "fact_fields": _staffing_fact_fields,
    },
}


def register() -> None:
    """Объявить кадровые объекты согласуемыми. Зовётся из HrConfig.ready().

    Явный вызов, а не автопоиск модулей: автопоиск — тот же межаппный
    импорт, только спрятанный от проверки границ. Здесь его видно и
    человеку, и грепу.

    Идёт по ``SUBJECT_MODELS``/``SUBJECT_SPECS``, а не вызывает
    ``register_subject`` по разу на предмет вручную: добавление восьмого
    предмета (задачи 2–8 этого блока) становится одной записью в каждой
    таблице, а не новой веткой кода здесь.
    """
    for subject_type, model in SUBJECT_MODELS.items():
        signoff.register_subject(subject_type, model=model,
                                 **SUBJECT_SPECS[subject_type])

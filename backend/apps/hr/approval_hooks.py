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

from apps.hr.models import (
    Department, PersonnelHistory, PersonnelHistoryEventType, PersonnelOrder,
    PersonnelOrderKind, StaffingPosition,
)
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


# ── строки 5, 6, 7: кадровый приказ ──────────────────────────────────────

_ORDER_EVENT = {
    PersonnelOrderKind.HIRE: PersonnelHistoryEventType.HIRED,
    PersonnelOrderKind.DISMISS: PersonnelHistoryEventType.DISMISSED,
    PersonnelOrderKind.TRANSFER: PersonnelHistoryEventType.TRANSFER,
}


def _describe_personnel_order(subject_id: int) -> dict | None:
    order = (PersonnelOrder.objects
             .select_related("position", "department", "employee")
             .filter(pk=subject_id).first())
    if order is None:
        return None
    who = (f"{order.employee.last_name} {order.employee.first_name}"
           if order.employee_id else order.candidate_name)
    return {
        "title": (f"{order.get_kind_display()}: {who} — {order.position.title}, "
                  f"{order.department.name}, с {order.effective_date.isoformat()}"),
        "url": f"/hr/orders/{order.pk}",
    }


def _personnel_order_facts(subject_id: int) -> dict:
    order = (PersonnelOrder.objects
             .select_related("position")
             .filter(pk=subject_id).first())
    if order is None:
        return {}
    return {
        "kind": order.kind,
        "position_id": order.position_id,
        # Категория должности (roadmap §6.2): уровень и признак руководителя
        # — то, чем строка 5 матрицы отличается от строки 6.
        "position_level": order.position.level,
        "is_manager": order.position.is_manager,
        # Пусто для своей компании. Строка 7 — назначение директора ДО.
        "target_company_slug": order.target_company_slug or None,
        "salary": order.salary,
        "effective_date": order.effective_date.isoformat(),
    }


def _personnel_order_fact_fields() -> list[dict]:
    return [
        {"key": "kind", "label": "Вид приказа", "type": "choice",
         "options": [{"value": v, "label": l} for v, l in PersonnelOrderKind.choices]},
        {"key": "position_id", "label": "Должность", "type": "number"},
        {"key": "position_level", "label": "Уровень должности", "type": "number"},
        {"key": "is_manager", "label": "Руководящая должность", "type": "boolean"},
        {"key": "target_company_slug", "label": "Компания назначения", "type": "string"},
        {"key": "salary", "label": "Оклад", "type": "number"},
        {"key": "effective_date", "label": "Дата вступления в силу", "type": "string"},
    ]


def _personnel_order_on_approved(subject_id: int) -> None:
    """Утверждённый приказ пишет запись в кадровую историю.

    Единственный автоматический эффект во всём блоке — и он заказан
    (решение заказчика 3). Приказ о приёме, у которого ещё нет карточки
    сотрудника, не пишет ничего: карточку заводит кадровик, глядя на
    утверждённый приказ.
    """
    order = PersonnelOrder.objects.filter(pk=subject_id).first()
    if order is None or order.employee_id is None:
        return
    PersonnelHistory.objects.create(
        employee_id=order.employee_id,
        event_type=_ORDER_EVENT.get(order.kind, PersonnelHistoryEventType.OTHER),
        event_date=order.effective_date,
        to_department_id=order.department_id,
        to_position_id=order.position_id,
        order_number=order.basis,
        comment=order.comment,
    )


# ── регистрация ──────────────────────────────────────────────────────────

#: Тип предмета → класс модели. Единственное место соответствия: и
#: register(), и approval_service берут его отсюда.
SUBJECT_MODELS: dict[str, type] = {
    StaffingPosition.SIGNOFF_SUBJECT_TYPE: StaffingPosition,
    PersonnelOrder.SIGNOFF_SUBJECT_TYPE: PersonnelOrder,
}

#: Тип предмета → как его показывать и по каким фактам ветвить маршрут.
SUBJECT_SPECS: dict[str, dict] = {
    StaffingPosition.SIGNOFF_SUBJECT_TYPE: {
        "label": "Штатная единица",
        "describe": _describe_staffing,
        "facts": _staffing_facts,
        "fact_fields": _staffing_fact_fields,
    },
    PersonnelOrder.SIGNOFF_SUBJECT_TYPE: {
        "label": "Кадровый приказ",
        "describe": _describe_personnel_order,
        "facts": _personnel_order_facts,
        "fact_fields": _personnel_order_fact_fields,
        "on_approved": _personnel_order_on_approved,
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

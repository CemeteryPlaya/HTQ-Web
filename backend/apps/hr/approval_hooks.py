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
    Bonus, BonusKind, BusinessTrip, Department, LeaveKind, LeaveRequest,
    PersonnelHistory, PersonnelHistoryEventType, PersonnelOrder, PersonnelOrderKind,
    Reprimand, ReprimandSeverity, StaffingPosition,
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


# ── строка 8: премия ─────────────────────────────────────────────────────

def _describe_bonus(subject_id: int) -> dict | None:
    bonus = (Bonus.objects
             .select_related("employee")
             .filter(pk=subject_id).first())
    if bonus is None:
        return None
    return {
        "title": (f"Премия: {bonus.employee.last_name} {bonus.employee.first_name} — "
                  f"{bonus.amount} ({bonus.get_kind_display()}, {bonus.period})"),
        "url": f"/hr/bonuses/{bonus.pk}",
    }


def _bonus_facts(subject_id: int) -> dict:
    bonus = (Bonus.objects
             .select_related("employee", "employee__position")
             .filter(pk=subject_id).first())
    if bonus is None:
        return {}
    return {
        "employee_id": bonus.employee_id,
        "department_id": bonus.employee.department_id,
        # Категория должности (roadmap §6.2) — читается через сотрудника: у
        # премии, в отличие от штатной строки, нет своего FK на должность.
        "position_level": bonus.employee.position.level,
        # Главный факт этого предмета (roadmap §6.2 называет её первой из
        # трёх) — по ней второй разработчик строит условия маршрута.
        "amount": bonus.amount,
        "period": bonus.period,
        "kind": bonus.kind,
    }


def _bonus_fact_fields() -> list[dict]:
    return [
        {"key": "employee_id", "label": "Сотрудник", "type": "number"},
        {"key": "department_id", "label": "Подразделение", "type": "choice",
         "options": _department_options()},
        {"key": "position_level", "label": "Уровень должности", "type": "number"},
        {"key": "amount", "label": "Сумма премии", "type": "number"},
        {"key": "period", "label": "Период", "type": "string"},
        {"key": "kind", "label": "Вид премии", "type": "choice",
         "options": [{"value": v, "label": l} for v, l in BonusKind.choices]},
    ]


# ── строка 9: дисциплинарное взыскание ───────────────────────────────────

def _describe_reprimand(subject_id: int) -> dict | None:
    reprimand = (Reprimand.objects
                 .select_related("employee")
                 .filter(pk=subject_id).first())
    if reprimand is None:
        return None
    return {
        "title": (f"{reprimand.get_severity_display()}: "
                  f"{reprimand.employee.last_name} {reprimand.employee.first_name} — "
                  f"с {reprimand.event_date.isoformat()}"),
        "url": f"/hr/reprimands/{reprimand.pk}",
    }


def _reprimand_facts(subject_id: int) -> dict:
    reprimand = (Reprimand.objects
                 .select_related("employee", "employee__position")
                 .filter(pk=subject_id).first())
    if reprimand is None:
        return {}
    return {
        "employee_id": reprimand.employee_id,
        "department_id": reprimand.employee.department_id,
        "position_level": reprimand.employee.position.level,
        # Маршрут ветвится именно по ней: замечание и строгий выговор
        # проходят разный круг согласования.
        "severity": reprimand.severity,
        "event_date": reprimand.event_date.isoformat(),
    }


def _reprimand_fact_fields() -> list[dict]:
    return [
        {"key": "employee_id", "label": "Сотрудник", "type": "number"},
        {"key": "department_id", "label": "Подразделение", "type": "choice",
         "options": _department_options()},
        {"key": "position_level", "label": "Уровень должности", "type": "number"},
        {"key": "severity", "label": "Степень взыскания", "type": "choice",
         "options": [{"value": v, "label": l} for v, l in ReprimandSeverity.choices]},
        {"key": "event_date", "label": "Дата события", "type": "string"},
    ]


# ── строка 10б: заявление на отпуск ──────────────────────────────────────

def _describe_leave_request(subject_id: int) -> dict | None:
    leave = (LeaveRequest.objects
             .select_related("employee")
             .filter(pk=subject_id).first())
    if leave is None:
        return None
    return {
        "title": (f"{leave.get_kind_display()}: "
                  f"{leave.employee.last_name} {leave.employee.first_name} — "
                  f"с {leave.date_from.isoformat()} по {leave.date_to.isoformat()}"),
        "url": f"/hr/leave-requests/{leave.pk}",
    }


def _leave_request_facts(subject_id: int) -> dict:
    leave = (LeaveRequest.objects
             .select_related("employee")
             .filter(pk=subject_id).first())
    if leave is None:
        return {}
    return {
        "employee_id": leave.employee_id,
        "department_id": leave.employee.department_id,
        "kind": leave.kind,
        # Срок отпуска (roadmap §6.2 называет его вторым из трёх поимённых
        # фактов) — границы включительные: с 1-го по 1-е число это ОДИН
        # день, а не ноль. Считается здесь, а не хранится полем: хранимое
        # разъехалось бы с датами при первой же правке.
        "days": (leave.date_to - leave.date_from).days + 1,
        "date_from": leave.date_from,
        "date_to": leave.date_to,
    }


def _leave_request_fact_fields() -> list[dict]:
    return [
        {"key": "employee_id", "label": "Сотрудник", "type": "number"},
        {"key": "department_id", "label": "Подразделение", "type": "choice",
         "options": _department_options()},
        {"key": "kind", "label": "Вид отпуска", "type": "choice",
         "options": [{"value": v, "label": l} for v, l in LeaveKind.choices]},
        {"key": "days", "label": "Срок отпуска, дней", "type": "number"},
        {"key": "date_from", "label": "Дата начала", "type": "string"},
        {"key": "date_to", "label": "Дата окончания", "type": "string"},
    ]


# ── строка 10в: командировка ─────────────────────────────────────────────

def _describe_business_trip(subject_id: int) -> dict | None:
    trip = (BusinessTrip.objects
            .select_related("employee")
            .filter(pk=subject_id).first())
    if trip is None:
        return None
    return {
        "title": (f"Командировка: {trip.employee.last_name} {trip.employee.first_name} — "
                  f"{trip.destination}, с {trip.date_from.isoformat()} "
                  f"по {trip.date_to.isoformat()}"),
        "url": f"/hr/business-trips/{trip.pk}",
    }


def _business_trip_facts(subject_id: int) -> dict:
    trip = (BusinessTrip.objects
            .select_related("employee")
            .filter(pk=subject_id).first())
    if trip is None:
        return {}
    return {
        "employee_id": trip.employee_id,
        "department_id": trip.employee.department_id,
        "destination": trip.destination,
        "country": trip.country,
        "days": (trip.date_to - trip.date_from).days + 1,
        # Сумма командировки — тоже факт маршрута: согласование ветвится по
        # ней так же, как по сумме премии у строки 8.
        "estimated_cost": trip.estimated_cost,
        "date_from": trip.date_from,
        "date_to": trip.date_to,
    }


def _business_trip_fact_fields() -> list[dict]:
    return [
        {"key": "employee_id", "label": "Сотрудник", "type": "number"},
        {"key": "department_id", "label": "Подразделение", "type": "choice",
         "options": _department_options()},
        {"key": "destination", "label": "Пункт назначения", "type": "string"},
        {"key": "country", "label": "Код страны", "type": "string"},
        {"key": "days", "label": "Срок командировки, дней", "type": "number"},
        {"key": "estimated_cost", "label": "Сумма командировки", "type": "number"},
        {"key": "date_from", "label": "Дата начала", "type": "string"},
        {"key": "date_to", "label": "Дата окончания", "type": "string"},
    ]


# ── регистрация ──────────────────────────────────────────────────────────

#: Тип предмета → класс модели. Единственное место соответствия: и
#: register(), и approval_service берут его отсюда.
SUBJECT_MODELS: dict[str, type] = {
    StaffingPosition.SIGNOFF_SUBJECT_TYPE: StaffingPosition,
    PersonnelOrder.SIGNOFF_SUBJECT_TYPE: PersonnelOrder,
    Bonus.SIGNOFF_SUBJECT_TYPE: Bonus,
    Reprimand.SIGNOFF_SUBJECT_TYPE: Reprimand,
    LeaveRequest.SIGNOFF_SUBJECT_TYPE: LeaveRequest,
    BusinessTrip.SIGNOFF_SUBJECT_TYPE: BusinessTrip,
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
    # Ни у премии, ни у взыскания, ни у отпуска, ни у командировки нет
    # "on_approved" (решение 11 плана блока G): единственный автоматический
    # эффект утверждения во всём блоке — у кадрового приказа выше. Взыскание
    # объявляет приказ, а не платформа; утверждённый отпуск не проставляет
    # отсутствие в календаре и не трогает табель — это делает кадровик.
    Bonus.SIGNOFF_SUBJECT_TYPE: {
        "label": "Премия",
        "describe": _describe_bonus,
        "facts": _bonus_facts,
        "fact_fields": _bonus_fact_fields,
    },
    Reprimand.SIGNOFF_SUBJECT_TYPE: {
        "label": "Дисциплинарное взыскание",
        "describe": _describe_reprimand,
        "facts": _reprimand_facts,
        "fact_fields": _reprimand_fact_fields,
    },
    LeaveRequest.SIGNOFF_SUBJECT_TYPE: {
        "label": "Заявление на отпуск",
        "describe": _describe_leave_request,
        "facts": _leave_request_facts,
        "fact_fields": _leave_request_fact_fields,
    },
    BusinessTrip.SIGNOFF_SUBJECT_TYPE: {
        "label": "Командировка",
        "describe": _describe_business_trip,
        "facts": _business_trip_facts,
        "fact_fields": _business_trip_fact_fields,
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

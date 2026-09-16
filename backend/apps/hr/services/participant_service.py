"""Системная должность «Участник (ОСУ)» — блок F дорожной карты.

Общее собрание участников в документах руководства — орган владельцев НАД
генеральным директором (оргструктура, стр. 1), утверждающий назначение
директора ДО, бюджет группы и крупные сделки (HR-FRM-004, п. 7, 11, 14).
Чтобы маршрут согласования мог сослаться на него обычным ``position_id``,
ОСУ представлено должностью:

* ``is_system=True`` — переименовать, перевести в другой отдел,
  деактивировать через интерфейс нельзя (``position_service``), удалить —
  тоже. Маршрут, однажды сославшийся на ОСУ, не укажет в пустоту.
* вес ``0`` — вершина шкалы («меньший вес = выше»); отдельного порога
  уровней для ОСУ нет намеренно: ``LevelThreshold`` не допускает уровень 0,
  а дерево оргструктуры раскладывается по связям подчинения, не по номеру
  уровня, — связь «ГД → ОСУ» ставит его над генеральным директором и так.
* своё подразделение «Общее собрание участников» без руководителя: класть
  орган владельцев внутрь «Руководства», которым командует ГД, значило бы
  перевернуть смысл.
* руководящая должность с внешней иерархией (блок B): владелец видит все
  дочерние компании. НЕ ``serves_subsidiaries`` (блок C): владелец не
  обслуживает ДО, права в них ему раздаются членством и ролями, как любому.

Единственный способ завести ОСУ — ``ensure_participant()``: его зовут и
боевая команда ``hr_participant``, и демо-сид, — чтобы стенд и бой не
разъехались. Связь «ГД подчинён ОСУ» сервис НЕ заводит: искать ГД по
названию строки — угадывание, которое на бою попадёт не в ту должность.
На стенде связь идёт из справочника структур, на бою её ставит кадровик.

Функция действует в контексте ТЕКУЩЕЙ компании (схема) — как весь домен.
"""

from __future__ import annotations

from django.db import transaction

from apps.hr.models import Department, ExternalHierarchy, Position, UnitType
from apps.hr.services import position_service

PARTICIPANT_TITLE = "Участник (ОСУ)"
PARTICIPANT_UNIT_PATH = "osu"
PARTICIPANT_UNIT_NAME = "Общее собрание участников"
PARTICIPANT_WEIGHT = 0


class ParticipantWeightTaken(Exception):
    """Вес 0 держит другая должность. Двигать её молча нельзя — это чужие
    данные; человек решает сам, что с ней делать."""

    def __init__(self, holder: Position) -> None:
        self.detail = (
            f"Вес {PARTICIPANT_WEIGHT} уже занят должностью «{holder.title}» "
            f"(id={holder.id}). Освободите его (смените вес той должности) "
            f"и повторите."
        )
        super().__init__(self.detail)


# Состояние, к которому ensure_participant приводит должность ПРИ КАЖДОМ
# вызове. Это не «умолчания при создании», а предписание: повторный вызов
# чинит расхождение, а не пропускает его.
_PRESCRIBED = {
    "is_system": True,
    "is_active": True,
    "grade": 10,
    "weight": PARTICIPANT_WEIGHT,
    "is_manager": True,
    "external_hierarchy": ExternalHierarchy.INHERIT,
    "serves_subsidiaries": False,
    "permissions": {"hr_level": "lead", "permissions": []},
    "description": (
        "Общее собрание участников — высший орган управления. Утверждает "
        "назначение директоров дочерних обществ, бюджет группы и крупные "
        "сделки (HR-FRM-004)."
    ),
}


def find_participant() -> Position | None:
    return (Position.objects
            .filter(title=PARTICIPANT_TITLE, is_system=True)
            .select_related("department")
            .first())


@transaction.atomic
def ensure_participant() -> tuple[Position, bool]:
    """Завести или привести к предписанному состоянию должность ОСУ.

    Возвращает ``(должность, создана_ли_заново)``.
    """
    unit, _ = Department.objects.update_or_create(
        path=PARTICIPANT_UNIT_PATH,
        defaults={
            "name": PARTICIPANT_UNIT_NAME,
            "unit_type": UnitType.DEPARTMENT,
            "description": "Орган владельцев над генеральным директором.",
            "is_active": True,
        },
    )

    existing = find_participant()
    qs = Position.objects.filter(weight=PARTICIPANT_WEIGHT)
    if existing is not None:
        qs = qs.exclude(pk=existing.pk)
    holder = qs.first()
    if holder is not None:
        raise ParticipantWeightTaken(holder)

    fields = {**_PRESCRIBED, "department": unit,
              "level": position_service._compute_level(PARTICIPANT_WEIGHT)}
    if existing is None:
        position = Position.objects.create(title=PARTICIPANT_TITLE, **fields)
        return position, True

    for name, value in fields.items():
        setattr(existing, name, value)
    existing.save()
    return existing, False

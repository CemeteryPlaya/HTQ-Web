"""Доска задач ↔ «Проект» модуля БЗО (D-02: «Проект» главный).

Доска заводится только к уже существующему «Проекту» (``project_ref`` —
строка UUID, не FK: межаппный FK запрещён) и одна на проект. Название,
статус, сроки и руководитель у связанной доски — копия «Проекта»: правятся
только в «Проектах», сюда приезжают подпиской ``on_project_changed`` в той
же транзакции, а правка этих полей через доску — 409. Остальное (описание,
цвет, отдел, календарь, объекты) — доски, «Проект» его не знает.

Правку «Проекта» доска принимает всегда (решение 01.10: «Проект» главный —
подстраивается доска). Названия досок уникальны, «Проектов» — нет, поэтому
название, которое уже носит другая доска, доска получает с кодом проекта:
«ЖК Нурлы Жол (П-015)» (``board_name``). Сроки проверяет сам «Проект».

Доски без ссылки — наследие до связи: миграция ``0023`` связала все, что
были, но строки, заведённые мимо сервиса (ORM, старые сиды), правятся
по-старому, пока их не свяжет ``manage.py project_link_tasks``.
"""

from __future__ import annotations

import uuid

from django.db import IntegrityError, transaction

from apps.project import interface as project
from htqweb import date_rules

from ..models import Project, ProjectStatus

#: Статус «Проекта» → статус доски. У доски «завершён», у «Проекта» —
#: «закрыт»; смысл один.
STATUS_FROM_PROJECT = {
    "active": ProjectStatus.ACTIVE,
    "closed": ProjectStatus.COMPLETED,
    "archived": ProjectStatus.ARCHIVED,
}
STATUS_TO_PROJECT = {board: plat for plat, board in STATUS_FROM_PROJECT.items()}

#: Поля доски, которые повторяют «Проект» (поле доски → поле паспорта).
MIRRORED = {
    "name": "name",
    "status": "status",
    "start_date": "date_start",
    "end_date": "date_end",
    "owner_id": "manager_user_id",
}

_NAME_MAX = Project._meta.get_field("name").max_length


class ProjectLinkError(Exception):
    """Доску нельзя завести или поправить так, как просили. Текст — для
    человека, ``status`` — HTTP-код ответа."""

    def __init__(self, message: str, *, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def board_name(brief: dict, *, board_id: int | None = None) -> str:
    """Название доски для «Проекта»: его название, а если его уже носит
    другая доска — с кодом проекта, «ЖК Нурлы Жол (П-015)» (``-2``, ``-3``…
    — если занято и это). Вмещается в поле доски: длинное название
    обрезается перед кодом."""
    others = Project.objects.exclude(pk=board_id) if board_id else Project.objects.all()
    name = brief["name"][:_NAME_MAX]
    if not others.filter(name=name).exists():
        return name
    n = 1
    while True:
        suffix = f" ({brief['code']})" if n == 1 else f" ({brief['code']}-{n})"
        candidate = brief["name"][:_NAME_MAX - len(suffix)].rstrip() + suffix
        if not others.filter(name=candidate).exists():
            return candidate
        n += 1


def mirrored_values(brief: dict, *, board_id: int | None = None) -> dict:
    """Значения зеркальных полей доски по паспорту «Проекта»."""
    return {
        "name": board_name(brief, board_id=board_id),
        "status": STATUS_FROM_PROJECT[brief["status"]],
        "start_date": brief["date_start"],
        "end_date": brief["date_end"],
        "owner_id": brief["manager_user_id"],
    }


def on_project_changed(brief: dict) -> None:
    """Подписчик правки «Проекта» (``project.interface.
    register_change_listener``): привести связанную доску к нему — в той же
    транзакции, поэтому данные не расходятся ни на миг. Доска принимает
    любую правку: занятое название — с кодом проекта (``board_name``), сроки
    проверил сам «Проект»."""
    board = (Project.objects.select_for_update()
             .filter(project_ref=brief["id"]).first())
    if board is None:
        return
    values = mirrored_values(brief, board_id=board.pk)
    changed = [field for field, value in values.items() if getattr(board, field) != value]
    if not changed:
        return
    for field in changed:
        setattr(board, field, values[field])
    board.save(update_fields=[*changed, "updated_at"])


def _brief(ref: str) -> dict | None:
    try:
        key = str(uuid.UUID(str(ref)))
    except (ValueError, AttributeError, TypeError):
        return None
    return project.project_brief([key]).get(key)


def create_linked(payload: dict) -> Project:
    """Завести доску к «Проекту» ``payload["project_ref"]``: зеркальные поля
    берутся из него, остальное — из запроса."""
    fields = dict(payload)
    brief = _brief(fields.pop("project_ref"))
    if brief is None:
        raise ProjectLinkError("Проект не найден.", status=422)
    if brief["status"] == "archived":
        raise ProjectLinkError(f"Проект {brief['code']} в архиве — доску задач к нему не заводят.")
    taken = Project.objects.filter(project_ref=brief["id"]).first()
    if taken is not None:
        raise ProjectLinkError(
            f"У проекта {brief['code']} уже есть доска задач «{taken.name}».")
    values = mirrored_values(brief)
    if date_rules.out_of_order(values["start_date"], values["end_date"]):
        # «Проект» со старыми перевёрнутыми сроками (до проверки в самом
        # «Проекте»): доска с такими сроками не правилась бы вовсе.
        raise ProjectLinkError(
            f"У проекта {brief['code']} дата окончания раньше даты начала — "
            f"исправьте сроки в разделе «Проекты».")
    try:
        with transaction.atomic():
            return Project.objects.create(**fields, **values, project_ref=brief["id"])
    except IntegrityError as exc:
        # Параллельная заявка успела первой: та же доска или то же название.
        raise ProjectLinkError(
            f"Доску к проекту {brief['code']} или доску с тем же названием только что "
            f"завели — обновите список и повторите.") from exc


def strip_mirrored(board: Project, changes: dict) -> dict:
    """Правка связанной доски: зеркальные поля меняются только в «Проектах».
    Прислать их можно (форма шлёт все поля), но лишь с теми же значениями —
    иначе 409; из правки они убираются."""
    if not board.project_ref:
        return changes
    blocked = [field for field in MIRRORED
               if field in changes and changes[field] != getattr(board, field)]
    if blocked:
        raise ProjectLinkError(
            "Название, статус, сроки и руководитель доски повторяют проект и "
            "меняются в разделе «Проекты».")
    return {field: value for field, value in changes.items() if field not in MIRRORED}


def candidates(query: str, *, user_id: int, limit: int = 20) -> list[dict]:
    """«Проекты», к которым ещё можно завести доску: не в архиве и без доски."""
    taken = set(Project.objects.exclude(project_ref="").values_list("project_ref", flat=True))
    rows = project.search_projects(query, user_id=user_id, only_member=False, limit=200)
    return [{"id": row["id"], "code": row["code"], "name": row["name"],
             "status": row["status"], "date_start": row["date_start"],
             "date_end": row["date_end"], "manager_user_id": row["manager_user_id"]}
            for row in rows if row["id"] not in taken][:limit]

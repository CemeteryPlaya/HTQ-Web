"""Связать каждую доску задач с «Проектом» БЗО (D-02: «Проект» главный).

С этой миграции доска заводится только к «Проекту», а её название, статус,
сроки и владелец — копия его полей (``services/project_link.py``). Уже
существующие доски связываются здесь, по правилам ``project_link_tasks``:

* доска без ссылки получает «Проект» с кодом ``TP-<id доски>``, заведённый
  из её же полей (страна — KZ, руководитель — владелец доски). Код занят
  «Проектом», заведённым человеком, или уже отдан другой доске — берётся
  ``TP-<id>-2``, ``-3``…; «Проект», заведённый командой (``created_by``
  пуст) и ещё ничей, переиспользуется;
* уже связанная доска (командой ``project_link_tasks``) сводится с
  «Проектом»: у «Проекта» главнее непустое, пустое заполняется с доски;
  статус «Проекта», оставшийся «активен» по умолчанию, берётся с доски.
  Название — «Проекта», если его не носит другая доска и оно вмещается в
  доску, иначе «Проект» получает название доски.

Обратного шага нет: связь не мешает старому коду, а «Проекты» могли уже
обрасти документами модуля.
"""

import uuid

from django.db import migrations

_STATUS_TO_PROJECT = {"active": "active", "completed": "closed", "archived": "archived"}
_STATUS_FROM_PROJECT = {plat: board for board, plat in _STATUS_TO_PROJECT.items()}
# Нестандартный статус (в БД ограничения нет) не должен ронять миграцию компании:
# такая доска/«Проект» считается действующим.
_NAME_MAX = 200


def _as_uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def link_boards(apps, schema_editor):
    Board = apps.get_model("tasks", "Project")
    Plat = apps.get_model("project", "Project")
    Member = apps.get_model("project", "ProjectMember")
    claimed: set[str] = set()

    def free_code(board):
        base = f"TP-{board.pk}"
        code, n = base, 1
        while True:
            existing = Plat.objects.filter(code=code).first()
            if existing is None:
                return code, None
            if existing.created_by is None and str(existing.pk) not in claimed \
                    and not Board.objects.filter(project_ref=str(existing.pk)).exclude(
                        pk=board.pk).exists():
                return code, existing
            n += 1
            code = f"{base}-{n}"

    def name_is_free(name, board):
        return (len(name) <= _NAME_MAX
                and not Board.objects.filter(name=name).exclude(pk=board.pk).exists())

    for board in Board.objects.order_by("pk"):
        key = _as_uuid(board.project_ref) if board.project_ref else None
        plat = Plat.objects.filter(pk=key).first() if key else None
        if plat is not None and str(plat.pk) in claimed:
            plat = None
        if plat is None:
            code, plat = free_code(board)
            if plat is None:
                plat = Plat(code=code, country_code="KZ")
            plat.name = board.name
            plat.status = _STATUS_TO_PROJECT.get(board.status, "active")
            plat.date_start = board.start_date
            plat.date_end = board.end_date
            plat.manager_user_id = board.owner_id
        else:
            if plat.date_start is None:
                plat.date_start = board.start_date
            if plat.date_end is None:
                plat.date_end = board.end_date
            if plat.manager_user_id is None:
                plat.manager_user_id = board.owner_id
            if plat.status == "active" and board.status != "active":
                plat.status = _STATUS_TO_PROJECT.get(board.status, "active")
            if not name_is_free(plat.name, board):
                plat.name = board.name
        plat.save()
        if plat.manager_user_id:
            Member.objects.get_or_create(project=plat, user_id=plat.manager_user_id)
        board.project_ref = str(plat.pk)
        board.name = plat.name
        board.status = _STATUS_FROM_PROJECT.get(plat.status, "active")
        board.start_date = plat.date_start
        board.end_date = plat.date_end
        board.owner_id = plat.manager_user_id
        board.save(update_fields=["project_ref", "name", "status", "start_date", "end_date",
                                  "owner_id"])
        claimed.add(str(plat.pk))


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0023_contractor_bpp_counterparty"),
        ("project", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(link_boards, migrations.RunPython.noop),
    ]

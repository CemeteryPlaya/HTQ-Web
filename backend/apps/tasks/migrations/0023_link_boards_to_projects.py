"""Связать каждую доску задач с «Проектом» БЗО (D-02: «Проект» главный).

С этой миграции доска заводится только к «Проекту», а её название, статус,
сроки и владелец — копия его полей (``services/project_link.py``). Уже
существующие доски связываются здесь (решения Руслана 29.09 и 01.10):

* название доски расширяется до 255 символов — как у «Проекта»;
* уже связанная доска (командой ``project_link_tasks``) приводится к своему
  «Проекту»; сам «Проект» не меняется — он главный;
* доска без ссылки получает «Проект» с кодом ``TP-<id доски>``, заведённый
  из её же полей (страна — KZ, руководитель — владелец доски). Код занят
  «Проектом», заведённым человеком, или уже отдан другой доске — берётся
  ``TP-<id>-2``, ``-3``…; «Проект», заведённый командой (``created_by``
  пуст) и ещё ничей, переиспользуется — и доска приводится к нему.

Названия досок уникальны, «Проектов» — нет: название, которое уже носит
другая доска, доска получает с кодом проекта, «ЖК Нурлы Жол (П-015)» — как
``project_link.board_name``.

Обратного шага у связывания нет: связь не мешает старому коду, а «Проекты»
могли уже обрасти документами модуля.
"""

import uuid

from django.db import migrations, models

_STATUS_TO_PROJECT = {"active": "active", "completed": "closed", "archived": "archived"}
_STATUS_FROM_PROJECT = {plat: board for board, plat in _STATUS_TO_PROJECT.items()}
_NAME_MAX = 255


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

    def board_name(plat, board):
        others = Board.objects.exclude(pk=board.pk)
        name = plat.name[:_NAME_MAX]
        if not others.filter(name=name).exists():
            return name
        n = 1
        while True:
            suffix = f" ({plat.code})" if n == 1 else f" ({plat.code}-{n})"
            candidate = plat.name[:_NAME_MAX - len(suffix)].rstrip() + suffix
            if not others.filter(name=candidate).exists():
                return candidate
            n += 1

    for board in Board.objects.order_by("pk"):
        key = _as_uuid(board.project_ref) if board.project_ref else None
        plat = Plat.objects.filter(pk=key).first() if key else None
        if plat is not None and str(plat.pk) in claimed:
            plat = None
        if plat is None:
            code, plat = free_code(board)
            if plat is None:
                plat = Plat.objects.create(
                    code=code, country_code="KZ", name=board.name,
                    status=_STATUS_TO_PROJECT.get(board.status, "active"), date_start=board.start_date,
                    date_end=board.end_date, manager_user_id=board.owner_id)
                if plat.manager_user_id:
                    Member.objects.get_or_create(project=plat, user_id=plat.manager_user_id)
        board.project_ref = str(plat.pk)
        board.name = board_name(plat, board)
        board.status = _STATUS_FROM_PROJECT.get(plat.status, "active")
        board.start_date = plat.date_start
        board.end_date = plat.date_end
        board.owner_id = plat.manager_user_id
        board.save(update_fields=["project_ref", "name", "status", "start_date", "end_date",
                                  "owner_id"])
        claimed.add(str(plat.pk))


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0022_project_ref"),
        ("project", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="project",
            name="name",
            field=models.CharField(max_length=255, unique=True),
        ),
        migrations.RunPython(link_boards, migrations.RunPython.noop),
    ]

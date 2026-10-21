"""Оргструктура для тестов видимости и прав досок задач (канбан, этап 1).

Отделы — модели ``hr`` напрямую: тесты ``tasks`` идут в ``public`` (у
компании ``helpers.COMPANY`` нет своей схемы), там же таблицы ``hr``; сторож
``test_app_isolation`` каталог ``tests`` пропускает.

Дерево::

    hq        — HEAD_IT числится здесь, но руководит it (глава «из другого отдела»)
    it        — EMP_IT (user 7, стандартный ``helpers.token()``), FIRED (уволен)
    it.dev    — EMP_DEV
    ops       — HEAD_OPS (глава ops)
    itops     — сосед с общим префиксом пути: не поддерево it

ОД, ГД, ТД, ПМ числятся в ``hq`` и получают узлы ролями (``assign``).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from apps.access.tests.helpers import assign
from apps.hr.models import Department, Employee, EmployeeStatus, Position
from apps.project.models import Project as Platform
from apps.project.models import ProjectMember
from apps.tasks.models import Project as Board
from apps.tasks.models import Task

from .helpers import COMPANY, auth, token

EMP_IT = 7
EMP_DEV = 701
HEAD_IT = 702
HEAD_OPS = 703
OD = 704
GD = 705
PM = 706
FIRED = 707
TD = 708
OUTSIDER = 709          # сотрудник ops, к it отношения не имеет


@dataclass
class Org:
    hq: Department
    it: Department
    dev: Department
    ops: Department
    itops: Department


_seq = {"n": 0}


def _employee(user_id: int, department: Department, position: Position,
              status: str = EmployeeStatus.ACTIVE) -> Employee:
    return Employee.objects.create(
        user_id=user_id, first_name=f"Имя{user_id}", last_name=f"Фамилия{user_id}",
        email=f"user{user_id}@kanban.test", department=department, position=position,
        hire_date=dt.date(2025, 1, 1), status=status)


def make_org() -> Org:
    hq = Department.objects.create(name="Дирекция (канбан)", path="kb_hq")
    it = Department.objects.create(name="ИТ (канбан)", path="kb_it")
    dev = Department.objects.create(name="Разработка (канбан)", path="kb_it.dev")
    ops = Department.objects.create(name="Эксплуатация (канбан)", path="kb_ops")
    itops = Department.objects.create(name="ИТ-эксплуатация (канбан)", path="kb_itops")
    position = Position.objects.create(title="Сотрудник (канбан-тест)", department=hq,
                                       weight=9201)
    _employee(EMP_IT, it, position)
    _employee(EMP_DEV, dev, position)
    head_it = _employee(HEAD_IT, hq, position)
    head_ops = _employee(HEAD_OPS, ops, position)
    for uid in (OD, GD, PM, TD):
        _employee(uid, hq, position)
    _employee(FIRED, it, position, status=EmployeeStatus.INACTIVE)
    _employee(OUTSIDER, ops, position)
    it.manager = head_it
    it.save(update_fields=["manager"])
    ops.manager = head_ops
    ops.save(update_fields=["manager"])
    for uid in (EMP_DEV, HEAD_IT, HEAD_OPS, OD, GD, PM, FIRED, TD, OUTSIDER):
        assign(COMPANY, uid, "tasks", "write")
    for uid in (OD, GD):
        assign(COMPANY, uid, "tasks.departments.all", "view")
    for uid in (OD, GD, TD):
        assign(COMPANY, uid, "project.board", "view")
        assign(COMPANY, uid, "project.all", "view")
    assign(COMPANY, PM, "project.board", "view")
    return Org(hq=hq, it=it, dev=dev, ops=ops, itops=itops)


def as_user(user_id: int) -> dict:
    return auth(token(user_id=user_id, sub=str(user_id)))


def make_task(**fields) -> Task:
    _seq["n"] += 1
    defaults = {"key": f"KB-{_seq['n']}", "summary": f"Задача {_seq['n']}"}
    defaults.update(fields)
    return Task.objects.create(**defaults)


def make_board(code: str, *, members: tuple[int, ...] = (), department=None) -> Board:
    platform = Platform.objects.create(code=code, name=f"Объект {code}", country_code="KZ")
    for uid in members:
        ProjectMember.objects.create(project=platform, user_id=uid)
    return Board.objects.create(name=f"Доска {code}", project_ref=str(platform.pk),
                                department_id=getattr(department, "id", None))

"""Блок I, задача 5: справочники ``hr`` (сотрудники/отделы/должности/
оргструктура) под гейтом ``module="hr", level=…``.

Продолжает ``apps.access.tests.test_module_gate``/``apps.users.tests.
test_module_gate`` (те же приёмы: ``Client()``, засеянные роли, заголовок
компании) для той половины ``hr``, которую гейтирует задача 5. ``hr`` ещё
не в ``apps.access.self_service.TRANSLATED_APPS`` (это делает задача 6,
когда добьёт остальные экраны) — сторож ``apps/access/tests/test_gate.py``
поэтому не проверяет ПОЛНОТУ покрытия ``hr`` автоматически, и этот файл
закрывает её вручную, ручка за ручкой, для того, что задача 5 действительно
изменила.

Что здесь закрыто:

1. ``employee-basic`` (``access/migrations/0004`` — ни одного узла ``hr.*``)
   СОХРАНЯЕТ доступ к своим данным (``employees/me``, ``employees/me/card`` —
   реестр ``apps.access.self_service``, причина ``self``), но получает 403
   на список сотрудников: первый же гейт ``module="hr"`` требует ХОТЬ ОДИН
   узел ``hr.*``, которого у этой роли нет и не может быть (докстринг
   ``self_service`` — выдать его означало бы открыть ВЕСЬ модуль).
2. Держатели настоящих засеянных ролей ``hr-junior``/``hr-middle``/
   ``hr-lead`` (``access/migrations/0005``) проходят через НОВЫЙ гейт ровно
   на уровне, который несёт их роль, но финальное решение по-прежнему даёт
   СТАРАЯ модель (``apps.hr.access.resolve_hr_access`` — Employee/Position-
   эвристика): обе двери должны быть открыты разом, поэтому фикстуры ниже
   заводят Employee/Position нужного уровня И назначают ту же по смыслу
   засеянную роль (тот же приём, что в ``test_employees_api.py::
   _grant_seeded_role`` — см. его докстринг про две независимые модели).
3. ЧТЕНИЕ справочников ``departments``/``positions`` открыто любому
   вошедшему без единой роли (см. ``apps.access.self_service`` — записи с
   причиной ``open``) — задача 5 это НЕ сузила, что здесь и проверяется
   regression-тестом на ``employee-basic``. ЗАПИСЬ отделов — наоборот, под
   гейтом (раунд правок 1: create/update → ``write``, delete → ``admin``,
   осознанное исключение из «как есть» — см. комментарий над
   ``_create_department`` в ``apps/hr/views.py``): рядовой получает 403,
   ``hr-middle`` создаёт, ``hr-lead`` удаляет, ``hr-middle`` на удалении —
   403.
4. **Чувствительность к самому гейту** (раунд правок 1). Все тесты пунктов
   1–3 с отказом используют вызывающего, которого СТАРАЯ модель
   (``resolve_hr_access``) тоже отвергает — они прошли бы и без единого
   ``module=``. После задачи 9 старая модель исчезнет, и гейт останется
   единственной защитой, поэтому нужен вызывающий, которого старая модель
   ПУСКАЕТ, а гейт — нет: ``is_staff=True`` БЕЗ единой роли.
   ``resolve_hr_access`` по ``token.is_elevated`` даёт ему ``HRAccess(
   level="lead", permissions={"*"})`` — старая модель открывает ему всё, —
   а ``permissions_for`` без назначений (и без ``is_superuser``) отдаёт
   ``{}``, уровень ``none``, и гейт обязан ответить 403. Эти тесты падают,
   стоит снять ``module=`` с ручки, — проверено вживую при раунде правок 1
   (см. отчёт задачи 5).
"""

from __future__ import annotations

import datetime

import pytest
from django.test import Client

from apps.access.models import Role, RoleAssignment, ScopeKind
from apps.hr.models import Department, Employee, Position, ReportingRelation
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/hr/v1"


@pytest.fixture
def client():
    return Client()


def _mk(username: str, **flags) -> User:
    user = User.objects.create(username=username, email=f"{username}@htq.test",
                               password="x", status=UserStatus.ACTIVE, **flags)
    user.set_password("S3cret!")
    user.save()
    return user


def headers(user: User, slug: str) -> dict:
    """Заголовки как их ставит шлюз: слаг компании + токен, выданный на неё."""
    token = issue_token_pair(user, company_slug=slug)["access"]
    return {"HTTP_X_HTQ_COMPANY": slug, "HTTP_AUTHORIZATION": f"Bearer {token}"}


def give_seeded_role(user: User, slug: str, code: str) -> None:
    """Назначить УЖЕ существующую роль каталога — засеянную миграцией."""
    RoleAssignment.objects.create(company_slug=slug, user_id=user.id,
                                  role=Role.objects.get(code=code),
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)


@pytest.fixture
def eng_dep(db):
    """Отдел ВНЕ HR — под ``classify_hr_level`` не матчится ни один маркер,
    level=None, ровно то, что нужно для employee-basic."""
    return Department.objects.create(name="Инженерный", path="eng")


@pytest.fixture
def hr_dep(db):
    return Department.objects.create(name="HR", path="hr")


@pytest.fixture
def plain_employee(company_row, eng_dep):
    """Рядовой сотрудник: роль ``employee-basic``, обычная должность вне HR
    (старая эвристика тоже даёт ``level=None`` — обе модели сходятся на
    «нет кадрового доступа»)."""
    pos = Position.objects.create(title="Инженер", department=eng_dep, weight=5)
    user = _mk("rank-file")
    emp = Employee.objects.create(
        email="rank-file@htq.test", department=eng_dep, position=pos,
        hire_date=datetime.date(2024, 1, 9), user_id=user.id,
        first_name="Рядовой", last_name="Сотрудник",
    )
    give_seeded_role(user, company_row, "employee-basic")
    return emp, headers(user, company_row)


@pytest.fixture
def junior_employee(company_row, hr_dep):
    pos = Position.objects.create(title="HR Assistant", department=hr_dep, weight=10)
    user = _mk("junior-gate")
    emp = Employee.objects.create(
        email="junior-gate@htq.test", department=hr_dep, position=pos,
        hire_date=datetime.date(2024, 1, 9), user_id=user.id,
        first_name="Джуниор", last_name="Кадровый",
    )
    give_seeded_role(user, company_row, "hr-junior")
    return emp, headers(user, company_row)


@pytest.fixture
def middle_employee(company_row, hr_dep):
    pos = Position.objects.create(title="HR Manager", department=hr_dep, weight=20)
    user = _mk("middle-gate")
    emp = Employee.objects.create(
        email="middle-gate@htq.test", department=hr_dep, position=pos,
        hire_date=datetime.date(2024, 1, 9), user_id=user.id,
        first_name="Мидл", last_name="Кадровый",
    )
    give_seeded_role(user, company_row, "hr-middle")
    return emp, headers(user, company_row)


@pytest.fixture
def lead_employee(company_row, hr_dep):
    pos = Position.objects.create(title="HR Director", department=hr_dep, weight=40)
    user = _mk("lead-gate")
    emp = Employee.objects.create(
        email="lead-gate@htq.test", department=hr_dep, position=pos,
        hire_date=datetime.date(2024, 1, 9), user_id=user.id,
        first_name="Лид", last_name="Кадровый",
    )
    give_seeded_role(user, company_row, "hr-lead")
    return emp, headers(user, company_row)


@pytest.fixture
def staff_without_roles(company_row):
    """``is_staff=True`` БЕЗ единой роли и без Employee-профиля.

    Старая модель его ПУСКАЕТ везде: ``resolve_hr_access`` первой строкой
    смотрит ``token.is_elevated`` (``is_admin or is_staff or is_superuser``)
    и отдаёт ``HRAccess(level="lead", permissions={"*"})``, не заглядывая ни
    в Employee, ни в Position; ``admin=True`` на ручках должностей —
    тот же предикат (``require_admin``). Новый гейт его НЕ пускает:
    ``permissions_for`` короткое замыкание делает только для
    ``is_superuser``, а дальше считает по назначениям ролей — их нет,
    карта пустая, уровень модуля ``none``. Единственный вызывающий, на
    котором 403 доказывает именно гейт, а не старую модель.
    """
    user = _mk("staff-no-roles", is_staff=True)
    return headers(user, company_row)


@pytest.fixture
def target_employee(eng_dep):
    """Чужой сотрудник — мишень для PATCH/DELETE."""
    pos = Position.objects.create(title="Инженер", department=eng_dep, weight=11)
    return Employee.objects.create(
        email="target-staff@htq.test", department=eng_dep, position=pos,
        hire_date=datetime.date(2024, 1, 9), first_name="Т", last_name="Т",
    )


# ── employee-basic: self-service остаётся открытым, список — нет ──────────


@pytest.mark.django_db
def test_employee_basic_keeps_own_profile(client, plain_employee):
    emp, head = plain_employee
    resp = client.get(f"{BASE}/employees/me/", **head)
    assert resp.status_code == 200
    assert resp.json()["id"] == emp.id


@pytest.mark.django_db
def test_employee_basic_keeps_own_card(client, plain_employee):
    _emp, head = plain_employee
    resp = client.get(f"{BASE}/employees/me/card/", **head)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_employee_basic_is_denied_the_employee_list(client, plain_employee):
    """``employee-basic`` не несёт ни одного узла ``hr.*`` — гейт
    ``module="hr"`` отказывает РАНЬШЕ, чем запрос доходит до старой
    ``require_hr_access``."""
    _emp, head = plain_employee
    resp = client.get(f"{BASE}/employees/", **head)
    assert resp.status_code == 403


@pytest.mark.django_db
def test_employee_basic_is_denied_employee_detail(client, plain_employee):
    """Даже собственную карточку через общую ``/employees/{id}/`` (не
    ``/employees/me/``) employee-basic не откроет — гейт не различает «свой
    id» от чужого, разница есть только у self-service ручек."""
    emp, head = plain_employee
    resp = client.get(f"{BASE}/employees/{emp.id}/", **head)
    assert resp.status_code == 403


@pytest.mark.django_db
def test_employee_basic_keeps_reading_the_open_department_directory(client, plain_employee):
    """Регресс: ``departments``/``positions`` не гейтируются этой задачей
    (сегодня открыты любому вошедшему — см. ``apps.access.self_service``,
    записи с причиной ``open``) — задача 5 это не сузила."""
    _emp, head = plain_employee
    Department.objects.create(name="Финансы", path="fin")
    resp = client.get(f"{BASE}/departments/", **head)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_employee_basic_cannot_create_a_department(client, plain_employee):
    """ЗАПИСЬ отделов — под гейтом (раунд правок 1 задачи 5). До блока
    ``POST /departments/`` стоял голым ``auth="jwt"`` и рядовой сотрудник
    заводил отделы (``department_service.py`` не содержит ни одной проверки
    прав) — это унаследованный пробел, а не спроектированная открытость,
    и он закрыт сознательно, в отступление от правила «как есть»: см.
    комментарий над ``_create_department`` в ``apps/hr/views.py``."""
    _emp, head = plain_employee
    resp = client.post(
        f"{BASE}/departments/", data={"name": "Новый отдел", "path": "new-dep"},
        content_type="application/json", **head,
    )
    assert resp.status_code == 403
    assert not Department.objects.filter(path="new-dep").exists()


@pytest.mark.django_db
def test_hr_middle_creates_a_department(client, middle_employee):
    """``_create_department`` — ``level="write"``; агрегат ``hr-middle`` —
    ``write``, проходит."""
    _actor, head = middle_employee
    resp = client.post(
        f"{BASE}/departments/", data={"name": "Новый отдел", "path": "new-dep"},
        content_type="application/json", **head,
    )
    assert resp.status_code == 201
    assert Department.objects.filter(path="new-dep").exists()


@pytest.mark.django_db
def test_hr_middle_cannot_delete_a_department(client, middle_employee):
    """``_delete_department`` — ``level="admin"`` (``?cascade=true``
    необратимо стирает сотрудников поддерева); агрегат ``hr-middle`` —
    ``write``, до ``admin`` не дотягивает."""
    _actor, head = middle_employee
    dep = Department.objects.create(name="Пустой", path="empty")
    resp = client.delete(f"{BASE}/departments/{dep.id}/", **head)
    assert resp.status_code == 403
    assert Department.objects.filter(id=dep.id).exists()


@pytest.mark.django_db
def test_hr_lead_deletes_a_department(client, lead_employee):
    _actor, head = lead_employee
    dep = Department.objects.create(name="Пустой", path="empty")
    resp = client.delete(f"{BASE}/departments/{dep.id}/", **head)
    assert resp.status_code == 204
    assert not Department.objects.filter(id=dep.id).exists()


# ── hr-junior/middle/lead: реальные засеянные роли, реальные уровни ───────


@pytest.mark.django_db
def test_hr_junior_sees_the_employee_directory(client, junior_employee):
    _emp, head = junior_employee
    resp = client.get(f"{BASE}/employees/", **head)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_hr_junior_cannot_edit_an_employee(client, junior_employee, eng_dep):
    """hr-junior несёт только VIEW-узлы (``access/migrations/0005``) —
    агрегированный уровень модуля ``hr`` у неё ``read``, а PATCH стоит под
    ``level="write"``: гейт отказывает РАНЬШЕ старой
    ``require_can_write_basic`` (которая тоже отказала бы — junior не имеет
    ``hr.employees.edit`` — но теперь до неё дело не доходит)."""
    _actor, head = junior_employee
    pos = Position.objects.create(title="Инженер", department=eng_dep, weight=6)
    target = Employee.objects.create(
        email="target-junior@htq.test", department=eng_dep, position=pos,
        hire_date=datetime.date(2024, 1, 9), first_name="Т", last_name="Т",
    )
    resp = client.patch(
        f"{BASE}/employees/{target.id}/", data={"first_name": "Изменено"},
        content_type="application/json", **head,
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_hr_middle_can_edit_an_employee(client, middle_employee, hr_dep):
    _actor, head = middle_employee
    pos = Position.objects.create(title="Инженер", department=hr_dep, weight=7)
    target = Employee.objects.create(
        email="target-middle@htq.test", department=hr_dep, position=pos,
        hire_date=datetime.date(2024, 1, 9), first_name="Т", last_name="Т",
    )
    resp = client.patch(
        f"{BASE}/employees/{target.id}/", data={"first_name": "Изменено"},
        content_type="application/json", **head,
    )
    assert resp.status_code == 200
    target.refresh_from_db()
    assert target.first_name == "Изменено"


@pytest.mark.django_db
def test_hr_middle_cannot_delete_an_employee(client, middle_employee, hr_dep):
    """``_delete_employee`` стоит под ``level="admin"`` — агрегат hr-middle
    (``write``, максимум ``CREATE``/``EDIT`` среди её узлов) до него не
    дотягивает: гейт отказывает, старая ``can_delete_employee`` (тоже
    отказала бы — EMPLOYEES_DELETE только у lead) не вызывается вовсе."""
    _actor, head = middle_employee
    pos = Position.objects.create(title="Инженер", department=hr_dep, weight=8)
    target = Employee.objects.create(
        email="target-middle-del@htq.test", department=hr_dep, position=pos,
        hire_date=datetime.date(2024, 1, 9), first_name="Т", last_name="Т",
    )
    resp = client.delete(f"{BASE}/employees/{target.id}/", **head)
    assert resp.status_code == 403


@pytest.mark.django_db
def test_hr_lead_can_delete_an_employee(client, lead_employee, hr_dep):
    _actor, head = lead_employee
    pos = Position.objects.create(title="Инженер", department=hr_dep, weight=9)
    target = Employee.objects.create(
        email="target-lead@htq.test", department=hr_dep, position=pos,
        hire_date=datetime.date(2024, 1, 9), first_name="Т", last_name="Т",
    )
    resp = client.delete(f"{BASE}/employees/{target.id}/", **head)
    assert resp.status_code == 204
    target.refresh_from_db()
    assert target.is_deleted is True


# ── чувствительность к гейту: is_staff без ролей — старая модель пускает ──
#
# Каждый тест ниже прошёл бы со статусом 2xx, не будь на ручке module=/level=:
# старая модель (resolve_hr_access → is_elevated → level="lead", {"*"};
# admin=True → require_admin → is_elevated) даёт этому вызывающему всё.
# Отказать может ТОЛЬКО гейт. Убери module= с ручки — соответствующий тест
# упадёт (проверено вживую при раунде правок 1, см. отчёт задачи 5).


@pytest.mark.django_db
def test_staff_without_roles_still_reads_the_open_department_directory(client, staff_without_roles):
    """Контроль: токен и заголовок компании у этого вызывающего в порядке —
    открытая (``open``) ручка отвечает 200. Значит, 403 в тестах ниже даёт
    именно гейт модуля, а не несовпадение компании или битый токен."""
    Department.objects.create(name="Финансы", path="fin")
    resp = client.get(f"{BASE}/departments/", **staff_without_roles)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_staff_without_roles_is_denied_the_employee_list(client, staff_without_roles):
    resp = client.get(f"{BASE}/employees/", **staff_without_roles)
    assert resp.status_code == 403


@pytest.mark.django_db
def test_staff_without_roles_cannot_edit_an_employee(client, staff_without_roles, target_employee):
    resp = client.patch(
        f"{BASE}/employees/{target_employee.id}/", data={"first_name": "Изменено"},
        content_type="application/json", **staff_without_roles,
    )
    assert resp.status_code == 403
    target_employee.refresh_from_db()
    assert target_employee.first_name == "Т"


@pytest.mark.django_db
def test_staff_without_roles_cannot_delete_an_employee(client, staff_without_roles, target_employee):
    resp = client.delete(f"{BASE}/employees/{target_employee.id}/", **staff_without_roles)
    assert resp.status_code == 403
    target_employee.refresh_from_db()
    assert target_employee.is_deleted is False


@pytest.mark.django_db
def test_staff_without_roles_cannot_create_a_position(client, staff_without_roles, eng_dep):
    """``_create_position`` — ``admin=True`` (is_staff ПРОХОДИТ) +
    ``module="hr", level="admin"``: отказывает ровно вторая дверь."""
    resp = client.post(
        f"{BASE}/positions/", data={"title": "Новая", "department_id": eng_dep.id},
        content_type="application/json", **staff_without_roles,
    )
    assert resp.status_code == 403
    assert not Position.objects.filter(title="Новая").exists()


@pytest.mark.django_db
def test_staff_without_roles_cannot_remove_a_reporting_relation(client, staff_without_roles, eng_dep):
    """``remove_reporting_relation`` — в теле ``_require_permission(ORG_EDIT)``,
    который ``{"*"}`` проходит; 403 — только от ``level="admin"``."""
    boss = Position.objects.create(title="Начальник", department=eng_dep, weight=1)
    sub = Position.objects.create(title="Подчинённый", department=eng_dep, weight=2)
    rel = ReportingRelation.objects.create(
        superior_position=boss, subordinate_position=sub,
        effective_from=datetime.date(2024, 1, 1),
    )
    resp = client.delete(f"{BASE}/org/relations/{rel.id}", **staff_without_roles)
    assert resp.status_code == 403
    assert ReportingRelation.objects.filter(id=rel.id).exists()


@pytest.mark.django_db
def test_staff_without_roles_cannot_create_a_department(client, staff_without_roles):
    """У записи отделов НЕТ старой проверки вовсе (``department_service`` не
    знает о правах) — без гейта этот вызывающий, как и любой другой,
    создал бы отдел."""
    resp = client.post(
        f"{BASE}/departments/", data={"name": "Новый отдел", "path": "new-dep"},
        content_type="application/json", **staff_without_roles,
    )
    assert resp.status_code == 403
    assert not Department.objects.filter(path="new-dep").exists()


@pytest.mark.django_db
def test_staff_without_roles_cannot_delete_a_department(client, staff_without_roles):
    dep = Department.objects.create(name="Пустой", path="empty")
    resp = client.delete(f"{BASE}/departments/{dep.id}/?cascade=true", **staff_without_roles)
    assert resp.status_code == 403
    assert Department.objects.filter(id=dep.id).exists()


# ── регресс: производственный календарь этой задачей НЕ тронут ────────────


@pytest.mark.django_db
def test_production_calendar_is_untouched_by_this_task(client, plain_employee):
    """``/calendar/*`` — вне области задачи 5 (справочники
    сотрудников/отделов/должностей/оргструктуры, не календарь — брифом
    отдано задаче 6, см. ``apps.access.self_service`` примечание к
    ``calendar_year``/``calendar_working_days``). Поведение для
    ``employee-basic`` не менялось этой задачей: ``_require_permission(
    CALENDAR_VIEW)`` уже сегодня требует кадровый уровень (``_JUNIOR`` и
    выше), которого у employee-basic нет ни по старой, ни по новой модели —
    поэтому 403 ДО и ПОСЛЕ этой задачи, без единой строки гейта на
    ``calendar_year``."""
    _emp, head = plain_employee
    resp = client.get(f"{BASE}/calendar/", **head)
    assert resp.status_code == 403

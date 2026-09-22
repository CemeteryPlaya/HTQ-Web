"""Блок I, задачи 5+6: ``hr`` под гейтом ``module="hr", level=…``.

Продолжает ``apps.access.tests.test_module_gate``/``apps.users.tests.
test_module_gate`` (те же приёмы: ``Client()``, засеянные роли, заголовок
компании). Задача 5 закрыла справочники (сотрудники/отделы/должности/
оргструктура) — секции 1–4 ниже. Задача 6 добила ОСТАЛЬНЫЕ экраны
(штатное расписание, календарь, документы, карточка Т2/groups, PMO,
назначение подтверждающего идентичности) И включила ``hr`` в
``apps.access.self_service.TRANSLATED_APPS`` — секция 5. С этого коммита
сторож ``apps/access/tests/test_gate.py::
test_gate_covers_every_handle_of_translated_apps`` уже проверяет ПОЛНОТУ
покрытия ``hr`` автоматически (раньше — как задача 5 оставила, до включения
в реестр — этот файл был единственной проверкой полноты вручную).

Что здесь закрыто:

1. ``employee-basic`` (``access/migrations/0004`` — ни одного узла ``hr.*``)
   СОХРАНЯЕТ доступ к своим данным (``employees/me``, ``employees/me/card`` —
   реестр ``apps.access.self_service``, причина ``self``), но получает 403
   на список сотрудников: первый же гейт ``module="hr"`` требует ХОТЬ ОДИН
   узел ``hr.*``, которого у этой роли нет и не может быть (докстринг
   ``self_service`` — выдать его означало бы открыть ВЕСЬ модуль).
2. Держатели настоящих засеянных ролей ``hr-junior``/``hr-middle``/
   ``hr-lead`` (``access/migrations/0005``) проходят через НОВЫЙ гейт ровно
   на уровне, который несёт их роль. На момент написания (задачи 5–6)
   финальное решение по-прежнему давала СТАРАЯ модель (``apps.hr.access.
   resolve_hr_access`` — Employee/Position-эвристика): обе двери должны
   были быть открыты разом, поэтому фикстуры ниже заводят Employee/Position
   нужного уровня И назначают ту же по смыслу засеянную роль (тот же приём,
   что в ``test_employees_api.py::_grant_seeded_role`` — см. его докстринг
   про две независимые модели). Задача 9 блока I сняла старую модель
   целиком — Employee/Position ниже переживают её как ИСТОРИЧЕСКАЯ
   избыточность (не мешают, но больше ни на что не влияют): единственная
   действующая проверка сегодня — роль ``apps.access``.
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
   (``resolve_hr_access``, на момент написания тестов) тоже отвергала — они
   прошли бы и без единого ``module=``. Задача 9 блока I сняла старую модель
   целиком, и гейт остался ЕДИНСТВЕННОЙ защитой — тогда, до её снятия, нужен
   был вызывающий, которого старая модель ПУСКАЛА, а гейт — нет:
   ``is_staff=True`` БЕЗ единой роли. ``resolve_hr_access`` по
   ``token.is_elevated`` давал ему ``HRAccess(level="lead",
   permissions={"*"})`` — старая модель открывала ему всё, — а
   ``permissions_for`` без назначений (и без ``is_superuser``) отдаёт
   ``{}``, уровень ``none``, и гейт обязан ответить 403 (это верно и
   сегодня, ``resolve_hr_access`` в формуле участвовать перестал, но исход
   для этого вызывающего тот же). Эти тесты падают, стоит снять ``module=``
   с ручки, — проверено вживую при раунде правок 1 (см. отчёт задачи 5).
"""

from __future__ import annotations

import datetime

import pytest
from django.test import Client

from apps.access.models import Role, RoleAssignment, ScopeKind
from apps.hr.models import (
    Department,
    Employee,
    PersonnelHistory,
    Position,
    ReportingRelation,
    StaffingPosition,
    WeekTemplate,
)
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/hr/v1"

_FIVE_TWO = {str(i): {"type": "working", "hours": 8} for i in range(5)}
_FIVE_TWO.update({"5": {"type": "weekend", "hours": 0}, "6": {"type": "weekend", "hours": 0}})


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
def senior_employee(company_row, hr_dep):
    """Задача 6: старший кадровик — на момент написания старая модель тоже
    отвечала ``senior`` (несёт ``STAFFING_VIEW``/``STAFFING_MANAGE``/
    ``CALENDAR_MANAGE``/``EMPLOYEES_VIEW_ALL`` — см. ``apps/hr/
    permissions.py::_SENIOR``); действующая сегодня (задача 9) — роль
    ``hr-senior`` (агрегат модуля ``hr`` — ``admin``, факт блока I). Нужен
    там, где ``middle``/``junior`` не несут нужного узла
    (``hr.staffing.*``/``hr.calendar.manage`` появляются только с senior) —
    в отличие от employees/org (задача 5), где middle/lead уже достаточно."""
    pos = Position.objects.create(title="Senior HR Manager", department=hr_dep, weight=30)
    user = _mk("senior-gate")
    emp = Employee.objects.create(
        email="senior-gate@htq.test", department=hr_dep, position=pos,
        hire_date=datetime.date(2024, 1, 9), user_id=user.id,
        first_name="Синьор", last_name="Кадровый",
    )
    give_seeded_role(user, company_row, "hr-senior")
    return emp, headers(user, company_row)


@pytest.fixture
def staff_admin(company_row):
    """Задача 6: ``is_staff=True`` (проходит ``admin=True``/``require_admin``
    в теле — тот предикат смотрит ТОЛЬКО на флаги токена, не на Employee/
    Position) + роль ``hr-lead`` (агрегат модуля ``hr`` — ``admin``). Нужна
    там, где проверка ручки — буквальный ``admin=True`` (PMO,
    personnel-history): ``lead_employee`` (несёт роль, но не ``is_staff``)
    эту дверь не проходит вовсе — ``require_admin`` не смотрит на Employee,
    только на флаги токена."""
    user = _mk("staff-admin", is_staff=True)
    give_seeded_role(user, company_row, "hr-lead")
    return headers(user, company_row)


@pytest.fixture
def staff_without_roles(company_row):
    """``is_staff=True`` БЕЗ единой роли и без Employee-профиля.

    До задачи 9 старая модель его ПУСКАЛА везде: ``resolve_hr_access``
    первой строкой смотрел ``token.is_elevated`` (``is_admin or is_staff or
    is_superuser``) и отдавал ``HRAccess(level="lead", permissions={"*"})``,
    не заглядывая ни в Employee, ни в Position; ``admin=True`` на ручках
    должностей — тот же предикат (``require_admin``, он не снят и действует
    сегодня так же). Гейт модуля его НЕ пускает ни тогда, ни сейчас:
    ``permissions_for`` короткое замыкание делает только для
    ``is_superuser``, а дальше считает по назначениям ролей — их нет,
    карта пустая, уровень модуля ``none``. Единственный вызывающий, на
    котором 403 доказывает именно гейт, а не (бывшую) старую модель.
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
    ``module="hr"`` отказывает раньше, чем запрос доходит до тела вьюхи."""
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
    ``level="write"``: гейт отказывает раньше, чем запрос доходит до тела
    вьюхи и её собственной проверки узла (``access.has(EMPLOYEES_EDIT)`` —
    junior не имеет ``hr.employees.edit`` и отказала бы тоже, но до неё дело
    не доходит)."""
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


# ── чувствительность к гейту: is_staff без ролей — старая модель пускала ──
#
# Каждый тест ниже прошёл бы со статусом 2xx, не будь на ручке module=/level=
# (это было верно и до задачи 9: старая модель — resolve_hr_access →
# is_elevated → level="lead", {"*"} — давала этому вызывающему всё же тогда).
# ``admin=True`` → ``require_admin`` → ``is_elevated`` не менялся и даёт то
# же самое сегодня. Отказать может ТОЛЬКО гейт. Убери module= с ручки —
# соответствующий тест упадёт (проверено вживую при раунде правок 1, см.
# отчёт задачи 5).


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


# ── регресс: производственный календарь этой задачей (5) НЕ тронут ────────


@pytest.mark.django_db
def test_production_calendar_is_untouched_by_this_task(client, plain_employee):
    """``/calendar/*`` — вне области задачи 5 (справочники
    сотрудников/отделов/должностей/оргструктуры, не календарь — брифом
    отдано задаче 6, см. ``apps.access.self_service`` примечание к
    ``calendar_year``/``calendar_working_days``). Поведение для
    ``employee-basic`` НЕ менялось задачей 5: ``_require_permission(
    CALENDAR_VIEW)`` уже тогда требовала кадровый уровень (``_JUNIOR`` и
    выше), которого у employee-basic нет ни по старой, ни по новой модели —
    403 ДО задачи 5. ⚠️ Обновлено задачей 6: ``calendar_year`` теперь
    ДЕЙСТВИТЕЛЬНО несёт ``module="hr", level="read"`` (секция 5 ниже) — но
    для employee-basic результат тот же самый 403 (ни одного узла ``hr.*``,
    гейт отказывает даже раньше, чем добрался бы до ``_require_permission``),
    поэтому regression держится и после задачи 6, просто по другой причине."""
    _emp, head = plain_employee
    resp = client.get(f"{BASE}/calendar/", **head)
    assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════
#  Задача 6: остальные экраны hr — штатное расписание, календарь, документы,
#  карточка Т2/groups, PMO, назначение подтверждающего идентичности + hr в
#  TRANSLATED_APPS.
# ═══════════════════════════════════════════════════════════════════════════
#
# Тот же формат, что у секций 1–4: держатель настоящей роли проходит гейт
# ровно на своём уровне (решение по-прежнему у СТАРОЙ модели), а
# ``staff_without_roles`` (старая модель пускает через ``is_elevated``/
# ``admin=True``, новая — нет) доказывает, что 403 даёт ИМЕННО гейт, а не
# что-то ещё. ``senior_employee`` — новая фикстура этой секции: часть старых
# ключей (``hr.staffing.*``, ``hr.calendar.manage``) появляется только с
# senior, не с middle (``apps/hr/permissions.py::_MIDDLE``/``_SENIOR``).


@pytest.fixture
def staffing_line(eng_dep):
    pos = Position.objects.create(title="Инженер", department=eng_dep, weight=50)
    return StaffingPosition.objects.create(position=pos, department=eng_dep)


# ── /staffing/* ──────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_hr_senior_reads_staffing_occupancy(client, senior_employee):
    _emp, head = senior_employee
    resp = client.get(f"{BASE}/staffing/occupancy", **head)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_staff_without_roles_cannot_read_staffing_occupancy(client, staff_without_roles):
    """``staffing_occupancy`` — ``level="read"``; ``_require_permission(
    STAFFING_VIEW)`` в теле пропустил бы ``{"*"}`` — отказывает только гейт."""
    resp = client.get(f"{BASE}/staffing/occupancy", **staff_without_roles)
    assert resp.status_code == 403


@pytest.mark.django_db
def test_hr_senior_creates_a_staffing_line(client, senior_employee, eng_dep):
    _emp, head = senior_employee
    pos = Position.objects.create(title="Прораб", department=eng_dep, weight=51)
    resp = client.post(
        f"{BASE}/staffing/", data={"position_id": pos.id, "department_id": eng_dep.id},
        content_type="application/json", **head,
    )
    assert resp.status_code == 201


@pytest.mark.django_db
def test_staff_without_roles_cannot_create_a_staffing_line(client, staff_without_roles, eng_dep):
    pos = Position.objects.create(title="Прораб", department=eng_dep, weight=52)
    resp = client.post(
        f"{BASE}/staffing/", data={"position_id": pos.id, "department_id": eng_dep.id},
        content_type="application/json", **staff_without_roles,
    )
    assert resp.status_code == 403
    assert not StaffingPosition.objects.filter(position=pos).exists()


@pytest.mark.django_db
def test_hr_senior_deletes_a_staffing_line(client, senior_employee, staffing_line):
    _emp, head = senior_employee
    resp = client.delete(f"{BASE}/staffing/{staffing_line.id}", **head)
    assert resp.status_code == 204


@pytest.mark.django_db
def test_staff_without_roles_cannot_delete_a_staffing_line(client, staff_without_roles, staffing_line):
    """``_delete_staffing_line`` — ``level="admin"`` (delete-правило), хотя
    старая проверка внутри та же ``STAFFING_MANAGE``, что и у create/update —
    ``{"*"}`` её тоже проходит, отказывает только гейт."""
    resp = client.delete(f"{BASE}/staffing/{staffing_line.id}", **staff_without_roles)
    assert resp.status_code == 403
    assert StaffingPosition.objects.filter(id=staffing_line.id).exists()


# ── /calendar/* (модульный) ──────────────────────────────────────────────


@pytest.mark.django_db
def test_hr_senior_reads_calendar_year(client, senior_employee):
    _emp, head = senior_employee
    resp = client.get(f"{BASE}/calendar/?year=2026", **head)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_staff_without_roles_cannot_read_calendar_year(client, staff_without_roles):
    resp = client.get(f"{BASE}/calendar/?year=2026", **staff_without_roles)
    assert resp.status_code == 403


@pytest.mark.django_db
def test_hr_senior_creates_a_calendar_template(client, senior_employee):
    _emp, head = senior_employee
    resp = client.post(
        f"{BASE}/calendar/templates/", data={"name": "5/2 сеньор", "days": _FIVE_TWO},
        content_type="application/json", **head,
    )
    assert resp.status_code == 201


@pytest.mark.django_db
def test_staff_without_roles_cannot_create_a_calendar_template(client, staff_without_roles):
    resp = client.post(
        f"{BASE}/calendar/templates/", data={"name": "Чужой", "days": _FIVE_TWO},
        content_type="application/json", **staff_without_roles,
    )
    assert resp.status_code == 403
    assert not WeekTemplate.objects.filter(name="Чужой").exists()


@pytest.mark.django_db
def test_staff_without_roles_cannot_delete_a_calendar_template(client, staff_without_roles):
    tmpl = WeekTemplate.objects.create(name="Держится", days=_FIVE_TWO)
    resp = client.delete(f"{BASE}/calendar/templates/{tmpl.id}", **staff_without_roles)
    assert resp.status_code == 403
    assert WeekTemplate.objects.filter(id=tmpl.id).exists()


@pytest.mark.django_db
def test_staff_without_roles_cannot_read_employee_calendar(client, staff_without_roles, target_employee):
    """``employee_calendar`` — ``level="read"`` ПОВЕРХ ``_visible_access``
    (видимость отдела); до задачи 9 ``{"*"}`` старой модели прошёл бы и её
    отдельную «есть ли HR-доступ вообще», и видимость отдела — отказывает
    только гейт."""
    resp = client.get(
        f"{BASE}/employees/{target_employee.id}/calendar"
        "?start=2026-06-01&end=2026-06-01",
        **staff_without_roles,
    )
    assert resp.status_code == 403


# ── /documents/* — только гейтированные ручки (multipart/JSON/patch) ──────
#
# Раунд правок 1: ``POST /documents/`` — ОДНА ручка (``documents_
# collection``), диспетчеризуемая по ``Content-Type`` на две функции
# (``_upload_document_multipart``/``_upload_document``). Обе теперь несут
# ``module="hr", level="write"`` — гейт не должен сниматься сменой
# заголовка запроса, поэтому обе ветки проверяются отдельно ниже, ОДНИМ
# и тем же ``staff_without_roles``.


@pytest.mark.django_db
def test_staff_without_roles_cannot_upload_a_document_multipart(client, staff_without_roles, target_employee):
    resp = client.post(
        f"{BASE}/documents/",
        data={"employee": str(target_employee.id), "title": "Т", "doc_type": "other"},
        **staff_without_roles,
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_staff_without_roles_cannot_upload_a_document_json(client, staff_without_roles, target_employee):
    """Зеркало ``..._multipart`` выше для JSON-ветки той же ручки — гейт
    обязан отказывать одинаково независимо от ``Content-Type``, иначе он
    хуже отсутствующего (сообщает, что ручка защищена, а сам обходится
    сменой заголовка)."""
    resp = client.post(
        f"{BASE}/documents/",
        data={
            "employee_id": target_employee.id, "title": "Т", "doc_type": "other",
            "file_path": "/files/x.pdf", "file_size": 1, "uploaded_by": target_employee.id,
        },
        content_type="application/json",
        **staff_without_roles,
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_staff_without_roles_cannot_patch_a_document(client, staff_without_roles, target_employee):
    from apps.hr.models import Document

    doc = Document.objects.create(
        employee=target_employee, title="Т", doc_type="other",
        file_path="/files/a.pdf", file_size=1,
    )
    resp = client.patch(
        f"{BASE}/documents/{doc.id}/", data={"title": "Новое"},
        content_type="application/json", **staff_without_roles,
    )
    assert resp.status_code == 403
    doc.refresh_from_db()
    assert doc.title == "Т"


# ── /employees/{id}/card/t2, /card/groups ──────────────────────────────────


@pytest.mark.django_db
def test_hr_senior_reads_card_t2(client, senior_employee, target_employee):
    """senior несёт ``EMPLOYEES_VIEW_ALL`` — видит карточку сотрудника ЧУЖОГО
    отдела (``target_employee`` в ``eng_dep``, senior — в ``hr_dep``)."""
    _emp, head = senior_employee
    resp = client.get(f"{BASE}/employees/{target_employee.id}/card/t2", **head)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_staff_without_roles_cannot_read_card_t2(client, staff_without_roles, target_employee):
    resp = client.get(f"{BASE}/employees/{target_employee.id}/card/t2", **staff_without_roles)
    assert resp.status_code == 403


@pytest.mark.django_db
def test_staff_without_roles_cannot_edit_card_groups(client, staff_without_roles, target_employee):
    resp = client.put(
        f"{BASE}/employees/{target_employee.id}/card/groups", data={"education": []},
        content_type="application/json", **staff_without_roles,
    )
    assert resp.status_code == 403


# ── /pmo/* — только гейтированные (admin=True) task-6 ручки ────────────────


@pytest.mark.django_db
def test_staff_admin_creates_a_pmo(client, staff_admin):
    """``_create_pmo`` — старая дверь ``admin=True`` смотрит ТОЛЬКО на
    ``token.is_elevated`` (не на Employee) — ``staff_admin`` несёт и её, и
    новую роль ``hr-lead``."""
    resp = client.post(
        f"{BASE}/pmo/", data={"name": "Проект А", "code": "P-A"},
        content_type="application/json", **staff_admin,
    )
    assert resp.status_code == 201


@pytest.mark.django_db
def test_staff_without_roles_cannot_create_a_pmo(client, staff_without_roles):
    """``_create_pmo`` — ``admin=True`` (``is_staff`` ПРОХОДИТ, как и у
    ``_create_position`` в секции 4) + ``module="hr", level="admin"``:
    отказывает ровно вторая дверь."""
    from apps.hr.models import PMO

    resp = client.post(
        f"{BASE}/pmo/", data={"name": "Чужой проект", "code": "P-X"},
        content_type="application/json", **staff_without_roles,
    )
    assert resp.status_code == 403
    assert not PMO.objects.filter(code="P-X").exists()


# ── /identity-approver — PUT (назначение) под гейтом, GET — открыт ────────


@pytest.mark.django_db
def test_hr_lead_sets_identity_approver(client, lead_employee):
    """``_set_identity_approver`` — ``module="hr", level="admin"`` ПОВЕРХ
    ``hr.identity.manage``; ``hr-lead`` несёт оба (``_LEAD`` — единственный
    пресет с ``IDENTITY_MANAGE``, см. ``apps/hr/permissions.py``)."""
    emp, head = lead_employee
    resp = client.put(
        f"{BASE}/identity-approver/", data={"user_id": None},
        content_type="application/json", **head,
    )
    assert resp.status_code == 200


@pytest.mark.django_db
def test_staff_without_roles_cannot_set_identity_approver(client, staff_without_roles):
    """``is_staff`` даёт ``is_admin``-эквивалент в СТАРОЙ проверке
    (``_identity_access`` -> ``is_admin=require_admin(token)`` — тоже
    ``is_elevated``-based, ПРОХОДИТ), отказывает только новый гейт."""
    resp = client.put(
        f"{BASE}/identity-approver/", data={"user_id": None},
        content_type="application/json", **staff_without_roles,
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_employee_basic_still_reads_identity_approver(client, plain_employee):
    """GET ``/identity-approver/`` — ``open`` (реестр self_service): не
    гейтируется, потому что кто подтверждающий — не секрет, а approver-
    escape-ход (право РЕШАТЬ у назначенного, не у кадровика) не должен
    упираться в гейт модуля на этой ручке. employee-basic по-прежнему
    читает без единого узла ``hr.*`` — задача 6 это не сузила."""
    _emp, head = plain_employee
    resp = client.get(f"{BASE}/identity-approver/", **head)
    assert resp.status_code == 200


# ── /personnel-history/ — writes admin=True, reads open ────────────────────


@pytest.mark.django_db
def test_staff_admin_creates_personnel_history(client, staff_admin, target_employee):
    """``_create_personnel_history`` — та же ``admin=True``-дверь, что у
    PMO: смотрит на токен, не на Employee, поэтому ``staff_admin``, не
    ``lead_employee``."""
    resp = client.post(
        f"{BASE}/personnel-history/",
        data={"employee": target_employee.id, "event_type": "hired", "event_date": "2026-01-01"},
        content_type="application/json", **staff_admin,
    )
    assert resp.status_code == 201


@pytest.mark.django_db
def test_staff_without_roles_cannot_create_personnel_history(client, staff_without_roles, target_employee):
    """``_create_personnel_history`` — ``admin=True`` (проходит) +
    ``module="hr", level="admin"``: отказывает вторая дверь."""
    resp = client.post(
        f"{BASE}/personnel-history/",
        data={"employee": target_employee.id, "event_type": "hired", "event_date": "2026-01-01"},
        content_type="application/json", **staff_without_roles,
    )
    assert resp.status_code == 403
    assert not PersonnelHistory.objects.filter(employee=target_employee).exists()


@pytest.mark.django_db
def test_employee_basic_still_reads_personnel_history(client, plain_employee):
    _emp, head = plain_employee
    resp = client.get(f"{BASE}/personnel-history/", **head)
    assert resp.status_code == 200


# ── regression: секции ``open``/``self`` реестра — не сужены задачей 6 ────


@pytest.mark.django_db
def test_employee_basic_still_reads_the_open_vacancy_list(client, plain_employee):
    _emp, head = plain_employee
    resp = client.get(f"{BASE}/vacancies/", **head)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_employee_basic_still_reads_the_open_pmo_list(client, plain_employee):
    _emp, head = plain_employee
    resp = client.get(f"{BASE}/pmo/", **head)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_employee_basic_still_reads_audit_logs(client, plain_employee):
    _emp, head = plain_employee
    resp = client.get(f"{BASE}/logs/", **head)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_employee_basic_can_still_create_and_list_own_share_link(client, plain_employee):
    """``self`` (реестр self_service): привязано к ``request.token.user_id``,
    не к роли — доступно employee-basic без единого узла ``hr.*``."""
    emp, head = plain_employee
    resp = client.post(
        f"{BASE}/share-links/", data={"target_type": "org"},
        content_type="application/json", **head,
    )
    assert resp.status_code == 201
    assert "token" in resp.json()

    listed = client.get(f"{BASE}/share-links/", **head)
    assert listed.status_code == 200
    assert len(listed.json()) == 1


# ── hr в TRANSLATED_APPS (финальный шаг задачи 6) ──────────────────────────


def test_hr_is_in_translated_apps():
    """Последний шаг задачи 6: как только ``hr`` попадает в ``TRANSLATED_
    APPS``, сторож ``apps.access.tests.test_gate`` начинает требовать
    ``module=`` у КАЖДОЙ ручки этой аппки, кроме перечисленных в
    ``SELF_SERVICE``, — это и есть главная проверка «ничего не забыто»,
    её прогон см. в отчёте задачи."""
    from apps.access.self_service import TRANSLATED_APPS

    assert "hr" in TRANSLATED_APPS


# ── Сознательное исключение №3 (рулинг O финальной волны блока I) ─────────
#
# Разрушающие ручки, которые до блока были голым auth="jwt" и остались в
# реестре как ``open``: закрытие вакансии, удаление отклика, записи учёта
# времени, документа. Основание — то же, что у удаления отделов (задача 5,
# рулинг I-2): кнопка в UI видна только кадровику с правом писать по всей
# компании (seeded — hr-senior/hr-lead, агрегат admin), поэтому гейт admin
# сужает лишь тех, кого UI сюда не пускал. Создание/правка — по-прежнему open.


def _destructive_target(kind: str, target_employee):
    """(URL, «ресурс ещё цел?») для каждой из четырёх ручек."""
    from apps.hr.models import Application, Document, TimeEntry, Vacancy

    if kind == "vacancy":
        obj = Vacancy.objects.create(title="Инженер", department=target_employee.department,
                                     position=target_employee.position, status="open")
        return f"{BASE}/vacancies/{obj.id}/", lambda: Vacancy.objects.get(id=obj.id).status == "open"
    if kind == "application":
        vacancy = Vacancy.objects.create(title="Инженер", department=target_employee.department,
                                         position=target_employee.position)
        obj = Application.objects.create(vacancy=vacancy, candidate_name="И",
                                         candidate_email="cand@htq.test")
        return f"{BASE}/applications/{obj.id}/", Application.objects.filter(id=obj.id).exists
    if kind == "time_entry":
        obj = TimeEntry.objects.create(employee=target_employee, date=datetime.date(2026, 1, 5),
                                       start_time=datetime.time(9, 0), end_time=datetime.time(17, 0))
        return f"{BASE}/time-tracking/entries/{obj.id}/", TimeEntry.objects.filter(id=obj.id).exists
    obj = Document.objects.create(employee=target_employee, title="Т", doc_type="other",
                                  file_path="/files/a.pdf", file_size=1)
    return f"{BASE}/documents/{obj.id}/", Document.objects.filter(id=obj.id).exists


_DESTRUCTIVE = ("vacancy", "application", "time_entry", "document")


@pytest.mark.django_db
@pytest.mark.parametrize("kind", _DESTRUCTIVE)
def test_staff_without_roles_cannot_run_destructive_open_handles(
        client, staff_without_roles, target_employee, kind):
    url, intact = _destructive_target(kind, target_employee)
    assert client.delete(url, **staff_without_roles).status_code == 403
    assert intact()


@pytest.mark.django_db
@pytest.mark.parametrize("kind", _DESTRUCTIVE)
def test_hr_middle_cannot_run_destructive_open_handles(
        client, middle_employee, target_employee, kind):
    """middle — ``hr:write`` со своим отделом: кнопки удаления в UI у него
    нет (``companyWide`` на экранах), гейт admin его и не пускает."""
    _emp, head = middle_employee
    url, intact = _destructive_target(kind, target_employee)
    assert client.delete(url, **head).status_code == 403
    assert intact()


@pytest.mark.django_db
@pytest.mark.parametrize("kind", _DESTRUCTIVE)
def test_hr_senior_runs_destructive_open_handles_as_before(
        client, senior_employee, target_employee, kind):
    _emp, head = senior_employee
    url, intact = _destructive_target(kind, target_employee)
    assert client.delete(url, **head).status_code == 204
    assert not intact()


def test_destructive_handles_left_the_open_registry():
    from apps.access.self_service import SELF_SERVICE

    gone = {"_close_vacancy", "_delete_application", "_delete_time_entry", "_delete_document"}
    assert gone.isdisjoint(SELF_SERVICE["hr"])

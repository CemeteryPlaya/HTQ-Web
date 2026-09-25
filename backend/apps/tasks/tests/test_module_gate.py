"""Блок I, задача 7: ``tasks`` под гейтом ``module="tasks", level=…``.

Продолжает ``apps.access.tests.test_module_gate``/``apps.users.tests.
test_module_gate``/``apps.hr.tests.test_module_gate`` (те же приёмы:
``Client()``, засеянные роли, заголовок компании) — этот файл его последнее
звено: ``tasks`` — четвёртая и последняя аппка блока I, и с её включением в
``apps.access.self_service.TRANSLATED_APPS`` сторож
``apps/access/tests/test_gate.py::test_gate_covers_every_handle_of_
translated_apps`` начинает требовать ``module=`` у 122 из её 128 ручек.
Шесть исключений (раунд правок 1) — ``/notifications/*``: платформенная
лента (колокольчик в шапке, несёт уведомления мессенджера/конференций/
календаря тоже, не только задач), защищённая строго ``request.token.
user_id`` без единого параметра-подмены — ``self`` в реестре
``SELF_SERVICE["tasks"]``, тот же принцип, что у ``users._get_profile``/
``hr.my_employee`` (см. докстринг ``self_service``).

Отличие от ``hr``: у ``tasks`` есть засеянная роль рядового сотрудника
(``employee-basic``, ``access/migrations/0004_seed_employee_role.py``) с
узлами ``tasks.tasks`` (``view/create/edit``), ``tasks.calendar``
(``view/create``) и ``tasks.daily_reports`` (``view/create``) — ни одного
``can_delete``. ``apps.access.services.resolve.permissions_for`` считает
уровень МОДУЛЯ по ВСЕМУ его поддереву (объединяя флаги всех узлов роли под
``tasks``/``tasks.*``), поэтому overall-уровень ``employee-basic`` на модуль
``tasks`` — ``write`` (``apps/access/depth.py::legacy_level``: ``DELETE``
отсутствует, ``CREATE``/``EDIT`` есть → ``write``), а НЕ ``read``. Отсюда
два вывода, которые тесты ниже проверяют напрямую:

1. Обычные CRUD-ручки задач/календаря/ежедневки, гейтированные на
   ``level="read"``/``"write"``, ``employee-basic`` не теряет — её
   overall-уровень модуля уже ``write`` (пункт 1 брифа задачи 7).
2. Управленческая сводка по группе (``GET /holding/projects``,
   ``holding_projects`` — единственная ручка домена, где ``is_elevated``
   раньше был ЧИСТЫМ гейтом, без запасного хода по владению) стоит РОВНО на
   ``level="admin"``, а не ``"write"``: будь она на ``"write"``,
   ``employee-basic`` прошла бы её ТОЖЕ (тот же overall ``write``) — только
   ``admin`` реально отсекает роль без единого ``can_delete`` где-либо в
   поддереве ``tasks``.

Чувствительность к гейту (не к старой конвенции ``is_elevated``) доказывает
``staff_without_roles``: ``is_staff=True`` без единой роли. Старая
конвенция домена задач читает флаг ``request.token.is_elevated`` (``is_admin
or is_staff or is_superuser``) — этот вызывающий её проходит ВЕЗДЕ, где она
раньше стояла (``admin=True`` на словарях, чистый гейт ``holding_
projects``). Новая — ``permissions_for`` без единого назначения роли отдаёт
``{}``, уровень ``none``: гейт отказывает.

Проверено вручную (не автоматизировано здесь — временная правка руками, не
коммитится), сняв ``module=``/``level=`` с двух РАЗНЫХ по устройству ручек:

* ``_create_label`` (``admin=True`` — старая дверь) — без гейта модуля
  ``test_staff_without_roles_cannot_create_a_label`` падает (201 вместо
  403), остальные 12 тестов файла остаются зелёными: сняли ровно одну дверь
  у ровно одной ручки.
* ``holding_projects`` (чистый ``is_elevated``-гейт, без запасного хода по
  владению) — без гейта модуля ``test_employee_basic_is_denied_the_
  holding_summary``/``test_staff_without_roles_cannot_read_the_holding_
  summary`` тоже падают (запрос доходит до ``holding_service.
  projects_by_company()``, которому по-настоящему собранных вьюх холдинга в
  изолированной БД этого файла взять неоткуда). Оба теста стоят намеренно
  на ``holding_company`` (не на ``company_row``): на не-холдинговом
  поддомене ``_deny_unless_holding`` отказал бы САМ ПО СЕБЕ, и 403 не
  доказывал бы ничего про гейт модуля конкретно — первая версия этого файла
  была на этом поймана и переписана.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.access.models import Role, RoleAssignment, ScopeKind
from apps.access.tests.helpers import assign
from apps.tasks.models import Task, TaskVolume, WorkVolumeType
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/tasks/v1"


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
    """Назначить УЖЕ существующую роль каталога — засеянную миграцией.

    Тесты этого файла — обычные ``@pytest.mark.django_db`` (не
    ``transaction=True``), поэтому роль, засеянная миграцией ДО начала
    тестовой транзакции, спокойно переживает её: ловушка «transaction=True
    стирает засеянные миграцией роли» (см. CLAUDE.md/бриф задачи 7) здесь не
    в игре — она про TRUNCATE-очистку, а не про откат обычной атомарной
    транзакции.
    """
    RoleAssignment.objects.create(company_slug=slug, user_id=user.id,
                                  role=Role.objects.get(code=code),
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)


@pytest.fixture
def employee_basic(company_row):
    """Рядовой сотрудник — настоящая ``employee-basic``, не синтетика."""
    user = _mk("rank-file-tasks")
    give_seeded_role(user, company_row, "employee-basic")
    return user, headers(user, company_row)


@pytest.fixture
def module_admin(company_row):
    """Держатель роли ``tasks`` уровня ``admin`` (полный доступ к модулю) —
    синтетическая роль через ``assign()``: несёт ``can_delete``, поэтому
    ``legacy_level`` даёт ``admin``, в отличие от ``employee-basic`` выше.

    ``is_staff=True`` тоже: часть admin-ручек домена (словари — labels,
    equipment, ...) держат СТАРУЮ дверь ``admin=True`` (``require_admin`` =
    ``is_elevated``) РЯДОМ с новым гейтом, не вместо него (тот же приём, что
    ``apps/hr/tests/test_module_gate.py::staff_admin``) — эта фикстура
    обязана пройти ОБЕ.
    """
    user = _mk("tasks-module-admin", is_staff=True)
    assign(company_row, user.id, "tasks", "full")
    return user, headers(user, company_row)


@pytest.fixture
def staff_without_roles(company_row):
    """``is_staff=True`` БЕЗ единой роли и без назначений.

    Старая конвенция (``request.token.is_elevated``) пускает его везде, где
    раньше стояла (см. докстринг модуля); новый гейт — нигде. Единственный
    вызывающий, на котором 403 доказывает именно гейт, а не что-то ещё.
    """
    user = _mk("staff-no-roles-tasks", is_staff=True)
    return user, headers(user, company_row)


@pytest.fixture
def holding_company(db):
    """Компания вида ``holding`` (без схемы — как ``company_row``, только со
    своим kind): нужна ``module_admin``, чтобы дойти до ``_deny_unless_
    holding`` внутри ``holding_projects`` и доказать, что гейт МОДУЛЯ его
    пропускает — правило поддомена внутри вьюхи проверяется отдельным файлом
    (``test_holding_api.py``), не здесь.
    """
    from apps.companies.models import Company, CompanyKind

    slug = "tsk-gate-holding"
    Company.objects.create(slug=slug, name="Holding gate fixture",
                           kind=CompanyKind.HOLDING)
    return slug


# ── employee-basic: сохраняет СВОИ задачи, календарь и ежедневку ──────────


@pytest.mark.django_db
def test_employee_basic_lists_and_creates_tasks(client, employee_basic):
    """``_list_tasks``/``_create_task`` — ``level="read"``/``"write"``.

    ``employee-basic`` не несёт отдельного узла ``tasks.tasks`` на КАЖДУЮ
    ручку — узел один, а уровень МОДУЛЯ считается по всему поддереву
    (докстринг модуля): раз он ``write``, обе ручки открыты.
    """
    _user, head = employee_basic
    listed = client.get(f"{BASE}/tasks/", **head)
    assert listed.status_code == 200

    created = client.post(
        f"{BASE}/tasks/",
        data={"summary": "Своя задача"},
        content_type="application/json", **head,
    )
    assert created.status_code == 201


@pytest.mark.django_db
def test_employee_basic_files_a_daily_report_on_their_own_task(client, employee_basic):
    """``_create_task_report`` — ``level="write"``, ПОВЕРХ ``require_soft_
    edit`` (владение — задача СВОЯ, employee-basic в ней исполнитель).
    ``tasks.daily_reports`` несёт только ``view/create`` — тот же overall
    ``write`` модуля, что и у ``tasks.tasks``, открывает и эту ручку тоже.
    """
    user, head = employee_basic
    volume_type = WorkVolumeType.objects.create(slug="valy", name="Валы")
    task = Task.objects.create(key="GATE-1", summary="Своя смена",
                               assignee_id=user.id, reporter_id=user.id)
    TaskVolume.objects.create(task=task, volume_type=volume_type,
                              planned_quantity=100)

    resp = client.post(
        f"{BASE}/tasks/{task.id}/daily-reports",
        data={"work_date": "2026-06-05", "quantity": "50"},
        content_type="application/json", **head,
    )
    assert resp.status_code == 201


@pytest.mark.django_db
def test_employee_basic_reads_and_creates_calendar_events(client, employee_basic):
    """``_list_events``/``_create_event`` — ``level="read"``/``"write"``;
    ``tasks.calendar`` несёт ``view/create`` у employee-basic — тот же
    overall ``write``, что открывает и эти ручки."""
    _user, head = employee_basic
    listed = client.get(f"{BASE}/calendar/", **head)
    assert listed.status_code == 200

    created = client.post(
        f"{BASE}/calendar/",
        data={"title": "Планёрка",
              "start_at": "2026-06-05T09:00:00Z",
              "end_at": "2026-06-05T10:00:00Z"},
        content_type="application/json", **head,
    )
    assert created.status_code == 201


# ── управленческая сводка по группе: admin, не write ──────────────────────


@pytest.mark.django_db
def test_employee_basic_cannot_create_a_label(client, employee_basic):
    """Корпоративный словарь (``_create_label`` — ``admin=True`` ПОВЕРХ
    ``module="tasks", level="admin"``): overall-уровень employee-basic на
    модуль ``tasks`` — ``write`` (нет ни одного ``can_delete``), до
    ``admin`` не дотягивает. Отличие от tasks/calendar/daily_reports выше —
    здесь именно ГЕЙТ отказывает, а не отсутствие узла как такового."""
    from apps.tasks.models import Label

    _user, head = employee_basic
    resp = client.post(
        f"{BASE}/labels/", data={"name": "Рядовой", "color": "#000000"},
        content_type="application/json", **head,
    )
    assert resp.status_code == 403
    assert not Label.objects.filter(name="Рядовой").exists()


@pytest.mark.django_db
def test_module_admin_creates_a_label(client, module_admin):
    """Контраст к тесту выше: та же ручка, держатель ``tasks`` уровня
    ``admin`` (``can_delete`` где-то в поддереве) проходит обе двери —
    старый ``admin=True`` (is_staff тут не нужен вовсе, роль сама по себе
    решает) и новый ``module="tasks", level="admin"``."""
    from apps.tasks.models import Label

    _user, head = module_admin
    resp = client.post(
        f"{BASE}/labels/", data={"name": "Админский", "color": "#000000"},
        content_type="application/json", **head,
    )
    assert resp.status_code == 201
    assert Label.objects.filter(name="Админский").exists()


@pytest.mark.django_db
def test_employee_basic_is_denied_the_holding_summary(client, holding_company):
    """``holding_projects`` — ``level="admin"``. Будь она ``"write"``,
    employee-basic (overall ``write`` модуля) прошла бы её тоже.

    Проверяется на ``holding_company`` (не на ``company_row``) НАРОЧНО:
    ``company_row`` не холдинг, и там ``_deny_unless_holding`` отказал бы
    ЛЮБОМУ вызывающему сам по себе — 403 ничего не доказывал бы про гейт
    модуля конкретно (проверено вручную: сняв ``module=`` с ``holding_
    projects``, этот тест на ``company_row`` остаётся зелёным, потому что
    вторая проверка отказывает и без гейта). На поддомене холдинга
    единственная причина 403 для employee-basic — именно гейт.
    """
    user = _mk("rank-file-holding")
    give_seeded_role(user, holding_company, "employee-basic")
    head = headers(user, holding_company)

    resp = client.get(f"{BASE}/holding/projects", **head)
    assert resp.status_code == 403


@pytest.mark.django_db(transaction=True)
def test_module_admin_passes_the_gate_on_the_holding_summary(client, holding_company):
    """Держатель ``tasks`` уровня ``admin`` (``can_delete`` где-то в
    поддереве — единственное, что отличает её от ``employee-basic``)
    проходит ГЕЙТ: ответ не 403. Собранности вьюх-представлений холдинга это
    не проверяет (для этого есть ``test_holding_api.py`` — тут только
    границы доступа), поэтому дальше допускаются оба легитимных исхода:
    200 (представления есть) или 503 (``HoldingViewsUnavailable`` — их сейчас
    физически нет в изолированной тестовой БД этого файла), но не 403 и не
    голый 500.

    ``transaction=True``, не обычный ``django_db``: без реальных вьюх
    ``holding_service.projects_by_company()`` бьёт ``ProgrammingError``
    (``column tasks_project.company_slug does not exist`` — запрос ушёл в
    ``public`` вместо схемы ``holding``) и сам детектирует это как «вьюхи
    снесены» ВТОРЫМ запросом (``_views_are_gone``, докстринг явно
    предупреждает: "вызывающий не должен оборачивать сводку в
    transaction.atomic()" — ИМЕННО потому, что обычный ``django_db``
    оборачивает весь тест в ``atomic()``, и первый же ``ProgrammingError``
    отравляет транзакцию для второго запроса). ``transaction=True`` снимает
    эту обёртку — тот же приём и по той же причине, что в
    ``test_holding_api.py``.

    Не переиспользует фикстуру ``module_admin``: та выписывает роль и токен
    на ``company_row``, а ``api_view`` сверяет claim токена ``company`` с
    поддоменом запроса (вторая линия обороны — поддомен подделать
    тривиально) — под другой поддомен (``holding_company``) нужны СВОИ роль
    и токен, поэтому пользователь и назначение заводятся здесь же.
    """
    user = _mk("tasks-holding-admin")
    assign(holding_company, user.id, "tasks", "full")
    head = headers(user, holding_company)

    resp = client.get(f"{BASE}/holding/projects", **head)
    assert resp.status_code in (200, 503)


# ── чувствительность к гейту: is_staff без ролей — старая модель пускает ──
#
# Каждый тест ниже прошёл бы 2xx/201, не будь на соответствующей ручке
# module=/level=: старая конвенция домена (request.token.is_elevated) даёт
# этому вызывающему всё, что раньше стояло за ней. Отказать может ТОЛЬКО
# гейт. Убери module= с ручки — соответствующий тест упадёт (см. докстринг
# модуля и отчёт задачи 7 про ручную проверку).


@pytest.mark.django_db
def test_missing_token_is_401_not_403(client):
    """Контроль: без токена вообще — 401, а не 403. Отделяет «нет гейта
    модуля» ниже от «вообще не вошёл»."""
    resp = client.get(f"{BASE}/tasks/")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_staff_without_roles_is_denied_the_task_list(client, staff_without_roles):
    """``_list_tasks`` — ``level="read"``: сегодня голый ``auth="jwt"`` без
    единой другой проверки, отказать может только этот гейт."""
    _user, head = staff_without_roles
    resp = client.get(f"{BASE}/tasks/", **head)
    assert resp.status_code == 403


@pytest.mark.django_db
def test_staff_without_roles_cannot_create_a_task(client, staff_without_roles):
    _user, head = staff_without_roles
    resp = client.post(
        f"{BASE}/tasks/", data={"summary": "Чужая попытка"},
        content_type="application/json", **head,
    )
    assert resp.status_code == 403
    assert not Task.objects.filter(summary="Чужая попытка").exists()


@pytest.mark.django_db
def test_staff_without_roles_cannot_create_a_label(client, staff_without_roles):
    """``_create_label`` — старая дверь ``admin=True`` (``require_admin`` =
    ``is_elevated``) этого вызывающего ПРОПУСКАЕТ; отказывает ровно вторая,
    новая — ``module="tasks", level="admin"``."""
    from apps.tasks.models import Label

    _user, head = staff_without_roles
    resp = client.post(
        f"{BASE}/labels/", data={"name": "Самодел", "color": "#ffffff"},
        content_type="application/json", **head,
    )
    assert resp.status_code == 403
    assert not Label.objects.filter(name="Самодел").exists()


@pytest.mark.django_db
def test_staff_without_roles_cannot_read_the_holding_summary(client, holding_company):
    """``holding_projects`` — раньше чистый гейт по ``is_elevated`` (см.
    докстринг модуля), сегодня ``module="tasks", level="admin"``: тот же
    вызывающий, которого старая конвенция пускала бы (``is_staff=True``),
    новый гейт отклоняет. На ``holding_company``, по той же причине, что у
    ``test_employee_basic_is_denied_the_holding_summary`` выше — иначе
    ``_deny_unless_holding`` отказал бы и без единого гейта модуля."""
    user = _mk("staff-no-roles-holding", is_staff=True)
    head = headers(user, holding_company)

    resp = client.get(f"{BASE}/holding/projects", **head)
    assert resp.status_code == 403


# ── уведомления: платформенная лента, self, не module="tasks" (раунд 1) ───


@pytest.mark.django_db
def test_holder_of_an_unrelated_role_reads_and_marks_their_own_notifications(client, company_row):
    """Держатель роли БЕЗ единого узла ``tasks.*`` (здесь — только
    ``messenger``) обязан по-прежнему видеть и гасить СВОИ уведомления:
    колокольчик в шапке платформенный, не привязан к домену задач (см.
    комментарий над секцией ``Notifications`` в ``views.py`` и запись
    ``SELF_SERVICE["tasks"]`` — причина ``self``). До раунда правок 1 эти
    шесть ручек стояли под ``module="tasks", level=…`` и отказали бы этому
    вызывающему 403 — регресс, пойманный ревью, не тестами (``employee-
    basic`` в остальных тестах файла несёт ``tasks`` = write и не ловит
    сужение до чужого домена).
    """
    from apps.tasks.models import Notification

    user = _mk("messenger-only")
    assign(company_row, user.id, "messenger", "write")
    head = headers(user, company_row)

    notification = Notification.objects.create(
        recipient_id=user.id, verb="task_assigned:TASK-1")

    listed = client.get(f"{BASE}/notifications/", **head)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [notification.id]

    marked = client.post(
        f"{BASE}/notifications/{notification.id}/mark_read/", **head)
    assert marked.status_code == 204


# ── tasks в TRANSLATED_APPS (финальный шаг задачи 7) ──────────────────────


def test_tasks_is_in_translated_apps():
    """Последний шаг задачи 7: как только ``tasks`` попадает в
    ``TRANSLATED_APPS``, сторож ``apps.access.tests.test_gate`` начинает
    требовать ``module=`` у 122 из 128 её ручек (``SELF_SERVICE["tasks"]``
    несёт шесть исключений ``self`` — уведомления, раунд правок 1) — это и
    есть главная проверка «ничего не забыто»."""
    from apps.access.self_service import TRANSLATED_APPS

    assert "tasks" in TRANSLATED_APPS

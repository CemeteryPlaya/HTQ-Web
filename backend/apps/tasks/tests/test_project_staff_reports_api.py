"""Отчёты по персоналу проекта — вторая ось факта, рядом с ежедневкой.

Четыре вещи, ради которых модуль заведён, и которые тесты стерегут:

* **численность это состояние, а не инкремент**: ``UNIQUE(project,
  site_block, work_date)`` ЕСТЬ — в отличие от ``DailyReport``, где его нет
  намеренно, потому что смены складываются. Два отчёта за один день по
  одному блоку — не две смены, а двойной счёт людей;
* **дата выхода ≠ дата заполнения** — то же различие, что у ежедневки;
* **каждая правка оставляет след**, и снимок включает строки: правят чаще
  всего именно их;
* **это управленческие данные**: смотрит и ведёт их руководство,
  ответственный за проект и админ — в отличие от ежедневки, куда о своей
  смене отчитывается любой участник задачи.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.test import Client

from apps.tasks.models import (DailyReport, Project, ProjectSite,
                               ProjectStaffReport, ProjectStaffReportRevision,
                               ResourceKind, ResourceRequirement, Roadmap,
                               Site, SiteBlock, Task, TaskVolume, WorkRole,
                               WorkVolumeType)

from .helpers import BASE, admin_token, auth, patch_json, post_json, token

D = dt.date
ME = 7          # user_id обычного токена
OTHER = 555
DAY = "2026-06-05"


@pytest.fixture
def roles(db) -> dict[str, WorkRole]:
    return {
        "montazh": WorkRole.objects.create(slug="montazh", name="Монтажник"),
        "svar": WorkRole.objects.create(slug="svar", name="Сварщик"),
    }


@pytest.fixture
def site(db) -> Site:
    return Site.objects.create(name="Сазаган", code="SZG")


@pytest.fixture
def block(site) -> SiteBlock:
    return SiteBlock.objects.create(site=site, name="Блок 1", order=1)


@pytest.fixture
def project(db, site) -> Project:
    """Проект админа: обычный токен до него доберётся только как владелец."""
    project = Project.objects.create(name="Сазаган СЭС", owner_id=9)
    ProjectSite.objects.create(project=project, site=site)
    return project


def _create(project, block, roles, *, tok=None, **over):
    body = {"site_block_id": block.id, "work_date": DAY,
            "lines": [{"work_role_id": roles["montazh"].id, "headcount": 12}],
            **over}
    return post_json(Client(), f"{BASE}/projects/{project.id}/staff-reports",
                     body, **auth(tok or admin_token()))


# ── права ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_staff_routes_require_authentication(project):
    assert Client().get(
        f"{BASE}/projects/{project.id}/staff-board").status_code == 401


@pytest.mark.django_db
def test_project_outside_scope_is_404_not_403(project):
    """404, а не 403 — тот же контракт, что у задач: иначе по кодам ответа
    можно было бы перечислять проекты чужих отделов."""
    resp = Client().get(f"{BASE}/projects/{project.id}/staff-board", **auth())
    assert resp.status_code == 404


@pytest.mark.django_db
def test_owner_inside_scope_may_lead_staffing(project, block, roles,
                                              monkeypatch):
    """Внутри своей области видимости численность ведёт владелец проекта."""
    from apps.tasks.services import hydration

    monkeypatch.setattr(hydration, "employee_department_id", lambda _: 3)
    Project.objects.filter(pk=project.id).update(department_id=3, owner_id=ME)

    assert _create(project, block, roles, tok=token()).status_code == 201


@pytest.mark.django_db
def test_non_owner_inside_scope_is_denied(project, block, roles, monkeypatch):
    """Свой отдел — ещё не основание вести чужой проект: это акт руководства."""
    from apps.tasks.services import hydration

    monkeypatch.setattr(hydration, "employee_department_id", lambda _: 3)
    Project.objects.filter(pk=project.id).update(department_id=3,
                                                 owner_id=OTHER)

    resp = Client().get(f"{BASE}/projects/{project.id}/staff-board", **auth())
    assert resp.status_code == 403


@pytest.mark.django_db
def test_project_selector_lists_only_what_the_caller_may_open(project,
                                                              monkeypatch):
    """Селектор питается тем же правилом, что и гейт: предложить проект,
    который потом даст 403, страница не должна физически."""
    from apps.tasks.services import hydration

    monkeypatch.setattr(hydration, "employee_department_id", lambda _: 3)
    Project.objects.filter(pk=project.id).update(department_id=3,
                                                 owner_id=OTHER)
    mine = Project.objects.create(name="Мой", department_id=3, owner_id=ME)

    resp = Client().get(f"{BASE}/staff-reports/projects", **auth())
    assert resp.status_code == 200
    assert [row["id"] for row in resp.json()] == [mine.id]


@pytest.mark.django_db
def test_admin_sees_every_project(project):
    resp = Client().get(f"{BASE}/staff-reports/projects", **auth(admin_token()))
    assert [row["id"] for row in resp.json()] == [project.id]


# ── создание ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_creating_a_report_writes_revision_one_with_lines(project, block,
                                                          roles):
    """История начинается с исходного состояния, и строки входят в снимок:
    правят чаще всего именно их."""
    resp = _create(project, block, roles, comment="ночная смена", lines=[
        {"work_role_id": roles["montazh"].id, "headcount": 12},
        {"work_role_id": roles["svar"].id, "headcount": 8},
    ])
    assert resp.status_code == 201
    body = resp.json()
    assert body["current_revision"] == 1
    assert body["total_headcount"] == 20
    assert body["site_name"] == "Сазаган"
    assert body["site_block_name"] == "Блок 1"

    revision = ProjectStaffReportRevision.objects.get(report_id=body["id"])
    assert revision.revision_no == 1
    assert revision.total_headcount == 20
    # Имя роли лежит В снимке: версия обязана читаться, даже если роль
    # потом переименовали или убрали из справочника.
    assert {row["work_role_name"] for row in revision.lines} == {
        "Монтажник", "Сварщик"}


@pytest.mark.django_db
def test_work_date_is_not_created_at(project, block, roles):
    """Отчёт за пятницу заполняют в понедельник — на пятницу он и ложится."""
    body = _create(project, block, roles, work_date="2026-06-05").json()
    report = ProjectStaffReport.objects.get(pk=body["id"])
    assert report.work_date == D(2026, 6, 5)
    assert report.created_at.date() != D(2026, 6, 5)


@pytest.mark.django_db
def test_second_report_for_the_same_block_and_day_is_refused(project, block,
                                                             roles):
    """Численность — состояние: «12 монтажников» от прораба и от бригадира
    это одни и те же 12 человек, а не 24. Исправляют правкой."""
    assert _create(project, block, roles).status_code == 201
    resp = _create(project, block, roles)
    assert resp.status_code == 422
    assert "уже заведён" in resp.json()["detail"]


@pytest.mark.django_db
def test_a_deleted_report_frees_the_day(project, block, roles):
    """Партиал ``WHERE NOT is_deleted`` затем и нужен: удалённый отчёт не
    должен держать день занятым."""
    report_id = _create(project, block, roles).json()["id"]
    assert Client().delete(f"{BASE}/staff-reports/{report_id}",
                           **auth(admin_token())).status_code == 204
    assert _create(project, block, roles).status_code == 201


@pytest.mark.django_db
def test_duplicate_role_in_one_report_is_422_not_500(project, block, roles):
    """Дубль ловится сервисом, а не констрейнтом: IntegrityError дал бы 500
    там, где это ошибка ввода."""
    resp = _create(project, block, roles, lines=[
        {"work_role_id": roles["montazh"].id, "headcount": 12},
        {"work_role_id": roles["montazh"].id, "headcount": 3},
    ])
    assert resp.status_code == 422
    assert "дважды" in resp.json()["detail"]


@pytest.mark.django_db
def test_report_without_lines_is_refused(project, block, roles):
    resp = _create(project, block, roles, lines=[])
    assert resp.status_code == 422


@pytest.mark.django_db
def test_unknown_work_role_is_422(project, block, roles):
    resp = _create(project, block, roles,
                   lines=[{"work_role_id": 9999, "headcount": 5}])
    assert resp.status_code == 422
    assert "не найдена" in resp.json()["detail"]


@pytest.mark.django_db
def test_block_of_a_foreign_site_is_refused(project, roles):
    """Площадка блока обязана входить в объекты проекта — правило живёт в
    ``roadmap_service.require_project_block``, одно на весь домен."""
    other = Site.objects.create(name="Алга", code="ALG")
    foreign = SiteBlock.objects.create(site=other, name="Блок X")
    resp = _create(project, foreign, roles)
    assert resp.status_code == 422
    assert "не относится к выбранному проекту" in resp.json()["detail"]


# ── правки и ревизии ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_editing_lines_increments_the_revision(project, block, roles):
    report_id = _create(project, block, roles).json()["id"]
    resp = patch_json(Client(), f"{BASE}/staff-reports/{report_id}", {
        "lines": [{"work_role_id": roles["montazh"].id, "headcount": 10}],
    }, **auth(admin_token()))

    assert resp.status_code == 200
    assert resp.json()["current_revision"] == 2
    assert resp.json()["total_headcount"] == 10
    latest = ProjectStaffReportRevision.objects.get(report_id=report_id,
                                                    revision_no=2)
    assert latest.lines[0]["headcount"] == 10


@pytest.mark.django_db
def test_a_no_op_edit_creates_no_revision(project, block, roles):
    """Лента версий отвечает «что и когда исправили», а не «сколько раз
    открывали форму»."""
    report_id = _create(project, block, roles).json()["id"]
    resp = patch_json(Client(), f"{BASE}/staff-reports/{report_id}", {
        "comment": "",
        "lines": [{"work_role_id": roles["montazh"].id, "headcount": 12}],
    }, **auth(admin_token()))

    assert resp.status_code == 200
    assert resp.json()["current_revision"] == 1
    assert ProjectStaffReportRevision.objects.filter(
        report_id=report_id).count() == 1


@pytest.mark.django_db
def test_reordered_lines_are_not_an_edit(project, block, roles):
    """Строки сравниваются нормализованным снимком: порядок в теле запроса
    не является содержанием отчёта."""
    report_id = _create(project, block, roles, lines=[
        {"work_role_id": roles["montazh"].id, "headcount": 12},
        {"work_role_id": roles["svar"].id, "headcount": 8},
    ]).json()["id"]

    resp = patch_json(Client(), f"{BASE}/staff-reports/{report_id}", {
        "lines": [{"work_role_id": roles["svar"].id, "headcount": 8},
                  {"work_role_id": roles["montazh"].id, "headcount": 12}],
    }, **auth(admin_token()))
    assert resp.json()["current_revision"] == 1


@pytest.mark.django_db
def test_moving_a_report_to_another_block_is_refused(project, site, block,
                                                     roles):
    """Не «нельзя технически», а «это другой отчёт»: перенос задним числом
    сдвинул бы численность между блоками, не оставив следа в ленте."""
    report_id = _create(project, block, roles).json()["id"]
    elsewhere = SiteBlock.objects.create(site=site, name="Блок 2", order=2)

    resp = patch_json(Client(), f"{BASE}/staff-reports/{report_id}",
                      {"site_block_id": elsewhere.id}, **auth(admin_token()))
    assert resp.status_code == 422
    assert "не меняются" in resp.json()["detail"]


@pytest.mark.django_db
def test_revisions_feed_is_readable(project, block, roles):
    report_id = _create(project, block, roles).json()["id"]
    patch_json(Client(), f"{BASE}/staff-reports/{report_id}",
               {"comment": "пересчёт по табелю"}, **auth(admin_token()))

    resp = Client().get(f"{BASE}/staff-reports/{report_id}/revisions",
                        **auth(admin_token()))
    assert resp.status_code == 200
    assert [row["revision_no"] for row in resp.json()] == [1, 2]


@pytest.mark.django_db
def test_soft_deleted_report_disappears_from_the_board(project, block, roles):
    report_id = _create(project, block, roles).json()["id"]
    Client().delete(f"{BASE}/staff-reports/{report_id}", **auth(admin_token()))

    board = Client().get(f"{BASE}/projects/{project.id}/staff-board?date={DAY}",
                         **auth(admin_token())).json()
    row = next(b for b in board["blocks"] if b["site_block_id"] == block.id)
    assert row["report_id"] is None
    assert row["total_headcount"] == 0
    assert ProjectStaffReport.objects.filter(pk=report_id).exists()


# ── доска ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_board_lists_every_block_even_without_a_report(project, block):
    """Блок без отчёта — самая нужная строка на странице: она отвечает на
    «где ещё не отчитались»."""
    board = Client().get(f"{BASE}/projects/{project.id}/staff-board",
                         **auth(admin_token())).json()
    assert [row["site_block_id"] for row in board["blocks"]] == [block.id]
    assert board["blocks"][0]["report_id"] is None


@pytest.mark.django_db
def test_board_compares_fact_against_the_roadmap_plan(project, block, roles):
    """План — потребности РОУДМАПОВ блока, действующие на дату."""
    roadmap = Roadmap.objects.create(project=project, site_block=block,
                                     name="Развозка", owner_id=9)
    ResourceRequirement.objects.create(
        roadmap=roadmap, kind=ResourceKind.HUMAN,
        work_role=roles["montazh"], quantity=15,
        start_date=D(2026, 6, 1), end_date=D(2026, 6, 30))
    _create(project, block, roles)      # факт: 12 монтажников

    board = Client().get(f"{BASE}/projects/{project.id}/staff-board?date={DAY}",
                         **auth(admin_token())).json()
    row = board["blocks"][0]
    assert row["planned_headcount"] == 15
    assert row["total_headcount"] == 12
    assert row["delta"] == -3
    assert board["total_planned"] == 15


@pytest.mark.django_db
def test_plan_outside_its_date_window_is_not_counted(project, block, roles):
    roadmap = Roadmap.objects.create(project=project, site_block=block,
                                     name="Развозка", owner_id=9)
    ResourceRequirement.objects.create(
        roadmap=roadmap, kind=ResourceKind.HUMAN,
        work_role=roles["montazh"], quantity=15,
        start_date=D(2026, 7, 1), end_date=D(2026, 7, 30))

    board = Client().get(f"{BASE}/projects/{project.id}/staff-board?date={DAY}",
                         **auth(admin_token())).json()
    # None, а не 0: без плана сравнивать не с чем, и нарисованный ноль
    # читался бы как «расхождения нет».
    assert board["blocks"][0]["planned_headcount"] is None
    assert board["blocks"][0]["delta"] is None
    assert board["total_planned"] is None


@pytest.mark.django_db
def test_task_level_requirements_do_not_double_count_the_plan(project, block,
                                                              roles):
    """Потребности задач — детализация того же плана уровнем ниже. То же
    правило, что в ``resource_service.roadmap_resource_totals``."""
    roadmap = Roadmap.objects.create(project=project, site_block=block,
                                     name="Развозка", owner_id=9)
    ResourceRequirement.objects.create(roadmap=roadmap,
                                       kind=ResourceKind.HUMAN,
                                       work_role=roles["montazh"], quantity=15)
    task = Task.objects.create(key="TASK-1", summary="T", project=project,
                               roadmap=roadmap, site_block=block)
    ResourceRequirement.objects.create(task=task, kind=ResourceKind.HUMAN,
                                       work_role=roles["montazh"], quantity=4)

    board = Client().get(f"{BASE}/projects/{project.id}/staff-board?date={DAY}",
                         **auth(admin_token())).json()
    assert board["blocks"][0]["planned_headcount"] == 15


@pytest.mark.django_db
def test_board_shows_headcount_reported_through_the_daily_board(project, block,
                                                                roles):
    """Первый агрегат, который вообще читает ``DailyReport.headcount``."""
    valy = WorkVolumeType.objects.create(slug="valy", name="Валы")
    task = Task.objects.create(key="TASK-1", summary="Развезти валы",
                               project=project, site_block=block)
    TaskVolume.objects.create(task=task, volume_type=valy,
                              planned_quantity=250)
    DailyReport.objects.create(task=task, volume_type=valy,
                               work_date=D(2026, 6, 5), quantity=40,
                               headcount=9)
    _create(project, block, roles)     # по объекту заведено 12

    board = Client().get(f"{BASE}/projects/{project.id}/staff-board?date={DAY}",
                         **auth(admin_token())).json()
    row = board["blocks"][0]
    assert row["total_headcount"] == 12
    assert row["daily_headcount"] == 9      # сверка, а не источник
    assert board["total_daily"] == 9


@pytest.mark.django_db
def test_board_role_rows_merge_plan_and_fact(project, block, roles):
    roadmap = Roadmap.objects.create(project=project, site_block=block,
                                     name="Развозка", owner_id=9)
    ResourceRequirement.objects.create(roadmap=roadmap,
                                       kind=ResourceKind.HUMAN,
                                       work_role=roles["svar"], quantity=6)
    _create(project, block, roles)     # факт только по монтажникам

    board = Client().get(f"{BASE}/projects/{project.id}/staff-board?date={DAY}",
                         **auth(admin_token())).json()
    by_name = {row["work_role_name"]: row for row in board["blocks"][0]["roles"]}
    assert by_name["Монтажник"] == {"work_role_id": roles["montazh"].id,
                                    "work_role_name": "Монтажник",
                                    "planned": None, "actual": 12}
    assert by_name["Сварщик"]["planned"] == 6
    assert by_name["Сварщик"]["actual"] == 0


@pytest.mark.django_db
def test_plan_without_a_role_still_counts_towards_the_block(project, block,
                                                            roles):
    """``ResourceRequirement.work_role`` nullable намеренно («нужно 2
    человека, роль не важна») — в итог по блоку такой план входит."""
    roadmap = Roadmap.objects.create(project=project, site_block=block,
                                     name="Развозка", owner_id=9)
    ResourceRequirement.objects.create(roadmap=roadmap,
                                       kind=ResourceKind.HUMAN, quantity=5)

    board = Client().get(f"{BASE}/projects/{project.id}/staff-board?date={DAY}",
                         **auth(admin_token())).json()
    row = board["blocks"][0]
    assert row["planned_headcount"] == 5
    assert row["roles"][0]["work_role_id"] is None
    assert row["roles"][0]["work_role_name"] == "Без указания роли"


@pytest.mark.django_db
def test_board_defaults_to_today_and_rejects_a_malformed_date(project, block):
    ok = Client().get(f"{BASE}/projects/{project.id}/staff-board",
                      **auth(admin_token()))
    assert ok.status_code == 200
    assert ok.json()["date"] == dt.date.today().isoformat()

    bad = Client().get(f"{BASE}/projects/{project.id}/staff-board?date=вчера",
                       **auth(admin_token()))
    assert bad.status_code == 422


@pytest.mark.django_db
def test_both_slash_spellings_are_registered(project):
    """``APPEND_SLASH=False``: 307 здесь не спасёт, каждое написание должно
    отвечать само."""
    hdr = auth(admin_token())
    for path in (f"{BASE}/projects/{project.id}/staff-board",
                 f"{BASE}/projects/{project.id}/staff-board/",
                 f"{BASE}/staff-reports/projects",
                 f"{BASE}/staff-reports/projects/"):
        assert Client().get(path, **hdr).status_code == 200, path

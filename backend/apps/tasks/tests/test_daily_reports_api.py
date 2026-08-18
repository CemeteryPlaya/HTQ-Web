"""Ежедневные отчёты — единственный источник факта выполнения.

Три вещи, ради которых отчёты и заведены, и которые тесты стерегут:

* **дата выполнения ≠ дата заполнения**: отчёт за пятницу заполняют в
  понедельник, и всё, что считается по дням, обязано лечь на пятницу;
* **каждая правка оставляет след**: цифра выполнения — основание для
  расчётов с партнёром, и «кто и когда её исправил» должно быть видно;
* **несколько смен в день складываются**: ``UNIQUE(task, work_date)`` нет
  намеренно.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.test import Client

from apps.tasks.models import (DailyReport, DailyReportRevision, Project,
                               ProjectSite, Roadmap, Site, SiteBlock, Task,
                               TaskVolume, WorkVolumeType)

from .helpers import (BASE, admin_token, auth, patch_json, post_json, token)

D = dt.date
ME = 7          # user_id обычного токена
OTHER = 555


@pytest.fixture
def valy(db) -> WorkVolumeType:
    return WorkVolumeType.objects.create(slug="valy", name="Валы")


@pytest.fixture
def task(db, valy) -> Task:
    task = Task.objects.create(key="TASK-1", summary="Развезти валы",
                               assignee_id=ME, reporter_id=ME)
    TaskVolume.objects.create(task=task, volume_type=valy, planned_quantity=250)
    return task


# ── создание ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_report_routes_require_authentication(task):
    assert Client().get(f"{BASE}/tasks/{task.id}/daily-reports").status_code == 401


@pytest.mark.django_db
def test_creating_a_report_writes_revision_one(task, valy):
    """История начинается с исходного состояния, а не с первой правки:
    иначе «что было до» для самого первого значения взять неоткуда."""
    resp = post_json(Client(), f"{BASE}/tasks/{task.id}/daily-reports",
                     {"work_date": "2026-06-05", "quantity": "180",
                      "headcount": 2, "comment": "две смены"}, **auth())
    assert resp.status_code == 201
    body = resp.json()
    assert body["current_revision"] == 1
    assert body["quantity"] == 180.0
    assert body["author_id"] == ME
    assert body["volume_type_name"] == "Валы"

    revisions = Client().get(f"{BASE}/daily-reports/{body['id']}/revisions",
                             **auth()).json()
    assert [r["revision_no"] for r in revisions] == [1]
    assert revisions[0]["quantity"] == 180.0


@pytest.mark.django_db
def test_work_date_is_independent_of_the_filing_date(task):
    """Отчёт за прошлую пятницу, заполненный сегодня, ложится на пятницу."""
    body = post_json(Client(), f"{BASE}/tasks/{task.id}/daily-reports",
                     {"work_date": "2026-06-05", "quantity": "10"},
                     **auth()).json()
    assert body["work_date"] == "2026-06-05"
    # created_at — сегодняшний, и это ДРУГАЯ дата.
    assert not body["created_at"].startswith("2026-06-05")


@pytest.mark.django_db
def test_volume_type_is_inferred_when_the_task_has_exactly_one(task, valy):
    """Форма не спрашивает очевидное: вид работ у задачи один."""
    body = post_json(Client(), f"{BASE}/tasks/{task.id}/daily-reports",
                     {"work_date": "2026-06-05", "quantity": "10"},
                     **auth()).json()
    assert body["volume_type_id"] == valy.id


@pytest.mark.django_db
def test_volume_type_is_required_when_the_task_has_several(task, valy):
    """Угадать нельзя — сервис отказывает, а не выбирает наугад."""
    beams = WorkVolumeType.objects.create(slug="konstr", name="Конструкции")
    TaskVolume.objects.create(task=task, volume_type=beams, planned_quantity=40)
    resp = post_json(Client(), f"{BASE}/tasks/{task.id}/daily-reports",
                     {"work_date": "2026-06-05", "quantity": "10"}, **auth())
    assert resp.status_code == 422

    ok = post_json(Client(), f"{BASE}/tasks/{task.id}/daily-reports",
                   {"work_date": "2026-06-05", "quantity": "10",
                    "volume_type_id": beams.id}, **auth())
    assert ok.status_code == 201


@pytest.mark.django_db
def test_task_without_planned_volumes_needs_an_explicit_type(valy):
    bare = Task.objects.create(key="TASK-9", summary="Без объёмов",
                               assignee_id=ME)
    resp = post_json(Client(), f"{BASE}/tasks/{bare.id}/daily-reports",
                     {"work_date": "2026-06-05", "quantity": "10"}, **auth())
    assert resp.status_code == 422
    ok = post_json(Client(), f"{BASE}/tasks/{bare.id}/daily-reports",
                   {"work_date": "2026-06-05", "quantity": "10",
                    "volume_type_id": valy.id}, **auth())
    assert ok.status_code == 201


@pytest.mark.django_db
def test_several_shifts_in_one_day_are_allowed_and_add_up(task, valy):
    """UNIQUE(task, work_date) нет намеренно: смен за день бывает несколько."""
    hdr = auth()
    for quantity in ("100", "80"):
        assert post_json(Client(), f"{BASE}/tasks/{task.id}/daily-reports",
                         {"work_date": "2026-06-05", "quantity": quantity},
                         **hdr).status_code == 201

    volumes = Client().get(f"{BASE}/tasks/{task.id}/volumes", **hdr).json()
    assert volumes[0]["completed_quantity"] == 180.0


@pytest.mark.django_db
def test_negative_quantity_is_rejected(task):
    resp = post_json(Client(), f"{BASE}/tasks/{task.id}/daily-reports",
                     {"work_date": "2026-06-05", "quantity": "-1"}, **auth())
    assert resp.status_code == 422


# ── правки и ревизии ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_editing_bumps_the_revision_and_snapshots_the_new_state(task):
    report_id = post_json(Client(), f"{BASE}/tasks/{task.id}/daily-reports",
                          {"work_date": "2026-06-05", "quantity": "180"},
                          **auth()).json()["id"]

    resp = patch_json(Client(), f"{BASE}/daily-reports/{report_id}",
                      {"quantity": "200"}, **auth())
    assert resp.status_code == 200
    assert resp.json()["current_revision"] == 2

    revisions = Client().get(f"{BASE}/daily-reports/{report_id}/revisions",
                             **auth()).json()
    assert [(r["revision_no"], r["quantity"]) for r in revisions] \
        == [(1, 180.0), (2, 200.0)]
    assert revisions[1]["edited_by_id"] == ME


@pytest.mark.django_db
def test_a_no_op_edit_does_not_create_a_revision(task):
    """Лента версий отвечает «что исправили», а не «сколько раз открывали
    форму»."""
    report_id = post_json(Client(), f"{BASE}/tasks/{task.id}/daily-reports",
                          {"work_date": "2026-06-05", "quantity": "180"},
                          **auth()).json()["id"]
    patch_json(Client(), f"{BASE}/daily-reports/{report_id}",
               {"quantity": "180"}, **auth())
    assert DailyReportRevision.objects.filter(report_id=report_id).count() == 1


@pytest.mark.django_db
def test_changing_the_volume_type_is_refused(task, valy):
    """Это другой отчёт, а не другая версия этого: подмена вида задним
    числом перенесла бы объём между видами, не оставив следа."""
    beams = WorkVolumeType.objects.create(slug="konstr", name="Конструкции")
    report_id = post_json(Client(), f"{BASE}/tasks/{task.id}/daily-reports",
                          {"work_date": "2026-06-05", "quantity": "180"},
                          **auth()).json()["id"]
    resp = patch_json(Client(), f"{BASE}/daily-reports/{report_id}",
                      {"volume_type_id": beams.id}, **auth())
    assert resp.status_code == 422


@pytest.mark.django_db
def test_soft_delete_hides_the_report_without_a_revision(task):
    report_id = post_json(Client(), f"{BASE}/tasks/{task.id}/daily-reports",
                          {"work_date": "2026-06-05", "quantity": "180"},
                          **auth()).json()["id"]
    assert Client().delete(f"{BASE}/daily-reports/{report_id}",
                           **auth()).status_code == 204

    assert Client().get(f"{BASE}/tasks/{task.id}/daily-reports",
                        **auth()).json() == []
    assert DailyReport.objects.get(pk=report_id).is_deleted is True
    # Удаление не меняет содержания — новой ревизии быть не должно.
    assert DailyReportRevision.objects.filter(report_id=report_id).count() == 1


@pytest.mark.django_db
def test_deleted_report_no_longer_counts_as_fact(task):
    report_id = post_json(Client(), f"{BASE}/tasks/{task.id}/daily-reports",
                          {"work_date": "2026-06-05", "quantity": "180"},
                          **auth()).json()["id"]
    Client().delete(f"{BASE}/daily-reports/{report_id}", **auth())
    volumes = Client().get(f"{BASE}/tasks/{task.id}/volumes", **auth()).json()
    assert volumes[0]["completed_quantity"] == 0.0


# ── права ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_a_stranger_cannot_edit_someone_elses_report(task):
    """Завести свой отчёт может участник; править чужой — только автор,
    супервайзер задачи или админ."""
    report_id = post_json(Client(), f"{BASE}/tasks/{task.id}/daily-reports",
                          {"work_date": "2026-06-05", "quantity": "180"},
                          **auth()).json()["id"]
    resp = patch_json(Client(), f"{BASE}/daily-reports/{report_id}",
                      {"quantity": "1"}, **auth(token(user_id=OTHER,
                                                      sub=str(OTHER))))
    assert resp.status_code in (403, 404)


@pytest.mark.django_db
def test_the_task_supervisor_can_edit_a_report_they_did_not_write(valy):
    task = Task.objects.create(key="TASK-1", summary="A", assignee_id=OTHER,
                               supervisor_id=ME)
    TaskVolume.objects.create(task=task, volume_type=valy, planned_quantity=250)
    report = DailyReport.objects.create(task=task, volume_type=valy,
                                        author_id=OTHER,
                                        work_date=D(2026, 6, 5), quantity=10)
    resp = patch_json(Client(), f"{BASE}/daily-reports/{report.id}",
                      {"quantity": "20"}, **auth())
    assert resp.status_code == 200


@pytest.mark.django_db
def test_admin_can_edit_any_report(valy):
    task = Task.objects.create(key="TASK-1", summary="A", assignee_id=OTHER)
    TaskVolume.objects.create(task=task, volume_type=valy, planned_quantity=250)
    report = DailyReport.objects.create(task=task, volume_type=valy,
                                        author_id=OTHER,
                                        work_date=D(2026, 6, 5), quantity=10)
    resp = patch_json(Client(), f"{BASE}/daily-reports/{report.id}",
                      {"quantity": "20"}, **auth(admin_token()))
    assert resp.status_code == 200


# ── лента пакета работ ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_roadmap_feed_gathers_reports_of_all_its_tasks(valy):
    project = Project.objects.create(name="Парк", owner_id=9)
    site = Site.objects.create(name="Сазаган")
    ProjectSite.objects.create(project=project, site=site)
    block = SiteBlock.objects.create(site=site, name="Блок 1")
    roadmap = Roadmap.objects.create(project=project, site_block=block,
                                     name="Развозка", owner_id=9)
    for index, day in enumerate(("2026-06-01", "2026-06-09"), start=1):
        task = Task.objects.create(key=f"TASK-{index}", summary=f"T{index}",
                                   roadmap=roadmap)
        DailyReport.objects.create(task=task, volume_type=valy,
                                   work_date=dt.date.fromisoformat(day),
                                   quantity=10)

    hdr = auth(admin_token())
    everything = Client().get(f"{BASE}/roadmaps/{roadmap.id}/daily-reports",
                              **hdr).json()
    # По дате выполнения, свежие сверху.
    assert [r["work_date"] for r in everything] == ["2026-06-09", "2026-06-01"]

    narrowed = Client().get(
        f"{BASE}/roadmaps/{roadmap.id}/daily-reports"
        f"?date_from=2026-06-05&date_to=2026-06-30", **hdr).json()
    assert [r["work_date"] for r in narrowed] == ["2026-06-09"]


@pytest.mark.django_db
def test_fact_is_countable_as_of_any_date(task, valy):
    """Ради этого отчёты и заведены: «сколько было сделано на 5 июня» —
    вопрос, на который число без даты ответить не могло."""
    from apps.tasks.services import daily_report_service

    for day, quantity in (("2026-06-01", 50), ("2026-06-05", 70),
                          ("2026-06-10", 60)):
        DailyReport.objects.create(task=task, volume_type=valy,
                                   work_date=dt.date.fromisoformat(day),
                                   quantity=quantity)

    upto_5 = daily_report_service.completed_by_volume_type(
        task_ids=[task.id], upto=D(2026, 6, 5))
    upto_all = daily_report_service.completed_by_volume_type(
        task_ids=[task.id])
    assert float(upto_5[(task.id, valy.id)]) == 120.0
    assert float(upto_all[(task.id, valy.id)]) == 180.0


@pytest.mark.django_db
def test_daily_series_is_ordered_by_work_date(task, valy):
    from apps.tasks.services import daily_report_service

    for day, quantity in (("2026-06-10", 60), ("2026-06-01", 50)):
        DailyReport.objects.create(task=task, volume_type=valy,
                                   work_date=dt.date.fromisoformat(day),
                                   quantity=quantity)
    series = daily_report_service.daily_series(task_id=task.id)
    assert [(row["date"].isoformat(), float(row["quantity"]))
            for row in series] == [("2026-06-01", 50.0), ("2026-06-10", 60.0)]


# ── сводка ежедневки ────────────────────────────────────────────────────
#
# Страница «Ежедневка» строится ровно из этого ответа. Правило отбора здесь
# то же, что у записи: показать строку, сохранение которой даст 403, хуже,
# чем не показать её вовсе.

@pytest.mark.django_db
def test_board_lists_my_reportable_tasks_with_plan_and_fact(task, valy):
    DailyReport.objects.create(task=task, volume_type=valy,
                               work_date=D(2026, 6, 4), quantity=30)
    DailyReport.objects.create(task=task, volume_type=valy,
                               work_date=D(2026, 6, 5), quantity=20)

    body = Client().get(f"{BASE}/daily-reports/board?date=2026-06-05",
                        **auth()).json()

    assert [row["task_id"] for row in body] == [task.id]
    volume = body[0]["volumes"][0]
    assert volume["planned_quantity"] == 250.0
    # Факт нарастающим итогом НА дату: 30 + 20, а не только сегодняшние 20.
    assert volume["completed_quantity"] == 50.0
    # А в reports — только отчёты выбранного дня.
    assert [r["quantity"] for r in body[0]["reports"]] == [20.0]


@pytest.mark.django_db
def test_board_defaults_to_today(task, valy):
    DailyReport.objects.create(task=task, volume_type=valy,
                               work_date=dt.date.today(), quantity=15)
    body = Client().get(f"{BASE}/daily-reports/board", **auth()).json()
    assert [r["quantity"] for r in body[0]["reports"]] == [15.0]


@pytest.mark.django_db
def test_board_skips_tasks_without_a_planned_volume(task):
    """Вид работ отчёта берётся из объёмов; без них отчёт невозможен, и
    строка в сводке вела бы в 422."""
    Task.objects.create(key="TASK-2", summary="Согласование", assignee_id=ME)
    body = Client().get(f"{BASE}/daily-reports/board", **auth()).json()
    assert [row["key"] for row in body] == ["TASK-1"]


@pytest.mark.django_db
def test_board_skips_finished_work(task):
    task.status = "done"
    task.save(update_fields=["status"])
    assert Client().get(f"{BASE}/daily-reports/board", **auth()).json() == []


@pytest.mark.django_db
def test_board_shows_only_what_i_may_write_to(valy):
    """Наблюдатель задачу видит, но отчитаться не вправе — в сводке её нет.

    Тот же водораздел, что у ``soft_edit_q`` против ``_participant_q``:
    иначе страница предложила бы заполнить строку, которую сервер отвергнет.
    """
    from apps.tasks.models import TaskWatcher

    mine = Task.objects.create(key="TASK-1", summary="Моя", assignee_id=ME)
    TaskVolume.objects.create(task=mine, volume_type=valy, planned_quantity=10)
    watched = Task.objects.create(key="TASK-2", summary="Чужая",
                                  assignee_id=OTHER, reporter_id=OTHER)
    TaskVolume.objects.create(task=watched, volume_type=valy,
                              planned_quantity=10)
    TaskWatcher.objects.create(task=watched, user_id=ME)

    body = Client().get(f"{BASE}/daily-reports/board", **auth()).json()
    assert [row["key"] for row in body] == ["TASK-1"]


@pytest.mark.django_db
def test_board_gives_an_admin_everything(valy):
    """Админ вправе отчитаться где угодно, значит и видит всё — иначе у
    него страница была бы пустой при полных правах."""
    other = Task.objects.create(key="TASK-9", summary="Чужая",
                                assignee_id=OTHER, reporter_id=OTHER)
    TaskVolume.objects.create(task=other, volume_type=valy,
                              planned_quantity=10)
    body = Client().get(f"{BASE}/daily-reports/board",
                        **auth(admin_token())).json()
    assert [row["key"] for row in body] == ["TASK-9"]


@pytest.mark.django_db
def test_board_requires_authentication_and_validates_the_date():
    assert Client().get(f"{BASE}/daily-reports/board").status_code == 401
    resp = Client().get(f"{BASE}/daily-reports/board?date=вчера", **auth())
    assert resp.status_code == 422

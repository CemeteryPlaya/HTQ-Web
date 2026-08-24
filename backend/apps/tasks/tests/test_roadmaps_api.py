"""Роудмапы — пакеты работ на блоке. Новый домен, FastAPI-оригинала нет.

Проверяется то, что делает роудмап уровнем, а не просто ещё одной меткой:

* он живёт на паре (проект, блок), и площадка блока обязана быть проектной;
* своей колонки площадки у него НЕТ — она выводится через блок, и фильтр
  ``?site_id=`` обязан работать этим джойном;
* выбранный на задаче, он ЗАДАЁТ ей проект, площадку и блок, а не
  проверяется против них;
* метрика сравнивает введённый руками план с фактом, свёрнутым из задач,
  и молчит (``None``), когда сравнивать не с чем.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.test import Client

from apps.tasks.models import (DailyReport, Project, ProjectSite, Roadmap,
                               RoadmapStatus, Site, SiteBlock, Status, Task,
                               TaskVolume, WorkVolumeType)

from .helpers import (BASE, admin_token, auth, patch_json, post_json, put_json,
                      token)


@pytest.fixture
def project(db) -> Project:
    return Project.objects.create(name="Солнечный парк", owner_id=9)


@pytest.fixture
def site(db, project) -> Site:
    site = Site.objects.create(name="Сазаган", code="SZG")
    ProjectSite.objects.create(project=project, site=site, is_primary=True)
    return site


@pytest.fixture
def block(db, site) -> SiteBlock:
    return SiteBlock.objects.create(site=site, name="Блок 1", order=1)


@pytest.fixture
def roadmap(db, project, block) -> Roadmap:
    return Roadmap.objects.create(
        project=project, site_block=block, owner_id=9,
        name="Развозка валов трекерных конструкций",
        planned_working_days=20,
    )


# ── права и маршруты ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_roadmap_routes_require_authentication():
    assert Client().get(f"{BASE}/roadmaps/").status_code == 401


@pytest.mark.django_db
def test_creating_a_roadmap_is_admin_only(project, block):
    resp = post_json(Client(), f"{BASE}/roadmaps/",
                     {"project_id": project.id, "site_block_id": block.id,
                      "name": "Монтаж"}, **auth(token()))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_roadmap_detail_accepts_both_slash_spellings(roadmap):
    hdr = auth(admin_token())
    assert Client().get(f"{BASE}/roadmaps/{roadmap.id}", **hdr).status_code == 200
    assert Client().get(f"{BASE}/roadmaps/{roadmap.id}/", **hdr).status_code == 200


@pytest.mark.django_db
def test_non_owner_cannot_edit_someone_elses_roadmap(project, block):
    """Та же калитка, что у проекта: править план — действие владельца."""
    other = Roadmap.objects.create(project=project, site_block=block,
                                   owner_id=555, name="Чужой пакет",
                                   department_id=None)
    resp = patch_json(Client(), f"{BASE}/roadmaps/{other.id}",
                      {"name": "Мой теперь"}, **auth(token()))
    assert resp.status_code in (403, 404)


# ── проект + блок ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_roadmap_rejects_a_block_outside_its_project(project, site):
    """``site`` в аргументах обязателен: у проекта БЕЗ объектов действует
    послабление «разрешён любой» (следующий тест), и без него проверка
    просто не включилась бы."""
    stranger = Site.objects.create(name="Алга")
    other_project = Project.objects.create(name="Другой")
    ProjectSite.objects.create(project=other_project, site=stranger)
    foreign = SiteBlock.objects.create(site=stranger, name="Блок 1")
    resp = post_json(Client(), f"{BASE}/roadmaps/",
                     {"project_id": project.id, "site_block_id": foreign.id,
                      "name": "Монтаж"}, **auth(admin_token()))
    assert resp.status_code == 400


@pytest.mark.django_db
def test_roadmap_allows_any_block_when_the_project_has_none(block):
    """Послабление то же, что в site_service: у существующих проектов
    объектов нет, и строгая проверка сломала бы их разом."""
    bare = Project.objects.create(name="Без объектов")
    resp = post_json(Client(), f"{BASE}/roadmaps/",
                     {"project_id": bare.id, "site_block_id": block.id,
                      "name": "Монтаж"}, **auth(admin_token()))
    assert resp.status_code == 201


@pytest.mark.django_db
def test_roadmap_response_carries_the_site_derived_from_the_block(roadmap, site):
    """Колонки площадки у роудмапа нет, но в ответе она есть — иначе фронту
    пришлось бы ходить за блоком ради имени и цвета чипа."""
    body = Client().get(f"{BASE}/roadmaps/{roadmap.id}",
                        **auth(admin_token())).json()
    assert body["site_block_name"] == "Блок 1"
    assert (body["site_id"], body["site_name"]) == (site.id, "Сазаган")


@pytest.mark.django_db
def test_roadmap_name_is_unique_within_project_and_block(project, block, roadmap):
    resp = post_json(Client(), f"{BASE}/roadmaps/",
                     {"project_id": project.id, "site_block_id": block.id,
                      "name": roadmap.name}, **auth(admin_token()))
    assert resp.status_code == 409


@pytest.mark.django_db
def test_same_roadmap_name_is_fine_on_another_block(project, site, roadmap):
    """«Развозка валов» законно идёт и на блоке 1, и на блоке 2."""
    second = SiteBlock.objects.create(site=site, name="Блок 2", order=2)
    resp = post_json(Client(), f"{BASE}/roadmaps/",
                     {"project_id": project.id, "site_block_id": second.id,
                      "name": roadmap.name}, **auth(admin_token()))
    assert resp.status_code == 201


@pytest.mark.django_db
def test_roadmap_rejects_inverted_planned_dates(project, block):
    resp = post_json(Client(), f"{BASE}/roadmaps/",
                     {"project_id": project.id, "site_block_id": block.id,
                      "name": "Монтаж", "planned_start_date": "2026-06-01",
                      "planned_end_date": "2026-05-01"}, **auth(admin_token()))
    assert resp.status_code == 422


@pytest.mark.django_db
def test_roadmaps_can_be_filtered_by_site_through_the_block(project, site,
                                                            roadmap):
    """Фильтр по площадке обязан работать джойном, а не колонкой."""
    alga = Site.objects.create(name="Алга")
    ProjectSite.objects.create(project=project, site=alga)
    alga_block = SiteBlock.objects.create(site=alga, name="Блок 1")
    Roadmap.objects.create(project=project, site_block=alga_block,
                           name="Монтаж на Алге")
    hdr = auth(admin_token())
    by_site = Client().get(f"{BASE}/roadmaps/?site_id={site.id}", **hdr).json()
    assert [r["name"] for r in by_site] == [roadmap.name]


@pytest.mark.django_db
def test_roadmaps_can_be_filtered_by_block(project, site, roadmap):
    second = SiteBlock.objects.create(site=site, name="Блок 2", order=2)
    Roadmap.objects.create(project=project, site_block=second, name="Монтаж")
    resp = Client().get(f"{BASE}/roadmaps/?block_id={second.id}",
                        **auth(admin_token()))
    assert [r["name"] for r in resp.json()] == ["Монтаж"]


@pytest.mark.django_db
def test_deleting_a_roadmap_with_tasks_is_409(roadmap):
    """Пакет несёт сроки и потребности, по которым считается отставание;
    «разгруппировать» его одним кликом значит молча обнулить план."""
    Task.objects.create(key="TASK-1", summary="A", roadmap=roadmap)
    resp = Client().delete(f"{BASE}/roadmaps/{roadmap.id}",
                           **auth(admin_token()))
    assert resp.status_code == 409
    assert Roadmap.objects.filter(pk=roadmap.id).exists()


@pytest.mark.django_db
def test_empty_roadmap_can_be_deleted(roadmap):
    assert Client().delete(f"{BASE}/roadmaps/{roadmap.id}",
                           **auth(admin_token())).status_code == 204


# ── роудмап задаёт проект, площадку и блок задачи ───────────────────────

@pytest.mark.django_db
def test_task_inherits_project_site_and_block_from_its_roadmap(
        roadmap, project, site, block):
    resp = post_json(Client(), f"{BASE}/tasks/",
                     {"summary": "Развезти 250 валов на блок I",
                      "roadmap_id": roadmap.id}, **auth())
    assert resp.status_code == 201
    body = resp.json()
    assert body["roadmap_id"] == roadmap.id
    assert body["roadmap_name"] == roadmap.name
    assert body["project_id"] == project.id
    assert body["site_id"] == site.id
    # Блок тоже: задача пакета не может стоять на чужом блоке.
    assert body["site_block_id"] == block.id


@pytest.mark.django_db
def test_roadmap_overrides_a_conflicting_block_on_create(roadmap, site, block):
    """Выбрал пакет — блок следует из него, а не спорит с ним."""
    other = SiteBlock.objects.create(site=site, name="Блок 2", order=2)
    resp = post_json(Client(), f"{BASE}/tasks/",
                     {"summary": "A", "roadmap_id": roadmap.id,
                      "site_block_id": other.id}, **auth())
    assert resp.json()["site_block_id"] == block.id


@pytest.mark.django_db
def test_roadmap_overrides_a_conflicting_project_on_create(roadmap, project):
    """Выбрал пакет — проект следует из него. Это переезд, а не конфликт."""
    other = Project.objects.create(name="Другой")
    resp = post_json(Client(), f"{BASE}/tasks/",
                     {"summary": "A", "roadmap_id": roadmap.id,
                      "project_id": other.id}, **auth())
    assert resp.json()["project_id"] == project.id


@pytest.mark.django_db
def test_task_rejects_an_unknown_roadmap():
    resp = post_json(Client(), f"{BASE}/tasks/",
                     {"summary": "A", "roadmap_id": 9999}, **auth())
    assert resp.status_code == 400


@pytest.mark.django_db
def test_moving_a_task_into_a_roadmap_moves_its_project_and_site(roadmap,
                                                                 project, site):
    task = Task.objects.create(key="TASK-1", summary="A", reporter_id=7)
    resp = patch_json(Client(), f"{BASE}/tasks/{task.id}",
                      {"roadmap_id": roadmap.id}, **auth(admin_token()))
    assert resp.status_code == 200
    body = resp.json()
    assert (body["roadmap_id"], body["project_id"], body["site_id"]) == \
        (roadmap.id, project.id, site.id)


@pytest.mark.django_db
def test_task_can_be_detached_from_its_roadmap(roadmap, project, site):
    task = Task.objects.create(key="TASK-1", summary="A", roadmap=roadmap,
                               project=project, site=site, reporter_id=7)
    resp = patch_json(Client(), f"{BASE}/tasks/{task.id}", {"roadmap_id": None},
                      **auth(admin_token()))
    body = resp.json()
    assert body["roadmap_id"] is None
    # Проект и объект остаются: открепление от пакета не выкидывает задачу
    # из проекта.
    assert body["project_id"] == project.id


@pytest.mark.django_db
def test_tasks_can_be_filtered_by_roadmap_and_by_its_absence(roadmap):
    Task.objects.create(key="TASK-1", summary="В пакете", roadmap=roadmap)
    Task.objects.create(key="TASK-2", summary="Вне пакета")
    hdr = auth(admin_token())
    inside = Client().get(f"{BASE}/tasks/?roadmap_id={roadmap.id}", **hdr).json()
    assert [t["summary"] for t in inside] == ["В пакете"]
    outside = Client().get(f"{BASE}/tasks/?no_roadmap=true", **hdr).json()
    assert [t["summary"] for t in outside] == ["Вне пакета"]


@pytest.mark.django_db
def test_roadmap_tasks_endpoint_lists_only_its_own(roadmap):
    Task.objects.create(key="TASK-1", summary="Своя", roadmap=roadmap)
    Task.objects.create(key="TASK-2", summary="Чужая")
    resp = Client().get(f"{BASE}/roadmaps/{roadmap.id}/tasks",
                        **auth(admin_token()))
    assert [t["summary"] for t in resp.json()] == ["Своя"]


# ── партнёр на роудмапе ───────────────────────────────────────────────

@pytest.mark.django_db
def test_contractor_can_be_engaged_on_a_roadmap_alone(roadmap):
    """Третья стрелка в «Партнёр» на схеме: «развозку отдали партнёру,
    монтаж делаем сами»."""
    from apps.tasks.models import Contractor
    org = Contractor.objects.create(name="СтройПодряд")
    resp = post_json(Client(), f"{BASE}/contractor-engagements/",
                     {"contractor_id": org.id, "roadmap_id": roadmap.id,
                      "contract_no": "Д-1"}, **auth(admin_token()))
    assert resp.status_code == 201
    body = resp.json()
    assert body["roadmap_id"] == roadmap.id
    assert body["roadmap_name"] == roadmap.name


@pytest.mark.django_db
def test_engagement_still_requires_at_least_one_target():
    from apps.tasks.models import Contractor
    org = Contractor.objects.create(name="СтройПодряд")
    resp = post_json(Client(), f"{BASE}/contractor-engagements/",
                     {"contractor_id": org.id}, **auth(admin_token()))
    assert resp.status_code == 422


# ── план против факта ───────────────────────────────────────────────────

@pytest.mark.django_db
def test_metrics_report_no_plan_as_none_not_zero(project, block):
    """«Плана нет» и «запланировали ноль» рисуются по-разному."""
    bare = Roadmap.objects.create(project=project, site_block=block,
                                  name="Без плана")
    body = Client().get(f"{BASE}/roadmaps/{bare.id}/metrics",
                        **auth(admin_token())).json()
    assert body["schedule"]["planned_working_days"] is None
    assert body["schedule"]["delta_working_days"] is None
    assert body["human"]["planned"] is None
    assert body["progress"] is None


@pytest.mark.django_db
def test_metrics_fold_actual_dates_out_of_the_tasks(roadmap):
    """По умолчанию длительность — КАЛЕНДАРНАЯ: стройка идёт 7/7."""
    Task.objects.create(key="TASK-1", summary="A", roadmap=roadmap,
                        start_date=dt.date(2026, 6, 1),
                        due_date=dt.date(2026, 6, 10))
    Task.objects.create(key="TASK-2", summary="B", roadmap=roadmap,
                        start_date=dt.date(2026, 6, 5),
                        due_date=dt.date(2026, 6, 20))
    body = Client().get(f"{BASE}/roadmaps/{roadmap.id}/metrics",
                        **auth(admin_token())).json()
    sched = body["schedule"]
    assert sched["actual_start_date"] == "2026-06-01"
    assert sched["actual_end_date"] == "2026-06-20"
    assert sched["actual_working_days"] == 20      # 1–20 июня включительно
    assert sched["delta_working_days"] == 0        # план тоже 20


@pytest.mark.django_db
def test_metrics_count_working_days_when_the_project_opts_in(project, roadmap):
    """Офисный режим включается флагом проекта, а не зашит в код."""
    project.use_production_calendar = True
    project.save(update_fields=["use_production_calendar"])
    Task.objects.create(key="TASK-1", summary="A", roadmap=roadmap,
                        start_date=dt.date(2026, 6, 1),
                        due_date=dt.date(2026, 6, 20))
    body = Client().get(f"{BASE}/roadmaps/{roadmap.id}/metrics",
                        **auth(admin_token())).json()
    # 1–20 июня 2026 без выходных = 15 рабочих дней.
    assert body["schedule"]["actual_working_days"] == 15


@pytest.mark.django_db
def test_four_planned_weeks_against_four_real_weeks_show_no_variance(project,
                                                                     block):
    """Регресс, ради которого флаг и заведён.

    Раньше рабочие дни были зашиты безальтернативно: план «4 недели»,
    введённый как 28, против фактического размаха ровно в 4 календарные
    недели давал 20 дней факта и «опережение на 8 дней» там, где идут точно
    по плану.
    """
    roadmap = Roadmap.objects.create(
        project=project, site_block=block, owner_id=9, name="Развозка",
        planned_working_days=28)
    Task.objects.create(key="TASK-1", summary="A", roadmap=roadmap,
                        start_date=dt.date(2026, 6, 1),
                        due_date=dt.date(2026, 6, 28))

    sched = Client().get(f"{BASE}/roadmaps/{roadmap.id}/metrics",
                         **auth(admin_token())).json()["schedule"]
    assert sched["actual_working_days"] == 28
    assert sched["delta_working_days"] == 0


@pytest.mark.django_db
def test_metrics_progress_prefers_volumes_over_statuses(roadmap):
    """Ровно доска: «развезти 250 валов», развезли 180 — это 72%, хотя обе
    задачи ещё в работе и по статусам вышло бы 0%."""
    valy = WorkVolumeType.objects.create(slug="valy", name="Валы")
    for key, done in (("TASK-1", 100), ("TASK-2", 80)):
        task = Task.objects.create(key=key, summary=key, roadmap=roadmap,
                                   status=Status.IN_PROGRESS)
        TaskVolume.objects.create(task=task, volume_type=valy,
                                  planned_quantity=125)
        DailyReport.objects.create(task=task, volume_type=valy,
                                   work_date=dt.date(2026, 6, 1), quantity=done)
    body = Client().get(f"{BASE}/roadmaps/{roadmap.id}/metrics",
                        **auth(admin_token())).json()
    assert body["progress"] == 72.0


@pytest.mark.django_db
def test_metrics_fall_back_to_statuses_without_volumes(roadmap):
    """Согласование или приёмка объёма не имеют — для них статус и есть
    единственная доступная мера."""
    Task.objects.create(key="TASK-1", summary="A", roadmap=roadmap,
                        status=Status.DONE)
    Task.objects.create(key="TASK-2", summary="B", roadmap=roadmap,
                        status=Status.TODO)
    body = Client().get(f"{BASE}/roadmaps/{roadmap.id}/metrics",
                        **auth(admin_token())).json()
    assert body["progress"] == 50.0
    assert (body["task_count"], body["done_count"]) == (2, 1)


@pytest.mark.django_db
def test_metrics_ignore_deleted_tasks(roadmap):
    Task.objects.create(key="TASK-1", summary="A", roadmap=roadmap,
                        status=Status.DONE)
    Task.objects.create(key="TASK-2", summary="B", roadmap=roadmap,
                        status=Status.DONE, is_deleted=True)
    body = Client().get(f"{BASE}/roadmaps/{roadmap.id}/metrics",
                        **auth(admin_token())).json()
    assert body["task_count"] == 1


@pytest.mark.django_db
def test_metrics_handle_a_reversed_actual_window(roadmap):
    """Одна задача только с началом, другая только со сроком — границы
    могут перевернуться, и это не повод падать."""
    Task.objects.create(key="TASK-1", summary="A", roadmap=roadmap,
                        start_date=dt.date(2026, 6, 20))
    Task.objects.create(key="TASK-2", summary="B", roadmap=roadmap,
                        due_date=dt.date(2026, 6, 1))
    body = Client().get(f"{BASE}/roadmaps/{roadmap.id}/metrics",
                        **auth(admin_token())).json()
    assert body["schedule"]["actual_working_days"] is None
    assert body["schedule"]["delta_working_days"] is None


@pytest.mark.django_db
def test_roadmap_list_carries_a_cheap_status_progress(roadmap):
    Task.objects.create(key="TASK-1", summary="A", roadmap=roadmap,
                        status=Status.DONE)
    Task.objects.create(key="TASK-2", summary="B", roadmap=roadmap)
    row = Client().get(f"{BASE}/roadmaps/?block_id={roadmap.site_block_id}",
                       **auth(admin_token())).json()[0]
    assert (row["task_count"], row["done_count"], row["progress"]) == (2, 1, 50.0)
    assert row["status"] == RoadmapStatus.ACTIVE


# ── полная цепочка с доски ──────────────────────────────────────────────

@pytest.mark.django_db
def test_the_whiteboard_example_end_to_end(project, site):
    """Проект → площадка → блок с объёмом → роудмап на блоке → задача.

    Сценарий приёмки целиком: 250 валов на блок 1, задача развозит 180 из
    них, и обе метрики — блока и роудмапа — считают штуки, а не статусы.
    Площадку и блок задача не получает руками: их задаёт роудмап.
    """
    hdr = auth(admin_token())
    valy = WorkVolumeType.objects.create(slug="valy", name="Валы")

    block_id = post_json(Client(), f"{BASE}/sites/{site.id}/blocks",
                         {"name": "Блок 1", "order": 1}, **hdr).json()["id"]
    put_json(Client(), f"{BASE}/blocks/{block_id}/volumes", {"volumes": [
        {"volume_type_id": valy.id, "planned_quantity": "250"}]}, **hdr)

    roadmap_id = post_json(Client(), f"{BASE}/roadmaps/", {
        "project_id": project.id, "site_block_id": block_id,
        "name": "Развозка валов трекерных конструкций",
        "planned_working_days": 20,
    }, **hdr).json()["id"]

    task = post_json(Client(), f"{BASE}/tasks/", {
        "summary": "Развезти 250 валов на блок I",
        "roadmap_id": roadmap_id, "estimated_working_days": 3,
    }, **hdr).json()
    assert task["project_id"] == project.id
    assert task["site_id"] == site.id
    assert task["site_block_id"] == block_id
    assert task["site_block_name"] == "Блок 1"

    put_json(Client(), f"{BASE}/tasks/{task['id']}/volumes", {"volumes": [
        {"volume_type_id": valy.id, "planned_quantity": "250"}]}, **hdr)
    # Факт приходит ежедневным отчётом с датой ВЫПОЛНЕНИЯ работ.
    post_json(Client(), f"{BASE}/tasks/{task['id']}/daily-reports", {
        "work_date": "2026-06-05", "quantity": "180"}, **hdr)

    block = Client().get(f"{BASE}/blocks/{block_id}/progress", **hdr).json()
    assert block["percent"] == 72.0
    roadmap = Client().get(f"{BASE}/roadmaps/{roadmap_id}/metrics", **hdr).json()
    assert roadmap["progress"] == 72.0
    assert roadmap["schedule"]["planned_working_days"] == 20

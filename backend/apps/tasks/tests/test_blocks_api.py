"""Блоки объекта и объёмы работ — новый домен, FastAPI-оригинала нет.

Проверяется то, ради чего блок и заведён:

* блок принадлежит площадке и уникален в её пределах («блок 1» есть и на
  Сазагане, и на Алге);
* задача ссылается на блок, и ссылка на чужой блок — отказ, а не молчаливая
  привязка;
* выполнение считается ПО ШТУКАМ (180 из 250 валов), а не по статусам задач,
  и это единственное место в аппе, где так.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.test import Client

from apps.tasks.models import (BlockStatus, DailyReport, Site, SiteBlock,
                               Status, Task, TaskVolume, WorkVolumeType)

from .helpers import (BASE, admin_token, auth, patch_json, post_json, put_json,
                      token)

D = dt.date


@pytest.fixture
def site(db) -> Site:
    return Site.objects.create(name="Сазаган", code="SZG")


@pytest.fixture
def valy(db) -> WorkVolumeType:
    return WorkVolumeType.objects.create(slug="valy", name="Валы", unit="piece")


# ── права и маршруты ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_block_routes_require_authentication(site):
    assert Client().get(f"{BASE}/sites/{site.id}/blocks").status_code == 401


@pytest.mark.django_db
def test_creating_a_block_is_admin_only(site):
    resp = post_json(Client(), f"{BASE}/sites/{site.id}/blocks",
                     {"name": "Блок 1"}, **auth(token()))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_blocks_of_an_unknown_site_are_404_not_an_empty_list():
    assert Client().get(f"{BASE}/sites/999/blocks", **auth()).status_code == 404


@pytest.mark.django_db
def test_block_detail_accepts_both_slash_spellings(site):
    block = SiteBlock.objects.create(site=site, name="Блок 1")
    assert Client().get(f"{BASE}/blocks/{block.id}", **auth()).status_code == 200
    assert Client().get(f"{BASE}/blocks/{block.id}/", **auth()).status_code == 200


# ── справочная часть ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_blocks_are_listed_in_declared_order(site):
    SiteBlock.objects.create(site=site, name="Блок 3", order=3)
    SiteBlock.objects.create(site=site, name="Блок 1", order=1)
    SiteBlock.objects.create(site=site, name="Блок 2", order=2)
    resp = Client().get(f"{BASE}/sites/{site.id}/blocks", **auth())
    assert [b["name"] for b in resp.json()] == ["Блок 1", "Блок 2", "Блок 3"]


@pytest.mark.django_db
def test_block_name_is_unique_within_a_site_only(site):
    """«Блок 1» есть на каждой площадке — это разные блоки."""
    other = Site.objects.create(name="Алга")
    hdr = auth(admin_token())
    assert post_json(Client(), f"{BASE}/sites/{site.id}/blocks",
                     {"name": "Блок 1"}, **hdr).status_code == 201
    assert post_json(Client(), f"{BASE}/sites/{other.id}/blocks",
                     {"name": "Блок 1"}, **hdr).status_code == 201
    dup = post_json(Client(), f"{BASE}/sites/{site.id}/blocks",
                    {"name": "Блок 1"}, **hdr)
    assert dup.status_code == 409


@pytest.mark.django_db
def test_block_rejects_inverted_dates(site):
    resp = post_json(Client(), f"{BASE}/sites/{site.id}/blocks",
                     {"name": "Блок 1", "start_date": "2026-05-10",
                      "end_date": "2026-05-01"}, **auth(admin_token()))
    assert resp.status_code == 422


@pytest.mark.django_db
def test_deleting_a_block_with_tasks_is_409(site):
    """``Task.site_block`` — SET_NULL: удаление молча обнулило бы задачам
    блок, поэтому сервис отказывает раньше."""
    block = SiteBlock.objects.create(site=site, name="Блок 1")
    Task.objects.create(key="TASK-1", summary="A", site=site, site_block=block)
    resp = Client().delete(f"{BASE}/blocks/{block.id}", **auth(admin_token()))
    assert resp.status_code == 409
    assert SiteBlock.objects.filter(pk=block.id).exists()


@pytest.mark.django_db
def test_free_block_can_be_deleted(site):
    block = SiteBlock.objects.create(site=site, name="Блок 1")
    assert Client().delete(f"{BASE}/blocks/{block.id}",
                           **auth(admin_token())).status_code == 204


# ── объёмы блока ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_block_volumes_are_replaced_wholesale(site, valy):
    block = SiteBlock.objects.create(site=site, name="Блок 1")
    beams = WorkVolumeType.objects.create(slug="konstr", name="Конструкции")
    hdr = auth(admin_token())

    put_json(Client(), f"{BASE}/blocks/{block.id}/volumes", {"volumes": [
        {"volume_type_id": valy.id, "planned_quantity": "250"},
        {"volume_type_id": beams.id, "planned_quantity": "40"},
    ]}, **hdr)
    resp = put_json(Client(), f"{BASE}/blocks/{block.id}/volumes", {"volumes": [
        {"volume_type_id": valy.id, "planned_quantity": "300"},
    ]}, **hdr)

    body = resp.json()
    assert [(v["volume_type_name"], v["planned_quantity"]) for v in body] \
        == [("Валы", 300.0)]


@pytest.mark.django_db
def test_block_volumes_reject_a_repeated_type(site, valy):
    block = SiteBlock.objects.create(site=site, name="Блок 1")
    resp = put_json(Client(), f"{BASE}/blocks/{block.id}/volumes", {"volumes": [
        {"volume_type_id": valy.id, "planned_quantity": "250"},
        {"volume_type_id": valy.id, "planned_quantity": "300"},
    ]}, **auth(admin_token()))
    assert resp.status_code == 422


@pytest.mark.django_db
def test_block_volumes_reject_an_unknown_type(site):
    block = SiteBlock.objects.create(site=site, name="Блок 1")
    resp = put_json(Client(), f"{BASE}/blocks/{block.id}/volumes", {"volumes": [
        {"volume_type_id": 9999, "planned_quantity": "1"},
    ]}, **auth(admin_token()))
    assert resp.status_code == 422


# ── прогресс по штукам ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_block_progress_counts_pieces_not_statuses(site, valy):
    """Ровно пример с доски: план 250 валов на блок, развезли 180.

    Обе задачи при этом в статусе todo — прогресс по статусам показал бы 0%.
    """
    block = SiteBlock.objects.create(site=site, name="Блок 1")
    block.volumes.create(volume_type=valy, planned_quantity=250)
    for summary, done in (("Развезти партию 1", 100), ("Развезти партию 2", 80)):
        task = Task.objects.create(key=f"TASK-{done}", summary=summary,
                                   site=site, site_block=block,
                                   status=Status.TODO)
        TaskVolume.objects.create(task=task, volume_type=valy,
                                  planned_quantity=125)
        DailyReport.objects.create(task=task, volume_type=valy,
                                   work_date=D(2026, 6, 1), quantity=done)

    body = Client().get(f"{BASE}/blocks/{block.id}/progress", **auth()).json()
    assert body["percent"] == 72.0
    assert body["items"][0]["completed_quantity"] == 180.0
    assert body["items"][0]["planned_quantity"] == 250.0
    assert body["items"][0]["unit"] == "piece"


@pytest.mark.django_db
def test_block_progress_is_none_when_no_volumes_are_planned(site):
    """«Объёмы не заданы» и «не сделано ничего» — разные состояния."""
    block = SiteBlock.objects.create(site=site, name="Блок 1")
    body = Client().get(f"{BASE}/blocks/{block.id}/progress", **auth()).json()
    assert body["percent"] is None
    assert body["items"] == []


@pytest.mark.django_db
def test_block_progress_averages_across_incomparable_units(site, valy):
    """250 валов и 40 тонн нельзя сложить — итог это среднее по видам."""
    metal = WorkVolumeType.objects.create(slug="metall", name="Металл",
                                          unit="ton")
    block = SiteBlock.objects.create(site=site, name="Блок 1")
    block.volumes.create(volume_type=valy, planned_quantity=250)
    block.volumes.create(volume_type=metal, planned_quantity=40)
    task = Task.objects.create(key="TASK-1", summary="A", site=site,
                               site_block=block)
    TaskVolume.objects.create(task=task, volume_type=valy,
                              planned_quantity=250)
    TaskVolume.objects.create(task=task, volume_type=metal,
                              planned_quantity=40)
    DailyReport.objects.create(task=task, volume_type=valy,
                               work_date=D(2026, 6, 1), quantity=125)
    DailyReport.objects.create(task=task, volume_type=metal,
                               work_date=D(2026, 6, 1), quantity=40)

    body = Client().get(f"{BASE}/blocks/{block.id}/progress", **auth()).json()
    # 50% по валам и 100% по металлу -> 75%, а не 165/290.
    assert body["percent"] == 75.0


@pytest.mark.django_db
def test_block_progress_ignores_deleted_tasks(site, valy):
    block = SiteBlock.objects.create(site=site, name="Блок 1")
    block.volumes.create(volume_type=valy, planned_quantity=100)
    task = Task.objects.create(key="TASK-1", summary="A", site=site,
                               site_block=block, is_deleted=True)
    TaskVolume.objects.create(task=task, volume_type=valy,
                              planned_quantity=100)
    DailyReport.objects.create(task=task, volume_type=valy,
                               work_date=D(2026, 6, 1), quantity=100)
    body = Client().get(f"{BASE}/blocks/{block.id}/progress", **auth()).json()
    assert body["percent"] == 0.0


# ── связь задачи с блоком ───────────────────────────────────────────────

@pytest.mark.django_db
def test_task_can_be_created_on_a_block(site, valy):
    block = SiteBlock.objects.create(site=site, name="Блок 1")
    resp = post_json(Client(), f"{BASE}/tasks/",
                     {"summary": "Развезти 250 валов на блок I",
                      "site_id": site.id, "site_block_id": block.id}, **auth())
    assert resp.status_code == 201
    body = resp.json()
    assert body["site_block_id"] == block.id
    assert body["site_block_name"] == "Блок 1"


@pytest.mark.django_db
def test_task_inherits_the_site_from_its_block(site):
    """«Блок 1» однозначно называет площадку — переспрашивать незачем."""
    block = SiteBlock.objects.create(site=site, name="Блок 1")
    resp = post_json(Client(), f"{BASE}/tasks/",
                     {"summary": "A", "site_block_id": block.id}, **auth())
    assert resp.json()["site_id"] == site.id


@pytest.mark.django_db
def test_task_rejects_a_block_from_another_site(site):
    other = Site.objects.create(name="Алга")
    foreign = SiteBlock.objects.create(site=other, name="Блок 1")
    resp = post_json(Client(), f"{BASE}/tasks/",
                     {"summary": "A", "site_id": site.id,
                      "site_block_id": foreign.id}, **auth())
    assert resp.status_code == 400


@pytest.mark.django_db
def test_moving_a_task_to_another_site_rejects_a_stale_block(site):
    """Смена площадки при сохранённом чужом блоке — отказ, а не тихое
    обнуление: та же логика, что у ``resolve_task_site`` для объекта."""
    other = Site.objects.create(name="Алга")
    block = SiteBlock.objects.create(site=site, name="Блок 1")
    task = Task.objects.create(key="TASK-1", summary="A", site=site,
                               site_block=block, reporter_id=7)
    resp = patch_json(Client(), f"{BASE}/tasks/{task.id}",
                      {"site_id": other.id}, **auth(admin_token()))
    assert resp.status_code == 400


@pytest.mark.django_db
def test_tasks_can_be_filtered_by_block(site):
    first = SiteBlock.objects.create(site=site, name="Блок 1")
    second = SiteBlock.objects.create(site=site, name="Блок 2")
    Task.objects.create(key="TASK-1", summary="На первом", site=site,
                        site_block=first)
    Task.objects.create(key="TASK-2", summary="На втором", site=site,
                        site_block=second)
    resp = Client().get(f"{BASE}/tasks/?site_block_id={first.id}",
                        **auth(admin_token()))
    assert [t["summary"] for t in resp.json()] == ["На первом"]


# ── объёмы задачи ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_task_volumes_carry_the_plan_and_the_fact_from_reports(site, valy):
    """В объёмах задачи ПЛАН, факт — свёртка ежедневных отчётов.

    Раньше факт лежал колонкой рядом с планом и правился тем же PUT; теперь
    он приходит отчётами с датой выполнения, а ответ показывает обе цифры.
    """
    task = Task.objects.create(key="TASK-1", summary="A", assignee_id=7)
    resp = put_json(Client(), f"{BASE}/tasks/{task.id}/volumes", {"volumes": [
        {"volume_type_id": valy.id, "planned_quantity": "250"},
    ]}, **auth(token()))
    assert resp.status_code == 200
    assert resp.json()[0]["completed_quantity"] == 0.0

    DailyReport.objects.create(task=task, volume_type=valy,
                               work_date=D(2026, 6, 1), quantity=180)
    again = Client().get(f"{BASE}/tasks/{task.id}/volumes", **auth(token()))
    assert again.json()[0]["completed_quantity"] == 180.0


@pytest.mark.django_db
def test_task_volumes_show_up_in_the_task_detail(valy):
    task = Task.objects.create(key="TASK-1", summary="A")
    TaskVolume.objects.create(task=task, volume_type=valy,
                              planned_quantity=250)
    DailyReport.objects.create(task=task, volume_type=valy,
                               work_date=D(2026, 6, 1), quantity=180)
    body = Client().get(f"{BASE}/tasks/{task.id}/", **auth(admin_token())).json()
    assert body["volumes"] == [{
        "id": task.volumes.get().id, "task_id": task.id,
        "volume_type_id": valy.id, "volume_type_name": "Валы", "unit": "piece",
        "planned_quantity": 250.0, "completed_quantity": 180.0,
    }]


@pytest.mark.django_db
def test_task_volume_quantities_cannot_be_negative(valy):
    task = Task.objects.create(key="TASK-1", summary="A", assignee_id=7)
    resp = put_json(Client(), f"{BASE}/tasks/{task.id}/volumes", {"volumes": [
        {"volume_type_id": valy.id, "planned_quantity": "-1"},
    ]}, **auth(token()))
    assert resp.status_code == 422


@pytest.mark.django_db
def test_block_status_defaults_to_planned(site):
    resp = post_json(Client(), f"{BASE}/sites/{site.id}/blocks",
                     {"name": "Блок 1"}, **auth(admin_token()))
    assert resp.json()["status"] == BlockStatus.PLANNED

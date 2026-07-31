"""Объекты (площадки) — ``/api/tasks/v1/sites/*`` и ось «объект» в задачах.

Новый домен, FastAPI-оригинала нет, поэтому здесь не «контракт против
источника», а проверка принятых решений. Главные из них:

* объект задачи обязан входить в объекты её проекта — правило живёт в
  сервисе, потому что охватывает три таблицы, и потому его легко потерять
  при рефакторинге; тесты ниже держат его на месте;
* пустой набор объектов у проекта разрешает любой объект — иначе в день
  выката сломалось бы создание задач во всех существующих проектах;
* объект с задачами или проектами не удаляется (409), а закрывается
  статусом: ``Task.site`` это ``SET_NULL``, и удаление молча обнулило бы
  привязку задним числом.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.tasks.models import Project, ProjectSite, Site, Task

from .helpers import BASE, admin_token, auth, patch_json, post_json

USER = 7


def _site(name: str, **over) -> Site:
    return Site.objects.create(name=name, **over)


def _task(**over) -> Task:
    fields = {"key": f"TASK-{Task.objects.count() + 1}", "summary": "S",
              "reporter_id": USER}
    fields.update(over)
    return Task.objects.create(**fields)


# ── доступ ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_sites_require_authentication():
    assert Client().get(f"{BASE}/sites/").status_code == 401


@pytest.mark.django_db
def test_site_list_is_open_but_writes_are_admin_only():
    _site("Алга")
    client = Client()
    assert client.get(f"{BASE}/sites/", **auth()).status_code == 200
    assert post_json(client, f"{BASE}/sites/", {"name": "Самоделка"},
                     **auth()).status_code == 403
    assert not Site.objects.filter(name="Самоделка").exists()


@pytest.mark.django_db
def test_both_slash_spellings_resolve():
    """APPEND_SLASH=False — 404/редиректа быть не должно ни в одном варианте."""
    site = _site("Сазаган")
    client = Client()
    for path in (f"{BASE}/sites", f"{BASE}/sites/"):
        assert client.get(path, **auth()).status_code == 200
    for path in (f"{BASE}/sites/{site.id}", f"{BASE}/sites/{site.id}/"):
        assert client.get(path, **auth()).status_code == 200


# ── CRUD ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_create_site_defaults():
    resp = post_json(Client(), f"{BASE}/sites/",
                     {"name": "Алга", "region": "Актюбинская область"},
                     **auth(admin_token()))
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Алга"
    assert body["status"] == "active"
    assert body["color"] == "#0ea5e9"


@pytest.mark.django_db
def test_site_name_is_unique():
    _site("Алга")
    resp = post_json(Client(), f"{BASE}/sites/", {"name": "Алга"},
                     **auth(admin_token()))
    assert resp.status_code == 500      # unique violation, как у проектов


@pytest.mark.django_db
def test_filter_by_status_and_search():
    _site("Алга")
    _site("Сазаган", status="closed")
    client = Client()
    active = client.get(f"{BASE}/sites/?status=active", **auth()).json()
    assert [s["name"] for s in active] == ["Алга"]
    found = client.get(f"{BASE}/sites/?search=заг", **auth()).json()
    assert [s["name"] for s in found] == ["Сазаган"]


@pytest.mark.django_db
def test_update_site():
    site = _site("Алга")
    resp = patch_json(Client(), f"{BASE}/sites/{site.id}/",
                      {"status": "suspended"}, **auth(admin_token()))
    assert resp.status_code == 200
    assert resp.json()["status"] == "suspended"


@pytest.mark.django_db
def test_delete_unused_site():
    site = _site("Пустой")
    assert Client().delete(f"{BASE}/sites/{site.id}/",
                           **auth(admin_token())).status_code == 204
    assert not Site.objects.filter(pk=site.id).exists()


@pytest.mark.django_db
def test_site_with_tasks_cannot_be_deleted():
    """Иначе SET_NULL молча обнулил бы объект у задач."""
    site = _site("Алга")
    _task(site=site)
    resp = Client().delete(f"{BASE}/sites/{site.id}/", **auth(admin_token()))
    assert resp.status_code == 409
    assert "используется" in resp.json()["detail"]
    assert Site.objects.filter(pk=site.id).exists()


@pytest.mark.django_db
def test_site_in_a_project_cannot_be_deleted():
    site = _site("Алга")
    project = Project.objects.create(name="Стройка")
    ProjectSite.objects.create(project=project, site=site)
    resp = Client().delete(f"{BASE}/sites/{site.id}/", **auth(admin_token()))
    assert resp.status_code == 409


# ── связь проект ↔ объект ───────────────────────────────────────────────

@pytest.mark.django_db
def test_set_and_list_project_sites():
    project = Project.objects.create(name="Стройка")
    alga, sazagan = _site("Алга"), _site("Сазаган")
    client = Client()

    resp = client.put(
        f"{BASE}/projects/{project.id}/sites/",
        data='{"site_ids": [%d, %d], "primary_site_id": %d}'
             % (alga.id, sazagan.id, sazagan.id),
        content_type="application/json", **auth(admin_token()))
    assert resp.status_code == 200
    body = resp.json()
    assert {row["name"] for row in body} == {"Алга", "Сазаган"}
    # Основной идёт первым.
    assert body[0]["name"] == "Сазаган" and body[0]["is_primary"] is True

    listed = client.get(f"{BASE}/projects/{project.id}/sites/", **auth()).json()
    assert {row["id"] for row in listed} == {alga.id, sazagan.id}


@pytest.mark.django_db
def test_set_project_sites_replaces_the_whole_set():
    project = Project.objects.create(name="Стройка")
    alga, sazagan = _site("Алга"), _site("Сазаган")
    ProjectSite.objects.create(project=project, site=alga)

    resp = Client().put(
        f"{BASE}/projects/{project.id}/sites/",
        data='{"site_ids": [%d]}' % sazagan.id,
        content_type="application/json", **auth(admin_token()))
    assert resp.status_code == 200
    assert [row["id"] for row in resp.json()] == [sazagan.id]
    assert not ProjectSite.objects.filter(project=project, site=alga).exists()


@pytest.mark.django_db
def test_set_project_sites_rejects_unknown_site():
    project = Project.objects.create(name="Стройка")
    resp = Client().put(
        f"{BASE}/projects/{project.id}/sites/",
        data='{"site_ids": [999999]}',
        content_type="application/json", **auth(admin_token()))
    assert resp.status_code == 400


@pytest.mark.django_db
def test_project_sites_appear_in_the_project_response():
    project = Project.objects.create(name="Стройка", owner_id=USER)
    site = _site("Алга")
    ProjectSite.objects.create(project=project, site=site, is_primary=True)

    body = Client().get(f"{BASE}/projects/{project.id}/",
                        **auth(admin_token())).json()
    assert body["site_ids"] == [site.id]
    assert body["sites"][0]["name"] == "Алга"
    assert body["sites"][0]["is_primary"] is True


# ── объект на задаче ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_task_carries_its_site_in_the_response():
    site = _site("Алга")
    task = _task(site=site)
    body = Client().get(f"{BASE}/tasks/{task.id}/", **auth()).json()
    assert body["site_id"] == site.id
    assert body["site_name"] == "Алга"
    assert body["site_color"] == site.color


@pytest.mark.django_db
def test_create_task_with_a_site_of_its_project():
    project = Project.objects.create(name="Стройка")
    site = _site("Алга")
    ProjectSite.objects.create(project=project, site=site)

    resp = post_json(Client(), f"{BASE}/tasks/",
                     {"summary": "Копать", "project_id": project.id,
                      "site_id": site.id}, **auth(admin_token()))
    assert resp.status_code == 201
    assert resp.json()["site_id"] == site.id


@pytest.mark.django_db
def test_create_task_rejects_a_site_outside_its_project():
    """400, а не 500 — вьюха создания задачи раньше не ловила ValueError."""
    project = Project.objects.create(name="Стройка")
    ProjectSite.objects.create(project=project, site=_site("Алга"))
    stranger = _site("Сазаган")

    resp = post_json(Client(), f"{BASE}/tasks/",
                     {"summary": "Копать", "project_id": project.id,
                      "site_id": stranger.id}, **auth(admin_token()))
    assert resp.status_code == 400
    assert "проект" in resp.json()["detail"]


@pytest.mark.django_db
def test_task_inherits_the_only_site_of_its_project():
    project = Project.objects.create(name="Стройка")
    site = _site("Алга")
    ProjectSite.objects.create(project=project, site=site)

    resp = post_json(Client(), f"{BASE}/tasks/",
                     {"summary": "Копать", "project_id": project.id},
                     **auth(admin_token()))
    assert resp.status_code == 201
    assert resp.json()["site_id"] == site.id


@pytest.mark.django_db
def test_project_without_sites_accepts_any_site():
    """Иначе в день выката сломалось бы создание задач во всех проектах."""
    project = Project.objects.create(name="Старый проект")
    site = _site("Алга")
    resp = post_json(Client(), f"{BASE}/tasks/",
                     {"summary": "Копать", "project_id": project.id,
                      "site_id": site.id}, **auth(admin_token()))
    assert resp.status_code == 201


@pytest.mark.django_db
def test_standalone_task_accepts_any_site():
    site = _site("Алга")
    resp = post_json(Client(), f"{BASE}/tasks/",
                     {"summary": "Разовая", "site_id": site.id},
                     **auth(admin_token()))
    assert resp.status_code == 201
    assert resp.json()["site_id"] == site.id


@pytest.mark.django_db
def test_create_task_rejects_unknown_site():
    resp = post_json(Client(), f"{BASE}/tasks/",
                     {"summary": "Копать", "site_id": 999999},
                     **auth(admin_token()))
    assert resp.status_code == 400


@pytest.mark.django_db
def test_moving_a_task_to_a_project_without_its_site_is_rejected():
    """Тихое обнуление привязки хуже явного отказа."""
    alga, sazagan = _site("Алга"), _site("Сазаган")
    old = Project.objects.create(name="Старый")
    ProjectSite.objects.create(project=old, site=alga)
    new = Project.objects.create(name="Новый")
    ProjectSite.objects.create(project=new, site=sazagan)
    task = _task(project=old, site=alga)

    resp = patch_json(Client(), f"{BASE}/tasks/{task.id}/",
                      {"project_id": new.id}, **auth(admin_token()))
    assert resp.status_code == 400
    task.refresh_from_db()
    assert task.site_id == alga.id      # не тронуто


# ── ось «объект» в списках и отчётах ────────────────────────────────────

@pytest.mark.django_db
def test_filter_tasks_by_site_and_by_absence_of_one():
    site = _site("Алга")
    on_site = _task(site=site)
    off_site = _task()
    client = Client()

    filtered = client.get(f"{BASE}/tasks/?site_id={site.id}",
                          **auth(admin_token())).json()
    assert [row["id"] for row in filtered] == [on_site.id]

    without = client.get(f"{BASE}/tasks/?no_site=true",
                         **auth(admin_token())).json()
    assert [row["id"] for row in without] == [off_site.id]


@pytest.mark.django_db
def test_site_tasks_endpoint():
    site = _site("Алга")
    task = _task(site=site)
    _task()                       # на другом объекте — не должна попасть
    resp = Client().get(f"{BASE}/sites/{site.id}/tasks/", **auth(admin_token()))
    assert resp.status_code == 200
    assert [row["id"] for row in resp.json()] == [task.id]


@pytest.mark.django_db
def test_site_tasks_404_for_unknown_site():
    assert Client().get(f"{BASE}/sites/999999/tasks/",
                        **auth(admin_token())).status_code == 404


@pytest.mark.django_db
def test_stats_report_by_site_and_by_project():
    project = Project.objects.create(name="Стройка")
    site = _site("Алга")
    _task(project=project, site=site)
    _task(project=project, site=site)
    _task()                                # без проекта и объекта

    body = Client().get(f"{BASE}/tasks/stats/", **auth(admin_token())).json()

    by_site = {row["site__name"]: row["count"] for row in body["by_site"]}
    assert by_site == {"Алга": 2, "Без объекта": 1}
    by_project = {row["project__name"]: row["count"]
                  for row in body["by_project"]}
    assert by_project == {"Стройка": 2, "Без проекта": 1}

    # Сумма разрезов сходится с total — иначе отчёт врёт.
    assert sum(by_site.values()) == body["total"]
    assert sum(by_project.values()) == body["total"]


@pytest.mark.django_db
def test_stats_can_be_narrowed_to_one_site():
    site = _site("Алга")
    _task(site=site)
    _task()
    body = Client().get(f"{BASE}/tasks/stats/?site_id={site.id}",
                        **auth(admin_token())).json()
    assert body["total"] == 1


@pytest.mark.django_db
def test_resource_gantt_can_be_narrowed_to_one_site():
    from datetime import date, timedelta

    site = _site("Алга")
    today = date.today()
    window = {"from": str(today - timedelta(days=1)),
              "to": str(today + timedelta(days=30))}
    _task(site=site, assignee_id=USER, start_date=today,
          due_date=today + timedelta(days=5))
    _task(assignee_id=USER, start_date=today,
          due_date=today + timedelta(days=5))

    client = Client()
    everything = client.get(
        f"{BASE}/reports/resource-gantt?from={window['from']}&to={window['to']}",
        **auth(admin_token())).json()
    narrowed = client.get(
        f"{BASE}/reports/resource-gantt?from={window['from']}"
        f"&to={window['to']}&site_id={site.id}",
        **auth(admin_token())).json()

    total_bars = sum(len(r["allocated_tasks"]) for r in everything["resources"])
    site_bars = sum(len(r["allocated_tasks"]) for r in narrowed["resources"])
    assert total_bars == 2
    assert site_bars == 1


# ── замена набора объектов: детали, которые легко потерять ──────────────

@pytest.mark.django_db
def test_primary_site_can_be_reassigned_without_recreating_links():
    """Смена основного объекта не должна пересоздавать связи — иначе
    период присутствия проекта на объекте обнулялся бы при каждой правке."""
    project = Project.objects.create(name="Стройка")
    alga, sazagan = _site("Алга"), _site("Сазаган")
    first = ProjectSite.objects.create(project=project, site=alga,
                                       is_primary=True,
                                       start_date="2026-01-01")
    ProjectSite.objects.create(project=project, site=sazagan)

    resp = Client().put(
        f"{BASE}/projects/{project.id}/sites/",
        data='{"site_ids": [%d, %d], "primary_site_id": %d}'
             % (alga.id, sazagan.id, sazagan.id),
        content_type="application/json", **auth(admin_token()))
    assert resp.status_code == 200

    first.refresh_from_db()
    assert first.is_primary is False
    assert str(first.start_date) == "2026-01-01"     # дата уцелела
    assert ProjectSite.objects.get(project=project,
                                   site=sazagan).is_primary is True


@pytest.mark.django_db
def test_set_project_sites_rejects_a_primary_outside_the_set():
    project = Project.objects.create(name="Стройка")
    alga, sazagan = _site("Алга"), _site("Сазаган")
    resp = Client().put(
        f"{BASE}/projects/{project.id}/sites/",
        data='{"site_ids": [%d], "primary_site_id": %d}' % (alga.id, sazagan.id),
        content_type="application/json", **auth(admin_token()))
    assert resp.status_code == 400


@pytest.mark.django_db
def test_set_project_sites_deduplicates_input():
    project = Project.objects.create(name="Стройка")
    alga = _site("Алга")
    resp = Client().put(
        f"{BASE}/projects/{project.id}/sites/",
        data='{"site_ids": [%d, %d, %d]}' % (alga.id, alga.id, alga.id),
        content_type="application/json", **auth(admin_token()))
    assert resp.status_code == 200
    assert ProjectSite.objects.filter(project=project).count() == 1


@pytest.mark.django_db
def test_clearing_project_sites_reopens_any_site_for_its_tasks():
    """Пустой набор снова разрешает любой объект — то же правило, что и для
    проектов, которым объекты никогда не задавали."""
    project = Project.objects.create(name="Стройка")
    alga, sazagan = _site("Алга"), _site("Сазаган")
    ProjectSite.objects.create(project=project, site=alga)
    client = Client()

    # Пока набор задан, чужой объект отвергается.
    assert post_json(client, f"{BASE}/tasks/",
                     {"summary": "X", "project_id": project.id,
                      "site_id": sazagan.id},
                     **auth(admin_token())).status_code == 400

    client.put(f"{BASE}/projects/{project.id}/sites/",
               data='{"site_ids": []}', content_type="application/json",
               **auth(admin_token()))

    assert post_json(client, f"{BASE}/tasks/",
                     {"summary": "Y", "project_id": project.id,
                      "site_id": sazagan.id},
                     **auth(admin_token())).status_code == 201


@pytest.mark.django_db
def test_site_can_be_deleted_after_its_project_link_is_removed():
    """409 держится ссылкой, а не навсегда: убрали связь — удаляется."""
    project = Project.objects.create(name="Стройка")
    site = _site("Временный")
    ProjectSite.objects.create(project=project, site=site)
    client = Client()

    assert client.delete(f"{BASE}/sites/{site.id}/",
                         **auth(admin_token())).status_code == 409

    client.put(f"{BASE}/projects/{project.id}/sites/",
               data='{"site_ids": []}', content_type="application/json",
               **auth(admin_token()))

    assert client.delete(f"{BASE}/sites/{site.id}/",
                         **auth(admin_token())).status_code == 204

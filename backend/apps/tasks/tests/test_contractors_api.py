"""Партнёры — ``/api/tasks/v1/contractors/*`` и атрибуция работ.

Этап «только справочник»: организации, их представители с уровнями и
привлечения на объекты заводятся и ведутся, но входа в систему у партнёра
нет. Первый блок тестов ниже держит именно это — чтобы «заготовку под
учётки» нельзя было случайно превратить в работающий доступ, не заметив.

Остальное — решения, которые легко потерять при рефакторинге:

* уровень (junior/middle/senior) принадлежит ЧЕЛОВЕКУ, а не организации;
* организацию с задачами/техникой/людьми не удаляют, а архивируют:
  ``Task.contractor`` это ``SET_NULL``, и удаление стёрло бы атрибуцию
  выполненных работ задним числом;
* техника со статусом «партнёра» обязана называть партнёра — правило
  про одну строку одной таблицы, поэтому оно в БД (CHECK), а не в сервисе.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.tasks.models import (
    Contractor, ContractorEngagement, ContractorLevel, ContractorWorker,
    Equipment, Project, Site, Task,
)

from .helpers import BASE, admin_token, auth, patch_json, post_json

USER = 7


def _contractor(name="ТОО СтройМонтаж", **over) -> Contractor:
    return Contractor.objects.create(name=name, **over)


def _worker(contractor, last="Иванов", **over) -> ContractorWorker:
    fields = {"last_name": last, "first_name": "Пётр"}
    fields.update(over)
    return ContractorWorker.objects.create(contractor=contractor, **fields)


def _task(**over) -> Task:
    fields = {"key": f"TASK-{Task.objects.count() + 1}", "summary": "S",
              "reporter_id": USER}
    fields.update(over)
    return Task.objects.create(**fields)


# ─────────────────────────────────────────────────────────────────────────
# Входа у партнёров нет — и не должно появиться незаметно
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_worker_user_id_is_never_populated_by_the_api():
    """``user_id`` — заготовка под будущий вход. Через API он не
    выставляется: привязка аккаунта это выдача доступа, а не правка
    карточки."""
    contractor = _contractor()
    resp = post_json(Client(), f"{BASE}/contractors/{contractor.id}/workers/",
                     {"last_name": "Иванов", "first_name": "Пётр",
                      "user_id": 12345},
                     **auth(admin_token()))
    assert resp.status_code == 201
    assert resp.json()["user_id"] is None
    assert ContractorWorker.objects.get(pk=resp.json()["id"]).user_id is None


@pytest.mark.django_db
def test_worker_user_id_cannot_be_set_through_update_either():
    worker = _worker(_contractor())
    resp = patch_json(Client(), f"{BASE}/contractor-workers/{worker.id}/",
                      {"user_id": 999}, **auth(admin_token()))
    assert resp.status_code == 200
    worker.refresh_from_db()
    assert worker.user_id is None


@pytest.mark.django_db
def test_contractor_level_does_not_affect_task_visibility_yet():
    """Уровень пока только хранится. Пока входа нет, он не может ничего
    открыть — а когда появится, это поведение поменяется осознанно."""
    contractor = _contractor()
    senior = _worker(contractor, level=ContractorLevel.SENIOR)
    hidden = _task(reporter_id=4242, assignee_id=4242,
                   contractor=contractor, contractor_worker=senior)

    # Обычный сотрудник (не участник) задачу партнёра не видит — ровно
    # так же, как любую другую чужую.
    assert Client().get(f"{BASE}/tasks/{hidden.id}/",
                        **auth()).status_code == 404


# ─────────────────────────────────────────────────────────────────────────
# Организации
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_contractors_require_authentication():
    assert Client().get(f"{BASE}/contractors/").status_code == 401


@pytest.mark.django_db
def test_list_is_open_but_writes_are_admin_only():
    _contractor()
    client = Client()
    assert client.get(f"{BASE}/contractors/", **auth()).status_code == 200
    assert post_json(client, f"{BASE}/contractors/", {"name": "Самозванец"},
                     **auth()).status_code == 403
    assert not Contractor.objects.filter(name="Самозванец").exists()


@pytest.mark.django_db
def test_create_contractor():
    resp = post_json(Client(), f"{BASE}/contractors/",
                     {"name": "ТОО СтройМонтаж", "bin_iin": "123456789012",
                      "contact_person": "Иванов И.И.",
                      "phone": "+7 (700) 483-55-81"},
                     **auth(admin_token()))
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "active"
    assert body["phone"] == "+7 (700) 483-55-81"


@pytest.mark.django_db
def test_bin_must_be_twelve_digits():
    resp = post_json(Client(), f"{BASE}/contractors/",
                     {"name": "ТОО X", "bin_iin": "12345"},
                     **auth(admin_token()))
    assert resp.status_code == 422


@pytest.mark.django_db
def test_filter_contractors_by_status_and_search():
    _contractor("ТОО Альфа")
    _contractor("ТОО Бета", status="archived")
    client = Client()
    active = client.get(f"{BASE}/contractors/?status=active", **auth()).json()
    assert [c["name"] for c in active] == ["ТОО Альфа"]
    found = client.get(f"{BASE}/contractors/?search=бет", **auth()).json()
    assert [c["name"] for c in found] == ["ТОО Бета"]


@pytest.mark.django_db
def test_contractor_with_tasks_is_not_deleted_but_archived():
    contractor = _contractor()
    _task(contractor=contractor)
    resp = Client().delete(f"{BASE}/contractors/{contractor.id}/",
                           **auth(admin_token()))
    assert resp.status_code == 409
    assert "архив" in resp.json()["detail"]
    assert Contractor.objects.filter(pk=contractor.id).exists()


@pytest.mark.django_db
def test_contractor_with_workers_is_not_deleted():
    contractor = _contractor()
    _worker(contractor)
    assert Client().delete(f"{BASE}/contractors/{contractor.id}/",
                           **auth(admin_token())).status_code == 409


@pytest.mark.django_db
def test_unused_contractor_can_be_deleted():
    contractor = _contractor()
    assert Client().delete(f"{BASE}/contractors/{contractor.id}/",
                           **auth(admin_token())).status_code == 204


# ─────────────────────────────────────────────────────────────────────────
# Представители и уровни
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_worker_level_defaults_to_junior():
    contractor = _contractor()
    resp = post_json(Client(), f"{BASE}/contractors/{contractor.id}/workers/",
                     {"last_name": "Иванов", "first_name": "Пётр"},
                     **auth(admin_token()))
    assert resp.status_code == 201
    assert resp.json()["level"] == "junior"


@pytest.mark.django_db
def test_level_belongs_to_the_person_not_the_organisation():
    """Одна организация держит людей разных уровней — прораб senior, его
    рабочие junior."""
    contractor = _contractor()
    _worker(contractor, "Прорабов", level=ContractorLevel.SENIOR)
    _worker(contractor, "Рабочих", level=ContractorLevel.JUNIOR)

    body = Client().get(f"{BASE}/contractors/{contractor.id}/workers/",
                        **auth()).json()
    levels = {row["last_name"]: row["level"] for row in body}
    assert levels == {"Прорабов": "senior", "Рабочих": "junior"}


@pytest.mark.django_db
def test_worker_full_name_is_composed():
    contractor = _contractor()
    worker = _worker(contractor, "Иванов", middle_name="Сергеевич")
    body = Client().get(f"{BASE}/contractors/{contractor.id}/workers/",
                        **auth()).json()
    row = next(r for r in body if r["id"] == worker.id)
    assert row["full_name"] == "Иванов Пётр Сергеевич"


@pytest.mark.django_db
def test_deleting_a_worker_only_deactivates_them():
    """Исторические задачи ссылаются на человека — жёсткое удаление
    обнулило бы им исполнителя."""
    contractor = _contractor()
    worker = _worker(contractor)
    assert Client().delete(f"{BASE}/contractor-workers/{worker.id}/",
                           **auth(admin_token())).status_code == 204
    worker.refresh_from_db()
    assert worker.is_active is False
    assert ContractorWorker.objects.filter(pk=worker.id).exists()


@pytest.mark.django_db
def test_worker_list_hides_deactivated_by_default():
    contractor = _contractor()
    _worker(contractor, "Активный")
    _worker(contractor, "Отключённый", is_active=False)
    client = Client()
    default = client.get(f"{BASE}/contractors/{contractor.id}/workers/",
                         **auth()).json()
    assert [r["last_name"] for r in default] == ["Активный"]
    everyone = client.get(
        f"{BASE}/contractors/{contractor.id}/workers/?active_only=false",
        **auth()).json()
    assert len(everyone) == 2


# ─────────────────────────────────────────────────────────────────────────
# Привлечения
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_engagement_requires_a_project_or_a_site():
    contractor = _contractor()
    resp = post_json(Client(), f"{BASE}/contractor-engagements/",
                     {"contractor_id": contractor.id},
                     **auth(admin_token()))
    assert resp.status_code == 422       # схема ловит раньше CHECK


@pytest.mark.django_db
def test_engagement_on_a_site_alone_is_valid():
    """Партнёр может работать на объекте вне конкретного проекта."""
    contractor = _contractor()
    site = Site.objects.create(name="Алга")
    resp = post_json(Client(), f"{BASE}/contractor-engagements/",
                     {"contractor_id": contractor.id, "site_id": site.id,
                      "contract_no": "Д-17"},
                     **auth(admin_token()))
    assert resp.status_code == 201
    body = resp.json()
    assert body["site_name"] == "Алга"
    assert body["project_id"] is None


@pytest.mark.django_db
def test_engagement_on_a_project_alone_is_valid():
    contractor = _contractor()
    project = Project.objects.create(name="Стройка")
    resp = post_json(Client(), f"{BASE}/contractor-engagements/",
                     {"contractor_id": contractor.id,
                      "project_id": project.id},
                     **auth(admin_token()))
    assert resp.status_code == 201
    assert resp.json()["site_id"] is None


@pytest.mark.django_db
def test_engagements_filter_by_site():
    contractor = _contractor()
    alga = Site.objects.create(name="Алга")
    sazagan = Site.objects.create(name="Сазаган")
    ContractorEngagement.objects.create(contractor=contractor, site=alga)
    ContractorEngagement.objects.create(contractor=contractor, site=sazagan)

    body = Client().get(
        f"{BASE}/contractor-engagements/?site_id={alga.id}", **auth()).json()
    assert [row["site_name"] for row in body] == ["Алга"]


@pytest.mark.django_db
def test_engagement_dates_must_be_ordered():
    contractor = _contractor()
    site = Site.objects.create(name="Алга")
    resp = post_json(Client(), f"{BASE}/contractor-engagements/",
                     {"contractor_id": contractor.id, "site_id": site.id,
                      "start_date": "2026-06-01", "end_date": "2026-01-01"},
                     **auth(admin_token()))
    assert resp.status_code == 500       # CHECK ck_engagement_dates


# ─────────────────────────────────────────────────────────────────────────
# Атрибуция задач
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_task_carries_its_contractor_in_the_response():
    contractor = _contractor()
    worker = _worker(contractor)
    task = _task(contractor=contractor, contractor_worker=worker)
    body = Client().get(f"{BASE}/tasks/{task.id}/", **auth()).json()
    assert body["contractor_id"] == contractor.id
    assert body["contractor_name"] == "ТОО СтройМонтаж"
    assert body["contractor_worker_name"] == "Иванов Пётр"


@pytest.mark.django_db
def test_task_without_a_contractor_means_our_own_crew():
    task = _task()
    body = Client().get(f"{BASE}/tasks/{task.id}/", **auth()).json()
    assert body["contractor_id"] is None
    assert body["contractor_worker_id"] is None


@pytest.mark.django_db
def test_create_task_with_a_contractor():
    contractor = _contractor()
    worker = _worker(contractor)
    resp = post_json(Client(), f"{BASE}/tasks/",
                     {"summary": "Монтаж", "contractor_id": contractor.id,
                      "contractor_worker_id": worker.id},
                     **auth(admin_token()))
    assert resp.status_code == 201
    assert resp.json()["contractor_id"] == contractor.id


@pytest.mark.django_db
def test_filter_tasks_by_contractor():
    contractor = _contractor()
    theirs = _task(contractor=contractor)
    _task()                                   # наша команда
    body = Client().get(f"{BASE}/tasks/?contractor_id={contractor.id}",
                        **auth(admin_token())).json()
    assert [row["id"] for row in body] == [theirs.id]


# ─────────────────────────────────────────────────────────────────────────
# Владелец техники
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_existing_equipment_reads_as_own():
    """Парк, который вёлся до партнёров, честно становится собственным —
    а не «неизвестно»."""
    eq = Equipment.objects.create(name="Экскаватор")
    body = Client().get(f"{BASE}/equipment/", **auth()).json()
    row = next(r for r in body if r["id"] == eq.id)
    assert row["ownership"] == "own"
    assert row["contractor_id"] is None


@pytest.mark.django_db
def test_contractor_equipment_names_its_contractor():
    contractor = _contractor()
    resp = post_json(Client(), f"{BASE}/equipment/",
                     {"name": "Кран подрядчика", "ownership": "contractor",
                      "contractor_id": contractor.id},
                     **auth(admin_token()))
    assert resp.status_code == 201
    assert resp.json()["contractor_name"] == "ТОО СтройМонтаж"


@pytest.mark.django_db
def test_contractor_equipment_without_a_contractor_is_rejected():
    resp = post_json(Client(), f"{BASE}/equipment/",
                     {"name": "Ничей кран", "ownership": "contractor"},
                     **auth(admin_token()))
    assert resp.status_code == 422
    assert not Equipment.objects.filter(name="Ничей кран").exists()


@pytest.mark.django_db
def test_rented_equipment_needs_no_contractor():
    resp = post_json(Client(), f"{BASE}/equipment/",
                     {"name": "Арендованный кран", "ownership": "rented"},
                     **auth(admin_token()))
    assert resp.status_code == 201
    assert resp.json()["contractor_id"] is None


@pytest.mark.django_db
def test_filter_equipment_by_ownership_and_contractor():
    contractor = _contractor()
    Equipment.objects.create(name="Наш экскаватор")
    Equipment.objects.create(name="Их кран", ownership="contractor",
                             contractor=contractor)
    client = Client()
    own = client.get(f"{BASE}/equipment/?ownership=own", **auth()).json()
    assert [r["name"] for r in own] == ["Наш экскаватор"]
    theirs = client.get(f"{BASE}/equipment/?contractor_id={contractor.id}",
                        **auth()).json()
    assert [r["name"] for r in theirs] == ["Их кран"]


# ─────────────────────────────────────────────────────────────────────────
# Фильтр «Своя команда» и вход будущей видимости
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_own_crew_filter_returns_tasks_without_a_contractor():
    """NULL нельзя выразить через параметр-число, поэтому «своя команда» —
    отдельный флаг, а не contractor_id=0."""
    contractor = _contractor()
    ours = _task()
    _task(contractor=contractor)

    body = Client().get(f"{BASE}/tasks/?own_crew=true",
                        **auth(admin_token())).json()
    assert [row["id"] for row in body] == [ours.id]


@pytest.mark.django_db
def test_own_crew_and_contractor_filters_are_complementary():
    """Вместе они дают полный список — иначе часть работ выпала бы из обоих
    представлений и не показалась бы нигде."""
    contractor = _contractor()
    _task()
    _task(contractor=contractor)
    client = Client()

    ours = client.get(f"{BASE}/tasks/?own_crew=true", **auth(admin_token())).json()
    theirs = client.get(f"{BASE}/tasks/?contractor_id={contractor.id}",
                        **auth(admin_token())).json()
    everything = client.get(f"{BASE}/tasks/", **auth(admin_token())).json()

    assert len(ours) + len(theirs) == len(everything)


@pytest.mark.django_db
def test_engagement_site_ids_feeds_the_future_visibility_scope():
    """Пара «организация + объект» — та единица, в которой сформулировано
    право senior. Функция уже возвращает её, хотя авторизация ещё не
    подключена: когда подключат, поведение должно быть этим."""
    from apps.tasks.services import contractor_service

    contractor = _contractor()
    alga = Site.objects.create(name="Алга")
    sazagan = Site.objects.create(name="Сазаган")
    ContractorEngagement.objects.create(contractor=contractor, site=alga)
    ContractorEngagement.objects.create(contractor=contractor, site=sazagan)

    assert set(contractor_service.engagement_site_ids(contractor.id)) == {
        alga.id, sazagan.id}


@pytest.mark.django_db
def test_engagement_site_ids_ignores_inactive_and_projectwide_rows():
    """Завершённое привлечение не должно оставлять доступ, а привлечение на
    проект целиком не называет объекта и в этот список не попадает."""
    from apps.tasks.services import contractor_service

    contractor = _contractor()
    alga = Site.objects.create(name="Алга")
    old = Site.objects.create(name="Старый объект")
    project = Project.objects.create(name="Стройка")
    ContractorEngagement.objects.create(contractor=contractor, site=alga)
    ContractorEngagement.objects.create(contractor=contractor, site=old,
                                        is_active=False)
    ContractorEngagement.objects.create(contractor=contractor, project=project)

    assert contractor_service.engagement_site_ids(contractor.id) == [alga.id]


@pytest.mark.django_db
def test_engagement_site_ids_is_scoped_to_one_contractor():
    from apps.tasks.services import contractor_service

    ours = _contractor("ТОО Наш")
    theirs = _contractor("ТОО Чужой")
    alga = Site.objects.create(name="Алга")
    sazagan = Site.objects.create(name="Сазаган")
    ContractorEngagement.objects.create(contractor=ours, site=alga)
    ContractorEngagement.objects.create(contractor=theirs, site=sazagan)

    assert contractor_service.engagement_site_ids(ours.id) == [alga.id]


@pytest.mark.django_db
def test_engagement_can_be_closed_by_date_and_deactivated():
    contractor = _contractor()
    site = Site.objects.create(name="Алга")
    engagement = ContractorEngagement.objects.create(contractor=contractor,
                                                     site=site)
    resp = patch_json(Client(),
                      f"{BASE}/contractor-engagements/{engagement.id}/",
                      {"end_date": "2026-03-31", "is_active": False},
                      **auth(admin_token()))
    assert resp.status_code == 200
    body = resp.json()
    assert body["end_date"] == "2026-03-31"
    assert body["is_active"] is False


@pytest.mark.django_db
def test_engagement_cannot_be_stripped_of_both_targets():
    """Обнулить и проект, и объект — значит оставить привлечение ни к чему
    не привязанным. 400, а не IntegrityError."""
    contractor = _contractor()
    site = Site.objects.create(name="Алга")
    engagement = ContractorEngagement.objects.create(contractor=contractor,
                                                     site=site)
    resp = patch_json(Client(),
                      f"{BASE}/contractor-engagements/{engagement.id}/",
                      {"site_id": None}, **auth(admin_token()))
    assert resp.status_code == 400
    engagement.refresh_from_db()
    assert engagement.site_id == site.id


@pytest.mark.django_db
def test_engagement_is_unique_per_contractor_project_site():
    contractor = _contractor()
    site = Site.objects.create(name="Алга")
    ContractorEngagement.objects.create(contractor=contractor, site=site)
    resp = post_json(Client(), f"{BASE}/contractor-engagements/",
                     {"contractor_id": contractor.id, "site_id": site.id},
                     **auth(admin_token()))
    assert resp.status_code == 500       # uq_contractor_engagement

# -*- coding: utf-8 -*-
"""Связь администратора бюджета с проектом из ``apps.tasks``.

До неё проект существовал в платформе дважды: как ``tasks.Project`` (с
объектами, блоками и задачами) и как строка ``contracts.Administrator.
project_name``. Здесь проверяется, что связь настоящая — то есть что имя
следует за проектом, а не живёт своей жизнью, — и что она не протекла в
запрещённую сторону: FK между доменами нет, разрешение только через
``apps.tasks.interface``.
"""
from __future__ import annotations

import pytest
from django.test import Client

from apps.contracts.models import Administrator
from apps.tasks.models import Project

from .helpers import (BASE, admin_token, auth, make_country, make_program,
                      patch_json, post_json, token)


@pytest.fixture
def project(db) -> Project:
    return Project.objects.create(name="QAZAQSTAN-Aralsk", color="#3b82f6")


@pytest.mark.django_db
def test_administrator_takes_its_name_from_the_linked_project(project):
    """Со связью подпись берётся у проекта, а не у присланного текста."""
    country = make_country()
    resp = post_json(Client(), f"{BASE}/administrators", {
        "country_id": country.pk,
        "project_id": project.pk,
        # Намеренно расходится с именем проекта: победить должен проект.
        "project_name": "написано от руки",
    }, **auth(admin_token()))
    assert resp.status_code == 201, resp.content
    data = resp.json()
    assert data["project_id"] == project.pk
    assert data["project_name"] == "QAZAQSTAN-Aralsk"
    assert data["project"]["name"] == "QAZAQSTAN-Aralsk"
    assert data["project"]["color"] == "#3b82f6"
    assert data["display_name"].startswith("QAZAQSTAN-Aralsk")


@pytest.mark.django_db
def test_administrator_without_a_link_keeps_its_own_name(project):
    """Без связи всё как раньше: имя из текста, ``project`` пустой."""
    country = make_country()
    resp = post_json(Client(), f"{BASE}/administrators", {
        "country_id": country.pk, "project_name": "Проект без доски задач",
    }, **auth(admin_token()))
    assert resp.status_code == 201, resp.content
    data = resp.json()
    assert data["project_name"] == "Проект без доски задач"
    assert data["project_id"] is None
    assert data["project"] is None


@pytest.mark.django_db
def test_neither_a_name_nor_a_link_is_rejected():
    """Подпись у записи должна быть хоть откуда-то."""
    country = make_country()
    resp = post_json(Client(), f"{BASE}/administrators",
                     {"country_id": country.pk}, **auth(admin_token()))
    # 422, а не 409: это форма запроса, а не конфликт с состоянием базы.
    assert resp.status_code == 422, (resp.status_code, resp.content)


@pytest.mark.django_db
def test_unknown_project_is_404_not_a_silently_stored_id():
    """Междоменного FK нет, поэтому целостность держит сервис."""
    country = make_country()
    resp = post_json(Client(), f"{BASE}/administrators", {
        "country_id": country.pk, "project_id": 999_999,
    }, **auth(admin_token()))
    assert resp.status_code == 404, (resp.status_code, resp.content)
    assert not Administrator.objects.exists()


@pytest.mark.django_db
def test_linking_later_rewrites_the_name(project):
    """PATCH со связью подтягивает имя проекта поверх старого текста."""
    country = make_country()
    admin = Administrator.objects.create(country=country,
                                         project_name="старое название")
    resp = patch_json(Client(), f"{BASE}/administrators/{admin.pk}",
                      {"project_id": project.pk}, **auth(admin_token()))
    assert resp.status_code == 200, resp.content
    assert resp.json()["project_name"] == "QAZAQSTAN-Aralsk"
    admin.refresh_from_db()
    assert admin.project_id == project.pk
    assert admin.project_name == "QAZAQSTAN-Aralsk"


@pytest.mark.django_db
def test_a_patch_that_does_not_mention_the_project_keeps_the_link(project):
    """Главная ловушка: ``None`` значит «не прислали», а не «отвязать».

    Схемы обновления объявляют все поля как ``Optional = None``, и обычный
    ``model_dump()`` кладёт ``project_id: None`` в КАЖДЫЙ PATCH. Без
    ``exclude_unset`` правка одного лишь ``is_active`` молча рвала бы связь.
    """
    country = make_country()
    admin = Administrator.objects.create(country=country, project_id=project.pk,
                                         project_name="QAZAQSTAN-Aralsk")
    resp = patch_json(Client(), f"{BASE}/administrators/{admin.pk}",
                      {"is_active": False}, **auth(admin_token()))
    assert resp.status_code == 200, resp.content
    admin.refresh_from_db()
    assert admin.project_id == project.pk, "PATCH оборвал связь с проектом"


@pytest.mark.django_db
def test_the_link_can_be_removed_explicitly(project):
    """Присланный null — это уже «отвязать»; подпись при этом остаётся."""
    country = make_country()
    admin = Administrator.objects.create(country=country, project_id=project.pk,
                                         project_name="QAZAQSTAN-Aralsk")
    resp = patch_json(Client(), f"{BASE}/administrators/{admin.pk}",
                      {"project_id": None}, **auth(admin_token()))
    assert resp.status_code == 200, resp.content
    data = resp.json()
    assert data["project_id"] is None
    assert data["project"] is None
    # Запись не должна остаться безымянной — иначе она пропала бы из списков.
    assert data["project_name"] == "QAZAQSTAN-Aralsk"


@pytest.mark.django_db
def test_a_project_deleted_in_tasks_leaves_the_link_but_empties_the_brief(project):
    """«Проект был, но его удалили» отличается от «связи не было».

    Стереть чужую ссылку в транзакции модуля задач некому, поэтому id
    остаётся, а паспорт приезжает пустым.
    """
    country = make_country()
    admin = Administrator.objects.create(country=country, project_id=project.pk,
                                         project_name="QAZAQSTAN-Aralsk")
    project_id = project.pk
    project.delete()

    resp = Client().get(f"{BASE}/administrators/{admin.pk}", **auth(token()))
    assert resp.status_code == 200, resp.content
    data = resp.json()
    assert data["project_id"] == project_id
    assert data["project"] is None


@pytest.mark.django_db
def test_budget_and_agreement_carry_the_project_id(project):
    """Карточка бюджета и договора знают проект — иначе связь не видна там,
    где на неё смотрят."""
    from .helpers import make_counterparty, make_line
    from .test_agreements_api import _agreement_body

    country = make_country()
    administrator = Administrator.objects.create(
        country=country, project_id=project.pk, project_name="QAZAQSTAN-Aralsk")
    line = make_line(administrator=administrator)
    counterparty = make_counterparty(country=country)
    client = Client()

    created = post_json(client, f"{BASE}/agreements",
                        _agreement_body(line, counterparty),
                        **auth(admin_token()))
    assert created.status_code == 201, created.content
    assert created.json()["project_id"] == project.pk

    budget = client.get(f"{BASE}/budgets/{line.budget_id}", **auth(token()))
    assert budget.status_code == 200, budget.content
    assert budget.json()["project_id"] == project.pk


@pytest.mark.django_db
def test_listing_administrators_does_not_query_per_project(django_assert_max_num_queries):
    """Проекты разрешаются ПАКЕТОМ, а не по запросу на строку.

    Проверяется ростом, а не абсолютным числом: точное количество запросов
    зависит от кэша реестра сервисов и поедет от любой соседней правки, а
    вопрос здесь один — растёт ли оно вместе с числом связанных строк.
    Пакетно — нет; поштучно — на каждую.
    """
    country = make_country()
    client = Client()

    def measure(count: int) -> int:
        Administrator.objects.all().delete()
        Project.objects.all().delete()
        for i in range(count):
            project = Project.objects.create(name=f"Проект {i}")
            Administrator.objects.create(country=country, project_id=project.pk,
                                         project_name=project.name)
        # Прогрев: реестр сервисов кэшируется на 5 с, и первый вызов иначе
        # добавил бы свой запрос только к первому замеру.
        client.get(f"{BASE}/administrators", **auth(token()))
        # max_num_queries — только ради захвата: утверждение делается ниже,
        # сравнением двух замеров, а не порогом.
        with django_assert_max_num_queries(100) as captured:
            resp = client.get(f"{BASE}/administrators", **auth(token()))
        assert resp.status_code == 200, resp.content
        return len(captured.captured_queries)

    assert measure(2) == measure(6), "число запросов растёт с числом проектов — N+1"


@pytest.mark.django_db
def test_listing_administrators_returns_each_projects_brief(project):
    """Пакетное разрешение не должно перепутать проекты между строками."""
    country = make_country()
    second = Project.objects.create(name="QAZAQSTAN-Shymkent")
    for name, pid in (("QAZAQSTAN-Aralsk", project.pk),
                      ("QAZAQSTAN-Shymkent", second.pk),
                      ("Без проекта", None)):
        Administrator.objects.create(country=country, project_name=name,
                                     project_id=pid)

    resp = Client().get(f"{BASE}/administrators", **auth(token()))
    assert resp.status_code == 200, resp.content
    linked = {row["project_name"]: row["project"] for row in resp.json()}
    assert linked["QAZAQSTAN-Aralsk"]["id"] == project.pk
    assert linked["QAZAQSTAN-Shymkent"]["id"] == second.pk
    assert linked["Без проекта"] is None


@pytest.mark.django_db
def test_budget_can_be_created_straight_from_a_task_project():
    """Основной путь формы: выбрали проект — администратор нашёлся сам.

    До этого в форме было два поля про проект (название администратора и
    отдельная связь), и разойдясь, они давали ДВУХ администраторов на один
    проект. Теперь выбор один, а имя администратора берётся у проекта.
    """
    country = make_country()
    project = Project.objects.create(name="QAZAQSTAN-Turkestan", color="#a855f7")
    program = make_program(name="Электромонтаж", expense_item="Кабельные линии")

    resp = post_json(Client(), f"{BASE}/budgets/full", {
        # Ни project_name, ни id администратора — только проект и страна.
        "administrator": {"project_id": project.pk, "country": {"id": country.pk}},
        "programs": [{"program": {"id": program.pk}, "amount": "1000000.00"}],
        "period_year": 2026,
        "currency": "KZT",
    }, **auth(admin_token()))
    assert resp.status_code == 201, resp.content
    assert resp.json()["project_id"] == project.pk

    admin = Administrator.objects.get(project_id=project.pk)
    assert admin.project_name == "QAZAQSTAN-Turkestan"
    assert admin.country_id == country.pk


@pytest.mark.django_db
def test_the_same_project_does_not_spawn_a_second_administrator():
    """Второй бюджет по тому же проекту переиспользует администратора."""
    country = make_country()
    project = Project.objects.create(name="QAZAQSTAN-Turkestan")
    program = make_program(name="Электромонтаж", expense_item="Кабельные линии")
    other = make_program(name="Земляные", expense_item="Планировка")

    def create(year: int, prog):
        return post_json(Client(), f"{BASE}/budgets/full", {
            "administrator": {"project_id": project.pk, "country": {"id": country.pk}},
            "programs": [{"program": {"id": prog.pk}, "amount": "500000.00"}],
            "period_year": year, "currency": "KZT",
        }, **auth(admin_token()))

    assert create(2026, program).status_code == 201
    assert create(2027, other).status_code == 201
    assert Administrator.objects.filter(project_id=project.pk).count() == 1


@pytest.mark.django_db
def test_a_project_absent_from_tasks_still_works_by_name():
    """Проекта нет на доске задач — бюджет всё равно заводится, без связи."""
    country = make_country()
    program = make_program(name="Прочее", expense_item="Хознужды")
    resp = post_json(Client(), f"{BASE}/budgets/full", {
        "administrator": {"project_name": "Стройка вне доски",
                          "country": {"id": country.pk}},
        "programs": [{"program": {"id": program.pk}, "amount": "100000.00"}],
        "period_year": 2026, "currency": "KZT",
    }, **auth(admin_token()))
    assert resp.status_code == 201, resp.content
    assert resp.json()["project_id"] is None
    assert Administrator.objects.get(project_name="Стройка вне доски").project_id is None

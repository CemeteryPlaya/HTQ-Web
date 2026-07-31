"""План/факт с прогнозом: SPI, отставание, дата финиша по фактическому темпу.

Числа взяты из SPEC §2 и §10, а не выдуманы: 250 валов на блок, план 4
недели, и проектный пример «старт 03.04.26, план-финиш 04.07.27, прогноз
02.08.27 → отставание ~30 дней ≈ 6,7 % плана».

Отдельно стерегутся два правила, которые легко нарушить незаметно:

* **не врать нулём** — там, где сравнивать не с чем, ``None``, а не ``0``;
* **единицы не складываются** — агрегат по разным видам работ это среднее
  отношений, а не отношение сумм.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.test import Client

from apps.tasks.models import (DailyReport, Project, ProjectSite, Roadmap,
                               Site, SiteBlock, Status, Task, TaskVolume,
                               WorkVolumeType)
from apps.tasks.services import plan_fact_service

from .helpers import BASE, admin_token, auth

D = dt.date


@pytest.fixture
def valy(db) -> WorkVolumeType:
    return WorkVolumeType.objects.create(slug="valy", name="Валы")


@pytest.fixture
def project(db) -> Project:
    return Project.objects.create(name="Дамона 100 МВт", owner_id=9,
                                  start_date=D(2026, 6, 1),
                                  end_date=D(2026, 6, 30))


@pytest.fixture
def block(db, project) -> SiteBlock:
    site = Site.objects.create(name="Сазаган")
    ProjectSite.objects.create(project=project, site=site)
    return SiteBlock.objects.create(site=site, name="Блок 1", order=1)


@pytest.fixture
def roadmap(db, project, block) -> Roadmap:
    return Roadmap.objects.create(
        project=project, site_block=block, owner_id=9,
        name="Развозка валов трекерных конструкций",
        planned_start_date=D(2026, 6, 1), planned_end_date=D(2026, 6, 28))


def _task(roadmap, valy, *, key="TASK-1", planned=250,
          start=D(2026, 6, 1), due=D(2026, 6, 28)) -> Task:
    task = Task.objects.create(key=key, summary=key, roadmap=roadmap,
                               project=roadmap.project,
                               start_date=start, due_date=due)
    TaskVolume.objects.create(task=task, volume_type=valy,
                              planned_quantity=planned)
    return task


def _report(task, valy, day, quantity):
    return DailyReport.objects.create(task=task, volume_type=valy,
                                      work_date=day, quantity=quantity)


# ── плановый процент ────────────────────────────────────────────────────

def test_plan_percent_is_linear_between_the_dates():
    start, end = D(2026, 6, 1), D(2026, 6, 10)     # 10 календарных дней
    assert plan_fact_service.plan_percent(start, end, D(2026, 5, 30),
                                          working=False) == 0.0
    assert plan_fact_service.plan_percent(start, end, D(2026, 6, 10),
                                          working=False) == 1.0
    # 1–5 июня это 5 дней из 10.
    assert plan_fact_service.plan_percent(start, end, D(2026, 6, 5),
                                          working=False) == 0.5


def test_plan_percent_is_none_without_dates():
    """Без плановых дат «сколько должно быть сделано» не определено, и
    ноль объявил бы работу просроченной с первого дня."""
    assert plan_fact_service.plan_percent(None, D(2026, 6, 10), D(2026, 6, 5),
                                          working=False) is None
    assert plan_fact_service.plan_percent(D(2026, 6, 1), None, D(2026, 6, 5),
                                          working=False) is None


# ── прогноз по темпу ────────────────────────────────────────────────────

def test_forecast_is_none_when_the_rate_is_zero():
    """Стоим — значит даты финиша нет. Ноль в знаменателе не «бесконечно
    быстро», а «не двигаемся»."""
    assert plan_fact_service.forecast_end(100, 0, D(2026, 6, 5)) is None
    assert plan_fact_service.forecast_end(100, None, D(2026, 6, 5)) is None


def test_forecast_is_today_when_nothing_is_left():
    """Чистая функция знает о работе только «остатка нет» и честно отвечает
    «сегодня». Дату настоящего закрытия подставляет вызывающий — см.
    следующий тест."""
    assert plan_fact_service.forecast_end(0, 10, D(2026, 6, 5)) == D(2026, 6, 5)


@pytest.mark.django_db
def test_finished_work_is_dated_by_its_last_report_not_by_today(roadmap, valy):
    """Пакет, закрытый в срок, не должен копить отставание день за днём.

    Регресс, найденный на демо-данных: прогноз закрытой работы брался как
    «сегодня», и сданный вовремя пакет показывал «+20 дней», «+21 день»,
    «+22» — прогноз полз за текущей датой, пока плановая стояла на месте.
    Финиш закончившейся работы — это дата последнего отчёта.
    """
    task = _task(roadmap, valy, planned=100, start=D(2026, 6, 1),
                 due=D(2026, 6, 10))
    _report(task, valy, D(2026, 6, 3), 60)
    _report(task, valy, D(2026, 6, 8), 40)

    def node_on(day: str) -> dict:
        return Client().get(
            f"{BASE}/plan-fact/roadmap/{roadmap.id}?date={day}",
            **auth(admin_token())).json()["children"][0]

    finished = node_on("2026-06-20")
    assert finished["fact_pct"] == 100.0
    assert finished["forecast_end"] == "2026-06-08"
    # Сдали 8-го при плане на 10-е — это опережение на два дня, и оно
    # остаётся тем же, с какой бы даты ни смотрели.
    assert finished["lag_days"] == -2
    assert node_on("2026-07-31")["lag_days"] == -2


@pytest.mark.django_db
def test_rate_is_measured_from_the_first_report_not_the_full_window(roadmap,
                                                                    valy):
    """Команда, вышедшая на объект три дня назад, не должна выглядеть втрое
    медленнее из-за деления на 14."""
    task = _task(roadmap, valy, planned=250)
    for day in range(3):
        _report(task, valy, D(2026, 6, 1) + dt.timedelta(days=day), 30)

    body = Client().get(
        f"{BASE}/plan-fact/roadmap/{roadmap.id}?date=2026-06-03",
        **auth(admin_token())).json()
    node = body["children"][0]
    assert node["rate_window_days"] == 3
    assert node["rate_per_day"] == 30.0        # 90 / 3, а не 90 / 14


@pytest.mark.django_db
def test_stalled_task_is_flagged_and_has_no_forecast(roadmap, valy):
    task = _task(roadmap, valy, planned=250)
    _report(task, valy, D(2026, 6, 1), 50)

    # Отчётная дата далеко после последнего отчёта: окно пустое, темп 0.
    body = Client().get(
        f"{BASE}/plan-fact/roadmap/{roadmap.id}?date=2026-06-28",
        **auth(admin_token())).json()
    node = body["children"][0]
    assert node["rate_per_day"] == 0.0
    assert node["forecast_end"] is None
    assert "stalled" in node["flags"]


# ── факт на отчётную дату ───────────────────────────────────────────────

@pytest.mark.django_db
def test_fact_counts_only_reports_up_to_the_data_date(roadmap, valy):
    """Ровно то, чего не мог сделать `completed_quantity`: спросить факт на
    произвольную дату."""
    task = _task(roadmap, valy, planned=250)
    _report(task, valy, D(2026, 6, 5), 100)
    _report(task, valy, D(2026, 6, 20), 80)

    hdr = auth(admin_token())
    early = Client().get(f"{BASE}/plan-fact/roadmap/{roadmap.id}?date=2026-06-10",
                         **hdr).json()
    late = Client().get(f"{BASE}/plan-fact/roadmap/{roadmap.id}?date=2026-06-25",
                        **hdr).json()
    assert early["children"][0]["fact_quantity"] == 100.0
    assert late["children"][0]["fact_quantity"] == 180.0


@pytest.mark.django_db
def test_task_without_volumes_falls_back_to_progress_percent(roadmap):
    """У согласования или приёмки измеримого объёма нет — единственная
    доступная мера это субъективный процент исполнителя."""
    Task.objects.create(key="TASK-9", summary="Согласование", roadmap=roadmap,
                        start_date=D(2026, 6, 1), due_date=D(2026, 6, 28),
                        progress_percent=40)
    body = Client().get(f"{BASE}/plan-fact/roadmap/{roadmap.id}?date=2026-06-14",
                        **auth(admin_token())).json()
    assert body["children"][0]["fact_pct"] == 40.0


# ── SPI и флаги ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_spi_below_the_threshold_raises_the_right_flag(roadmap, valy):
    """План на середине срока — 50%; сделано 25% → SPI 0.5, critical."""
    task = _task(roadmap, valy, planned=200)
    _report(task, valy, D(2026, 6, 2), 50)

    node = Client().get(
        f"{BASE}/plan-fact/roadmap/{roadmap.id}?date=2026-06-14",
        **auth(admin_token())).json()["children"][0]
    assert node["plan_pct"] == 50.0
    assert node["fact_pct"] == 25.0
    assert node["spi"] == 0.5
    assert "critical" in node["flags"]


@pytest.mark.django_db
def test_being_ahead_is_flagged_too(roadmap, valy):
    """Опережение обычно значит, что ресурсы ушли сюда с критического
    фронта, а не что здесь молодцы."""
    task = _task(roadmap, valy, planned=100)
    _report(task, valy, D(2026, 6, 2), 90)

    node = Client().get(
        f"{BASE}/plan-fact/roadmap/{roadmap.id}?date=2026-06-14",
        **auth(admin_token())).json()["children"][0]
    assert "ahead" in node["flags"]


@pytest.mark.django_db
def test_spi_is_none_without_a_plan(project, block, valy):
    """Пакет без плановых дат: сравнивать не с чем, и это не ноль."""
    bare = Roadmap.objects.create(project=project, site_block=block,
                                  name="Без плана")
    task = _task(bare, valy, planned=100, start=None, due=None)
    _report(task, valy, D(2026, 6, 2), 50)

    node = Client().get(f"{BASE}/plan-fact/roadmap/{bare.id}?date=2026-06-14",
                        **auth(admin_token())).json()["children"][0]
    assert node["plan_pct"] is None
    assert node["spi"] is None
    assert node["lag_days"] is None


# ── требуемый темп ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_required_rate_ratio_flags_an_unrealistic_plan(roadmap, valy):
    """Ползём по 1 в день, а надо ~12.6 — плана не видать без людей.

    Отчёты за все 14 дней окна: темп = 14/14 = 1/день. Остаток 186 за 14
    дней до 28 июня = 13.3/день, отношение ≈ 13.3 — сильно выше порога.
    """
    task = _task(roadmap, valy, planned=200)
    for offset in range(14):
        _report(task, valy, D(2026, 6, 1) + dt.timedelta(days=offset), 1)

    node = Client().get(
        f"{BASE}/plan-fact/roadmap/{roadmap.id}?date=2026-06-14",
        **auth(admin_token())).json()["children"][0]
    assert node["rate_per_day"] == 1.0
    assert node["required_rate_ratio"] >= plan_fact_service.REQUIRED_RATE_ALARM
    assert "unrealistic" in node["flags"]


@pytest.mark.django_db
def test_required_rate_is_none_after_the_deadline(roadmap, valy):
    """Срок прошёл — «во сколько раз ускориться» не имеет ответа."""
    task = _task(roadmap, valy, planned=200)
    _report(task, valy, D(2026, 7, 1), 20)

    node = Client().get(
        f"{BASE}/plan-fact/roadmap/{roadmap.id}?date=2026-07-01",
        **auth(admin_token())).json()["children"][0]
    assert node["required_rate_ratio"] is None


# ── свёртка вверх ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_roadmap_percent_is_weighted_by_planned_duration(roadmap, valy):
    """Двухдневная задача не должна весить столько же, сколько месячная."""
    short = _task(roadmap, valy, key="TASK-S", planned=10,
                  start=D(2026, 6, 1), due=D(2026, 6, 2))
    long = _task(roadmap, valy, key="TASK-L", planned=100,
                 start=D(2026, 6, 1), due=D(2026, 6, 21))
    _report(short, valy, D(2026, 6, 1), 10)      # 100 %
    _report(long, valy, D(2026, 6, 1), 0)        # 0 %

    body = Client().get(f"{BASE}/plan-fact/roadmap/{roadmap.id}?date=2026-06-14",
                        **auth(admin_token())).json()
    assert body["weighting"] == "duration"
    # Веса 2 и 21 дня: (100*2 + 0*21) / 23 ≈ 8.7, а не 50.
    assert 8.0 <= body["fact_pct"] <= 9.5


@pytest.mark.django_db
def test_node_forecast_is_the_worst_of_its_children(roadmap, valy):
    """Узел закончен, когда закончилась ПОСЛЕДНЯЯ его работа."""
    fast = _task(roadmap, valy, key="TASK-F", planned=10)
    slow = _task(roadmap, valy, key="TASK-S", planned=1000)
    _report(fast, valy, D(2026, 6, 1), 9)
    _report(slow, valy, D(2026, 6, 1), 10)

    body = Client().get(f"{BASE}/plan-fact/roadmap/{roadmap.id}?date=2026-06-02",
                        **auth(admin_token())).json()
    child_forecasts = [c["forecast_end"] for c in body["children"]
                       if c["forecast_end"]]
    assert body["forecast_end"] == max(child_forecasts)


@pytest.mark.django_db
def test_project_tree_has_all_four_levels(project, roadmap, valy, block):
    _task(roadmap, valy)
    body = Client().get(f"{BASE}/plan-fact/project/{project.id}?date=2026-06-14",
                        **auth(admin_token())).json()

    assert body["kind"] == "project"
    site_node = body["children"][0]
    assert site_node["kind"] == "site"
    block_node = site_node["children"][0]
    assert (block_node["kind"], block_node["name"]) == ("block", "Блок 1")
    roadmap_node = block_node["children"][0]
    assert roadmap_node["kind"] == "roadmap"
    # Задачи в проектное дерево не разворачиваются — их сотни.
    assert roadmap_node["children"] == []
    assert roadmap_node["task_count"] == 1


# ── отставание в днях и процентах ───────────────────────────────────────

@pytest.mark.django_db
def test_lag_is_reported_in_days_and_percent_of_the_plan(project, block, valy):
    """Пример из SPEC §10: старт 03.04.26, план-финиш 04.07.27 (~458 дн.),
    прогноз около 02.08.27 → отставание ~29 дней ≈ 6,3 % плана."""
    project.start_date, project.end_date = D(2026, 4, 3), D(2027, 7, 4)
    project.save(update_fields=["start_date", "end_date"])
    roadmap = Roadmap.objects.create(
        project=project, site_block=block, name="Развозка",
        planned_start_date=D(2026, 4, 3), planned_end_date=D(2027, 7, 4))
    # Темп ровно 1 в день (14 отчётов в 14-дневном окне). Объём подобран
    # так, чтобы остаток 457 лёг ровно на 02.08.27 от отчётной даты.
    task = _task(roadmap, valy, planned=487,
                 start=D(2026, 4, 3), due=D(2027, 7, 4))
    for offset in range(30):
        _report(task, valy, D(2026, 4, 3) + dt.timedelta(days=offset), 1)

    node = Client().get(
        f"{BASE}/plan-fact/roadmap/{roadmap.id}?date=2026-05-02",
        **auth(admin_token())).json()["children"][0]
    assert node["forecast_end"] == "2027-08-02"
    assert node["lag_days"] == 29
    # 29 дней от 458-дневного плана.
    assert 6.0 <= node["lag_pct"] <= 6.5


# ── S-кривая ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_s_curve_accumulates_fact_by_work_date(roadmap, valy):
    task = _task(roadmap, valy, planned=100)
    _report(task, valy, D(2026, 6, 2), 10)
    _report(task, valy, D(2026, 6, 4), 15)

    series = Client().get(
        f"{BASE}/plan-fact/roadmap/{roadmap.id}?date=2026-06-10",
        **auth(admin_token())).json()["series"]
    by_date = {row["date"]: row for row in series}
    assert by_date["2026-06-02"]["fact_cum"] == 10.0
    assert by_date["2026-06-04"]["fact_cum"] == 25.0     # накопительно


@pytest.mark.django_db
def test_s_curve_stops_the_fact_line_after_the_data_date(roadmap, valy):
    """После отчётной даты факта физически нет: обрыв честнее продолжения
    линии по горизонтали."""
    task = _task(roadmap, valy, planned=100)
    _report(task, valy, D(2026, 6, 2), 10)

    series = Client().get(
        f"{BASE}/plan-fact/roadmap/{roadmap.id}?date=2026-06-10",
        **auth(admin_token())).json()["series"]
    future = [row for row in series if row["date"] > "2026-06-10"]
    assert future and all(row["fact_cum"] is None for row in future)
    # А плановая линия продолжается — она известна до конца.
    assert all(row["plan_cum"] is not None for row in future)


@pytest.mark.django_db
def test_s_curve_has_no_plan_line_without_volumes(project, block):
    """Рисовать проценты против штук на одной оси нельзя."""
    bare = Roadmap.objects.create(project=project, site_block=block,
                                  name="Без объёмов",
                                  planned_start_date=D(2026, 6, 1),
                                  planned_end_date=D(2026, 6, 30))
    Task.objects.create(key="TASK-1", summary="A", roadmap=bare,
                        start_date=D(2026, 6, 1), due_date=D(2026, 6, 30))
    series = Client().get(f"{BASE}/plan-fact/roadmap/{bare.id}?date=2026-06-10",
                          **auth(admin_token())).json()["series"]
    assert all(row["plan_cum"] is None for row in series)


# ── режим рабочих дней ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_plan_percent_follows_the_project_calendar_mode(project, roadmap, valy):
    """Флаг проекта доходит до расчёта планового процента.

    Сравниваются два режима между собой, а не с магическим числом: на
    отрезке ровно в 4 недели обе меры дают одинаковые 50 %, и такой тест
    прошёл бы, даже если бы флаг вообще игнорировался.
    """
    _task(roadmap, valy, planned=100, start=D(2026, 6, 1), due=D(2026, 6, 28))
    url = f"{BASE}/plan-fact/roadmap/{roadmap.id}?date=2026-06-16"
    hdr = auth(admin_token())

    calendar_mode = Client().get(url, **hdr).json()["children"][0]["plan_pct"]
    project.use_production_calendar = True
    project.save(update_fields=["use_production_calendar"])
    working_mode = Client().get(url, **hdr).json()["children"][0]["plan_pct"]

    assert calendar_mode is not None and working_mode is not None
    assert calendar_mode != working_mode


@pytest.mark.django_db
def test_plan_fact_requires_authentication(roadmap):
    assert Client().get(f"{BASE}/plan-fact/roadmap/{roadmap.id}").status_code == 401

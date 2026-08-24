"""Команда наполнения домена задач.

Наполнение — такой же код, как остальной. Если оно молча перестанет
связывать проект с объектом, посадит работника одного партнёра на задачу
другого или повесит роудмап на блок чужой площадки, локальная база начнёт
врать, а по ней потом смотрят глазами и делают выводы об отчётах.

Отдельно проверяются инварианты, которые легко нарушить именно данными, а не
кодом:

* объект задачи входит в объекты её проекта — то самое правило, которое на
  запись стережёт ``site_service.resolve_task_site`` (400 при нарушении);
* площадка блока роудмапа входит в объекты его проекта —
  ``roadmap_service.require_project_block``;
* задача с роудмапом повторяет его проект, площадку и блок — тройку держит
  ``roadmap_service.resolve_task_roadmap``;
* отчёт отчитывается по виду работ, который у задачи запланирован;
* ``ownership='contractor'`` требует организации, иначе падает CHECK
  ``ck_equipment_contractor_owner``.

И сверх того — то, ради чего демо-данные вообще нужны в этом виде: план/факт
на них обязан показывать РАЗНЫЕ ситуации. Роудмап, у которого всё зелёное,
дашборд не проверяет.
"""
from __future__ import annotations

import datetime as dt

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from apps.hr.models import Department, Employee, Position
from apps.tasks.models import (
    Contractor,
    ContractorEngagement,
    ContractorWorker,
    DailyReport,
    DailyReportRevision,
    Equipment,
    EquipmentCategory,
    EquipmentOwnership,
    Project,
    ProjectSite,
    ProjectStaffReport,
    ResourceKind,
    ResourceRequirement,
    Roadmap,
    Site,
    SiteBlock,
    SiteBlockVolume,
    Status,
    Task,
    TaskType,
    TaskVolume,
    WorkRole,
    WorkVolumeType,
)
from apps.tasks.services import plan_fact_service


@pytest.fixture
def hr_data(db):
    """Отделы и сотрудники, которых ждёт команда.

    Полный ``seed_hr_demo`` здесь не гоняем: команде задач нужны только
    отделы по путям и сотрудники с ``user_id`` — минимальный набор быстрее
    и точнее показывает, что именно она из hr читает.
    """
    departments = {}
    for path, name in (("stroy", "Строительство"),
                       ("stroy.elektro", "Электромонтаж"),
                       ("proekt", "Проектирование"),
                       ("snab", "Снабжение")):
        departments[path] = Department.objects.create(name=name, path=path)

    position = Position.objects.create(
        title="Инженер", department=departments["stroy"], weight=1000)
    for i in range(4):
        Employee.objects.create(
            first_name=f"Имя{i}", last_name=f"Фамилия{i}",
            email=f"seed{i}@htq.test", department=departments["stroy"],
            position=position, hire_date="2024-01-09", user_id=100 + i,
        )
    return departments


def _seed(**kwargs):
    call_command("seed_tasks_demo", verbosity=0, **kwargs)


# ── наполнение ─────────────────────────────────────────────────────────────

def test_seed_creates_the_whole_chain(hr_data):
    _seed()
    assert Site.objects.count() == 4
    assert SiteBlock.objects.count() == 7
    assert SiteBlockVolume.objects.count() == 10
    assert Project.objects.count() == 4
    assert Roadmap.objects.count() == 8
    assert Contractor.objects.count() == 4
    assert ContractorWorker.objects.count() == 11
    assert ContractorEngagement.objects.count() == 5
    assert Equipment.objects.count() == 9
    assert Task.objects.count() == 25


def test_seed_fills_the_reference_tables_it_depends_on(hr_data):
    """Виды работ, роли и типы техники — не украшение: без них не построить
    ни плановый объём, ни потребность «нужно 2 кары»."""
    _seed()
    assert WorkVolumeType.objects.count() == 7
    assert WorkRole.objects.count() == 7
    assert EquipmentCategory.objects.count() == 8
    # Слаг обязателен и уникален — на нём стоит справочный API.
    slugs = list(WorkVolumeType.objects.values_list("slug", flat=True))
    assert all(slugs) and len(set(slugs)) == len(slugs)


def test_seed_is_idempotent(hr_data):
    """Второй запуск правит на месте, а не плодит копии.

    У задач ключ выдаёт общий счётчик, поэтому сравнивать записи не с чем —
    команда опознаёт их по ``summary``, а отчёты по тройке (задача, дата,
    вид работ). Если эта ветка сломается, повторный прогон удвоит доску.
    """
    def snapshot():
        return tuple(model.objects.count() for model in (
            Site, SiteBlock, SiteBlockVolume, Project, Roadmap, Contractor,
            ContractorWorker, ContractorEngagement, Equipment, Task,
            TaskVolume, DailyReport, DailyReportRevision,
            ResourceRequirement, WorkVolumeType, WorkRole, EquipmentCategory,
        ))

    _seed()
    counts = snapshot()
    _seed()
    assert snapshot() == counts


def test_seed_requires_departments(db):
    """Без отделов наполнять нечего — команда обязана сказать это словами,
    а не упасть на None в FK."""
    with pytest.raises(CommandError, match="нет отделов"):
        _seed()


# ── связки, ради которых всё это существует ────────────────────────────────

def test_every_project_has_sites_and_exactly_one_primary(hr_data):
    _seed()
    for project in Project.objects.all():
        links = list(ProjectSite.objects.filter(project=project))
        assert links, f"у проекта «{project.name}» нет объектов"
        primary = [link for link in links if link.is_primary]
        assert len(primary) == 1, (
            f"у проекта «{project.name}» основных объектов: {len(primary)}"
        )


def test_task_site_always_belongs_to_its_project(hr_data):
    """Главный инвариант оси планирования.

    На запись его стережёт ``site_service.resolve_task_site`` (объект не из
    проекта = 400). Наполнение обязано подчиняться тому же правилу, иначе в
    базе появятся строки, которые через API создать было бы нельзя.
    """
    _seed()
    for task in Task.objects.exclude(project=None).exclude(site=None):
        allowed = set(
            ProjectSite.objects.filter(project=task.project)
            .values_list("site_id", flat=True)
        )
        assert task.site_id in allowed, (
            f"задача «{task.summary}»: объект вне объектов своего проекта"
        )


def test_roadmap_block_belongs_to_a_site_of_its_project(hr_data):
    """То же правило уровнем выше: ``require_project_block``.

    Роудмап на блоке чужой площадки — это пакет работ, которого на объекте
    нет; свёртка проекта посчитала бы его как свой.
    """
    _seed()
    for roadmap in Roadmap.objects.select_related("site_block"):
        allowed = set(
            ProjectSite.objects.filter(project_id=roadmap.project_id)
            .values_list("site_id", flat=True)
        )
        assert roadmap.site_block.site_id in allowed, (
            f"роудмап «{roadmap.name}»: блок вне объектов своего проекта"
        )


def test_task_with_a_roadmap_repeats_its_project_site_and_block(hr_data):
    """Денормализованная тройка обязана совпадать с роудмапом.

    На запись её держит ``roadmap_service.resolve_task_roadmap``. Разъедься
    она — фильтр по площадке и свёртка по блоку начнут отвечать разное про
    одну задачу.
    """
    _seed()
    tasks = Task.objects.exclude(roadmap=None).select_related(
        "roadmap", "roadmap__site_block")
    assert tasks.count() >= 10, "роудмап-задач в демо стало подозрительно мало"
    for task in tasks:
        assert task.project_id == task.roadmap.project_id, task.summary
        assert task.site_block_id == task.roadmap.site_block_id, task.summary
        assert task.site_id == task.roadmap.site_block.site_id, task.summary


def test_task_block_belongs_to_the_task_site(hr_data):
    """``site_service.resolve_task_block``: блок задачи — блок её площадки."""
    _seed()
    for task in Task.objects.exclude(site_block=None).select_related(
            "site_block"):
        assert task.site_id == task.site_block.site_id, task.summary


def test_contractor_worker_always_belongs_to_the_named_contractor(hr_data):
    """Работник и организация на задаче должны быть одной парой — иначе
    отчёт «по партнёру» посчитает человека не тому."""
    _seed()
    mismatched = [
        task.summary
        for task in Task.objects.exclude(contractor_worker=None)
        .select_related("contractor", "contractor_worker")
        if task.contractor_id != task.contractor_worker.contractor_id
    ]
    assert mismatched == []


def test_some_tasks_inherit_their_contractor_from_the_site(hr_data):
    """Наследование партнёра проверяемо только на задачах, которые его не
    называют.

    Нужен не «хоть кто-то без партнёра» — таких хватает и в офисной
    части, — а именно задача пакета работ, у площадки которой есть активное
    привлечение: только на ней ``effective_contractors`` вернёт не то же
    самое, что ``task.contractor``.
    """
    _seed()
    sites_with_engagement = set(
        ContractorEngagement.objects.filter(is_active=True)
        .exclude(site=None).values_list("site_id", flat=True))
    inheriting = Task.objects.filter(
        contractor=None, site_id__in=sites_with_engagement).exclude(
        roadmap=None)
    assert inheriting.count() >= 2, (
        "в демо не осталось задач, на которых видно наследование партнёра")


def test_contractor_equipment_always_names_its_owner(hr_data):
    """CHECK ck_equipment_contractor_owner: организация обязательна ровно
    для ownership='contractor' — и не должна стоять у собственной."""
    _seed()
    for item in Equipment.objects.all():
        if item.ownership == EquipmentOwnership.CONTRACTOR:
            assert item.contractor_id is not None, item.name
        else:
            assert item.contractor_id is None, item.name


def test_projects_point_at_real_departments(hr_data):
    _seed()
    known = set(Department.objects.values_list("id", flat=True))
    for project in Project.objects.all():
        assert project.department_id in known, project.name


def test_tasks_are_assigned_to_real_accounts(hr_data):
    """Исполнитель — это user_id платформенной учётки, а не PK Employee.
    Здесь их выдаёт фикстура; в жизни — manage.py seed_employee_accounts."""
    _seed()
    known = set(Employee.objects.values_list("user_id", flat=True))
    assigned = Task.objects.exclude(assignee_id=None)
    assert assigned.count() == Task.objects.count()
    for task in assigned:
        assert task.assignee_id in known, task.summary


def test_seed_covers_every_status_and_leaves_tasks_outside_projects(hr_data):
    """Доска и отчёты должны быть проверяемы глазами: пустая колонка или
    отсутствующая корзина «Без проекта» делают их бесполезными."""
    _seed()
    statuses = set(Task.objects.values_list("status", flat=True))
    assert statuses == set(Status.values)
    assert Task.objects.filter(project=None).count() == 2


def test_every_task_has_a_type(hr_data):
    """Отчёт «по типу» на задачах без типа рисует один столбец `unknown`.

    Использованы только два из пяти системных типов, и это осознанно: «баг»
    и «эпик» в стройке значат не то же, что в трекере, и раскладывать по ним
    работы ради красивой диаграммы значило бы выдумать данные.
    """
    _seed()
    assert not Task.objects.filter(task_type=None).exists()
    assert set(Task.objects.values_list("task_type__slug", flat=True)) == {
        "task", "story",
    }


def test_engagements_may_have_no_project(hr_data):
    """Партнёр на объекте вне проекта — реальный случай, ради которого
    оба поля привлечения nullable."""
    _seed()
    assert ContractorEngagement.objects.filter(
        project=None).exclude(site=None).exists()


def test_contractor_levels_are_all_represented(hr_data):
    """Уровень — свойство человека, и в демо должны быть все три, иначе
    матрицу прав партнёров не на чем показать."""
    _seed()
    assert set(ContractorWorker.objects.values_list("level", flat=True)) == {
        "junior", "middle", "senior",
    }


# ── ресурсы ────────────────────────────────────────────────────────────────

def test_requirements_keep_their_kind_fields_clean(hr_data):
    """Потребность в людях с проставленной категорией техники — мусор,
    который потом кто-то посчитает. CHECK ck_requirement_kind_fields это
    запрещает; тест ловит попытку до того, как она дойдёт до БД чужой
    ветки."""
    _seed()
    assert ResourceRequirement.objects.exists()
    for row in ResourceRequirement.objects.all():
        if row.kind == ResourceKind.HUMAN:
            assert row.equipment_category_id is None
        else:
            assert row.work_role_id is None


def test_the_whiteboard_plan_is_on_the_roadmap(hr_data):
    """План с доски: развозка валов — 4 недели, 2 человека, 2 кары.

    Это исходная постановка задачи модуля, и она должна быть в демо
    дословно, иначе экран плана нечем проверить.
    """
    _seed()
    roadmap = Roadmap.objects.get(name="Развозка валов трекерных конструкций",
                                  site_block__name="Блок I")
    assert roadmap.planned_working_days == 28
    people = roadmap.requirements.get(kind=ResourceKind.HUMAN)
    machines = roadmap.requirements.get(kind=ResourceKind.EQUIPMENT)
    assert people.quantity == 2
    assert machines.quantity == 2
    assert machines.equipment_category.name == "Кара (вилопогрузчик)"


def test_task_volumes_of_a_roadmap_add_up_to_the_block_plan(hr_data):
    """250 валов на блоке разложены по задачам ровно, без остатка.

    Не арифметическая придирка: свёртка блока считает процент от планового
    объёма блока, и если сумма задач ему не равна, «100 % задач» и «100 %
    блока» перестанут быть одним и тем же событием.
    """
    _seed()
    block = SiteBlock.objects.get(name="Блок I", site__name="Сазаган")
    volume_type = WorkVolumeType.objects.get(
        name="Валы трекерных конструкций")
    planned = SiteBlockVolume.objects.get(
        block=block, volume_type=volume_type).planned_quantity
    from_tasks = sum(
        row.planned_quantity for row in TaskVolume.objects.filter(
            task__site_block=block, volume_type=volume_type,
            task__roadmap__name="Развозка валов трекерных конструкций")
    )
    assert from_tasks == planned == 250


# ── ежедневные отчёты ──────────────────────────────────────────────────────

def test_reports_only_name_work_types_the_task_actually_plans(hr_data):
    """«Сделано 40» по виду, которого у задачи нет, не к чему отнести:
    факт не сойдётся ни с одним плановым объёмом."""
    _seed()
    assert DailyReport.objects.count() == 31
    for report in DailyReport.objects.select_related("task"):
        planned = set(TaskVolume.objects.filter(task_id=report.task_id)
                      .values_list("volume_type_id", flat=True))
        assert report.volume_type_id in planned, (
            f"отчёт по задаче «{report.task.summary}» ссылается на вид работ "
            f"вне её планового объёма"
        )


def test_work_date_is_not_the_date_the_report_was_typed_in(hr_data):
    """Ключевое различие всего модуля: отчёт за пятницу заполняют в
    понедельник, и S-кривая обязана положить его на пятницу."""
    _seed()
    today = dt.date.today()
    assert DailyReport.objects.filter(work_date__lt=today).count() > 20
    assert not DailyReport.objects.filter(work_date__gt=today).exists()


def test_every_report_starts_with_revision_one(hr_data):
    """История версий должна начинаться с исходного состояния, иначе «что
    было до правки» для первого значения восстанавливать неоткуда."""
    _seed()
    for report in DailyReport.objects.all():
        assert report.revisions.filter(revision_no=1).exists(), report.id
        assert report.revisions.count() == report.current_revision


def test_demo_contains_a_corrected_report(hr_data):
    """Ровно одна правка — ради ленты версий: на данных без единой правки
    экран истории пустой и проверить его нечем."""
    _seed()
    corrected = DailyReport.objects.filter(current_revision__gt=1)
    assert corrected.count() == 1
    report = corrected.get()
    versions = list(DailyReportRevision.objects.filter(report=report))
    assert [v.revision_no for v in versions] == [1, 2]
    assert versions[0].quantity != versions[1].quantity


# ── отчёты по персоналу ────────────────────────────────────────────────────

def test_staff_reports_are_unique_per_block_and_day(hr_data):
    """У численности, в отличие от выработки, UNIQUE(проект, блок, дата)
    ЕСТЬ: два отчёта за один день на одном блоке — это двойной счёт людей,
    а не две смены. Сид обязан этому соответствовать."""
    _seed()
    pairs = list(ProjectStaffReport.objects.filter(is_deleted=False)
                 .values_list("project_id", "site_block_id", "work_date"))
    assert len(pairs) == len(set(pairs))
    assert len(pairs) == 18


def test_staff_reports_land_on_blocks_that_have_a_plan(hr_data):
    """Иначе доске нечего сравнивать: строка без плана показывает прочерк,
    и демо не отвечает на вопрос, ради которого заведено."""
    _seed()
    planned_blocks = set(
        ResourceRequirement.objects
        .filter(kind=ResourceKind.HUMAN, roadmap__isnull=False)
        .values_list("roadmap__site_block_id", flat=True))
    reported = set(ProjectStaffReport.objects.filter(is_deleted=False)
                   .values_list("site_block_id", flat=True))
    assert reported and reported <= planned_blocks


def test_staff_report_dates_are_never_in_the_future(hr_data):
    """Дата ВЫХОДА людей: отчитаться за завтра нельзя."""
    _seed()
    today = dt.date.today()
    assert not ProjectStaffReport.objects.filter(
        work_date__gt=today).exists()
    assert ProjectStaffReport.objects.filter(work_date=today).exists()


def test_every_staff_report_starts_with_revision_one(hr_data):
    _seed()
    for report in ProjectStaffReport.objects.all():
        assert report.revisions.filter(revision_no=1).exists(), report.id
        assert report.revisions.count() == report.current_revision


def test_demo_contains_a_corrected_staff_report(hr_data):
    """Ровно одна правка — ради ленты версий, та же причина, что у
    ежедневки. Снимок обязан отличаться СОСТАВОМ, иначе сервис (справедливо)
    второй версии не создаст."""
    _seed()
    corrected = ProjectStaffReport.objects.filter(current_revision__gt=1)
    assert corrected.count() == 1
    versions = list(corrected.get().revisions.all())
    assert [v.revision_no for v in versions] == [1, 2]
    assert versions[0].total_headcount != versions[1].total_headcount
    # Имя роли лежит в снимке: версия читается и без справочника.
    assert all("work_role_name" in line for line in versions[0].lines)


def test_a_stopped_site_has_no_recent_staffing(hr_data):
    """Кандыагаш «встал»: план на сегодня есть, людей нет. Ради этой строки
    на доске и видно отставание, а не ровные нули везде."""
    _seed()
    today = dt.date.today()
    stopped = SiteBlock.objects.get(name="Участок 12–19")
    assert not ProjectStaffReport.objects.filter(
        site_block=stopped, work_date=today).exists()
    latest = (ProjectStaffReport.objects.filter(site_block=stopped)
              .order_by("-work_date").first())
    assert latest is not None
    assert (today - latest.work_date).days > 14


def test_seeding_twice_adds_no_staff_reports(hr_data):
    """Проба на существование в сиде проверяет инвариант модели: без неё
    повторный прогон упёрся бы в UNIQUE, а не тихо создал дубль."""
    _seed()
    before = ProjectStaffReport.objects.count()
    _seed()
    assert ProjectStaffReport.objects.count() == before


# ── то, ради чего цифры подобраны именно так ───────────────────────────────

def test_plan_fact_shows_a_package_that_is_behind(hr_data):
    """Развозка валов идёт ниже критического порога SPI и не успевает.

    Демо, где всё зелёное, не проверяет ни порогов, ни прогноза: критический
    флаг и положительное отставание должны быть видны без правки данных.
    """
    _seed()
    roadmap = Roadmap.objects.select_related("project").get(
        name="Развозка валов трекерных конструкций",
        site_block__name="Блок I")
    node = plan_fact_service.roadmap_plan_fact(roadmap, dt.date.today())

    # 68.1, а не 200/250 = 80 %: процент пакета — это взвешенное среднее
    # процентов задач с весом по плановой длительности, а не отношение сумм.
    # Незакрытая порция идёт 10 дней против 4 у закрытых и тянет вниз
    # сильнее, чем её доля в валах, — так и задумано.
    assert node["fact_pct"] == pytest.approx(68.1, abs=0.5)
    assert node["spi"] < 0.90
    assert "critical" in node["flags"]
    assert node["lag_days"] > 0
    assert node["forecast_end"] > roadmap.planned_end_date
    assert node["series"], "S-кривой не на чем строиться"


def test_plan_fact_shows_a_package_that_has_stalled(hr_data):
    """Замена опор: последний отчёт полтора месяца назад.

    Нулевой темп при непустом остатке — это «стоим», и прогноз обязан быть
    ``None``, а не выдуманной датой. Отдельный случай, который на бодрых
    данных не воспроизводится.
    """
    _seed()
    roadmap = Roadmap.objects.select_related("project").get(
        name="Замена опор на участке 12–19")
    node = plan_fact_service.roadmap_plan_fact(roadmap, dt.date.today())

    assert node["fact_pct"] == pytest.approx(26.5, abs=0.5)
    assert node["forecast_end"] is None
    assert "critical" in node["flags"]


def test_plan_fact_shows_a_package_that_is_ahead(hr_data):
    """И обратный случай — иначе «ahead» на экране никогда не покажется."""
    _seed()
    roadmap = Roadmap.objects.select_related("project").get(
        name="Монтаж металлоконструкций ОРУ")
    node = plan_fact_service.roadmap_plan_fact(roadmap, dt.date.today())

    assert node["spi"] > 1.05
    assert "ahead" in node["flags"]


def test_a_package_that_has_not_started_reports_none_not_zero(hr_data):
    """Правило «не врать нулём»: до старта сравнивать не с чем, и SPI —
    ``None``. Ноль означал бы «посчитали и вышло ноль»."""
    _seed()
    roadmap = Roadmap.objects.select_related("project").get(
        name="Монтаж трекерных конструкций")
    node = plan_fact_service.roadmap_plan_fact(roadmap, dt.date.today())

    assert node["plan_pct"] == 0.0
    assert node["spi"] is None


def test_both_calendar_modes_are_present(hr_data):
    """Флаг производственного календаря должен стоять и так и так: с одним
    значением на всю базу вторая ветка расчёта никогда не исполняется."""
    _seed()
    modes = set(Project.objects.values_list("use_production_calendar",
                                            flat=True))
    assert modes == {True, False}


# ── очистка «своего» ───────────────────────────────────────────────────────

def test_purge_removes_everything_it_seeded(hr_data):
    _seed()
    _seed(purge_only=True)
    assert Site.objects.count() == 0
    assert SiteBlock.objects.count() == 0
    assert Project.objects.count() == 0
    assert Roadmap.objects.count() == 0
    assert Contractor.objects.count() == 0
    assert ContractorWorker.objects.count() == 0
    assert ContractorEngagement.objects.count() == 0
    assert Equipment.objects.count() == 0
    assert Task.objects.count() == 0
    # Отчёты и объёмы уходят каскадом от задач, а не отдельным проходом.
    assert DailyReport.objects.count() == 0
    assert TaskVolume.objects.count() == 0
    # А вот отчёты по персоналу — проходом: они держат блок через PROTECT,
    # и дожидаться каскада от проекта нельзя, тот сносится позже блока.
    assert ProjectStaffReport.objects.count() == 0


def test_purge_keeps_foreign_rows(hr_data):
    """Очистка бьёт по своим именам, а не по таблице целиком: чужие объекты
    и задачи переживают её."""
    _seed()
    outsider_site = Site.objects.create(name="Чужой объект")
    outsider_task = Task.objects.create(key="OTHER-1", summary="Чужая задача")

    _seed(purge_only=True)

    assert Site.objects.filter(id=outsider_site.id).exists()
    assert Task.objects.filter(id=outsider_task.id).exists()


def test_purge_keeps_the_reference_tables(hr_data):
    """Справочники — общие: снести виды работ вместе с демо значило бы
    сломать чужие объёмы, которые на них ссылаются (PROTECT)."""
    _seed()
    _seed(purge_only=True)
    assert WorkVolumeType.objects.count() == 7
    assert WorkRole.objects.count() == 7


def test_purge_then_seed_restores_the_same_shape(hr_data):
    _seed()
    _seed(purge=True)
    assert Site.objects.count() == 4
    assert Roadmap.objects.count() == 8
    assert Task.objects.count() == 25


# ── полная очистка домена ──────────────────────────────────────────────────

def test_wipe_empties_every_table_of_the_app(hr_data):
    """``--wipe`` — это «начать домен заново», и он обязан не оставить
    ничего: ни справочников, ни чужих строк."""
    _seed()
    Site.objects.create(name="Чужой объект")
    Task.objects.create(key="OTHER-1", summary="Чужая задача")

    _seed(wipe_only=True)

    for model in (Site, SiteBlock, SiteBlockVolume, Project, Roadmap, Task,
                  TaskVolume, DailyReport, DailyReportRevision, Contractor,
                  ContractorWorker, ContractorEngagement, Equipment,
                  EquipmentCategory, WorkRole, WorkVolumeType,
                  ResourceRequirement):
        assert model.objects.count() == 0, model.__name__


def test_wipe_restores_the_rows_a_migration_had_put_there(hr_data):
    """Пять системных типов задач ставит миграция 0002.

    TRUNCATE их сносит, а миграции повторно не пойдут — очистка обязана
    вернуть их сама, иначе домен остаётся в состоянии, которого никакая
    последовательность миграций не даёт: API их удалять запрещает, а фронт
    рисует по ним чипы.
    """
    _seed()
    _seed(wipe_only=True)
    assert TaskType.objects.filter(is_system=True).count() == 5
    assert TaskType.objects.filter(slug="task").exists()


def test_wipe_touches_nothing_outside_the_app(hr_data):
    """Соседние домены не должны заметить очистки задач — их данные не
    держатся ни на чём отсюда (кросс-доменных FK в проекте нет)."""
    _seed()
    _seed(wipe_only=True)
    assert Department.objects.count() == 4
    assert Employee.objects.count() == 4


def test_wipe_then_seed_restores_the_same_shape(hr_data):
    _seed()
    _seed(wipe=True)
    assert Site.objects.count() == 4
    assert Roadmap.objects.count() == 8
    assert Task.objects.count() == 25
    assert DailyReport.objects.count() == 31
    assert ProjectStaffReport.objects.count() == 18


def test_wipe_refuses_when_something_outside_references_the_domain(hr_data):
    """``TRUNCATE ... CASCADE`` вычистил бы и ссылающуюся таблицу.

    Кросс-доменных FK в проекте нет, поэтому в норме проверка молчит — она
    стоит ради того дня, когда чужая миграция такой ключ заведёт. Таблица
    создаётся прямо здесь и откатывается вместе с транзакцией теста.
    """
    _seed()
    with connection.cursor() as cursor:
        cursor.execute(
            "CREATE TABLE zz_outsider ("
            "  id serial PRIMARY KEY,"
            "  task_id integer REFERENCES tasks_task(id))"
        )

    with pytest.raises(CommandError, match="ссылаются извне"):
        _seed(wipe_only=True)

    assert Task.objects.count() == 25, "очистка не должна была начаться"


# ── защита от неместной БД ─────────────────────────────────────────────────
#
# Проверяется как чистое правило от строки хоста, а НЕ подменой
# settings.DATABASES: боевой адрес не должен оказываться в живых настройках
# даже на время теста — иначе тирдаун туда постучится.

def _guard(host: str, *, force: bool = False) -> None:
    from apps.tasks.management.commands.seed_tasks_demo import Command

    Command()._assert_local(force, host=host)


@pytest.mark.parametrize("host", ["45.10.110.212", "db.example.com", "10.8.0.4"])
def test_refuses_to_run_against_a_remote_database(host):
    with pytest.raises(CommandError, match="не похож на локальную"):
        _guard(host)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "db", "::1", ""])
def test_local_hosts_pass_the_guard(host):
    _guard(host)  # не бросает


def test_force_remote_is_the_only_way_past_the_guard():
    _guard("45.10.110.212", force=True)  # не бросает


def test_guard_runs_before_anything_is_written(hr_data, monkeypatch):
    """Отказ обязан случиться до первой записи, иначе «защита» оставит
    половину демо-данных на чужом хосте."""
    from apps.tasks.management.commands import seed_tasks_demo

    def refuse(self, force, host=None):
        raise CommandError("DB_HOST не похож на локальную БД")

    monkeypatch.setattr(seed_tasks_demo.Command, "_assert_local", refuse)

    with pytest.raises(CommandError, match="не похож на локальную"):
        _seed()
    assert Site.objects.count() == 0
    assert Task.objects.count() == 0

"""Переезд роудмапа с площадки на блок — бэкфилл миграции 0012.

Вторая миграция этой ветки, которая МОЖЕТ ПОТЕРЯТЬ ДАННЫЕ, и вторая, которую
обычные тесты не задевают: тестовая база создаётся пустой, так что
``RunPython`` отрабатывает на нуле строк и ничего не доказывает.

Тот же приём, что в ``test_equipment_category_migration``: откатываемся до
0011, пишем роудмапы в старую схему (с площадкой), накатываем 0012 и
проверяем, куда они легли. Про ``transaction=True`` и восстановление схемы в
``finally`` — см. докстринг того файла, причины ровно те же.
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = ("tasks", "0011_resource_allocation")
AFTER = ("tasks", "0012_roadmap_on_block")


def _migrate(target):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate([target])
    executor.loader.build_graph()
    return executor.loader.project_state([target]).apps


@pytest.fixture
def at_0011():
    try:
        yield _migrate(BEFORE)
    finally:
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(
            [key for key in executor.loader.graph.leaf_nodes() if key[0] == "tasks"]
        )


def _project_with_site(apps, *, site_name="Сазаган"):
    Project = apps.get_model("tasks", "Project")
    Site = apps.get_model("tasks", "Site")
    ProjectSite = apps.get_model("tasks", "ProjectSite")
    project = Project.objects.create(name=f"Проект {site_name}")
    site = Site.objects.create(name=site_name)
    ProjectSite.objects.create(project=project, site=site)
    return project, site


@pytest.mark.django_db(transaction=True)
def test_roadmap_lands_on_the_first_block_of_its_site(at_0011):
    Roadmap = at_0011.get_model("tasks", "Roadmap")
    SiteBlock = at_0011.get_model("tasks", "SiteBlock")
    project, site = _project_with_site(at_0011)
    # Порядок создания намеренно обратный порядку сортировки: миграция
    # обязана брать первый по ``order``, а не первый по id.
    SiteBlock.objects.create(site=site, name="Блок 2", order=2, status="planned")
    first = SiteBlock.objects.create(site=site, name="Блок 1", order=1,
                                     status="planned")
    Roadmap.objects.create(project=project, site=site, name="Развозка валов")

    apps = _migrate(AFTER)
    Roadmap = apps.get_model("tasks", "Roadmap")
    assert Roadmap.objects.get().site_block_id == first.id


@pytest.mark.django_db(transaction=True)
def test_roadmap_on_a_site_without_blocks_gets_one_invented(at_0011):
    """Придуманный «Блок 1» лучше упавшей миграции: имя очевидно временное,
    и его переименуют, а не будут гадать, куда делся пакет работ."""
    Roadmap = at_0011.get_model("tasks", "Roadmap")
    project, site = _project_with_site(at_0011)
    Roadmap.objects.create(project=project, site=site, name="Развозка валов")

    apps = _migrate(AFTER)
    Roadmap = apps.get_model("tasks", "Roadmap")
    SiteBlock = apps.get_model("tasks", "SiteBlock")
    block = SiteBlock.objects.get(site_id=site.id)
    assert block.name == "Блок 1"
    assert Roadmap.objects.get().site_block_id == block.id


@pytest.mark.django_db(transaction=True)
def test_several_roadmaps_on_one_bare_site_share_one_invented_block(at_0011):
    """Блок заводится ОДИН на площадку, а не по одному на роудмап."""
    Roadmap = at_0011.get_model("tasks", "Roadmap")
    project, site = _project_with_site(at_0011)
    Roadmap.objects.create(project=project, site=site, name="Развозка валов")
    Roadmap.objects.create(project=project, site=site, name="Забивка стоек")

    apps = _migrate(AFTER)
    SiteBlock = apps.get_model("tasks", "SiteBlock")
    Roadmap = apps.get_model("tasks", "Roadmap")
    assert SiteBlock.objects.filter(site_id=site.id).count() == 1
    assert len({r.site_block_id for r in Roadmap.objects.all()}) == 1


@pytest.mark.django_db(transaction=True)
def test_roadmaps_on_different_sites_stay_apart(at_0011):
    Roadmap = at_0011.get_model("tasks", "Roadmap")
    project_a, site_a = _project_with_site(at_0011, site_name="Сазаган")
    project_b, site_b = _project_with_site(at_0011, site_name="Алга")
    Roadmap.objects.create(project=project_a, site=site_a, name="Развозка")
    Roadmap.objects.create(project=project_b, site=site_b, name="Развозка")

    apps = _migrate(AFTER)
    Roadmap = apps.get_model("tasks", "Roadmap")
    SiteBlock = apps.get_model("tasks", "SiteBlock")
    landed = {r.site_block_id for r in Roadmap.objects.all()}
    assert len(landed) == 2
    assert {SiteBlock.objects.get(pk=b).site_id for b in landed} \
        == {site_a.id, site_b.id}

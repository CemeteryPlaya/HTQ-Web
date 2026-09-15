"""hr/0024: пороги N-1…N-4 появляются в НОВОЙ схеме компании и нигде больше.

Сид миграции — единственный способ дать новой компании уровни до того, как
кадровик откроет экран: без порогов каждая должность молча падает в
``_DEFAULT_LEVEL = 5`` и иерархия схлопывается в один ярус (roadmap §4).
Но ``public`` — это и pytest-база, и dev до tenancy_bootstrap, и боевая HTQ
до переноса: засеять туда значило бы подменить данные ETL и сломать тесты,
которые заводят уровень 1 с нуля.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as django_apps
from django.db import connection

from apps.hr.models import LevelThreshold

migration = importlib.import_module("apps.hr.migrations.0024_seed_level_thresholds")


def _search_path() -> str:
    with connection.cursor() as cur:
        cur.execute("SHOW search_path")
        return cur.fetchone()[0]


@pytest.mark.django_db
def test_public_is_never_seeded():
    assert "co_" not in _search_path()
    migration.seed(django_apps, None)
    assert LevelThreshold.objects.count() == 0


def test_company_schema_gets_the_four_document_levels(company_context):
    LevelThreshold.objects.all().delete()  # пул схем мог засеять при миграции
    migration.seed(django_apps, None)
    rows = list(LevelThreshold.objects.order_by("level_number")
                .values_list("level_number", "weight_from", "weight_to", "label"))
    assert rows == [(1, 0, 99, "N-1"), (2, 100, 299, "N-2"),
                    (3, 300, 599, "N-3"), (4, 600, 1999, "N-4")]


def test_existing_thresholds_are_left_alone(company_context):
    """HTQ с порогами от ETL — no-op: ни строки не добавлено, ни правлено."""
    LevelThreshold.objects.all().delete()
    LevelThreshold.objects.create(level_number=7, weight_from=0, weight_to=5000,
                                  label="из ETL")
    migration.seed(django_apps, None)
    assert list(LevelThreshold.objects.values_list("level_number", "label")) == [(7, "из ETL")]


def test_levels_do_not_overlap_and_cover_the_weight_axis():
    levels = sorted(migration.LEVELS)
    for (_, a_from, a_to, *_), (_, b_from, _b_to, *_) in zip(levels, levels[1:]):
        assert a_to + 1 == b_from
    assert levels[0][1] == 0
    assert levels[-1][2] >= 1999  # верх шкалы старого сида и next-weight

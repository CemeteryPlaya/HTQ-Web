"""Тесты бизнес-метрик реестра компаний (``apps.companies.metrics``).

Проверяют форму сборщика (соглашение apps/<domain>/metrics.py) и то, что
отставание схемы считается корректно: пустая target_migration — это
«прогона ещё не было», а не отставание.
"""

import pytest

from apps.companies import metrics
from apps.companies.models import (
    Company, CompanyKind, CompanySchemaVersion, CompanyStatus,
)


def _single(result: dict, name: str) -> float:
    """Значение метрики без меток. Форма values — [(кортеж_меток, число)]."""
    return result[name]["values"][0][1]


@pytest.mark.django_db
def test_active_companies_are_grouped_by_kind():
    Company.objects.create(slug="htq", name="Холдинг", kind=CompanyKind.HOLDING)
    Company.objects.create(slug="htq-kz", name="KZ", kind=CompanyKind.REGIONAL)
    Company.objects.create(slug="dead", name="Банкрот", kind=CompanyKind.SERVICE,
                           status=CompanyStatus.ARCHIVED)

    result = metrics.collect()
    by_kind = dict(result["companies_active_by_kind"]["values"])
    assert by_kind[("holding",)] == 1
    assert by_kind[("regional",)] == 1
    assert ("service",) not in by_kind  # архивная не считается действующей
    assert _single(result, "companies_archived") == 1


@pytest.mark.django_db
def test_metric_names_carry_no_prefix():
    """Префикс htqweb_ навешивает apps.core.metrics при экспорте.

    Вшитый здесь префикс дал бы htqweb_htqweb_* и метрику, которую не
    найдёт ни один дашборд.
    """
    assert all(not name.startswith("htqweb_") for name in metrics.collect())


@pytest.mark.django_db
def test_counts_schemas_behind_target():
    kz = Company.objects.create(slug="htq-kz", name="KZ", kind=CompanyKind.REGIONAL)
    CompanySchemaVersion.objects.create(
        company=kz, app_label="tasks",
        applied_migration="0039_x", target_migration="0042_y",
    )
    CompanySchemaVersion.objects.create(
        company=kz, app_label="hr",
        applied_migration="0012_z", target_migration="0012_z",
    )
    assert _single(metrics.collect(), "company_schemas_behind") == 1


@pytest.mark.django_db
def test_counts_schemas_with_error():
    kz = Company.objects.create(slug="htq-kz", name="KZ", kind=CompanyKind.REGIONAL)
    CompanySchemaVersion.objects.create(
        company=kz, app_label="tasks", last_error="relation does not exist",
    )
    assert _single(metrics.collect(), "company_schema_errors") == 1


@pytest.mark.django_db
def test_empty_registry_reports_zeros_not_nothing():
    """Здесь ноль — настоящий ноль, а не «сборщик умер»: строк в реестре
    просто нет, и это отличается от случая пустого кэша в apps.core.metrics.
    """
    result = metrics.collect()
    assert result["companies_active_by_kind"]["values"] == []
    assert _single(result, "companies_archived") == 0

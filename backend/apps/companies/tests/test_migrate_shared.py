"""migrate_shared: migrate только для нетенантных (общих) аппок.

Единственный сценарий, ради которого команда существует: после
tenancy_bootstrap django_migrations тенантных аппок нет в public, а их
таблиц там тоже уже нет (обе переехали в схему компании). Голый
`manage.py migrate` увидел бы это как "ни одной миграции не применено" и
СОЗДАЛ БЫ тенантные таблицы заново, уже пустыми, в public. Эта команда
обязана этого не делать — список общих аппок вычисляется из графа миграций
минус settings.TENANT_APPS, поэтому тенантные аппки в её план в принципе не
попадают.

Уборка — тот же общий помощник, что и в test_tenancy_bootstrap.py (см. его
докстринг и докстринг _tenancy_test_support.py про то, почему это НЕ голый
schema_service.drop_schema).
"""

import pytest
from django.core.management import call_command

from apps.companies.tests._tenancy_test_support import (
    public_tenant_leftovers,
    restore_public,
)

SLUG = "t-shared"


@pytest.fixture(autouse=True)
def cleanup():
    yield
    restore_public(SLUG)


@pytest.mark.django_db(transaction=True)
def test_does_not_recreate_tenant_tables_in_public():
    call_command("tenancy_bootstrap", slug=SLUG, name="Общие", kind="holding")

    # Предусловие: перенос действительно состоялся, иначе тест ничего не
    # доказывает (public и так пуст от тенантных таблиц с самого начала).
    assert public_tenant_leftovers() == set()

    call_command("migrate_shared")

    assert public_tenant_leftovers() == set(), (
        "migrate_shared пересоздал тенантные таблицы в public"
    )

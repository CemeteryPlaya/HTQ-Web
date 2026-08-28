"""Тесты общих фикстур компаний-схем из корневого conftest.py (задача 14).

Файл не тестирует ``apps.companies`` напрямую — он доказывает, что фикстуры
``company_schema``/``company_context``/``two_company_schemas`` действительно
дают то, что обещают: рабочий контекст компании и изоляцию данных между
схемами, обеспеченную СУБД, а не соглашением на уровне Python.
"""

import pytest

from htqweb.tenancy.context import current_company_or_none


@pytest.mark.django_db(transaction=True)
def test_company_context_fixture_sets_context(company_context):
    assert current_company_or_none() == company_context["slug"]


@pytest.mark.django_db(transaction=True)
def test_company_context_fixture_restores_previous_context_on_exit():
    """После выхода из фикстуры контекст обязан вернуться к тому, что было.

    Без явного восстановления вложенный ``use_company`` (или его отсутствие
    до входа) остался бы незаметно "протёкшим" в следующий шаг того же
    теста — здесь это проверяется напрямую, а не полагается на то, что
    autouse-фикстура ``reset_company_context`` в conftest сотрёт разницу
    между тестами.
    """
    from apps.companies.models import Company, CompanyKind
    from apps.companies.services import migration_service, schema_service
    from htqweb.tenancy.db import use_company

    assert current_company_or_none() is None

    slug = "t-fixture-nested-check"
    schema_service.drop_schema(slug)
    Company.objects.create(slug=slug, name=slug, kind=CompanyKind.SERVICE)
    schema_service.create_schema(slug)
    migration_service.migrate_company(slug)
    try:
        with use_company(slug):
            assert current_company_or_none() == slug
        assert current_company_or_none() is None
    finally:
        schema_service.drop_schema(slug)


@pytest.mark.django_db(transaction=True)
def test_company_schema_is_actually_migrated(company_schema):
    """Фикстура обещает "полностью мигрированную" схему — не просто CREATE SCHEMA.

    Тест создаёт строку тенантной модели без контекста компании (напрямую
    через use_company), проверяя, что таблица физически существует и
    доступна для записи — падение здесь означало бы, что миграции не
    применились, хотя фикстура вернула бы "успех".
    """
    from apps.hr.models import Department
    from htqweb.tenancy.db import use_company

    with use_company(company_schema["slug"]):
        dep = Department.objects.create(name="Отдел", path="root")
        assert Department.objects.filter(pk=dep.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_data_written_in_one_company_is_invisible_in_another(two_company_schemas):
    """Главный тест всей архитектуры: изоляция обеспечивается СУБД."""
    from apps.hr.models import Department
    from htqweb.tenancy.db import use_company

    alpha, beta = two_company_schemas

    with use_company(alpha):
        Department.objects.create(name="Отдел A", path="a")
        assert Department.objects.count() == 1

    with use_company(beta):
        assert Department.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_two_company_schemas_are_actually_different_schemas(two_company_schemas):
    """Изоляция не должна оказаться совпадением двух пустых выборок.

    Пишем в обе схемы РАЗНЫЕ данные и читаем из обеих — если бы фикстура
    молча подсунула одну и ту же схему под двумя именами, вторая проверка
    увидела бы строку первой компании вместо своей.
    """
    from apps.hr.models import Department
    from htqweb.tenancy.db import use_company

    alpha, beta = two_company_schemas
    assert alpha != beta

    with use_company(alpha):
        Department.objects.create(name="Только альфа", path="a")

    with use_company(beta):
        Department.objects.create(name="Только бета", path="b")
        assert list(Department.objects.values_list("name", flat=True)) == \
            ["Только бета"]

    with use_company(alpha):
        assert list(Department.objects.values_list("name", flat=True)) == \
            ["Только альфа"]


@pytest.mark.django_db(transaction=True)
def test_company_schema_data_does_not_leak_into_next_test_using_it(company_schema):
    """Данные предыдущего теста этого файла не должны быть видны здесь.

    ``company_schema`` — module-scoped пул схемы плюс чистка данных на
    выходе; этот тест и ``test_company_schema_is_actually_migrated`` (тоже
    пишущий в hr_department) идут по одной и той же физической схеме — без
    очистки между ними здесь оказалась бы чужая строка.
    """
    from apps.hr.models import Department
    from htqweb.tenancy.db import use_company

    with use_company(company_schema["slug"]):
        assert Department.objects.count() == 0

import pytest

from apps.companies.services import schema_service


@pytest.mark.django_db
def test_create_then_exists():
    schema_service.create_schema("t-alpha")
    assert schema_service.schema_exists("t-alpha") is True
    schema_service.drop_schema("t-alpha")
    assert schema_service.schema_exists("t-alpha") is False


@pytest.mark.django_db
def test_create_is_idempotent():
    """Повторный вызов не падает: создание компании должно переживать
    повтор после сетевого сбоя, как и остальные internal-ручки платформы."""
    schema_service.create_schema("t-beta")
    schema_service.create_schema("t-beta")
    assert schema_service.schema_exists("t-beta") is True
    schema_service.drop_schema("t-beta")


@pytest.mark.django_db
def test_drop_is_idempotent():
    schema_service.drop_schema("t-never-existed")


@pytest.mark.django_db
def test_tenant_apps_are_the_four_domain_apps(settings):
    assert settings.TENANT_APPS == ("hr", "tasks", "contracts", "signoff")

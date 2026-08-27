import pytest

from htqweb.tenancy.celery import MissingCompanyArgument, company_task
from htqweb.tenancy.context import current_company_or_none


@company_task
def _echo_company():
    return current_company_or_none()


@pytest.mark.django_db
def test_company_is_taken_from_kwarg():
    assert _echo_company(company_slug="htq-kz") == "htq-kz"


@pytest.mark.django_db
def test_missing_company_raises_instead_of_defaulting_to_public():
    """Молчаливый public здесь — самый дорогой из возможных дефектов:
    задача отработала бы «успешно», ничего не найдя, и никто бы не заметил.
    Тот же принцип, что и FALLBACK_MODE=strict."""
    with pytest.raises(MissingCompanyArgument):
        _echo_company()


@pytest.mark.django_db
def test_context_is_cleared_after_task():
    _echo_company(company_slug="htq-kz")
    assert current_company_or_none() is None


@pytest.mark.django_db
def test_positional_company_slug_is_not_accepted():
    """Позиционная передача не работает намеренно — декоратор читает kwargs.

    Тест фиксирует это как поведение, а не как случайность, и заодо
    проверяет, что сообщение подсказывает настоящую причину.
    """
    @company_task
    def _echo(company_slug):
        return current_company_or_none()

    with pytest.raises(MissingCompanyArgument) as exc:
        _echo("htq-kz")
    assert "именованный" in str(exc.value).lower()

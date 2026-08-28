import pytest

from htqweb.tenancy.celery import (
    MissingCompanyArgument,
    company_dispatch_task,
    company_task,
    fan_out_to_companies,
)
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


# ─────────────────────────────────────────────────────────────────────────
# Маркеры для мета-теста (apps/core/tests/test_invariants.py):
# задача tenant-аппки обязана быть либо @company_task, либо явно помеченным
# диспетчером — иначе падает в CI, а не на бою (followups.md п.1).
# ─────────────────────────────────────────────────────────────────────────


def test_company_task_marks_the_wrapper_for_the_meta_test():
    @company_task
    def _real(company_slug):
        return company_slug

    assert _real.is_company_task is True
    assert getattr(_real, "is_company_dispatch_task", False) is False


def test_company_dispatch_task_marks_the_function_for_the_meta_test():
    @company_dispatch_task
    def _dispatcher():
        return None

    assert _dispatcher.is_company_dispatch_task is True
    assert getattr(_dispatcher, "is_company_task", False) is False


def test_company_dispatch_task_does_not_wrap_the_function():
    """Диспетчер не работает в контексте компании — оборачивать нечего,
    маркер ставится прямо на функцию, без прокси."""
    def _dispatcher():
        return None

    marked = company_dispatch_task(_dispatcher)
    assert marked is _dispatcher


# ─────────────────────────────────────────────────────────────────────────
# fan_out_to_companies — общий веер диспетчера.
# ─────────────────────────────────────────────────────────────────────────


class _FakeTask:
    """Дублёр celery-задачи: фиксирует company_slug'и, переданные в .delay,
    не поднимая ни брокер, ни воркер."""

    def __init__(self, *, fail_on: frozenset[str] = frozenset()):
        self.calls: list[str] = []
        self._fail_on = fail_on

    def delay(self, *, company_slug):
        if company_slug in self._fail_on:
            raise RuntimeError(f"boom on {company_slug}")
        self.calls.append(company_slug)


@pytest.mark.django_db
def test_fan_out_dispatches_to_every_active_company(two_company_schemas):
    alpha, beta = two_company_schemas
    task = _FakeTask()

    result = fan_out_to_companies(task, label="test.fan_out")

    assert task.calls == sorted([alpha, beta])
    assert result["dispatched"] == sorted([alpha, beta])
    assert result["failed"] == []


@pytest.mark.django_db
def test_fan_out_keeps_going_after_one_company_fails(two_company_schemas):
    alpha, beta = two_company_schemas
    task = _FakeTask(fail_on=frozenset({alpha}))

    result = fan_out_to_companies(task, label="test.fan_out")

    assert task.calls == [beta]
    assert result["dispatched"] == [beta]
    assert result["failed"] == [alpha]

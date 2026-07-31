"""Команда заведения учёток для сотрудников HR.

Живёт в apps.users, а не в apps.hr, по границе аппок: пароль умеет ставить
только ``admin_service`` этой аппки, а карточки сотрудников читаются и
связываются через ``apps.hr.interface`` — прямой импорт моделей соседа
запрещён (apps/core/tests/test_app_isolation.py).

Проверяется то, что легко сломать незаметно: идемпотентность (повторный
прогон не должен ронять команду на уникальности почты и не должен менять
пароль), рядовые права у создаваемых учёток и защита от неместной БД.
"""
from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.hr.models import Department, Employee, Position
from apps.users.models import User


@pytest.fixture
def employees(db):
    department = Department.objects.create(name="Строительство", path="stroy")
    position = Position.objects.create(
        title="Инженер", department=department, weight=1000)
    for i in range(3):
        Employee.objects.create(
            first_name=f"Имя{i}", last_name=f"Фамилия{i}",
            email=f"emp{i}@htq.test", department=department,
            position=position, hire_date="2024-01-09",
        )
    return department


def _run(**kwargs):
    call_command("seed_employee_accounts", verbosity=0, **kwargs)


def test_creates_and_links_accounts(employees):
    _run()
    assert User.objects.filter(email__endswith="@htq.test").count() == 3
    for employee in Employee.objects.all():
        assert employee.user_id is not None
        user = User.objects.get(id=employee.user_id)
        assert user.email == employee.email


def test_created_accounts_are_ordinary_employees(employees):
    """Ровно ради этого команда и нужна была вторым делом: до неё в базе не
    существовало ни одного НЕ-администратора, и сценарии рядового
    сотрудника нечем было проверить."""
    _run()
    for user in User.objects.filter(email__endswith="@htq.test"):
        assert user.is_staff is False
        assert user.is_superuser is False
        # Демо-учётка обязана пережить первый вход, иначе входить незачем.
        assert user.must_change_password is False


def test_password_is_usable(employees):
    _run(password="s3cret-demo")
    user = User.objects.get(email="emp0@htq.test")
    assert user.check_password("s3cret-demo")


def test_is_idempotent(employees):
    _run()
    _run()
    assert User.objects.filter(email__endswith="@htq.test").count() == 3


def test_second_run_does_not_reset_password(employees):
    """Повтор не должен затирать пароль: учётку могли уже отдать человеку."""
    _run(password="first-pass")
    _run(password="second-pass")
    user = User.objects.get(email="emp0@htq.test")
    assert user.check_password("first-pass")


def test_limit_creates_only_the_first_n(employees):
    _run(limit=2)
    assert User.objects.filter(email__endswith="@htq.test").count() == 2


def test_refuses_when_there_are_no_employees(db):
    with pytest.raises(CommandError, match="нет сотрудников"):
        _run()


def test_skips_employees_without_email(employees):
    """Почта — источник и username, и связи; без неё заводить нечего.
    Команда пропускает такого человека, а не падает на всей партии."""
    Employee.objects.filter(email="emp0@htq.test").update(email="")
    _run()
    assert User.objects.filter(email__endswith="@htq.test").count() == 2


def test_leaves_already_linked_employees_alone(employees):
    """Человеку с учёткой вторую не заводят.

    Иначе связь переклеилась бы на новую, а задачи и проекты остались бы
    ссылаться на СТАРЫЙ user_id — то есть молча потеряли бы владельца.
    """
    existing = User.objects.create_user(
        username="veteran", email="veteran@htq.test", password="x")
    linked = Employee.objects.first()
    linked.user_id = existing.id
    linked.save(update_fields=["user_id"])

    _run()

    linked.refresh_from_db()
    assert linked.user_id == existing.id
    # И второй учётки под его почту не появилось.
    assert not User.objects.filter(email=linked.email).exists()


def test_does_not_steal_an_account_from_another_employee(employees):
    """``Employee.user_id`` уникален. Если учётка с такой почтой уже
    привязана к ДРУГОМУ человеку, связывать заново нельзя — иначе первый
    потерял бы доступ к своим задачам."""
    other = User.objects.create_user(
        username="emp0", email="emp0@htq.test", password="x")
    thief = Employee.objects.exclude(email="emp0@htq.test").first()
    thief.user_id = other.id
    thief.save(update_fields=["user_id"])

    _run()

    thief.refresh_from_db()
    assert thief.user_id == other.id
    # Владелец этой почты остался без связи, а не отобрал чужую учётку.
    assert Employee.objects.get(email="emp0@htq.test").user_id is None


# ── защита от неместной БД ─────────────────────────────────────────────────
#
# Как чистое правило от строки хоста: боевой адрес не должен оказываться в
# живых настройках даже на время теста.

def _guard(host: str, *, force: bool = False) -> None:
    from apps.users.management.commands.seed_employee_accounts import Command

    Command()._assert_local(force, host=host)


@pytest.mark.parametrize("host", ["45.10.110.212", "db.example.com"])
def test_refuses_to_run_against_a_remote_database(host):
    with pytest.raises(CommandError, match="не похож на локальную"):
        _guard(host)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "db", "::1", ""])
def test_local_hosts_pass_the_guard(host):
    _guard(host)


def test_force_remote_is_the_only_way_past_the_guard():
    _guard("45.10.110.212", force=True)


def test_guard_runs_before_any_account_is_created(employees, monkeypatch):
    from apps.users.management.commands import seed_employee_accounts

    def refuse(self, force, host=None):
        raise CommandError("DB_HOST не похож на локальную БД")

    monkeypatch.setattr(seed_employee_accounts.Command, "_assert_local", refuse)
    with pytest.raises(CommandError, match="не похож на локальную"):
        _run()
    assert User.objects.filter(email__endswith="@htq.test").count() == 0

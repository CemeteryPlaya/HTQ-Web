"""Команда наполнения HR демо-данными.

Наполнение — такой же код, как остальной: если оно молча перестанет
связывать сотрудника с отделом его должности или дублировать записи при
повторном запуске, локальная база начнёт врать, а по ней потом смотрят
глазами и делают выводы.

Отдельно проверяется защита от неместной БД: команда пишет в четыре
таблицы, а ``DB_HOST`` по умолчанию приходит из корневого ``.env``, где
стоит боевой адрес.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.hr.models import Department, Employee, LevelThreshold, Position


def _seed(**kwargs):
    call_command("seed_hr_demo", verbosity=0, **kwargs)


@pytest.mark.django_db
def test_seed_creates_the_whole_chain():
    _seed()
    assert LevelThreshold.objects.count() == 5
    assert Department.objects.count() >= 8
    assert Position.objects.count() >= 23
    assert Employee.objects.count() >= 24


@pytest.mark.django_db
def test_seed_is_idempotent():
    """Второй запуск правит на месте, а не плодит копии."""
    _seed()
    counts = (
        LevelThreshold.objects.count(),
        Department.objects.count(),
        Position.objects.count(),
        Employee.objects.count(),
    )
    _seed()
    assert (
        LevelThreshold.objects.count(),
        Department.objects.count(),
        Position.objects.count(),
        Employee.objects.count(),
    ) == counts


@pytest.mark.django_db
def test_levels_cover_every_seeded_position():
    """Ни одна должность не должна попасть в запасной уровень.

    Пороги считаются из веса; должность вне всех диапазонов молча получает
    ``_DEFAULT_LEVEL = 5``, и иерархия схлопывается. Ровно в этом состоянии
    и была локальная база до наполнения: 22 должности, 0 порогов.
    """
    _seed()
    thresholds = list(LevelThreshold.objects.order_by("level_number"))

    for position in Position.objects.all():
        matching = [t for t in thresholds
                    if t.weight_from <= position.weight <= t.weight_to]
        assert matching, (
            f"вес {position.weight} должности «{position.title}» "
            f"не попадает ни в один порог"
        )
        assert position.level == matching[0].level_number


@pytest.mark.django_db
def test_level_ranges_do_not_overlap():
    """Пересечение диапазонов сделало бы уровень неоднозначным."""
    _seed()
    ranges = list(
        LevelThreshold.objects.order_by("weight_from")
        .values_list("weight_from", "weight_to")
    )
    for (_, prev_to), (next_from, _) in zip(ranges, ranges[1:]):
        assert prev_to < next_from, f"диапазоны пересекаются: {prev_to} >= {next_from}"


@pytest.mark.django_db
def test_every_level_actually_has_positions():
    """Пустой уровень — признак того, что веса и пороги разъехались."""
    _seed()
    for threshold in LevelThreshold.objects.all():
        assert Position.objects.filter(level=threshold.level_number).exists(), (
            f"на уровне L{threshold.level_number} нет ни одной должности"
        )


@pytest.mark.django_db
def test_employee_department_always_matches_their_position():
    """Ключевой инвариант наполнения.

    Отдел сотрудника берётся у его должности, а не задаётся отдельно —
    иначе связка «человек → должность → отдел» разъезжается, и отчёты по
    отделам начинают считать людей не там.
    """
    _seed()
    mismatched = [
        e.email
        for e in Employee.objects.select_related("position")
        if e.department_id != e.position.department_id
    ]
    assert mismatched == []


@pytest.mark.django_db
def test_every_seeded_department_has_people_and_a_manager():
    _seed()
    seeded_paths = ["upr", "stroy", "stroy.elektro", "proekt", "snab",
                    "hr", "fin", "it"]
    for path in seeded_paths:
        dept = Department.objects.get(path=path)
        assert dept.employees.exists(), f"отдел {path} пуст"
        assert dept.manager_id is not None, f"у отдела {path} нет руководителя"
        # Руководитель обязан работать в своём отделе, а не в соседнем.
        assert dept.manager.department_id == dept.id


@pytest.mark.django_db
def test_positions_carry_an_explicit_hr_level():
    """Явная матрица прав приоритетнее эвристики по названию должности
    (apps/hr/access.py). Без неё уровень доступа кадровика зависел бы от
    того, угадалось ли в заголовке слово «кадр»."""
    _seed()
    seeded = Position.objects.filter(permissions__isnull=False)
    assert seeded.count() >= 23
    for position in seeded:
        assert position.permissions.get("hr_level") in {
            "junior", "middle", "senior", "lead",
        }


@pytest.mark.django_db
def test_phones_use_the_platform_mask():
    """Телефоны — в том же виде, который отдаёт PhoneInput. Данные, не
    совпадающие с форматом форм, обесценивают проверку глазами."""
    _seed()
    import re

    mask = re.compile(r"^\+7 \(7\d{2}\) \d{3}-\d{2}-\d{2}$")
    for employee in Employee.objects.exclude(phone__isnull=True).exclude(phone=""):
        assert mask.match(employee.phone), (
            f"{employee.email}: телефон «{employee.phone}» не по маске"
        )


@pytest.mark.django_db
def test_weights_are_unique():
    """weight глобально уникален; коллизия уронила бы наполнение на 409."""
    _seed()
    weights = list(Position.objects.values_list("weight", flat=True))
    assert len(weights) == len(set(weights))


@pytest.mark.django_db
def test_purge_removes_e2e_leftovers_only():
    """Очистка не должна задевать боевые (сидированные) записи."""
    _seed()
    dept = Department.objects.create(name="E2E отдел мусор", path="e2e-junk")
    Position.objects.create(title="E2E должность мусор", department=dept,
                            weight=4_242_424)
    before_real = Position.objects.filter(title="Генеральный директор").count()

    _seed(purge_e2e=True)

    assert not Position.objects.filter(title__startswith="E2E ").exists()
    assert not Department.objects.filter(name__startswith="E2E ").exists()
    assert Position.objects.filter(title="Генеральный директор").count() == before_real


# --- защита от неместной БД -------------------------------------------------
#
# Проверяется как чистое правило от строки хоста, а НЕ подменой
# settings.DATABASES. Первая версия этих тестов писала боевой адрес в живые
# настройки; запись не ушла на VPS только потому, что соединение уже было
# открыто и Django его не переоткрывал, — зато тирдаун туда постучался и
# отвалился по таймауту. Полагаться на кеш соединения в тесте, который
# существует ради недопущения записи на бой, — противоречие. Хост теперь
# передаётся параметром, и адреса VPS в настройках не оказывается никогда.

def _guard(host: str, *, force: bool = False) -> None:
    from apps.hr.management.commands.seed_hr_demo import Command

    command = Command()
    command._assert_local(force, host=host)


@pytest.mark.parametrize("host", ["45.10.110.212", "db.example.com", "10.8.0.4"])
def test_refuses_to_run_against_a_remote_database(host):
    """Защита от опечатки в окружении. Команда пишет десятки строк — не то,
    что стоит случайно отправить на боевой хост."""
    with pytest.raises(CommandError, match="не похож на локальную"):
        _guard(host)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "db", "::1", ""])
def test_local_hosts_pass_the_guard(host):
    _guard(host)  # не бросает


def test_force_remote_is_the_only_way_past_the_guard():
    _guard("45.10.110.212", force=True)  # не бросает


@pytest.mark.django_db
def test_guard_runs_before_anything_is_written(monkeypatch):
    """Отказ обязан случиться до первой записи, иначе «защита» оставит
    половину демо-данных на чужом хосте.

    Проверяется порядок вызовов, поэтому отказ подменяется, а не
    провоцируется настоящим адресом: чужой хост в настройках не нужен даже
    в виде документационного диапазона.
    """
    from apps.hr.management.commands import seed_hr_demo

    def refuse(self, force, host=None):
        raise CommandError("DB_HOST не похож на локальную БД")

    monkeypatch.setattr(seed_hr_demo.Command, "_assert_local", refuse)

    with pytest.raises(CommandError, match="не похож на локальную"):
        _seed()
    assert LevelThreshold.objects.count() == 0
    assert Department.objects.count() == 0

"""Реестр периодических задач тенантных аппок (``apps/core/periodic_tasks.py``).

Сторожит три вещи:

- ``ensure_periodic_tasks`` заводит недостающее и не трогает существующее
  (операторское ``enabled``/расписание), кроме починки пути из
  ``legacy_tasks``;
- реестр совпадает с КОНЕЧНЫМ состоянием миграций из
  ``SHARED_EFFECT_MIGRATIONS`` (их forward-функции прогоняются по чистой
  таблице), а каждая тенантная миграция, пишущая в ``django_celery_beat``,
  в этом списке есть — иначе на живом стеке её задачи не будет, потому что
  такие миграции там не выполняются вовсе;
- ``migrate_shared`` реестр действительно применяет.
"""

import io
import re
import sys
from pathlib import Path

import pytest
from django.apps import apps as django_apps
from django.conf import settings
from django.core.management import call_command
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations.special import RunPython
from django_celery_beat.models import (
    CrontabSchedule, IntervalSchedule, PeriodicTask,
)

from apps.companies.services.migration_service import SHARED_EFFECT_MIGRATIONS
from apps.core.periodic_tasks import (
    PERIODIC_TASKS, Crontab, ensure_periodic_tasks,
)

REGISTRY_NAMES = [spec.name for spec in PERIODIC_TASKS]


def _schedule_state(row):
    if row.crontab_id is not None:
        c = row.crontab
        return ("crontab", c.minute, c.hour, c.day_of_week, c.day_of_month,
                c.month_of_year, str(c.timezone))
    if row.interval_id is not None:
        return ("interval", row.interval.every, row.interval.period)
    return None


def _state(names=None):
    """name -> (task, enabled, description, расписание, args, kwargs)."""
    qs = PeriodicTask.objects.select_related("crontab", "interval")
    if names is not None:
        qs = qs.filter(name__in=names)
    return {
        row.name: (row.task, row.enabled, row.description,
                   _schedule_state(row), row.args, row.kwargs)
        for row in qs
    }


def _spec_schedule_state(spec):
    s = spec.schedule
    if isinstance(s, Crontab):
        return ("crontab", s.minute, s.hour, s.day_of_week, s.day_of_month,
                s.month_of_year, s.timezone)
    return ("interval", s.every, s.period)


def _clean_beat_tables():
    # Расписания тоже: get_or_create в миграциях без пояса нашёл бы чужой
    # crontab с теми же полями в другом поясе, и сравнение зависело бы от
    # того, что завели другие миграции. Откатывается вместе с тестом.
    PeriodicTask.objects.all().delete()
    CrontabSchedule.objects.all().delete()
    IntervalSchedule.objects.all().delete()


def _run_shared_effect_migrations_forward():
    loader = MigrationLoader(None, ignore_no_migrations=True)
    # Порядок внутри аппки — по имени (0019 до 0020, 0003 до 0019); между
    # аппками строки не пересекаются.
    for key in sorted(SHARED_EFFECT_MIGRATIONS):
        migration = loader.disk_migrations[key]
        ops = [op for op in migration.operations if isinstance(op, RunPython)]
        assert ops, f"{key}: в SHARED_EFFECT_MIGRATIONS, но без RunPython"
        for op in ops:
            op.code(django_apps, None)


def test_registry_names_are_unique():
    assert len(REGISTRY_NAMES) == len(set(REGISTRY_NAMES))


@pytest.mark.django_db
def test_ensure_creates_every_entry_on_an_empty_table():
    _clean_beat_tables()

    result = ensure_periodic_tasks()

    assert result == {"created": REGISTRY_NAMES, "repaired": [], "kept": []}
    state = _state()
    assert set(state) == set(REGISTRY_NAMES)
    for spec in PERIODIC_TASKS:
        task, enabled, description, schedule, _args, _kwargs = state[spec.name]
        assert task == spec.task
        assert enabled is spec.enabled
        assert description == spec.description
        assert schedule == _spec_schedule_state(spec)


@pytest.mark.django_db
def test_ensure_never_touches_an_existing_row():
    """Оператор выключил задачу и сменил расписание — старт контейнера
    (migrate_shared) не вправе это откатить."""
    _clean_beat_tables()
    custom, _ = CrontabSchedule.objects.get_or_create(
        minute="45", hour="4", day_of_week="*", day_of_month="*",
        month_of_year="*", timezone="UTC",
    )
    PeriodicTask.objects.create(
        name="bpp.committed_check", task="apps.bpp.tasks.committed_check_dispatch",
        crontab=custom, enabled=False, description="оператор",
    )
    before = _state(["bpp.committed_check"])

    result = ensure_periodic_tasks()

    assert "bpp.committed_check" in result["kept"]
    assert "bpp.committed_check" not in result["created"]
    assert _state(["bpp.committed_check"]) == before
    # Повтор — ничего нового.
    again = ensure_periodic_tasks()
    assert again["created"] == [] and again["repaired"] == []
    assert again["kept"] == REGISTRY_NAMES


@pytest.mark.django_db
def test_ensure_repairs_only_the_task_path_of_a_legacy_row():
    """Строка из времён голого migrate (hr/0019 без hr/0020) указывает на
    задачу, которой без company_slug нельзя, — путь чинится, операторские
    enabled и расписание остаются."""
    _clean_beat_tables()
    custom, _ = CrontabSchedule.objects.get_or_create(
        minute="0", hour="5", day_of_week="*", day_of_month="*",
        month_of_year="*", timezone="UTC",
    )
    PeriodicTask.objects.create(
        name="hr.sync_identity", task="apps.hr.tasks.sync_identity",
        crontab=custom, enabled=False, description="старое",
    )

    result = ensure_periodic_tasks()

    assert result["repaired"] == ["hr.sync_identity"]
    row = PeriodicTask.objects.get(name="hr.sync_identity")
    spec = next(s for s in PERIODIC_TASKS if s.name == "hr.sync_identity")
    assert row.task == spec.task == "apps.hr.tasks.sync_identity_dispatch"
    assert row.enabled is False
    assert row.crontab_id == custom.pk


@pytest.mark.django_db
def test_registry_equals_final_state_of_shared_effect_migrations():
    """Прогон forward-функций всех миграций списка по чистой таблице даёт
    ровно то же, что ensure_periodic_tasks по чистой таблице: те же имена,
    пути, расписания, enabled и описания."""
    _clean_beat_tables()
    _run_shared_effect_migrations_forward()
    from_migrations = _state()

    _clean_beat_tables()
    ensure_periodic_tasks()
    from_registry = _state()

    assert set(from_migrations) == set(REGISTRY_NAMES), (
        "реестр PERIODIC_TASKS разошёлся с миграциями SHARED_EFFECT_MIGRATIONS "
        "по составу задач"
    )
    assert from_registry == from_migrations


_BEAT_WRITE = re.compile(r"""get_model\(\s*["']django_celery_beat["']""")


def test_every_tenant_beat_migration_is_listed():
    """Тенантная миграция, пишущая в django_celery_beat, на живом стеке не
    выполняется — её эффект обязан быть в SHARED_EFFECT_MIGRATIONS (и через
    сторож выше — в реестре)."""
    loader = MigrationLoader(None, ignore_no_migrations=True)
    tenant_apps = set(settings.TENANT_APPS)
    found = set()
    for key, migration in loader.disk_migrations.items():
        if key[0] not in tenant_apps:
            continue
        source = Path(sys.modules[type(migration).__module__].__file__).read_text(
            encoding="utf-8")
        if _BEAT_WRITE.search(source):
            found.add(key)
    assert found == set(SHARED_EFFECT_MIGRATIONS)


def test_registry_tasks_are_registered_in_celery():
    from htqweb.celery import app as celery_app

    celery_app.loader.import_default_modules()
    missing = [spec.task for spec in PERIODIC_TASKS if spec.task not in celery_app.tasks]
    assert missing == []


@pytest.mark.django_db
def test_migrate_shared_ensures_periodic_tasks(monkeypatch):
    """Старт контейнера — migrate_shared — и заводит расписания: сам migrate
    здесь заглушён, проверяется только вызов реестра после него."""
    from apps.companies.management.commands import migrate_shared

    migrated = []
    monkeypatch.setattr(migrate_shared, "call_command",
                        lambda *args, **kw: migrated.append(args[1]))
    PeriodicTask.objects.filter(name__in=REGISTRY_NAMES).delete()

    out = io.StringIO()
    call_command("migrate_shared", stdout=out)

    assert "django_celery_beat" in migrated
    assert set(_state(REGISTRY_NAMES)) == set(REGISTRY_NAMES)
    assert f"заведено {len(REGISTRY_NAMES)}" in out.getvalue()

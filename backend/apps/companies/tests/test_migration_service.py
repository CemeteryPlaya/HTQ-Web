"""Прогон миграций по схемам компаний.

Тесты, которые действительно мигрируют, идут с ``transaction=True``:
миграции — это DDL, выполняемый многими операторами подряд, и обычный
обёрнутый в atomic тест откатил бы половину сделанного между шагами. Платой
за это является ручная уборка — схему за таким тестом никто не откатывает,
поэтому ``drop_schema`` в фикстуре обязателен. Тесты сухого прогона и
разбора аргументов обходятся обычным ``django_db``: они ничего не создают,
и откат транзакции убирает за ними всё сам.
"""

import io
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from apps.companies.models import Company, CompanyKind, CompanySchemaVersion
from apps.companies.services import migration_service, schema_service


def _company(slug: str, name: str) -> Company:
    company = Company.objects.create(slug=slug, name=name, kind=CompanyKind.SERVICE)
    # Уборка на входе, а не только на выходе: схема, оставшаяся от прогона,
    # который упал до teardown, иначе делала бы следующий прогон зелёным по
    # чужим таблицам.
    schema_service.drop_schema(slug)
    schema_service.create_schema(slug)
    return company


@pytest.fixture
def alpha(db):
    company = _company("t-alpha", "Alpha")
    yield company
    schema_service.drop_schema("t-alpha")


@pytest.fixture
def beta(db):
    company = _company("t-beta", "Beta")
    yield company
    schema_service.drop_schema("t-beta")


def _tables_in(schema: str) -> set[str]:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
            [schema],
        )
        return {row[0] for row in cur.fetchall()}


def _advisory_locks_held() -> int:
    """Сколько раз ключ модуля сейчас взят в этой БД.

    pg_locks раскладывает bigint-ключ на пару int'ов; ключ модуля влезает в
    младшую половину, поэтому classid = 0. Проверять через
    pg_try_advisory_lock нельзя: та же сессия берёт свой же ключ повторно
    успешно (блокировки реентерабельны), и снятия это не докажет.
    """
    with connection.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
            "AND classid = %s AND objid = %s",
            [migration_service.ADVISORY_LOCK_KEY >> 32,
             migration_service.ADVISORY_LOCK_KEY & 0xFFFFFFFF],
        )
        return cur.fetchone()[0]


def _periodic_task_state() -> list[tuple]:
    """Снимок платформенного расписания beat (public, одно на всю группу)."""
    with connection.cursor() as cur:
        cur.execute(
            "SELECT name, enabled FROM public.django_celery_beat_periodictask "
            "ORDER BY name"
        )
        return cur.fetchall()


def _migration_rows(schema: str) -> set[tuple[str, str]]:
    """Содержимое django_migrations КОНКРЕТНОЙ схемы.

    Имя схемы подставляется в SQL, а не передаётся параметром: имя таблицы
    плейсхолдером не задаётся. Значения приходят только из этого модуля.
    """
    if "django_migrations" not in _tables_in(schema):
        return set()
    with connection.cursor() as cur:
        cur.execute(f'SELECT app, name FROM "{schema}".django_migrations')
        return {(row[0], row[1]) for row in cur.fetchall()}


@pytest.mark.django_db(transaction=True)
def test_migrate_creates_tenant_tables_in_company_schema(alpha):
    migration_service.migrate_company("t-alpha")
    tables = _tables_in("co_t_alpha")
    assert "hr_employee" in tables
    assert "tasks_task" in tables
    assert "contracts_counterparty" in tables


@pytest.mark.django_db(transaction=True)
def test_each_schema_gets_its_own_migration_state(alpha, beta):
    """Ключевая деталь всей задачи.

    Если во время миграции Django находит public.django_migrations и пишет
    состояние туда, ВСЕ компании начинают считать себя мигрированными
    вместе, а их схемы остаются пустыми. Проверяется в трёх местах сразу:
    состояние легло в схему компании, public не изменился, и вторая
    компания после прогона первой по-прежнему считает себя непромигрированной.
    """
    public_before = _migration_rows("public")

    migration_service.migrate_company("t-alpha")

    alpha_rows = _migration_rows("co_t_alpha")
    assert any(app == "hr" for app, _ in alpha_rows)
    assert _migration_rows("public") == public_before

    # Вторая компания не «промигрировалась» заодно с первой.
    assert migration_service.migrate_company("t-beta", plan=True)["planned"]
    migration_service.migrate_company("t-beta")
    assert "hr_employee" in _tables_in("co_t_beta")


@pytest.mark.django_db(transaction=True)
def test_migrate_does_not_touch_shared_apps(alpha):
    """users/cms/media_files живут в public и в схему компании не копируются.

    django_celery_beat попадает сюда же, хотя формально он ЗАВИСИМОСТЬ двух
    тенантных миграций (hr.0019, tasks.0003 заводят периодические задачи):
    расписание у платформы одно на всех, beat читает его из public, и вторая
    копия таблицы в схеме компании была бы мёртвым грузом.
    """
    migration_service.migrate_company("t-alpha")
    tables = _tables_in("co_t_alpha")
    assert not any(t.startswith("users_") for t in tables)
    assert not any(t.startswith("cms_") for t in tables)
    assert not any(t.startswith("django_celery_beat_") for t in tables)


@pytest.mark.django_db(transaction=True)
def test_migrate_records_version(alpha):
    migration_service.migrate_company("t-alpha")
    rows = CompanySchemaVersion.objects.filter(company=alpha)
    assert rows.count() == 4
    assert all(r.applied_migration for r in rows)
    assert all(r.last_error == "" for r in rows)
    assert all(r.last_run_at is not None for r in rows)


@pytest.mark.django_db(transaction=True)
def test_plan_mode_changes_nothing(alpha):
    result = migration_service.migrate_company("t-alpha", plan=True)
    assert result["planned"]
    assert result["applied"] == {}
    # Ни одной таблицы, включая django_migrations: сухой прогон читает
    # состояние схемы, но не заводит его.
    assert _tables_in("co_t_alpha") == set()
    assert not CompanySchemaVersion.objects.filter(company=alpha).exists()


@pytest.mark.django_db(transaction=True)
def test_second_run_is_a_noop(alpha):
    migration_service.migrate_company("t-alpha")
    result = migration_service.migrate_company("t-alpha")
    assert result["planned"] == []


@pytest.mark.django_db(transaction=True)
def test_single_app_run_pulls_in_its_tenant_dependencies(alpha):
    """``--app signoff`` тянет hr (signoff зависит от него), но не tasks.

    Сужение до одной аппки не имеет права оставить схему в состоянии,
    где таблица создана, а таблица, на которую она ссылается FK, — нет.
    """
    result = migration_service.migrate_company("t-alpha", app_label="signoff")
    tables = _tables_in("co_t_alpha")
    assert "signoff_approvalroute" in tables
    assert "hr_employee" in tables
    assert not any(t.startswith("tasks_") for t in tables)
    # hr отчитывается вместе с signoff: он реально промигрирован до той
    # версии, от которой signoff зависит, и умолчать о ней значило бы
    # оставить CompanySchemaVersion расходящимся с реальностью.
    assert "signoff" in result["applied"]
    assert "hr" in result["applied"]
    assert "tasks" not in result["applied"]


@pytest.mark.django_db
def test_missing_schema_is_an_error(db):
    """Схемы нет — прогон обязан отказаться, а не молча уйти в public.

    Postgres создаёт таблицу в ПЕРВОЙ существующей схеме search_path: если
    co_<slug> не существует, весь набор тенантных таблиц лёг бы в public
    поверх общих. Ошибка здесь дешевле разбора последствий.
    """
    Company.objects.create(slug="t-gamma", name="Gamma", kind=CompanyKind.SERVICE)
    with pytest.raises(migration_service.SchemaMissing):
        migration_service.migrate_company("t-gamma")


@pytest.mark.django_db
def test_unknown_app_is_rejected(alpha):
    with pytest.raises(ValueError):
        migration_service.migrate_company("t-alpha", app_label="cms")


@pytest.mark.django_db
def test_command_refuses_when_there_are_no_companies():
    """Пустой реестр — это ошибка команды, а не «нечего делать».

    Молчаливый успех на пустом списке скрыл бы и настоящую поломку резолва
    компаний, и опечатку в --company.
    """
    with pytest.raises(CommandError):
        call_command("migrate_companies", "--plan")


@pytest.mark.django_db
def test_command_plan_prints_pending_migrations(alpha):
    out = io.StringIO()
    call_command("migrate_companies", "--company", "t-alpha", "--plan", stdout=out)
    printed = out.getvalue()
    assert "t-alpha" in printed
    assert "hr.0001_initial" in printed


@pytest.mark.django_db
def test_command_reports_unknown_app_without_traceback(alpha):
    with pytest.raises(CommandError):
        call_command("migrate_companies", "--company", "t-alpha", "--app", "cms")


@pytest.mark.django_db(transaction=True)
def test_shared_effect_migrations_are_marked_but_not_run(alpha):
    """hr.0019 и tasks.0003 пишут в public, а не в схему компании.

    Они тенантные по принадлежности, но по эффекту общие: заводят
    периодические задачи beat, одни на всю группу. Выполнить их на каждую
    компанию значило бы молча вернуть выключенную оператором задачу и
    сбросить изменённое им расписание — поэтому они помечаются
    применёнными, но не выполняются.
    """
    # Расписание в public заводится миграциями при создании тестовой БД, но
    # transaction=True-тест вычищает public целиком (TRUNCATE), поэтому
    # состояние оператора воспроизводится здесь явно: задача заведена и
    # ВЫКЛЮЧЕНА. Выполнись hr.0019 ещё раз — её update_or_create вернул бы
    # enabled=True.
    from django_celery_beat.models import CrontabSchedule, PeriodicTask

    # update_or_create, а не create: заведена ли строка миграциями к этому
    # моменту, зависит от того, вычистил ли public предыдущий
    # transaction=True-тест, — и от порядка тестов зависеть здесь нечему.
    schedule, _ = CrontabSchedule.objects.get_or_create(minute="30", hour="3")
    PeriodicTask.objects.update_or_create(
        name="hr.sync_identity",
        defaults={"task": "apps.hr.tasks.sync_identity", "crontab": schedule,
                  "enabled": False},
    )
    before = _periodic_task_state()
    assert ("hr.sync_identity", False) in before

    migration_service.migrate_company("t-alpha")

    assert _periodic_task_state() == before
    applied = _migration_rows("co_t_alpha")
    for key in migration_service.SHARED_EFFECT_MIGRATIONS:
        assert key in applied
    # И при этом аппка считается доведённой до листа, а не отставшей.
    hr_row = CompanySchemaVersion.objects.get(company=alpha, app_label="hr")
    assert hr_row.applied_migration == hr_row.target_migration


@pytest.mark.django_db(transaction=True)
def test_backwards_migration_is_refused(alpha):
    """Откат закрыт целиком — и ничего не успевает изменить.

    Реверс тенантных data-миграций пошёл бы по public (он второй в
    search_path) и выключил бы периодические задачи ВСЕЙ группы, а не одной
    компании.
    """
    migration_service.migrate_company("t-alpha", app_label="signoff")
    tables_before = _tables_in("co_t_alpha")
    beat_before = _periodic_task_state()

    with pytest.raises(migration_service.BackwardsMigrationRefused):
        migration_service.migrate_company(
            "t-alpha", app_label="signoff", target="zero",
        )

    assert _tables_in("co_t_alpha") == tables_before
    assert _periodic_task_state() == beat_before
    assert _advisory_locks_held() == 0


@pytest.mark.django_db(transaction=True)
def test_plan_refuses_backwards_shared_effect_migration(alpha):
    """Правка 4а итогового ревью: ``--plan`` обязан отказывать на обратном
    направлении ровно там же, где откажет боевой прогон — включая план,
    срезанный ИСКЛЮЧИТЕЛЬНО до shared-effect шага.

    ``hr.0019`` — лист графа hr и одна из ``SHARED_EFFECT_MIGRATIONS``:
    после полного прогона она отмечена применённой (без выполнения). Откат
    ровно на один шаг (target — предыдущая миграция) даёт план из ОДНОГО
    обратного шага, и этот шаг попадает не в ``steps``, а в ``shared`` —
    ``_split_plan`` кладёт ключи из SHARED_EFFECT_MIGRATIONS туда. До
    исправления сухой прогон проверял на обратное направление только
    ``steps`` (пустой здесь) и молча отчитывался «нечего делать», хотя тот
    же вызов без ``plan=True`` уже отказывал ``BackwardsMigrationRefused``
    (см. ``_refuse_backwards(shared)`` в боевой ветке).
    """
    migration_service.migrate_company("t-alpha")
    assert ("hr", "0019_identity_sync_periodic_task") in \
        migration_service.SHARED_EFFECT_MIGRATIONS

    with pytest.raises(migration_service.BackwardsMigrationRefused):
        migration_service.migrate_company(
            "t-alpha", app_label="hr",
            target="0018_identityapprover_identitychangerequest_and_more",
            plan=True,
        )


@pytest.mark.django_db(transaction=True)
def test_failed_run_records_error_and_cleans_up(alpha, monkeypatch):
    """Путь ошибки: строка версии с last_error, путь сброшен, замок снят.

    Самый хрупкий участок модуля — замыкание, восстанавливающее search_path
    ПЕРЕД записью в public, и глушитель поверх него. Без теста утверждение
    «last_error реально пишется» остаётся утверждением.
    """
    from django.db.migrations.executor import MigrationExecutor

    def explode(self, targets, plan=None, **kwargs):
        # Колбэк дёргается руками: он и определяет, в чью строку ляжет
        # ошибка, а настоящий прогон до него не дойдёт.
        self.progress_callback("apply_start", plan[0][0], False)
        raise RuntimeError("миграция не задалась")

    monkeypatch.setattr(MigrationExecutor, "migrate", explode)

    with pytest.raises(RuntimeError, match="миграция не задалась"):
        migration_service.migrate_company("t-alpha")

    rows = CompanySchemaVersion.objects.filter(company=alpha)
    assert rows.count() == 1, "ошибка помечается у той аппки, на которой упало"
    assert "RuntimeError: миграция не задалась" in rows[0].last_error

    with connection.cursor() as cur:
        cur.execute("SHOW search_path")
        assert cur.fetchone()[0] == "public"
    assert _advisory_locks_held() == 0


@pytest.mark.django_db(transaction=True)
def test_version_row_is_zeroed_when_app_left_the_schema(alpha):
    """Строка версии обязана врать не больше, чем схема.

    Аппка, у которой в схеме не осталось ни одной применённой миграции,
    получает ПУСТУЮ фактическую версию, а не сохраняет прежнюю. Иначе
    CompanySchemaVersion утверждала бы, что схема на такой-то версии, при
    пустой схеме — то есть скрывала бы ровно то отставание, ради видимости
    которого заведена.
    """
    migration_service.migrate_company("t-alpha", app_label="tasks")
    assert CompanySchemaVersion.objects.get(
        company=alpha, app_label="tasks",
    ).applied_migration

    # Схема заведена заново — в ней пусто, хотя строка версии осталась.
    schema_service.drop_schema("t-alpha")
    schema_service.create_schema("t-alpha")
    migration_service.migrate_company("t-alpha", app_label="signoff")

    assert CompanySchemaVersion.objects.get(
        company=alpha, app_label="tasks",
    ).applied_migration == ""
    assert CompanySchemaVersion.objects.get(
        company=alpha, app_label="signoff",
    ).applied_migration
    # А аппка, которой в схеме не было НИКОГДА, строки не заводит: «версии
    # нет» и «версия пуста» — разные утверждения.
    assert not CompanySchemaVersion.objects.filter(
        company=alpha, app_label="contracts",
    ).exists()


class _FakeExecutor:
    """План задаётся руками: настоящий Django такой ситуации не создаёт."""

    def __init__(self, plan):
        self._plan = plan

    def migration_plan(self, targets):
        return self._plan


def _step(app_label, name, backwards=False):
    return (SimpleNamespace(app_label=app_label, name=name), backwards)


def test_split_plan_refuses_foreign_migrations():
    """Фильтр плана не имеет права срезать молча.

    Сегодня нетенантные миграции до плана не доходят — они помечены
    применёнными. Но если завтра появится нетенантная миграция, зависящая от
    тенантной, беззвучный срез увёл бы схему в расхождение. Это ровно тот
    класс, из которого выросли SHARED_EFFECT_MIGRATIONS.
    """
    plan = [_step("hr", "0002_x"), _step("cms", "0007_y")]
    tenant = frozenset({"hr", "tasks", "contracts", "signoff"})

    with pytest.raises(migration_service.ForeignMigrationInPlan) as info:
        migration_service._split_plan(_FakeExecutor(plan), [], tenant, strict=True)
    assert "cms.0007_y" in str(info.value)

    # Сухой прогон отметок не ставит, поэтому нетенантные шаги в его плане
    # штатны и просто не показываются.
    steps, shared = migration_service._split_plan(
        _FakeExecutor(plan), [], tenant, strict=False,
    )
    assert [m.name for m, _ in steps] == ["0002_x"]
    assert shared == []

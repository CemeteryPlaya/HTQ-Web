"""Прогон миграций Django по схемам компаний.

ГЛАВНОЕ, ради чего этот модуль существует отдельно от штатной команды
migrate: у каждой компании должно быть СВОЁ состояние миграций. Если Django
во время прогона находит public.django_migrations, он пишет состояние туда —
и все компании начинают считать себя мигрированными вместе, при полностью
пустых схемах. Ошибка молчаливая и проявляется только на первом запросе к
несуществующей таблице, поэтому она закреплена тестом
test_each_schema_gets_its_own_migration_state.

Изоляция достигается так. Сначала соединение переводится в схему компании
БЕЗ public и там создаётся собственная django_migrations
(``_isolate_migration_state``) — это единственный момент, когда public обязан
отсутствовать: Django ищет таблицу по видимости имени и при public в пути
нашёл бы общую, а свою не создал бы. Только после этого public добавляется
в search_path ВТОРЫМ, и таблица компании ЗАТЕНЯЕТ общую: неквалифицированное
имя Postgres разрешает по первой схеме пути, а pg_table_is_visible (по нему
Django перечисляет таблицы) для public-копии становится ложным. Состояние
читается и пишется в схему компании.

Почему public всё-таки в пути, а не выброшен совсем. Две тенантные миграции
зависят от django_celery_beat — аппки НЕтенантной, живущей в public: hr.0019
и tasks.0003 заводят периодические задачи. Расписание у платформы одно на
всех, beat читает его из public, поэтому вторая копия этих таблиц в схеме
компании была бы мёртвым грузом, а без public в пути миграции просто падают
на несуществующей таблице. С public вторым в пути их SQL разрешается туда,
где эти таблицы уже есть и где им место.

Обратная сторона решения названа прямо: тенантная миграция, обратившаяся к
общей таблице, здесь не упадёт, а тихо сработает по public. Инвариант
«межаппных FK нет» это ограничивает, но не отменяет; CREATE TABLE при этом
безопасен всегда — он идёт в ПЕРВУЮ схему пути, то есть в схему компании.
Из этой же обратной стороны выросли две защиты: закрытое обратное
направление (``BackwardsMigrationRefused``) и список
``SHARED_EFFECT_MIGRATIONS`` — см. их докстринги.

Миграции нетенантных аппок в схеме компании помечаются применёнными без
выполнения (``_adopt_shared_state``). Причина не косметическая: Django
собирает состояние проекта перед прогоном ТОЛЬКО из применённых миграций
(MigrationExecutor._migrate_all_forwards, в отличие от отката, состояние
пропущенных шагов не доигрывает), поэтому без этих отметок hr.0019 получил
бы состояние без моделей django_celery_beat и упал бы на
``apps.get_model("django_celery_beat", ...)``. Смысл отметки честный:
«для этой схемы миграция считается применённой, её таблицы живут в public».
Побочно это же убирает нетенантные шаги из плана — иначе Django завёл бы их
таблицы в схеме компании.

Схема обязана существовать ДО прогона (``SchemaMissing``). Postgres создаёт
таблицу в первой СУЩЕСТВУЮЩЕЙ схеме search_path: не будь этой проверки,
пропущенный create_schema привёл бы не к ошибке, а к укладке всего набора
тенантных таблиц в public поверх общих.

Блокировка — advisory lock на уровне сессии Postgres, а не строка в таблице:
одновременная выкатка двух контейнеров backend-web — обычное дело, а
advisory lock снимается автоматически при обрыве соединения, тогда как
строка-семафор осталась бы висеть навсегда.
"""

from __future__ import annotations

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

from htqweb.fallback import fallback
from htqweb.tenancy.context import current_company_or_none
from htqweb.tenancy.db import apply_search_path

from ..models import Company, CompanySchemaVersion
from .schema_service import schema_exists

# Произвольная, но фиксированная константа: два процесса должны выбирать
# один и тот же ключ, иначе блокировка не блокирует.
ADVISORY_LOCK_KEY = 0x48545143  # "HTQC"

# Тенантные по принадлежности, но по эффекту — общие: это data-миграции,
# которые не создают в схеме компании ничего, а пишут в public
# (django_celery_beat). Их эффект глобален и уже достигнут обычным
# manage.py migrate; повторное выполнение на каждую компанию — чистый
# побочный эффект, причём вредный: defaults в обеих несут enabled=True и
# crontab, то есть заведение новой компании молча вернуло бы выключенную
# оператором задачу и сбросило бы изменённое им расписание.
#
# Поэтому они помечаются применёнными, но НЕ выполняются. Отметка ставится
# ПОСЛЕ прогона, а не заранее вместе с нетенантными: hr.0019 — лист графа
# hr, а лист, помеченный применённым заранее, уводит
# MigrationExecutor.migration_plan в ветку отката (``elif target in
# applied``), где детей у листа нет и план выходит ПУСТЫМ — hr не
# мигрировался бы вовсе.
SHARED_EFFECT_MIGRATIONS = frozenset({
    ("hr", "0019_identity_sync_periodic_task"),
    ("tasks", "0003_tasks_periodic_tasks"),
})


class SchemaMissing(RuntimeError):
    """Схемы компании нет — мигрировать некуда (см. докстринг модуля)."""


class BackwardsMigrationRefused(RuntimeError):
    """Откат схемы компании через этот модуль запрещён.

    Не «пока не реализован», а именно запрещён: реверс тенантных
    data-миграций выполняется по public (public второй в search_path), и
    откат ОДНОЙ компании удалил бы платформенные строки PeriodicTask —
    выключив периодические задачи всей группы. Пока это не покрыто тестами
    и не осмыслено отдельно, направление закрыто.

    Откатить схему одной компании можно вручную: выставить search_path на
    неё и вызвать manage.py migrate <app> <migration>.
    """


class ForeignMigrationInPlan(RuntimeError):
    """В плане прогона оказался шаг, которому в схеме компании не место.

    Сегодня такого не бывает: нетенантные миграции помечаются применёнными
    до построения плана и в него не попадают. Но если завтра появится
    нетенантная миграция, зависящая от тенантной, молчаливый фильтр урезал
    бы план — и схема разъехалась бы без единого следа. Это ровно тот класс
    ошибок, из которого выросли SHARED_EFFECT_MIGRATIONS.
    """


def _acquire_lock() -> None:
    with connection.cursor() as cur:
        cur.execute("SELECT pg_advisory_lock(%s)", [ADVISORY_LOCK_KEY])


def _release_lock() -> None:
    with connection.cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(%s)", [ADVISORY_LOCK_KEY])
        released = cur.fetchone()[0]
    if not released:
        # Значит, снимаем не в той сессии, в которой брали: соединение
        # пересоздалось посреди прогона. Само по себе не опасно (оборванная
        # сессия отдаёт свои блокировки), но означает, что взаимного
        # исключения между процессами в этот прогон не было.
        fallback("companies.migration.lock_not_held", None,
                 reason="pg_advisory_unlock вернул false: блокировку брало "
                        "другое соединение",
                 expected=True, key=ADVISORY_LOCK_KEY)


def _cleanup(step: str, action) -> None:
    """Уборка, которой запрещено заслонять настоящую ошибку прогона.

    Если миграция упала, соединение может остаться в оборванной транзакции,
    где ЛЮБОЙ следующий запрос — включая SET и снятие блокировки — тоже
    падает. Такой вторичный сбой не должен подменять собой причину, но и
    исчезать бесследно не имеет права: продолжение после проглоченного
    исключения — это подмена по определению из CLAUDE.md, поэтому она идёт
    через общий примитив (htqweb/fallback.py), а не через голый except.
    ``expected=True`` — путь предусмотренный, но редкий: strict-режим на нём
    не падает, зато подмена видна в логе и в htqweb_fallback_total.
    """
    try:
        action()
    except Exception as exc:
        fallback("companies.migration.cleanup_failed", None,
                 reason="уборка после прогона миграций не отработала",
                 exc=exc, expected=True, step=step)


def _isolate_migration_state(slug: str) -> None:
    """Завести django_migrations в схеме компании, пока public не в пути."""
    apply_search_path(slug, include_public=False)
    MigrationRecorder(connection).ensure_schema()


def _mark_applied(keys) -> int:
    """Отметить миграции применёнными в схеме компании, НЕ выполняя их.

    Возвращает число добавленных отметок — по нему вызывающий понимает,
    надо ли перечитывать граф.
    """
    recorder = MigrationRecorder(connection)
    known = set(recorder.applied_migrations())
    missing = sorted(key for key in keys if key not in known)
    if missing:
        # bulk_create, а не record_applied в цикле: отметок полторы сотни, и
        # это ровно один раз на компанию.
        Migration = recorder.Migration
        recorder.migration_qs.bulk_create(
            [Migration(app=app, name=name) for app, name in missing]
        )
    return len(missing)


def _adopt_shared_state(loader, tenant_apps: frozenset[str]) -> int:
    """Принять состояние нетенантных аппок как есть (см. докстринг модуля)."""
    return _mark_applied(key for key in loader.graph.nodes
                         if key[0] not in tenant_apps)


def _targets(loader, app_labels: tuple[str, ...], target: str | None) -> list[tuple]:
    if target is None:
        return sorted(n for n in loader.graph.leaf_nodes() if n[0] in app_labels)
    # "zero" (откатить аппку целиком) распознаётся не ради поддержки, а ради
    # внятного отказа: без этой строки Django упал бы на «нет такой
    # миграции», а с ней получается честный BackwardsMigrationRefused.
    return [(app_labels[0], None if target == "zero" else target)]


def _split_plan(executor: MigrationExecutor, targets: list[tuple],
                tenant_apps: frozenset[str], *, strict: bool) -> tuple[list, list]:
    """Разложить план на «выполнить» и «пометить применённым».

    ``strict=True`` (боевой прогон) требует, чтобы срезать было нечего сверх
    SHARED_EFFECT_MIGRATIONS: нетенантные шаги к этому моменту уже помечены
    применёнными и в плане появиться не могут. ``strict=False`` — сухой
    прогон, где отметки намеренно не проставлены, поэтому нетенантные шаги
    в плане штатны и просто не показываются.
    """
    steps: list = []
    shared: list = []
    foreign: list = []
    for step in executor.migration_plan(targets):
        migration = step[0]
        key = (migration.app_label, migration.name)
        if key in SHARED_EFFECT_MIGRATIONS:
            shared.append(step)
        elif migration.app_label in tenant_apps:
            steps.append(step)
        else:
            foreign.append(step)
    if strict and foreign:
        raise ForeignMigrationInPlan(
            "В плане прогона схемы компании оказались нетенантные миграции: "
            + ", ".join(f"{m.app_label}.{m.name}" for m, _ in foreign)
            + ". Их таблицы живут в public: выполнять их здесь нельзя, а "
              "молча выбросить — значит разъехаться со схемой."
        )
    return steps, shared


def _refuse_backwards(steps: list) -> None:
    """Не выпустить обратный план дальше построения (см. исключение)."""
    backwards = [m for m, is_backwards in steps if is_backwards]
    if backwards:
        raise BackwardsMigrationRefused(
            "Откат схемы компании запрещён, а план получился обратным: "
            + ", ".join(f"{m.app_label}.{m.name}" for m in backwards)
            + ". Реверс тенантных data-миграций выполнился бы по public и "
              "выключил бы периодические задачи всей группы."
        )


def _app_versions(loader, applied: set[tuple[str, str]],
                  tenant_apps: frozenset[str]) -> dict[str, tuple[str, str]]:
    """{аппка: (фактическая миграция, целевая)} по состоянию текущей схемы.

    Аппка без единой применённой миграции попадает сюда с ПУСТОЙ фактической
    версией, а не пропускается. Пропуск оставил бы в CompanySchemaVersion
    прежнее значение — то есть строка утверждала бы, что схема на такой-то
    версии, при пустой схеме. Ровно то отставание, ради видимости которого
    таблица заведена, оказалось бы скрыто.

    «Фактическая» ищется по топологическому порядку графа, а не как max()
    по имени: порядок задаётся зависимостями, и склейка (squash) или
    нестандартный префикс имени не должны превращать отставание в
    «всё применено».
    """
    versions: dict[str, tuple[str, str]] = {}
    for app_label in sorted(tenant_apps):
        leaves = sorted(n for n in loader.graph.leaf_nodes() if n[0] == app_label)
        if not leaves:
            continue
        leaf = leaves[-1]
        ordered = [n for n in loader.graph.forwards_plan(leaf) if n[0] == app_label]
        done = [n[1] for n in ordered if n in applied]
        versions[app_label] = (done[-1] if done else "", leaf[1])
    return versions


def _record_versions(company: Company, versions: dict[str, tuple[str, str]]) -> None:
    """Записать версии схемы. Строка заводится только для живых аппок.

    Пустая фактическая версия и отсутствие строки — разные вещи: первая
    означает «в схеме этой аппки не осталось», вторая — «мы про неё ничего
    не утверждаем». Заводить строку на аппку, которой в схеме никогда не
    было, незачем; а вот ОБНУЛИТЬ уже существующую, если применённых
    миграций не осталось, обязательно — иначе строка продолжит утверждать
    прежнюю версию при пустой схеме.
    """
    for app_label, (applied, target) in versions.items():
        exists = CompanySchemaVersion.objects.filter(
            company=company, app_label=app_label,
        ).exists()
        if not applied and not exists:
            continue
        CompanySchemaVersion.objects.update_or_create(
            company=company, app_label=app_label,
            defaults={
                "applied_migration": applied,
                "target_migration": target,
                "last_run_at": timezone.now(),
                "last_error": "",
            },
        )


def _record_failure(company: Company, app_labels: list[str], error: str) -> None:
    """Отметить неудачу, не затирая уже известную фактическую версию."""
    for app_label in app_labels:
        CompanySchemaVersion.objects.update_or_create(
            company=company, app_label=app_label,
            defaults={"last_run_at": timezone.now(), "last_error": error},
        )


class _LastStarted:
    """Последняя НАЧАТАЯ миграция — по ней видно, на чём прогон упал.

    Нужна, чтобы ошибка попадала в строку той аппки, которая её вызвала, а
    не размазывалась по всем аппкам плана, включая те, до которых прогон не
    дошёл. MigrationExecutor зовёт колбэк и без миграции ("render_start"),
    поэтому аргументы необязательные.
    """

    def __init__(self) -> None:
        self.migration = None

    def __call__(self, action: str, migration=None, fake: bool = False) -> None:
        if action == "apply_start":
            self.migration = migration


def migrate_company(slug: str, *, app_label: str | None = None,
                    target: str | None = None, plan: bool = False) -> dict:
    """Довести схему компании до целевой версии.

    ``app_label`` сужает прогон до одной аппки, ``target`` — до конкретной
    миграции (expand/contract). Направление ТОЛЬКО вперёд: план, оказавшийся
    обратным, отвергается (``BackwardsMigrationRefused``). ``plan=True`` даёт
    сухой прогон: возвращает список того, что применилось бы, ничего не меняя.

    Возвращает ``{"slug", "applied": {аппка: миграция}, "planned": [строки]}``.
    ``applied`` — фактическое состояние схемы ПОСЛЕ прогона по тем тенантным
    аппкам, у которых в схеме что-то есть, а не перечень тронутого: сужение
    до одной аппки всё равно тянет её тенантные зависимости (signoff тянет
    hr), и умолчать о них значило бы оставить CompanySchemaVersion
    расходящимся с реальностью. ``planned`` — только то, что будет
    ВЫПОЛНЕНО; SHARED_EFFECT_MIGRATIONS туда не попадают, потому что
    помечаются применёнными без выполнения.
    """
    tenant_apps = frozenset(settings.TENANT_APPS)
    if app_label is not None and app_label not in tenant_apps:
        raise ValueError(
            f"{app_label!r} не тенантная аппка; в схеме компании живут только "
            f"{', '.join(sorted(tenant_apps))}."
        )
    if target is not None and app_label is None:
        raise ValueError("target без app_label неоднозначен: укажите аппку.")

    company = Company.objects.get(slug=slug)
    if not schema_exists(slug):
        raise SchemaMissing(
            f"Схемы компании {slug!r} не существует. Сначала create_schema."
        )

    app_labels = (app_label,) if app_label else tuple(settings.TENANT_APPS)
    # Восстанавливается ПРЕЖНИЙ путь, а не public: прогон может идти внутри
    # уже открытого use_company (та же логика, что в use_holding), и жёсткий
    # сброс оставил бы contextvar и реальный search_path соединения в
    # расхождении — запросы вызывающего молча ушли бы в public.
    previous = current_company_or_none()

    _acquire_lock()
    try:
        if plan:
            # Сухой прогон не пишет НИЧЕГО, поэтому и django_migrations в
            # схеме не заводит. public при этом обязан быть вне пути: иначе
            # пустая схема прочитала бы состояние public и честно отчиталась
            # «всё применено» — ровно та молчаливая ошибка, ради которой
            # существует модуль.
            apply_search_path(slug, include_public=False)
            executor = MigrationExecutor(connection)
            targets = _targets(executor.loader, app_labels, target)
            steps, _shared = _split_plan(executor, targets, tenant_apps,
                                         strict=False)
            _refuse_backwards(steps)
            return {"slug": slug, "applied": {},
                    "planned": [f"{m.app_label}.{m.name}" for m, _ in steps]}

        _isolate_migration_state(slug)
        # Теперь public можно вернуть: django_migrations компании затеняет
        # общую, а нетенантные таблицы разрешаются в public.
        apply_search_path(slug)

        progress = _LastStarted()
        executor = MigrationExecutor(connection, progress_callback=progress)
        if _adopt_shared_state(executor.loader, tenant_apps):
            # Загрузчик кэширует applied_migrations на момент сборки графа —
            # после дописанных отметок его нужно перечитать, иначе план
            # окажется построенным по устаревшему состоянию.
            executor.loader.build_graph()

        targets = _targets(executor.loader, app_labels, target)
        steps, shared = _split_plan(executor, targets, tenant_apps, strict=True)
        _refuse_backwards(steps)
        _refuse_backwards(shared)
        planned = [f"{m.app_label}.{m.name}" for m, _ in steps]

        try:
            if steps:
                executor.migrate(targets, plan=steps)
            # Отметка ПОСЛЕ прогона: зависимости этих миграций к этому
            # моменту применены, а сами они выполнению не подлежат.
            _mark_applied((m.app_label, m.name) for m, _ in shared)
            # Состояние перечитывается из БД, а не берётся из загрузчика: тот
            # знает его на момент сборки графа, то есть ДО прогона.
            applied_keys = set(MigrationRecorder(connection).applied_migrations())
            versions = _app_versions(executor.loader, applied_keys, tenant_apps)
        except Exception as exc:
            def mark_failure() -> None:
                # CompanySchemaVersion лежит в public, а во время прогона
                # его не видно, поэтому путь восстанавливается здесь, ДО
                # записи, а не в finally. Повтор там безвреден.
                apply_search_path(previous)
                failed = progress.migration
                touched = ([failed.app_label] if failed is not None
                           else sorted({m.app_label for m, _ in steps})
                           or list(app_labels))
                _record_failure(company, touched, f"{type(exc).__name__}: {exc}")

            _cleanup("отметка неудачи прогона", mark_failure)
            raise
    finally:
        _cleanup("сброс search_path", lambda: apply_search_path(previous))
        _cleanup("снятие advisory lock", _release_lock)

    _record_versions(company, versions)

    return {
        "slug": slug,
        "applied": {label: applied for label, (applied, _t) in versions.items()
                    if applied},
        "planned": planned,
    }

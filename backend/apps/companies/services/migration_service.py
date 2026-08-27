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

import logging

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

from htqweb.tenancy.context import current_company_or_none
from htqweb.tenancy.db import apply_search_path

from ..models import Company, CompanySchemaVersion
from .schema_service import schema_exists

logger = logging.getLogger(__name__)

# Произвольная, но фиксированная константа: два процесса должны выбирать
# один и тот же ключ, иначе блокировка не блокирует.
ADVISORY_LOCK_KEY = 0x48545143  # "HTQC"


class SchemaMissing(RuntimeError):
    """Схемы компании нет — мигрировать некуда (см. докстринг модуля)."""


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
        logger.warning(
            "pg_advisory_unlock(%s) вернул false: блокировку брало другое "
            "соединение", ADVISORY_LOCK_KEY,
        )


def _quietly(what: str, action) -> None:
    """Уборка, которой запрещено заслонять настоящую ошибку прогона.

    Если миграция упала, соединение может остаться в оборванной транзакции,
    где ЛЮБОЙ следующий запрос — включая SET и снятие блокировки — тоже
    падает. Такой вторичный сбой не должен подменять собой причину, поэтому
    он только логируется.
    """
    try:
        action()
    except Exception:
        logger.exception("Не удалось выполнить: %s", what)


def _isolate_migration_state(slug: str) -> None:
    """Завести django_migrations в схеме компании, пока public не в пути."""
    apply_search_path(slug, include_public=False)
    MigrationRecorder(connection).ensure_schema()


def _adopt_shared_state(loader, tenant_apps: frozenset[str]) -> int:
    """Отметить миграции нетенантных аппок применёнными в схеме компании.

    Ничего не выполняет — только пишет строки в django_migrations схемы.
    Зачем это нужно, см. докстринг модуля. Возвращает число добавленных
    отметок, чтобы вызывающий знал, надо ли перечитывать граф.
    """
    recorder = MigrationRecorder(connection)
    known = set(recorder.applied_migrations())
    missing = [key for key in loader.graph.nodes
               if key[0] not in tenant_apps and key not in known]
    if missing:
        # bulk_create, а не record_applied в цикле: отметок полторы сотни, и
        # это ровно один раз на компанию.
        Migration = recorder.Migration
        recorder.migration_qs.bulk_create(
            [Migration(app=app, name=name) for app, name in sorted(missing)]
        )
    return len(missing)


def _targets(loader, app_labels: tuple[str, ...], target: str | None) -> list[tuple]:
    if target is None:
        return sorted(n for n in loader.graph.leaf_nodes() if n[0] in app_labels)
    # "zero" — язык самой команды migrate: откатить аппку целиком.
    return [(app_labels[0], None if target == "zero" else target)]


def _tenant_plan(executor: MigrationExecutor, targets: list[tuple],
                 tenant_apps: frozenset[str]) -> list[tuple]:
    """План прогона, из которого выброшено всё нетенантное.

    После ``_adopt_shared_state`` фильтр обычно ничего не отсеивает — он
    нужен режиму ``plan=True``, где отметки намеренно не ставятся (сухой
    прогон не имеет права ничего писать), и служит страховкой в остальных.
    """
    return [
        step for step in executor.migration_plan(targets)
        if step[0].app_label in tenant_apps
    ]


def _app_versions(loader, applied: set[tuple[str, str]],
                  tenant_apps: frozenset[str]) -> dict[str, tuple[str, str]]:
    """{аппка: (фактическая миграция, целевая)} по состоянию текущей схемы.

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
        if not done:
            # Аппки в этой схеме нет вовсе — строку версии не заводим, чтобы
            # «не мигрировали» и «мигрировали» не выглядели одинаково.
            continue
        versions[app_label] = (done[-1], leaf[1])
    return versions


def _record(company: Company, app_label: str, applied: str, target: str) -> None:
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


def migrate_company(slug: str, *, app_label: str | None = None,
                    target: str | None = None, plan: bool = False) -> dict:
    """Довести схему компании до целевой версии.

    ``app_label`` сужает прогон до одной аппки, ``target`` — до конкретной
    миграции (для отката вперёд-назад в expand/contract; ``"zero"`` — откат
    аппки целиком). ``plan=True`` даёт сухой прогон: возвращает список того,
    что применилось бы, ничего не меняя.

    Возвращает ``{"slug", "applied": {аппка: миграция}, "planned": [строки]}``.
    ``applied`` — фактическое состояние схемы ПОСЛЕ прогона по всем тенантным
    аппкам, а не перечень тронутого: сужение до одной аппки всё равно тянет
    её тенантные зависимости (signoff тянет hr), и умолчать о них значило бы
    оставить CompanySchemaVersion расходящимся с реальностью.
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
            steps = _tenant_plan(executor, targets, tenant_apps)
            return {"slug": slug, "applied": {},
                    "planned": [f"{m.app_label}.{m.name}" for m, _ in steps]}

        _isolate_migration_state(slug)
        # Теперь public можно вернуть: django_migrations компании затеняет
        # общую, а нетенантные таблицы разрешаются в public.
        apply_search_path(slug)

        executor = MigrationExecutor(connection)
        if _adopt_shared_state(executor.loader, tenant_apps):
            # Загрузчик кэширует applied_migrations на момент сборки графа —
            # после дописанных отметок его нужно перечитать, иначе план
            # окажется построенным по устаревшему состоянию.
            executor.loader.build_graph()

        targets = _targets(executor.loader, app_labels, target)
        steps = _tenant_plan(executor, targets, tenant_apps)
        planned = [f"{m.app_label}.{m.name}" for m, _ in steps]

        touched = sorted({m.app_label for m, _ in steps}) or list(app_labels)
        try:
            if steps:
                executor.migrate(targets, plan=steps)
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
                _record_failure(company, touched, f"{type(exc).__name__}: {exc}")

            _quietly("отметка неудачи прогона", mark_failure)
            raise
    finally:
        _quietly("сброс search_path", lambda: apply_search_path(previous))
        _quietly("снятие advisory lock", _release_lock)

    for label, (applied_name, target_name) in versions.items():
        _record(company, label, applied_name, target_name)

    return {
        "slug": slug,
        "applied": {label: names[0] for label, names in versions.items()},
        "planned": planned,
    }

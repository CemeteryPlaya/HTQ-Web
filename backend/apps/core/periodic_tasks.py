"""Реестр периодических задач тенантных аппок и их заведение в ``public``.

Зачем он нужен. Расписания ``hr``/``tasks``/``signoff``/``bpp`` заводят
data-миграции ЭТИХ аппок (``SHARED_EFFECT_MIGRATIONS`` в
``apps/companies/services/migration_service.py``), а пишут они в
``django_celery_beat`` — общую аппку в ``public``. На живом стеке ни одна из
них не выполняется: старт контейнера зовёт ``migrate_shared``, который
тенантные аппки пропускает целиком, а ``migrate_companies`` помечает эти
миграции применёнными БЕЗ выполнения (иначе каждая компания заново включала
бы выключенную оператором задачу и сбрасывала его расписание). Только голый
``manage.py migrate`` (pytest) их реально выполнял — поэтому на dev, стенде и
проде не было ни ночной сверки «Задействовано» (и алерт на её устаревание не
мог сработать — результата не писал никто), ни уборки разборов выписки, ни
повтора «Нет исполнителя».

Теперь их конечное состояние описано здесь одной таблицей данных, а
``ensure_periodic_tasks`` заводит недостающие строки — из ``migrate_shared``
на каждом старте и командой ``manage.py ensure_periodic_tasks`` вручную.

Правила.

- Только недостающие. Существующая строка ``PeriodicTask`` (по ``name``) не
  меняется ни в расписании, ни в ``enabled``: её мог выключить или
  перенастроить оператор, и старт контейнера не вправе это откатывать.
  Единственное исключение — ``legacy_tasks``: строка, заведённая ещё голым
  ``migrate`` до перевода на диспетчеров, указывает на задачу, которая без
  ``company_slug`` падает ``MissingCompanyArgument``. Такой строке меняется
  только путь задачи (и описание вместе с ним) — ровно то, что сделала бы
  пропущенная миграция перевода (hr/0020, tasks/0019); расписание и
  ``enabled`` остаются операторскими.
- Реестр — КОНЕЧНОЕ состояние, а не история: переименования и переводы
  (hr/0020, tasks/0019) уже сведены в записи.
- Только строки-данные: пути задач — строки, код соседних аппок отсюда не
  импортируется (``test_app_isolation``). Что пути реально зарегистрированы в
  Celery и что реестр совпадает с итогом миграций, сторожит
  ``apps/core/tests/test_periodic_tasks.py``.
- Новая data-миграция тенантной аппки, пишущая строку расписания, обязана
  попасть и сюда, и в ``SHARED_EFFECT_MIGRATIONS`` — иначе на живом стеке её
  задачи не будет.

Периодика общих аппок (``core``, ``mail``, ``media_files``, ``messenger``,
``conference``, ``notifications``, ``refdata``) сюда не входит: их миграции
выполняет сам ``migrate_shared``.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction


@dataclass(frozen=True)
class Crontab:
    minute: str
    hour: str
    day_of_week: str = "*"
    day_of_month: str = "*"
    month_of_year: str = "*"
    # Явно, а не умолчанием модели: hr/0019 заводила crontab без пояса, и он
    # получал CELERY_TIMEZONE (UTC) — реестр не должен зависеть от настройки.
    timezone: str = "UTC"


@dataclass(frozen=True)
class Interval:
    every: int
    period: str  # значение IntervalSchedule.period: "minutes", "hours", …


@dataclass(frozen=True)
class PeriodicTaskSpec:
    name: str
    task: str
    schedule: Crontab | Interval
    description: str
    enabled: bool = True
    # Пути, на которые строка указывала до перевода на диспетчера (см.
    # докстринг модуля) — их чинит ensure_periodic_tasks.
    legacy_tasks: tuple[str, ...] = ()


PERIODIC_TASKS: tuple[PeriodicTaskSpec, ...] = (
    # hr/0019 + hr/0020 — ночная сверка идентичности, диспетчер по компаниям.
    PeriodicTaskSpec(
        name="hr.sync_identity",
        task="apps.hr.tasks.sync_identity_dispatch",
        schedule=Crontab(minute="30", hour="3"),
        description=(
            "Диспетчер сверки кадровой копии идентичности с аккаунтами: "
            "без компании, веером ставит sync_identity на каждую "
            "действующую компанию (company_slug именованным аргументом)."
        ),
        legacy_tasks=("apps.hr.tasks.sync_identity",),
    ),
    # tasks/0003 + tasks/0019 — напоминания о сроках задач, каждый час.
    PeriodicTaskSpec(
        name="tasks.task_deadline_reminder",
        task="apps.tasks.tasks.task_deadline_reminder_dispatch",
        schedule=Crontab(minute="0", hour="*"),
        description=(
            "Dispatcher: no company of its own, fans "
            "task_deadline_reminder out to every active company "
            "(company_slug as a named argument)."
        ),
        legacy_tasks=("apps.tasks.tasks.task_deadline_reminder",),
    ),
    # tasks/0003 + tasks/0019 — напоминания о событиях календаря, раз в 5 минут.
    PeriodicTaskSpec(
        name="tasks.calendar_event_reminder",
        task="apps.tasks.tasks.calendar_event_reminder_dispatch",
        schedule=Crontab(minute="*/5", hour="*"),
        description=(
            "Dispatcher: no company of its own, fans "
            "calendar_event_reminder out to every active company "
            "(company_slug as a named argument)."
        ),
        legacy_tasks=("apps.tasks.tasks.calendar_event_reminder",),
    ),
    # signoff/0014 — повтор поиска исполнителей этапам «Нет исполнителя».
    PeriodicTaskSpec(
        name="signoff.retry_no_executor",
        task="apps.signoff.tasks.retry_no_executor_dispatch",
        schedule=Interval(every=15, period="minutes"),
        description=(
            "Повторный поиск исполнителей этапам «Нет исполнителя» (ТЗ §16.1 "
            "п.5): диспетчер без компании, веером по действующим компаниям."
        ),
    ),
    # bpp/0004 — ночная сверка «Задействовано», 02:30 по Алматы.
    PeriodicTaskSpec(
        name="bpp.committed_check",
        task="apps.bpp.tasks.committed_check_dispatch",
        schedule=Crontab(minute="30", hour="2", timezone="Asia/Almaty"),
        description=(
            "Ночная сверка «Задействовано» по статьям бюджетов (CALC-002): "
            "агрегат против пересчёта по позициям, расхождение — алерт."
        ),
    ),
    # bpp/0012 — уборка потерянных разборов выписки, раз в 10 минут.
    PeriodicTaskSpec(
        name="bpp.bank_import_reaper",
        task="apps.bpp.tasks_bank.reap_stale_imports_dispatch",
        schedule=Interval(every=10, period="minutes"),
        description=(
            "Загрузки выписок, чей разбор не закончился за 15 минут, — в «Ошибка "
            "загрузки» с отменой строк: диспетчер без компании, веером по "
            "действующим компаниям."
        ),
    ),
)


def _schedule_fields(schedule: Crontab | Interval) -> dict:
    """Строка расписания для ``PeriodicTask`` — существующая или новая."""
    from django_celery_beat.models import CrontabSchedule, IntervalSchedule

    if isinstance(schedule, Crontab):
        row, _ = CrontabSchedule.objects.get_or_create(
            minute=schedule.minute, hour=schedule.hour,
            day_of_week=schedule.day_of_week,
            day_of_month=schedule.day_of_month,
            month_of_year=schedule.month_of_year,
            timezone=schedule.timezone,
        )
        return {"crontab": row}
    row, _ = IntervalSchedule.objects.get_or_create(
        every=schedule.every, period=schedule.period,
    )
    return {"interval": row}


def ensure_periodic_tasks(*, stdout=None) -> dict:
    """Завести недостающие периодические задачи реестра в ``public``.

    Возвращает ``{"created": [...], "repaired": [...], "kept": [...]}`` —
    имена по порядку реестра. Существующие строки не трогаются (кроме
    починки пути из ``legacy_tasks``, см. докстринг модуля).

    Таблицы ``django_celery_beat`` живут только в ``public``; если вызов
    пришёл изнутри контекста компании, путь на время переводится в чистый
    ``public`` и затем восстанавливается.
    """
    from django_celery_beat.models import PeriodicTask

    from htqweb.tenancy.context import current_company_or_none
    from htqweb.tenancy.db import apply_search_path

    result: dict[str, list[str]] = {"created": [], "repaired": [], "kept": []}
    previous = current_company_or_none()
    if previous is not None:
        apply_search_path(None)
    try:
        with transaction.atomic():
            for spec in PERIODIC_TASKS:
                row = PeriodicTask.objects.filter(name=spec.name).first()
                if row is None:
                    PeriodicTask.objects.create(
                        name=spec.name,
                        task=spec.task,
                        enabled=spec.enabled,
                        description=spec.description,
                        **_schedule_fields(spec.schedule),
                    )
                    result["created"].append(spec.name)
                elif row.task in spec.legacy_tasks:
                    row.task = spec.task
                    row.description = spec.description
                    row.save(update_fields=["task", "description"])
                    result["repaired"].append(spec.name)
                else:
                    result["kept"].append(spec.name)
    finally:
        if previous is not None:
            apply_search_path(previous)

    if stdout is not None:
        for name in result["created"]:
            stdout.write(f"  периодическая задача заведена: {name}")
        for name in result["repaired"]:
            stdout.write(f"  периодическая задача переведена на диспетчера: {name}")
    return result

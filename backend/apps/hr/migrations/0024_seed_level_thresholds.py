"""Сид уровней N-1…N-4 для НОВОЙ схемы компании (блок D, roadmap §5.D).

Без порогов ``position_service._compute_level`` отдаёт запасной уровень 5
каждой должности, и оргструктура новой компании схлопывается в один ярус.
Сид — единственное место, где уровни появляются раньше кадровика.

Два условия, оба обязательны:

* **только в схеме компании** — ``migrate_company`` не ставит контекст
  компании, поэтому «где я» читается из ``search_path``; в боевом прогоне
  путь выглядит как ``co_<slug>, public``, и схема компании всегда ПЕРВАЯ —
  отсюда проверка по первому элементу. ``public`` — это pytest-база, dev до
  ``tenancy_bootstrap`` и боевая HTQ до переноса; засеять туда значило бы
  подменить данные ETL и сломать тесты, заводящие уровень 1 с нуля;
* **только в пустую таблицу** — у HTQ пороги уже есть от ETL: no-op.

``search_path`` читается через ``schema_editor.connection``, а не глобальный
``django.db.connection``: при ``migrate --database=...`` страж иначе
прочитал бы путь не того соединения. Та же причина — ``.using(...)`` при
чтении и записи модели ниже.

Обратной операции нет намеренно: ``migrate_companies`` откатов не делает
(«только ВПЕРЁД»), а отличить засеянные строки от правленных потом нельзя.

После сева порогов пересчитывается кэш ``Position.level``: это тот же
самый кэш, который читает ``org_service`` напрямую (цвет уровня на схеме),
и штатный путь правки порогов (``position_service._recompute_all_levels``)
его пересчитывает — сеющая пороги миграция обязана делать то же самое,
иначе схема, где должности уже есть, а порогов ещё не было, получит
пороги, но должности останутся на уровне 5, которого больше нет.
Аудит веса (``_record_weight_audit`` в ``position_service``) здесь
намеренно не пишется: у миграции нет ни пользователя, ни HTTP-запроса, от
чьего имени фиксировать «кто поменял уровень», — это системная
инициализация схемы, а не решение кадровика.

Копия ``LEVELS`` живёт в ``apps/hr/management/group_structures.py`` для
демо-сида; тест ``test_group_structures.py`` держит их равными. Миграция
не импортирует код аппки: её содержимое обязано быть заморожено.
"""

from django.db import migrations

from htqweb.tenancy.context import SCHEMA_PREFIX

# (level_number, weight_from, weight_to, label, color)
# N-4 доходит до 1999: верх шкалы старого сида и next-weight — ни один вес не
# должен проваливаться в запасной уровень.
LEVELS = [
    (1, 0, 99, "N-1", "#7c3aed"),
    (2, 100, 299, "N-2", "#2563eb"),
    (3, 300, 599, "N-3", "#0891b2"),
    (4, 600, 1999, "N-4", "#059669"),
]

# Копия position_service._DEFAULT_LEVEL — миграция не импортирует код аппки
# и обязана быть заморожена; используется только как запасной уровень для
# веса, не попавшего ни в один порог (тот же смысл, что и в app-коде).
_DEFAULT_LEVEL = 5


def _level_for(weight: int) -> int:
    return next((n for n, w_from, w_to, *_ in LEVELS if w_from <= weight <= w_to), _DEFAULT_LEVEL)


def _in_company_schema(connection) -> bool:
    with connection.cursor() as cur:
        cur.execute("SHOW search_path")
        (path,) = cur.fetchone()
    first = path.split(",")[0].strip().strip('"')
    return first.startswith(SCHEMA_PREFIX)


def _recompute_position_levels(apps, using: str) -> None:
    """Обновить кэш ``Position.level`` по только что засеянным порогам.

    Если должностей в схеме ещё нет (обычный случай новой компании) —
    цикл просто ничего не находит, это нормально.
    """
    Position = apps.get_model("hr", "Position")
    for pos in Position.objects.using(using).all():
        level = _level_for(pos.weight)
        if pos.level != level:
            Position.objects.using(using).filter(pk=pos.pk).update(level=level)


def seed(apps, schema_editor):
    connection = schema_editor.connection
    if not _in_company_schema(connection):
        return
    LevelThreshold = apps.get_model("hr", "LevelThreshold")
    thresholds = LevelThreshold.objects.using(connection.alias)
    if thresholds.exists():
        return
    thresholds.bulk_create([
        LevelThreshold(level_number=number, weight_from=w_from, weight_to=w_to,
                       label=label, color=color)
        for number, w_from, w_to, label, color in LEVELS
    ])
    _recompute_position_levels(apps, connection.alias)


class Migration(migrations.Migration):

    dependencies = [("hr", "0023_alter_department_unit_type")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]

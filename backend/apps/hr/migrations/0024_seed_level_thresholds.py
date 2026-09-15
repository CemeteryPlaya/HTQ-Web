"""Сид уровней N-1…N-4 для НОВОЙ схемы компании (блок D, roadmap §5.D).

Без порогов ``position_service._compute_level`` отдаёт запасной уровень 5
каждой должности, и оргструктура новой компании схлопывается в один ярус.
Сид — единственное место, где уровни появляются раньше кадровика.

Два условия, оба обязательны:

* **только в схеме компании** — ``migrate_company`` не ставит контекст
  компании (только ``search_path`` без ``public``), поэтому «где я» читается
  из ``search_path``. ``public`` — это pytest-база, dev до
  ``tenancy_bootstrap`` и боевая HTQ до переноса; засеять туда значило бы
  подменить данные ETL и сломать тесты, заводящие уровень 1 с нуля;
* **только в пустую таблицу** — у HTQ пороги уже есть от ETL: no-op.

Обратной операции нет намеренно: ``migrate_companies`` откатов не делает
(«только ВПЕРЁД»), а отличить засеянные строки от правленных потом нельзя.

Копия ``LEVELS`` живёт в ``apps/hr/management/group_structures.py`` для
демо-сида; тест ``test_group_structures.py`` держит их равными. Миграция
не импортирует код аппки: её содержимое обязано быть заморожено.
"""

from django.db import connection, migrations

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


def _in_company_schema() -> bool:
    with connection.cursor() as cur:
        cur.execute("SHOW search_path")
        (path,) = cur.fetchone()
    first = path.split(",")[0].strip().strip('"')
    return first.startswith(SCHEMA_PREFIX)


def seed(apps, schema_editor):
    if not _in_company_schema():
        return
    LevelThreshold = apps.get_model("hr", "LevelThreshold")
    if LevelThreshold.objects.exists():
        return
    LevelThreshold.objects.bulk_create([
        LevelThreshold(level_number=number, weight_from=w_from, weight_to=w_to,
                       label=label, color=color)
        for number, w_from, w_to, label, color in LEVELS
    ])


class Migration(migrations.Migration):

    dependencies = [("hr", "0023_alter_department_unit_type")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]

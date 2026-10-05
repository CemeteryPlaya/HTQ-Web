"""Начальный справочник проектных ролей (спек 2026-10-06 §2.1, §6).

Приём ``hr/0024_seed_level_thresholds``, оба условия обязательны:

* **только в схеме компании** — ``migrate_companies`` контекст компании не
  ставит, поэтому «где я» читается из ``search_path``: в боевом прогоне схема
  компании в нём первая. ``public`` — pytest-база и dev до
  ``tenancy_bootstrap``: засеянная туда роль мешала бы тестам, заводящим
  справочник с нуля;
* **только в пустую таблицу** — справочник, который уже правили, не трогаем.

Обратной операции нет намеренно: ``migrate_companies`` идёт только вперёд, а
засеянную роль от поправленной потом не отличить. Миграция не импортирует
код аппки — её содержимое заморожено.
"""

from django.db import migrations

from htqweb.tenancy.context import SCHEMA_PREFIX

# (название, уровень, часть по умолчанию, порядок)
ROLES = [
    ("Руководитель проекта (ГД)", 1, "office", 10),
    ("Заместитель директора", 2, "office", 20),
    ("Технический директор", 2, "office", 30),
    ("Специалист", 3, "office", 40),
    ("Рабочий", 4, "site", 50),
]


def _in_company_schema(connection) -> bool:
    with connection.cursor() as cur:
        cur.execute("SHOW search_path")
        (path,) = cur.fetchone()
    first = path.split(",")[0].strip().strip('"')
    return first.startswith(SCHEMA_PREFIX)


def seed(apps, schema_editor):
    connection = schema_editor.connection
    if not _in_company_schema(connection):
        return
    roles = apps.get_model("project", "ProjectRole").objects.using(connection.alias)
    if roles.exists():
        return
    roles.bulk_create([
        roles.model(name=name, level=level, default_part=part, sort_order=order)
        for name, level, part, order in ROLES
    ])


class Migration(migrations.Migration):

    dependencies = [("project", "0004_project_structure")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]

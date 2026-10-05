"""«Проекты»: «Код в 1С» хранится только в нижнем регистре (D-S8-4).

Уникальность ``uq_project_ext_1c`` (``0002``) регистрозависима: GUID,
введённый мимо сервиса (django-admin, ORM) заглавными, её обходил. Порядок:

1. дубли непустых значений БЕЗ учёта регистра — стоп ``RuntimeError`` с
   перечнем (до 50 ключей): приведение к нижнему регистру их склеило бы, а
   какая из записей настоящая, решает человек; миграция ничего не удаляет;
2. ``UPDATE … SET ext_1c_ref = lower(ext_1c_ref)`` для непустых значений не
   в нижнем регистре, число приведённых строк печатается по схеме. Правка
   идёт мимо сервиса владельца: подписчики изменений «Проекта» (доска
   задач) не уведомляются, журнала нет (значение то же, меняется только
   написание);
3. ``CheckConstraint`` ``ck_project_ext_1c_lower`` — дальше верхний регистр
   в БД не попадает (ORM — ``IntegrityError``, django-admin — ошибка формы).

Откат снимает только ограничение, данные остаются в нижнем регистре
(``RunPython.noop``). Тенантная аппка, expand: на бою — шаг
``migrate_companies``, в схеме каждой компании."""

from django.db import migrations, models
from django.db.models.functions import Lower


def _schema(schema_editor) -> str:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT current_schema()")
        return cursor.fetchone()[0]


def refuse_case_duplicates(apps, schema_editor):
    model = apps.get_model("project", "Project")
    rows = (model.objects.exclude(ext_1c_ref="").annotate(key=Lower("ext_1c_ref"))
            .values("key").annotate(n=models.Count("pk")).filter(n__gt=1).order_by("key"))
    total = rows.count()
    found = [f"{row['key']} — {row['n']} записей" for row in rows[:50]]
    if total > len(found):
        found.append(f"… и ещё {total - len(found)}")
    if found:
        raise RuntimeError(
            "«Проекты»: есть непустые «Код в 1С», совпадающие без учёта регистра; "
            "к нижнему регистру не приведены. Исправьте записи и повторите миграцию:\n"
            + "\n".join(found))


def lowercase_refs(apps, schema_editor):
    model = apps.get_model("project", "Project")
    changed = (model.objects.exclude(ext_1c_ref="")
               .exclude(ext_1c_ref=Lower("ext_1c_ref"))
               .update(ext_1c_ref=Lower("ext_1c_ref")))
    print(f"\n  «Проекты» [{_schema(schema_editor)}]: «Код в 1С» приведено к нижнему "
          f"регистру: {changed}")


class Migration(migrations.Migration):

    dependencies = [
        ('project', '0002_ext_1c_unique'),
    ]

    operations = [
        migrations.RunPython(refuse_case_duplicates, migrations.RunPython.noop),
        migrations.RunPython(lowercase_refs, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='project',
            constraint=models.CheckConstraint(condition=models.Q(('ext_1c_ref', Lower('ext_1c_ref'))), name='ck_project_ext_1c_lower', violation_error_message='«Код в 1С» хранится в нижнем регистре (GUID строчными буквами).'),
        ),
    ]

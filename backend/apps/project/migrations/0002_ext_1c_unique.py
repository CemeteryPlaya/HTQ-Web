"""«Проекты»: ключ записи в 1С уникален среди непустых (A7.3, D-S7-5).

Expand: ограничение частичное, пустые значения не затрагивает. Перед ним —
проверка дублей непустых значений: есть дубли — стоп с перечнем, правят
руками (какая из записей настоящая, решает человек), миграция ничего не
удаляет. Идёт в схеме каждой компании (``migrate_companies``)."""

from django.db import migrations, models


def refuse_duplicates(apps, schema_editor):
    model = apps.get_model("project", "Project")
    rows = (model.objects.exclude(ext_1c_ref="").values("ext_1c_ref")
            .annotate(n=models.Count("pk")).filter(n__gt=1).order_by("ext_1c_ref"))
    found = [f"{row['ext_1c_ref']} — {row['n']} записей" for row in rows[:50]]
    if found:
        raise RuntimeError(
            "«Проекты»: есть повторяющиеся непустые «Код в 1С», ограничение уникальности "
            "не наложено. Исправьте записи и повторите миграцию:\n" + "\n".join(found))


class Migration(migrations.Migration):

    dependencies = [
        ('project', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(refuse_duplicates, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='project',
            constraint=models.UniqueConstraint(condition=models.Q(('ext_1c_ref', ''), _negated=True), fields=('ext_1c_ref',), name='uq_project_ext_1c'),
        ),
    ]

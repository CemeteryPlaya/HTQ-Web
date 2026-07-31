"""Ресурсы: план количеством (``ResourceRequirement``) + факт именами.

``TaskAssignment`` ПЕРЕИМЕНОВЫВАЕТСЯ в ``ResourceAllocation``, а не
удаляется и создаётся заново: в таблице лежат живые назначения, и
``DeleteModel`` + ``CreateModel``, которые сгенерировал бы
``makemigrations``, снесли бы их молча. Отсюда и ручная миграция.

Порядок операций не косметический:

1. переименование модели (и таблицы) — до всего, что ссылается на новое имя;
2. ``task`` становится nullable — назначение теперь может висеть на роудмапе;
3. ``ResourceRequirement`` создаётся раньше, чем на неё появляется FK;
4. старый ``uq_task_assignment`` снимается и ставится заново по четырём
   полям с ``nulls_distinct=False`` — иначе на роудмап-строках, где ``task``
   всегда NULL, он ничего не гарантирует.
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [("tasks", "0010_roadmap")]

    operations = [
        migrations.RenameModel(old_name="TaskAssignment",
                               new_name="ResourceAllocation"),
        migrations.RemoveConstraint(model_name="resourceallocation",
                                    name="uq_task_assignment"),
        migrations.AlterField(
            model_name="resourceallocation", name="task",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="resource_assignments", to="tasks.task"),
        ),
        migrations.AddField(
            model_name="resourceallocation", name="roadmap",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="resource_assignments", to="tasks.roadmap"),
        ),
        migrations.CreateModel(
            name="ResourceRequirement",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("kind", models.CharField(
                    choices=[("human", "Человек"), ("equipment", "Техника")],
                    db_index=True, max_length=20)),
                ("quantity", models.PositiveSmallIntegerField(db_default=1,
                                                              default=1)),
                ("start_date", models.DateField(blank=True, null=True)),
                ("end_date", models.DateField(blank=True, null=True)),
                ("note", models.CharField(blank=True, max_length=255,
                                          null=True)),
                ("created_at", models.DateTimeField(
                    auto_now_add=True,
                    db_default=models.functions.Now())),
                ("updated_at", models.DateTimeField(
                    auto_now=True, db_default=models.functions.Now())),
                ("equipment_category", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="requirements",
                    to="tasks.equipmentcategory")),
                ("roadmap", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="requirements", to="tasks.roadmap")),
                ("task", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="requirements", to="tasks.task")),
                ("work_role", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="requirements", to="tasks.workrole")),
            ],
        ),
        migrations.AddField(
            model_name="resourceallocation", name="requirement",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="allocations", to="tasks.resourcerequirement"),
        ),
        migrations.AddConstraint(
            model_name="resourceallocation",
            constraint=models.CheckConstraint(
                condition=models.Q(("roadmap__isnull", False),
                                   ("task__isnull", True))
                | models.Q(("roadmap__isnull", True), ("task__isnull", False)),
                name="ck_allocation_exactly_one_target"),
        ),
        migrations.AddConstraint(
            model_name="resourceallocation",
            constraint=models.UniqueConstraint(
                fields=("task", "roadmap", "employee_id", "equipment"),
                name="uq_task_assignment", nulls_distinct=False),
        ),
        migrations.AddConstraint(
            model_name="resourcerequirement",
            constraint=models.CheckConstraint(
                condition=models.Q(("roadmap__isnull", True),
                                   ("task__isnull", False))
                | models.Q(("roadmap__isnull", False), ("task__isnull", True)),
                name="ck_requirement_exactly_one_target"),
        ),
        migrations.AddConstraint(
            model_name="resourcerequirement",
            constraint=models.CheckConstraint(
                condition=models.Q(("equipment_category__isnull", True),
                                   ("kind", "human"))
                | models.Q(("kind", "equipment"), ("work_role__isnull", True)),
                name="ck_requirement_kind_fields"),
        ),
        migrations.AddConstraint(
            model_name="resourcerequirement",
            constraint=models.CheckConstraint(
                condition=models.Q(("start_date__isnull", True))
                | models.Q(("end_date__isnull", True))
                | models.Q(("start_date__lte", models.F("end_date"))),
                name="ck_requirement_dates"),
        ),
    ]

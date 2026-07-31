"""Ежедневные отчёты + перенос факта из ``TaskVolume.completed_quantity``.

Факт выполнения перестаёт быть числом на строке объёма и становится лентой
отчётов с датой ВЫПОЛНЕНИЯ работ. Из этого растут S-кривая, темп и прогноз —
всё, чего у числа без даты быть не могло.

**Порядок операций отличается от сгенерированного, и это важно.**
``makemigrations`` ставит ``RemoveField completed_quantity`` ДО того, как у
``DailyReport`` появятся внешние ключи, то есть переносить накопленный факт
было бы уже некуда и не из чего. Здесь таблицы отчётов создаются целиком,
затем идёт перенос, и только потом колонка удаляется.

**Что делает перенос.** Каждое ненулевое ``completed_quantity`` становится
одним отчётом. Дата берётся по убыванию достоверности:
``task.due_date`` → ``task.start_date`` → дата применения миграции, — и это
единственная выдумка во всей операции, поэтому она названа прямо в
комментарии отчёта. Альтернатива — молча выбросить числа — хуже на порядок:
блок, показывавший 72%, стал бы показывать 0, и никто бы не понял, почему.

Ревизия 1 пишется тем же порядком, что и обычному отчёту: лента правок
должна начинаться с исходного состояния, даже если оно приехало из миграции.

Необратима намеренно. Обратный ход должен был бы схлопнуть ленту отчётов
обратно в одно число, потеряв даты, авторов и историю правок, — то есть
сделать ровно то, ради отмены чего миграция и написана. Откатывать нужно
восстановлением из бэкапа, а не притворством, что данные складываются назад.
"""

import datetime as dt

import django.db.models.deletion
import django.db.models.functions.datetime
from django.db import migrations, models


def carry_over_completed(apps, schema_editor):
    TaskVolume = apps.get_model("tasks", "TaskVolume")
    DailyReport = apps.get_model("tasks", "DailyReport")
    DailyReportRevision = apps.get_model("tasks", "DailyReportRevision")

    today = dt.date.today()
    rows = (TaskVolume.objects
            .filter(completed_quantity__gt=0)
            .values("task_id", "volume_type_id", "completed_quantity",
                    "task__due_date", "task__start_date"))

    for row in rows:
        report = DailyReport.objects.create(
            task_id=row["task_id"],
            volume_type_id=row["volume_type_id"],
            author_id=None,
            work_date=(row["task__due_date"] or row["task__start_date"]
                       or today),
            quantity=row["completed_quantity"],
            comment="Перенесено из TaskVolume.completed_quantity при переходе "
                    "на ежедневные отчёты. Дата выполнения выведена из сроков "
                    "задачи и может быть неточной — уточните её.",
            current_revision=1,
        )
        DailyReportRevision.objects.create(
            report=report, revision_no=1, work_date=report.work_date,
            quantity=report.quantity, headcount=None,
            comment=report.comment, edited_by_id=None,
        )


class Migration(migrations.Migration):

    dependencies = [("tasks", "0013_project_calendar_mode")]

    operations = [
        migrations.CreateModel(
            name="DailyReport",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("author_id", models.IntegerField(blank=True, db_index=True,
                                                  null=True)),
                ("work_date", models.DateField(db_index=True)),
                ("quantity", models.DecimalField(decimal_places=2,
                                                 max_digits=12)),
                ("headcount", models.PositiveSmallIntegerField(blank=True,
                                                               null=True)),
                ("comment", models.TextField(blank=True, db_default="",
                                             default="")),
                ("current_revision", models.PositiveSmallIntegerField(
                    db_default=1, default=1)),
                ("is_deleted", models.BooleanField(db_default=False,
                                                   db_index=True,
                                                   default=False)),
                ("created_at", models.DateTimeField(
                    auto_now_add=True,
                    db_default=django.db.models.functions.datetime.Now())),
                ("updated_at", models.DateTimeField(
                    auto_now=True,
                    db_default=django.db.models.functions.datetime.Now())),
                ("task", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="daily_reports", to="tasks.task")),
                ("volume_type", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="daily_reports", to="tasks.workvolumetype")),
            ],
        ),
        migrations.CreateModel(
            name="DailyReportRevision",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("revision_no", models.PositiveSmallIntegerField()),
                ("work_date", models.DateField()),
                ("quantity", models.DecimalField(decimal_places=2,
                                                 max_digits=12)),
                ("headcount", models.PositiveSmallIntegerField(blank=True,
                                                               null=True)),
                ("comment", models.TextField(blank=True, db_default="",
                                             default="")),
                ("edited_by_id", models.IntegerField(blank=True, null=True)),
                ("edited_at", models.DateTimeField(
                    auto_now_add=True,
                    db_default=django.db.models.functions.datetime.Now())),
                ("report", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="revisions", to="tasks.dailyreport")),
            ],
            options={"ordering": ["revision_no"]},
        ),
        migrations.AddIndex(
            model_name="dailyreport",
            index=models.Index(fields=["task", "work_date"],
                               name="ix_daily_report_task_date"),
        ),
        migrations.AddConstraint(
            model_name="dailyreport",
            constraint=models.CheckConstraint(
                condition=models.Q(("quantity__gte", 0)),
                name="ck_daily_report_quantity_non_negative"),
        ),
        migrations.AddConstraint(
            model_name="dailyreportrevision",
            constraint=models.UniqueConstraint(
                fields=("report", "revision_no"),
                name="uq_daily_report_revision"),
        ),

        # Перенос — строго между созданием таблиц и удалением колонки.
        migrations.RunPython(carry_over_completed,
                             migrations.RunPython.noop),

        migrations.RemoveConstraint(model_name="taskvolume",
                                    name="ck_task_volume_non_negative"),
        migrations.RemoveField(model_name="taskvolume",
                               name="completed_quantity"),
        migrations.AddConstraint(
            model_name="taskvolume",
            constraint=models.CheckConstraint(
                condition=models.Q(("planned_quantity__gte", 0)),
                name="ck_task_volume_non_negative"),
        ),
    ]

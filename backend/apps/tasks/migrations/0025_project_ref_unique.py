"""Одна доска задач на «Проект» БЗО. Отдельно от связывания (0024): индекс
строится в своей транзакции, после того как данные уже сведены."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0024_link_boards_to_projects"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="project",
            constraint=models.UniqueConstraint(
                condition=models.Q(("project_ref", ""), _negated=True),
                fields=("project_ref",), name="uq_task_project_ref"),
        ),
    ]

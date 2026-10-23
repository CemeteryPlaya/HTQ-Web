"""Признак «новая задача» у исполнителя (канбан K-28, мастер-план §3.3).

Expand: столбец допускает ``NULL``, старый код вставляет строки без него.
Существующим строкам ``seen_at = assigned_at`` одним ``UPDATE`` — иначе после
выкатки у каждого все старые задачи стали бы «новыми». Тенантная аппка: на
бою — шагом ``migrate_companies``.
"""

from django.db import migrations, models
from django.db.models import F


def mark_existing_seen(apps, schema_editor):
    TaskAssignee = apps.get_model("tasks", "TaskAssignee")
    TaskAssignee.objects.filter(seen_at__isnull=True).update(seen_at=F("assigned_at"))


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0028_board_card_rank'),
    ]

    operations = [
        migrations.AddField(
            model_name='taskassignee',
            name='seen_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(mark_existing_seen, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name='taskassignee',
            index=models.Index(condition=models.Q(('seen_at__isnull', True)), fields=['user_id'], name='ix_task_assignee_unseen'),
        ),
    ]

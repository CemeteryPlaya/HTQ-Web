"""Чек-листы задачи (решение K-20, мастер-план канбана §3.6).

Две новые таблицы; порядок чек-листов и пунктов — дробный ранг в
``COLLATE "C"``, как у карточек доски. Тенантная аппка: на бою — шагом
``migrate_companies``.
"""

import django.db.models.deletion
import django.db.models.functions.datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0030_board_settings'),
    ]

    operations = [
        migrations.CreateModel(
            name='TaskChecklist',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('position', models.CharField(db_collation='C', max_length=64)),
                ('created_by_id', models.IntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_default=django.db.models.functions.datetime.Now())),
                ('updated_at', models.DateTimeField(auto_now=True, db_default=django.db.models.functions.datetime.Now())),
                ('task', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='checklists', to='tasks.task')),
            ],
            options={
                'verbose_name': 'Чек-лист задачи',
                'verbose_name_plural': 'Чек-листы задач',
                'indexes': [models.Index(fields=['task', 'position'], name='ix_task_checklist_order')],
            },
        ),
        migrations.CreateModel(
            name='TaskChecklistItem',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('text', models.CharField(max_length=500)),
                ('is_done', models.BooleanField(db_default=False, default=False)),
                ('done_by_id', models.IntegerField(blank=True, null=True)),
                ('done_at', models.DateTimeField(blank=True, null=True)),
                ('position', models.CharField(db_collation='C', max_length=64)),
                ('created_by_id', models.IntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_default=django.db.models.functions.datetime.Now())),
                ('updated_at', models.DateTimeField(auto_now=True, db_default=django.db.models.functions.datetime.Now())),
                ('checklist', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='tasks.taskchecklist')),
            ],
            options={
                'verbose_name': 'Пункт чек-листа',
                'verbose_name_plural': 'Пункты чек-листов',
                'indexes': [models.Index(fields=['checklist', 'position'], name='ix_checklist_item_order')],
                'constraints': [models.CheckConstraint(condition=models.Q(models.Q(('done_at__isnull', False), ('is_done', True)), models.Q(('done_at__isnull', True), ('done_by_id__isnull', True), ('is_done', False)), _connector='OR'), name='ck_checklist_item_done')],
            },
        ),
    ]

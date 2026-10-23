"""Настройки досок: названия, цвета и скрытость колонок-статусов (решение K-34).

Новая таблица; строка доски заводится при первом сохранении настроек.
Тенантная аппка: на бою — шагом ``migrate_companies``.
"""

import django.db.models.functions.datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0029_assignee_seen_at'),
    ]

    operations = [
        migrations.CreateModel(
            name='BoardSettings',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('board_kind', models.CharField(choices=[('personal', 'Personal'), ('department', 'Department'), ('project', 'Project')], max_length=12)),
                ('board_id', models.IntegerField()),
                ('columns', models.JSONField(blank=True, default=dict)),
                ('updated_by', models.IntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_default=django.db.models.functions.datetime.Now())),
                ('updated_at', models.DateTimeField(auto_now=True, db_default=django.db.models.functions.datetime.Now())),
            ],
            options={
                'verbose_name': 'Настройки доски',
                'verbose_name_plural': 'Настройки досок',
                'constraints': [models.UniqueConstraint(fields=('board_kind', 'board_id'), name='uq_board_settings')],
            },
        ),
    ]

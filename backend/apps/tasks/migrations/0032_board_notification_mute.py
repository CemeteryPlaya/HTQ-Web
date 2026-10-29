"""Выключенные уведомления по доске (решение K-30, мастер-план канбана §3.4).

Новая таблица: строка есть — уведомления о своих задачах этой доски выключены.
Тенантная аппка: на бою — шагом ``migrate_companies``.
"""

import django.db.models.functions.datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0031_checklists'),
    ]

    operations = [
        migrations.CreateModel(
            name='BoardNotificationMute',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('board_kind', models.CharField(choices=[('personal', 'Personal'), ('department', 'Department'), ('project', 'Project')], max_length=12)),
                ('board_id', models.IntegerField()),
                ('user_id', models.IntegerField(db_index=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_default=django.db.models.functions.datetime.Now())),
            ],
            options={
                'verbose_name': 'Выключенные уведомления доски',
                'verbose_name_plural': 'Выключенные уведомления досок',
                'constraints': [models.UniqueConstraint(fields=('board_kind', 'board_id', 'user_id'), name='uq_board_notification_mute')],
            },
        ),
    ]

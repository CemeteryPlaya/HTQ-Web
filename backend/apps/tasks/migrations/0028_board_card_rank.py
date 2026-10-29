"""Порядок карточек на досках (канбан-доски, этап S1; мастер-план §3.2).

Новая таблица: старый код её не знает и не трогает. Бэкфилла нет — строка
появляется при первом переносе или быстром добавлении карточки. Тенантная
аппка: на бою — шагом ``migrate_companies``.
"""

import django.db.models.deletion
import django.db.models.functions.datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0027_department_link_kind'),
    ]

    operations = [
        migrations.CreateModel(
            name='BoardCardRank',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('board_kind', models.CharField(choices=[('personal', 'Personal'), ('department', 'Department'), ('project', 'Project')], max_length=12)),
                ('board_id', models.IntegerField()),
                ('rank', models.CharField(db_collation='C', max_length=64)),
                ('updated_at', models.DateTimeField(auto_now=True, db_default=django.db.models.functions.datetime.Now())),
                ('task', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='board_ranks', to='tasks.task')),
            ],
            options={
                'verbose_name': 'Порядок карточки на доске',
                'verbose_name_plural': 'Порядок карточек на досках',
                'indexes': [models.Index(fields=['board_kind', 'board_id', 'rank'], name='ix_board_card_order')],
                'constraints': [models.UniqueConstraint(fields=('board_kind', 'board_id', 'task'), name='uq_board_card_rank')],
            },
        ),
    ]

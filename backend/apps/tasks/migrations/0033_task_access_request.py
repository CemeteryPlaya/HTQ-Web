"""Запросы доступа к задаче (решения K-31, K-32, мастер-план канбана §3.5).

Новая таблица; ожидающий запрос уникален по задаче, запросившему и виду.
Тенантная аппка: на бою — шагом ``migrate_companies``.
"""

import django.db.models.deletion
import django.db.models.functions.datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0032_board_notification_mute'),
    ]

    operations = [
        migrations.CreateModel(
            name='TaskAccessRequest',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('requester_id', models.IntegerField(db_index=True)),
                ('kind', models.CharField(choices=[('execute', 'На исполнение'), ('own', 'На владение')], max_length=10)),
                ('comment', models.TextField(blank=True, default='')),
                ('status', models.CharField(choices=[('pending', 'Ждёт решения'), ('approved', 'Одобрен'), ('rejected', 'Отклонён'), ('cancelled', 'Отозван')], db_default='pending', default='pending', max_length=10)),
                ('approve_mode', models.CharField(blank=True, choices=[('replace', 'С заменой'), ('delegate', 'Делегатом')], max_length=10, null=True)),
                ('replaced_user_id', models.IntegerField(blank=True, null=True)),
                ('decided_by_id', models.IntegerField(blank=True, null=True)),
                ('decided_at', models.DateTimeField(blank=True, null=True)),
                ('decision_comment', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_default=django.db.models.functions.datetime.Now())),
                ('updated_at', models.DateTimeField(auto_now=True, db_default=django.db.models.functions.datetime.Now())),
                ('task', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='access_requests', to='tasks.task')),
            ],
            options={
                'verbose_name': 'Запрос доступа к задаче',
                'verbose_name_plural': 'Запросы доступа к задачам',
                'indexes': [models.Index(fields=['status', 'created_at'], name='ix_task_access_request_status')],
                'constraints': [models.UniqueConstraint(condition=models.Q(('status', 'pending')), fields=('task', 'requester_id', 'kind'), name='uq_task_access_request_pending')],
            },
        ),
    ]

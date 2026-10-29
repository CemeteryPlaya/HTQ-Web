"""Логика автоматизаций досок (канбан, этап S4b; спецификация
docs/plans/2026-10-28-kanban-automation-logic.md).

Признак поломки и момент включения у ``AutomationRule``, правило у
``TaskComment``, статус журнала «пропущено» и таблица скрытых «Рекомендаций» —
expand. Тенантная аппка: на бою — шагом ``migrate_companies``.
"""

import django.db.models.functions.datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0036_automation_periodic_tasks'),
    ]

    operations = [
        migrations.AddField(
            model_name='automationrule',
            name='activated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='automationrule',
            name='broken_reason',
            field=models.CharField(blank=True, db_default='', default='', max_length=500),
        ),
        migrations.AddField(
            model_name='taskcomment',
            name='via_rule_id',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='automationrun',
            name='status',
            field=models.CharField(choices=[('ok', 'Ok'), ('no_match', 'No Match'), ('failed', 'Failed'), ('blocked', 'Blocked'), ('limited', 'Limited'), ('skipped', 'Skipped'), ('changed', 'Changed')], max_length=12),
        ),
        migrations.CreateModel(
            name='AutomationSuggestionDismissal',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('board_kind', models.CharField(choices=[('personal', 'Personal'), ('department', 'Department'), ('project', 'Project')], max_length=12)),
                ('board_id', models.IntegerField()),
                ('user_id', models.IntegerField()),
                ('key', models.CharField(max_length=80)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_default=django.db.models.functions.datetime.Now())),
            ],
            options={
                'verbose_name': 'Скрытая рекомендация автоматизации',
                'verbose_name_plural': 'Скрытые рекомендации автоматизации',
                'constraints': [models.UniqueConstraint(fields=('board_kind', 'board_id', 'user_id', 'key'), name='uq_automation_suggestion_dismissal')],
            },
        ),
    ]

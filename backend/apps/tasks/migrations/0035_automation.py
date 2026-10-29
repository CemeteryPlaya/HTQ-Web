"""Автоматизация досок (решения K-36…K-40, канбан, этап S4).

Новые таблицы ``AutomationRule``/``AutomationRun``/``AutomationDueMark`` и
пустой столбец ``TaskActivity.via_rule_id`` — expand. Тенантная аппка: на бою
— шагом ``migrate_companies``.
"""

import django.db.models.deletion
import django.db.models.functions.datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0034_board_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='taskactivity',
            name='via_rule_id',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name='AutomationRule',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('board_kind', models.CharField(choices=[('personal', 'Personal'), ('department', 'Department'), ('project', 'Project')], max_length=12)),
                ('board_id', models.IntegerField()),
                ('kind', models.CharField(choices=[('rule', 'Rule'), ('card_button', 'Card Button'), ('board_button', 'Board Button'), ('due', 'Due'), ('schedule', 'Schedule')], max_length=16)),
                ('name', models.CharField(blank=True, default='', max_length=200)),
                ('icon', models.CharField(blank=True, default='', max_length=32)),
                ('trigger', models.JSONField(blank=True, default=dict)),
                ('conditions', models.JSONField(blank=True, default=list)),
                ('actions', models.JSONField(blank=True, default=list)),
                ('enabled', models.BooleanField(default=True)),
                ('position', models.CharField(db_collation='C', max_length=64)),
                ('preset_key', models.CharField(blank=True, default='', max_length=64)),
                ('next_run_at', models.DateTimeField(blank=True, null=True)),
                ('state', models.JSONField(blank=True, default=dict)),
                ('created_by', models.IntegerField(blank=True, null=True)),
                ('updated_by', models.IntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_default=django.db.models.functions.datetime.Now())),
                ('updated_at', models.DateTimeField(auto_now=True, db_default=django.db.models.functions.datetime.Now())),
            ],
            options={
                'verbose_name': 'Автоматизация доски',
                'verbose_name_plural': 'Автоматизации досок',
                'indexes': [models.Index(fields=['board_kind', 'board_id', 'kind', 'position'], name='ix_automation_board')],
                'constraints': [models.UniqueConstraint(condition=models.Q(('preset_key', ''), _negated=True), fields=('board_kind', 'board_id', 'preset_key'), name='uq_automation_preset')],
            },
        ),
        migrations.CreateModel(
            name='AutomationDueMark',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('due_date', models.DateField()),
                ('created_at', models.DateTimeField(auto_now_add=True, db_default=django.db.models.functions.datetime.Now())),
                ('task', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='automation_due_marks', to='tasks.task')),
                ('rule', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='due_marks', to='tasks.automationrule')),
            ],
            options={
                'verbose_name': 'Срабатывание команды по сроку',
                'verbose_name_plural': 'Срабатывания команд по сроку',
                'constraints': [models.UniqueConstraint(fields=('rule', 'task', 'due_date'), name='uq_automation_due_mark')],
            },
        ),
        migrations.CreateModel(
            name='AutomationRun',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('board_kind', models.CharField(choices=[('personal', 'Personal'), ('department', 'Department'), ('project', 'Project')], max_length=12)),
                ('board_id', models.IntegerField()),
                ('rule_name', models.CharField(blank=True, default='', max_length=200)),
                ('event', models.CharField(blank=True, default='', max_length=40)),
                ('status', models.CharField(choices=[('ok', 'Ok'), ('no_match', 'No Match'), ('failed', 'Failed'), ('blocked', 'Blocked'), ('limited', 'Limited'), ('changed', 'Changed')], max_length=12)),
                ('actor_id', models.IntegerField(blank=True, null=True)),
                ('details', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_default=django.db.models.functions.datetime.Now())),
                ('rule', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='runs', to='tasks.automationrule')),
                ('task', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='automation_runs', to='tasks.task')),
            ],
            options={
                'verbose_name': 'Запуск автоматизации',
                'verbose_name_plural': 'Запуски автоматизации',
                'indexes': [models.Index(fields=['board_kind', 'board_id', 'created_at'], name='ix_automation_run_board'), models.Index(fields=['rule', 'created_at'], name='ix_automation_run_rule'), models.Index(fields=['created_at'], name='ix_automation_run_created')],
            },
        ),
    ]

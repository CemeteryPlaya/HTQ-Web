"""Свои поля досок и шаблоны чек-листов (решение K-35, канбан, этап S3).

Новые таблицы ``BoardField``/``TaskFieldValue`` и столбец
``BoardSettings.checklist_templates`` со значением по умолчанию — expand.
Тенантная аппка: на бою — шагом ``migrate_companies``.
"""

import django.db.models.deletion
import django.db.models.functions.datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0033_task_access_request'),
    ]

    operations = [
        migrations.AddField(
            model_name='boardsettings',
            name='checklist_templates',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.CreateModel(
            name='BoardField',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('board_kind', models.CharField(choices=[('personal', 'Personal'), ('department', 'Department'), ('project', 'Project')], max_length=12)),
                ('board_id', models.IntegerField()),
                ('name', models.CharField(max_length=100)),
                ('field_type', models.CharField(choices=[('text', 'Text'), ('number', 'Number'), ('date', 'Date'), ('checkbox', 'Checkbox'), ('list', 'List')], max_length=10)),
                ('options', models.JSONField(blank=True, default=list)),
                ('position', models.CharField(db_collation='C', max_length=64)),
                ('show_on_card', models.BooleanField(default=False)),
                ('created_by', models.IntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_default=django.db.models.functions.datetime.Now())),
                ('updated_at', models.DateTimeField(auto_now=True, db_default=django.db.models.functions.datetime.Now())),
            ],
            options={
                'verbose_name': 'Поле доски',
                'verbose_name_plural': 'Поля досок',
                'indexes': [models.Index(fields=['board_kind', 'board_id', 'position'], name='ix_board_field_board')],
                'constraints': [models.UniqueConstraint(fields=('board_kind', 'board_id', 'name'), name='uq_board_field_name')],
            },
        ),
        migrations.CreateModel(
            name='TaskFieldValue',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('value_text', models.TextField(blank=True, default='')),
                ('value_number', models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ('value_date', models.DateField(blank=True, null=True)),
                ('value_bool', models.BooleanField(blank=True, null=True)),
                ('value_option', models.CharField(blank=True, default='', max_length=16)),
                ('updated_by', models.IntegerField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True, db_default=django.db.models.functions.datetime.Now())),
                ('field', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='values', to='tasks.boardfield')),
                ('task', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='field_values', to='tasks.task')),
            ],
            options={
                'verbose_name': 'Значение поля задачи',
                'verbose_name_plural': 'Значения полей задач',
                'constraints': [models.UniqueConstraint(fields=('task', 'field'), name='uq_task_field_value')],
            },
        ),
    ]

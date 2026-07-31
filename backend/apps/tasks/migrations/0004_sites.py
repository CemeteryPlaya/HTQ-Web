"""Объекты (площадки) и их связь с проектами и задачами.

Всё аддитивно: новые таблицы плюс две nullable-колонки. Существующие
задачи остаются с ``site_id = NULL``, и бэкфилла здесь нет намеренно —
вывести объект исторической задачи не из чего, а выдуманное значение
отравило бы ровно ту отчётность, ради которой объекты и заводятся. «Без
объекта» — полноценная корзина в отчётах, как «Без отдела» рядом.

Отсюда же следует, что выкат однофазный: старый код просто не выбирает
новые колонки, поэтому миграцию можно применить, пока он ещё отвечает.

Правило «объект задачи входит в объекты её проекта» констрейнтом НЕ
выражено — оно охватывает три таблицы, а ``CheckConstraint`` видит одну
строку одной таблицы. Живёт в ``services/site_service.resolve_task_site``.
"""

import django.db.models.deletion
import django.db.models.functions.datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0003_tasks_periodic_tasks'),
    ]

    operations = [
        migrations.CreateModel(
            name='Site',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, unique=True)),
                ('code', models.CharField(blank=True, max_length=32, null=True, unique=True)),
                ('description', models.TextField(blank=True, db_default='', default='')),
                ('address', models.CharField(blank=True, max_length=500, null=True)),
                ('region', models.CharField(blank=True, max_length=120, null=True)),
                ('latitude', models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ('longitude', models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ('status', models.CharField(choices=[('active', 'Active'), ('suspended', 'Suspended'), ('closed', 'Closed')], db_default='active', db_index=True, default='active', max_length=20)),
                ('color', models.CharField(db_default='#0ea5e9', default='#0ea5e9', max_length=20)),
                ('department_id', models.IntegerField(blank=True, db_index=True, null=True)),
                ('manager_id', models.IntegerField(blank=True, db_index=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_default=django.db.models.functions.datetime.Now())),
                ('updated_at', models.DateTimeField(auto_now=True, db_default=django.db.models.functions.datetime.Now())),
            ],
        ),
        migrations.CreateModel(
            name='ProjectSite',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_primary', models.BooleanField(db_default=False, default=False)),
                ('start_date', models.DateField(blank=True, null=True)),
                ('end_date', models.DateField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_default=django.db.models.functions.datetime.Now())),
                ('updated_at', models.DateTimeField(auto_now=True, db_default=django.db.models.functions.datetime.Now())),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='site_links', to='tasks.project')),
                ('site', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='project_links', to='tasks.site')),
            ],
        ),
        migrations.AddField(
            model_name='project',
            name='sites',
            field=models.ManyToManyField(blank=True, related_name='projects', through='tasks.ProjectSite', to='tasks.site'),
        ),
        migrations.AddField(
            model_name='task',
            name='site',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tasks', to='tasks.site'),
        ),
        migrations.AddConstraint(
            model_name='projectsite',
            constraint=models.UniqueConstraint(fields=('project', 'site'), name='uq_project_site'),
        ),
        migrations.AddConstraint(
            model_name='projectsite',
            constraint=models.CheckConstraint(condition=models.Q(('start_date__isnull', True), ('end_date__isnull', True), ('start_date__lte', models.F('end_date')), _connector='OR'), name='ck_project_site_dates'),
        ),
    ]

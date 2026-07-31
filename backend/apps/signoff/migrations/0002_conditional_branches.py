"""Условные ветки маршрута.

Ветка — это группа этапов с одинаковым ``order``, из которой в процесс
попадают только те этапы, чьё ``condition`` сошлось на фактах предметного
объекта (``apps/signoff/services/conditions.py``).

Обратной совместимости ради значения по умолчанию выбраны так, чтобы
существующие маршруты не изменили поведения: ``condition = []`` — «этап нужен
всегда», ``is_fallback = false``, ``matched_by = 'always'``. Ни один
работающий маршрут этой миграцией не превращается в условный.

Данные не переносятся: ``subject_facts`` у процессов, запущенных до этой
миграции, остаётся пустым — фактов на момент их запуска никто не снимал, и
придумать их задним числом нельзя.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('signoff', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='approvalprocess',
            name='subject_facts',
            field=models.JSONField(blank=True, default=dict, verbose_name='Факты объекта'),
        ),
        migrations.AddField(
            model_name='approvalprocessstage',
            name='condition',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='approvalprocessstage',
            name='matched_by',
            field=models.CharField(db_default='always', default='always', max_length=16),
        ),
        migrations.AddField(
            model_name='approvalroutestage',
            name='condition',
            field=models.JSONField(blank=True, default=list, help_text='Пусто — этап нужен всегда', verbose_name='Условие'),
        ),
        migrations.AddField(
            model_name='approvalroutestage',
            name='is_fallback',
            field=models.BooleanField(db_default=False, default=False, help_text='Этап для случая, когда в группе не сошлось ни одно условие', verbose_name='Иначе'),
        ),
    ]

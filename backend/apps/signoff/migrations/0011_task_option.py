"""Голос за вариант на запросе согласования (мастер-план БЗО, задача B1.3).

Когда предметная аппка предлагает выбор (исходный документ или его
альтернатива, ТЗ §12.4), «согласовать» называет вариант — ключ и подпись
снимком хранятся на запросе.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('signoff', '0010_stage_requirement_key'),
    ]

    operations = [
        migrations.AddField(
            model_name='approvaltask',
            name='option_key',
            field=models.CharField(blank=True, db_default='', default='', max_length=64),
        ),
        migrations.AddField(
            model_name='approvaltask',
            name='option_label',
            field=models.CharField(blank=True, db_default='', default='', max_length=300),
        ),
    ]

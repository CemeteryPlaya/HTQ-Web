"""«Возвращено на доработку» — четвёртый исход круга согласования.

Одни ``AlterField``: ``choices`` в БД не хранятся, и колонки эта миграция не
трогает — она нужна ради того, чтобы состояние моделей в дереве миграций
совпадало с ``models.py`` (иначе следующий ``makemigrations`` в любой другой
аппке предложит её же). Данных к переносу тоже нет: значение ``rework``
появляется только у процессов, которые вернут на доработку после раскатки.

Смысл нового состояния — в ``models.ApprovalState``: возврат на доработку
единственный отпирает предметный объект для правки, тогда как согласованный
и отклонённый заперты одинаково.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('signoff', '0003_signature_stage_and_attachment'),
    ]

    operations = [
        migrations.AlterField(
            model_name='approvalprocess',
            name='state',
            field=models.CharField(choices=[('pending', 'На согласовании'), ('approved', 'Согласовано'), ('rejected', 'Отклонено'), ('rework', 'Возвращено на доработку'), ('cancelled', 'Отозвано')], db_default='pending', db_index=True, default='pending', max_length=16),
        ),
        migrations.AlterField(
            model_name='approvalprocessstage',
            name='state',
            field=models.CharField(choices=[('waiting', 'Ожидает очереди'), ('active', 'На рассмотрении'), ('approved', 'Согласован'), ('rejected', 'Отклонён'), ('rework', 'Возвращён на доработку'), ('skipped', 'Не потребовался')], db_default='waiting', default='waiting', max_length=16),
        ),
        migrations.AlterField(
            model_name='approvaltask',
            name='state',
            field=models.CharField(choices=[('pending', 'Ожидает решения'), ('approved', 'Согласовано'), ('rejected', 'Отклонено'), ('rework', 'Возвращено на доработку'), ('skipped', 'Не потребовалось')], db_default='pending', default='pending', max_length=16),
        ),
    ]

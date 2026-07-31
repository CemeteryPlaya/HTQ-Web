"""Состояние «на доработке» у колонки ``approval_state``.

Колонка объявлена примесью ``signoff.Approvable``, но живёт в таблицах
contracts (межаппного FK нет), поэтому расширение её ``choices`` требует
миграции ЗДЕСЬ — рядом с ``signoff/migrations/0004_rework_state.py``, где то
же самое сделано для собственных моделей движка.

Данных не трогает: ``choices`` в Postgres не хранятся, а значение ``rework``
появится только у тех записей, которые кто-то вернёт на доработку. Уже
согласованные и отклонённые записи после этой миграции становятся
НЕРЕДАКТИРУЕМЫМИ (``Approvable.assert_editable``) — это и есть цель
изменения, а ключ к правке даёт кнопка «Вернуть на доработку» в карточке
согласования.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0008_alter_counterparty_contact_name'),
        # Состояние осмысленно только вместе с движком, который его
        # проставляет: без 0004 в signoff запись 'rework' в этой колонке
        # взяться неоткуда.
        ('signoff', '0004_rework_state'),
    ]

    operations = [
        migrations.AlterField(
            model_name='agreement',
            name='approval_state',
            field=models.CharField(choices=[('draft', 'Черновик'), ('pending', 'На согласовании'), ('approved', 'Согласовано'), ('rejected', 'Отклонено'), ('rework', 'На доработке')], db_default='draft', db_index=True, default='draft', max_length=16, verbose_name='Состояние согласования'),
        ),
        migrations.AlterField(
            model_name='budget',
            name='approval_state',
            field=models.CharField(choices=[('draft', 'Черновик'), ('pending', 'На согласовании'), ('approved', 'Согласовано'), ('rejected', 'Отклонено'), ('rework', 'На доработке')], db_default='draft', db_index=True, default='draft', max_length=16, verbose_name='Состояние согласования'),
        ),
        migrations.AlterField(
            model_name='counterparty',
            name='approval_state',
            field=models.CharField(choices=[('draft', 'Черновик'), ('pending', 'На согласовании'), ('approved', 'Согласовано'), ('rejected', 'Отклонено'), ('rework', 'На доработке')], db_default='draft', db_index=True, default='draft', max_length=16, verbose_name='Состояние согласования'),
        ),
    ]

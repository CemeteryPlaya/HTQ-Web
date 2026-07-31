"""Подключение бюджетов, контрагентов и договоров к ``apps.signoff``.

Колонка ``approval_state`` приходит из абстрактной примеси
``signoff.Approvable`` и живёт в таблицах САМОГО contracts — межаппного FK
здесь нет и быть не может (правило границ, см. ``apps/signoff/models.py``).

Вторая операция — разовая: записи, ЗАВЕДЁННЫЕ ДО появления согласования,
помечаются согласованными. Иначе включение первого же маршрута мгновенно
сделало бы весь существующий реестр непригодным (все строки — ``draft``, а
несогласованный бюджет не источник денег), и разбирать это пришлось бы
руками по одной. Новые записи начинают с ``draft`` как положено.
"""

from django.db import migrations, models


def _approve_existing(apps, schema_editor):
    for name in ("Budget", "Counterparty", "Agreement"):
        apps.get_model("contracts", name).objects.update(approval_state="approved")


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='agreement',
            name='approval_state',
            field=models.CharField(choices=[('draft', 'Черновик'), ('pending', 'На согласовании'), ('approved', 'Согласовано'), ('rejected', 'Отклонено')], db_default='draft', db_index=True, default='draft', max_length=16, verbose_name='Состояние согласования'),
        ),
        migrations.AddField(
            model_name='budget',
            name='approval_state',
            field=models.CharField(choices=[('draft', 'Черновик'), ('pending', 'На согласовании'), ('approved', 'Согласовано'), ('rejected', 'Отклонено')], db_default='draft', db_index=True, default='draft', max_length=16, verbose_name='Состояние согласования'),
        ),
        migrations.AddField(
            model_name='counterparty',
            name='approval_state',
            field=models.CharField(choices=[('draft', 'Черновик'), ('pending', 'На согласовании'), ('approved', 'Согласовано'), ('rejected', 'Отклонено')], db_default='draft', db_index=True, default='draft', max_length=16, verbose_name='Состояние согласования'),
        ),
        # Обратной операции нет намеренно: откат вернул бы всем строкам
        # 'draft', а этого не хочет никто — колонку всё равно удаляет
        # AddField.reverse выше.
        migrations.RunPython(_approve_existing, migrations.RunPython.noop),
    ]

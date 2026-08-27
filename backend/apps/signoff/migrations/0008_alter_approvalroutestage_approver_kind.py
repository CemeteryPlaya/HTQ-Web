"""Догоняющая миграция: help_text у approver_kind разошёлся с моделью.

Миграция 0006_position_based_approvers объявила поле с текстом «список
должностей не заполняется», а models.py говорит «список согласующих».
Расхождение пришло вместе с PR #15 (обе стороны мерджа ruslan ->
pre-production несут одинаковый текст в модели), мерджем оно не создано.

На схему БД не влияет — help_text живёт только в состоянии миграций и в
формах админки. Но без этой миграции `makemigrations --check` считает
модели изменёнными, а значит любой CI-гейт на дрейф моделей будет красным.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('signoff', '0007_task_position_snapshot'),
    ]

    operations = [
        migrations.AlterField(
            model_name='approvalroutestage',
            name='approver_kind',
            field=models.CharField(choices=[('position', 'По должности'), ('initiator', 'Инициатор согласования')], db_default='position', default='position', help_text='«Инициатор» — список согласующих не заполняется, решение принимает отправивший объект на согласование', max_length=16, verbose_name='Кто согласует'),
        ),
    ]

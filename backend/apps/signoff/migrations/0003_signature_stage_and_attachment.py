"""Этап подписи: согласует инициатор, и только с приложенным PDF.

Два независимых поля на этапе (``approver_kind``, ``requires_attachment``) и
ссылка на документ у запроса (``ApprovalTask.file_id``). Те же два поля
дублируются на ``ApprovalProcessStage`` — это снимок маршрута, и правка
настройки не должна менять правила уже идущего согласования (докстринг
``ApprovalProcessStage``).

Обратная совместимость ради того же, что в ``0002``: значения по умолчанию
выбраны так, чтобы существующие маршруты не изменили поведения —
``approver_kind = 'named'`` (согласующие как раньше берутся из маршрута),
``requires_attachment = false`` (документ не требуется нигде), ``file_id =
NULL`` у всех прошлых решений. Ни один работающий маршрут этой миграцией в
маршрут с подписью не превращается.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('signoff', '0002_conditional_branches'),
    ]

    operations = [
        migrations.AddField(
            model_name='approvalprocessstage',
            name='approver_kind',
            field=models.CharField(choices=[('named', 'Названные в маршруте'), ('initiator', 'Инициатор согласования')], db_default='named', default='named', max_length=16),
        ),
        migrations.AddField(
            model_name='approvalprocessstage',
            name='requires_attachment',
            field=models.BooleanField(db_default=False, default=False),
        ),
        migrations.AddField(
            model_name='approvalroutestage',
            name='approver_kind',
            field=models.CharField(choices=[('named', 'Названные в маршруте'), ('initiator', 'Инициатор согласования')], db_default='named', default='named', help_text='«Инициатор» — список согласующих не заполняется, решение принимает отправивший объект на согласование', max_length=16, verbose_name='Кто согласует'),
        ),
        migrations.AddField(
            model_name='approvalroutestage',
            name='requires_attachment',
            field=models.BooleanField(db_default=False, default=False, help_text='Согласовать этап можно только приложив PDF', verbose_name='Требуется документ'),
        ),
        migrations.AddField(
            model_name='approvaltask',
            name='file_id',
            field=models.CharField(blank=True, max_length=64, null=True, verbose_name='Приложенный документ'),
        ),
    ]

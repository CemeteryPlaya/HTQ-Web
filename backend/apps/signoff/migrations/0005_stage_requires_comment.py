"""Этап может требовать пояснение к решению — третье независимое поле «этапа
подписи» рядом с ``approver_kind`` и ``requires_attachment`` (см. докстринг
``ApprovalRouteStage``).

То же поле дублируется на ``ApprovalProcessStage`` — это снимок маршрута, и
правка настройки не должна менять правила уже идущего согласования (докстринг
``ApprovalProcessStage``).

Обратная совместимость, как в ``0003``: ``requires_comment = false`` по
умолчанию — ни один существующий маршрут этой миграцией пояснения требовать не
начинает, и уже идущие процессы (у которых снимок заполняется тем же db_default)
ведут себя как прежде.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('signoff', '0004_rework_state'),
    ]

    operations = [
        migrations.AddField(
            model_name='approvalroutestage',
            name='requires_comment',
            field=models.BooleanField(db_default=False, default=False, help_text='Согласовать этап можно только с непустым комментарием', verbose_name='Требуется пояснение'),
        ),
        migrations.AddField(
            model_name='approvalprocessstage',
            name='requires_comment',
            field=models.BooleanField(db_default=False, default=False),
        ),
    ]

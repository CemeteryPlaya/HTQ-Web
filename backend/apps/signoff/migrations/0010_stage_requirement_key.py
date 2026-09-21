"""Требование этапа к объекту — ``requirement_key``.

Третье требование рядом с ``requires_attachment`` и ``requires_comment``,
но другого рода: не к решению, а к самому объекту — на нём должно быть
что-то сделано (у заявки заполнен поставщик), прежде чем этап закроется.
Что именно и выполнено ли, знает предметная аппка; движок хранит ключ.

Пустая строка у всех существующих этапов: ничего не требуется, поведение
не меняется. В снимок процесса поле копируется на запуске, как остальные
требования: перекроенный посреди согласования маршрут не должен менять
правила тем, кто ещё не решил.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("signoff", "0009_route_scope_and_approver_kinds"),
    ]

    operations = [
        migrations.AddField(
            model_name="approvalroutestage",
            name="requirement_key",
            field=models.CharField(
                blank=True, db_default="", default="", max_length=64,
                help_text="Ключ из Subject.requirement_fields предметной аппки",
                verbose_name="Этап требует от объекта",
            ),
        ),
        migrations.AddField(
            model_name="approvalprocessstage",
            name="requirement_key",
            field=models.CharField(blank=True, db_default="", default="",
                                   max_length=64),
        ),
    ]

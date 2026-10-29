"""Вид связи задачи с отделом: участник или отправитель (канбан-доски, K1.4).

Expand: столбец с ``db_default="member"`` — старый код вставляет связи без
него. Тенантная аппка: на бою — шагом ``migrate_companies``.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0026_engagement_bpp_agreement'),
    ]

    operations = [
        migrations.AddField(
            model_name='taskdepartmentlink',
            name='kind',
            field=models.CharField(choices=[('member', 'Member'), ('origin', 'Origin')], db_default='member', db_index=True, default='member', max_length=10),
        ),
    ]

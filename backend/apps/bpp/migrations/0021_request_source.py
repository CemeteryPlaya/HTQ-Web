"""Заявка на закупку: откуда она (``source``) и номер тендерной заявки
(``tender_number``) — пакет B-1 тендерного модуля (T1.2, T-07).

Expand: оба столбца с ``db_default=""``, старый код их не читает и не
пишет. Тенантная аппка — на бою шаг ``migrate_companies`` (в схеме каждой
компании); старт контейнера (``migrate_shared``) схем компаний не трогает."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bpp', '0020_ext_1c_lower'),
    ]

    operations = [
        migrations.AddField(
            model_name='purchaserequest',
            name='source',
            field=models.CharField(blank=True, choices=[('', 'БЗО'), ('tender', 'Тендерный модуль')], db_default='', default='', max_length=16),
        ),
        migrations.AddField(
            model_name='purchaserequest',
            name='tender_number',
            field=models.CharField(blank=True, db_default='', default='', max_length=32),
        ),
    ]

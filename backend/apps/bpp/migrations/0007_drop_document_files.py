"""Файлы документов модуля — через платформенную apps.files (решение 28.09):
таблицы DocumentFile и FileDownload этапа 1 снимаются. Они нигде не
выкатывались, данных в них нет."""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("bpp", "0006_counterparties"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="filedownload",
            name="file",
        ),
        migrations.DeleteModel(
            name="DocumentFile",
        ),
        migrations.DeleteModel(
            name="FileDownload",
        ),
    ]

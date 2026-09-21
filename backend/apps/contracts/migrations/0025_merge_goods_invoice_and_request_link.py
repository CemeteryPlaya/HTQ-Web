"""Шов веток ``ruslan`` и ``pre-production`` в графе миграций ``contracts``.

Операций нет: обе ветки выросли из ``0023_operations_import_fields`` и
заводили РАЗНОЕ — ``0024_goodsinvoice`` (pre-production) добавляла модель
товарной накладной, ``0024_merge_request_link_and_registry`` (ruslan) сшивала
связь договора с заявкой конструктора «Запросы». Django не выбирает порядок
у двух листьев сам, поэтому шов объявляется явно; после него лист снова один.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0024_goodsinvoice'),
        ('contracts', '0024_merge_request_link_and_registry'),
    ]

    operations = []

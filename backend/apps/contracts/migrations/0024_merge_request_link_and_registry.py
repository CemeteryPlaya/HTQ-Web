"""Шов двух веток миграций ``contracts``, разошедшихся в ветке ruslan.

Операций нет: ветки правили РАЗНЫЕ поля одних и тех же моделей —
``0022_agreement_invoice_request_id`` добавляла ``request_id`` (связь с
заявкой конструктора «Запросы»), а ``0023_operations_import_fields`` поверх
``0022_agreement_registry_fields`` — ``external_id``/``document_date``
(импорт реестра и операций из LARK). Django не умеет сам выбирать порядок у
двух листьев графа, поэтому шов объявляется явно; после него лист снова один.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0022_agreement_invoice_request_id'),
        ('contracts', '0023_operations_import_fields'),
    ]

    operations = []

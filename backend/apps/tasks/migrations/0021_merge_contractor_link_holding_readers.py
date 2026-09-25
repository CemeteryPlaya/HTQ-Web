"""Слияние двух веток миграций ``tasks``: ``0020_contractor_counterparty_link``
(pre-production — связь партнёра с контрагентом «Договоров») и
``0020_holding_readers`` (sanzhar — читатели сводок холдинга, блок H).

Обе — только expand и друг друга не касаются, поэтому операций здесь нет:
миграция лишь сводит граф в один лист, без которого ``migrate``/
``migrate_companies`` отказываются работать. Tenant-аппка: доводится
``manage.py migrate_companies`` вместе с обеими ветками.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0020_contractor_counterparty_link"),
        ("tasks", "0020_holding_readers"),
    ]

    operations = []

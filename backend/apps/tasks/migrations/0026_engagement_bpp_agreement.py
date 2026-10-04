from django.db import migrations, models


class Migration(migrations.Migration):
    """Expand: договор привлечения в модуле «Закупки и оплаты» (хвост этапа 6, M-5).

    Столбец с умолчанием — обратно-совместимый шаг: код без него работает, а
    ``migrate_companies`` довозит столбец в схемы компаний отдельным шагом
    выкатки.
    """

    dependencies = [
        ('tasks', '0025_contractor_bpp_counterparty'),
    ]

    operations = [
        migrations.AddField(
            model_name='contractorengagement',
            name='bpp_agreement_id',
            field=models.CharField(blank=True, db_default='', default='', max_length=36),
        ),
    ]

"""Предложение поставщика: ``Offer``, ``OfferLine``, ``OfferExtra`` и
``PaymentScheme.offer`` (T3.3, план этапа 3). Expand: новые таблицы и
столбец с NULL. Тенантная аппка — на бою шаг ``migrate_companies``."""

import django.db.models.deletion
import django.db.models.functions.datetime
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tender', '0003_tenders'),
    ]

    operations = [
        migrations.CreateModel(
            name='OfferExtra',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_default=django.db.models.functions.datetime.Now())),
                ('created_by', models.IntegerField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True, db_default=django.db.models.functions.datetime.Now())),
                ('updated_by', models.IntegerField(blank=True, null=True)),
                ('kind', models.CharField(choices=[('delivery', 'Доставка'), ('works', 'СМР')], max_length=8)),
                ('amount', models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)),
                ('included_in_price', models.BooleanField(db_default=False, default=False)),
                ('note', models.TextField(blank=True, default='')),
            ],
            options={
                'verbose_name': 'Доставка / СМР предложения',
                'verbose_name_plural': 'Доставка / СМР предложений',
            },
        ),
        migrations.CreateModel(
            name='OfferLine',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_default=django.db.models.functions.datetime.Now())),
                ('created_by', models.IntegerField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True, db_default=django.db.models.functions.datetime.Now())),
                ('updated_by', models.IntegerField(blank=True, null=True)),
                ('participates', models.BooleanField(db_default=True, default=True)),
                ('price', models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)),
                ('qty', models.DecimalField(blank=True, decimal_places=3, max_digits=15, null=True)),
                ('delivery_date', models.DateField(blank=True, null=True)),
                ('is_analog', models.BooleanField(db_default=False, default=False)),
                ('analog_note', models.TextField(blank=True, default='')),
                ('comment', models.TextField(blank=True, default='')),
            ],
            options={
                'verbose_name': 'Строка предложения',
                'verbose_name_plural': 'Строки предложения',
            },
        ),
        migrations.CreateModel(
            name='Offer',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_default=django.db.models.functions.datetime.Now())),
                ('created_by', models.IntegerField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True, db_default=django.db.models.functions.datetime.Now())),
                ('updated_by', models.IntegerField(blank=True, null=True)),
                ('version', models.PositiveIntegerField(db_default=1, default=1)),
                ('number', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('status', models.CharField(choices=[('draft', 'Черновик'), ('submitted', 'Отправлено'), ('replaced', 'Заменено'), ('withdrawn', 'Отозвано')], default='draft', max_length=16)),
                ('submitted_at', models.DateTimeField(blank=True, null=True)),
                ('currency_code', models.CharField(default='KZT', max_length=3)),
                ('with_vat', models.BooleanField(db_default=True, default=True)),
                ('vat_rate', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('delivery_cost', models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)),
                ('delivery_included', models.BooleanField(db_default=False, default=False)),
                ('works_cost', models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)),
                ('works_note', models.TextField(blank=True, default='')),
                ('valid_until', models.DateField(blank=True, null=True)),
                ('extra_terms', models.TextField(blank=True, default='')),
                ('requisites', models.JSONField(blank=True, default=dict)),
                ('pd_consent_at', models.DateTimeField(blank=True, null=True)),
                ('declined_reason', models.TextField(blank=True, default='')),
                ('invitation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='offers', to='tender.invitation')),
            ],
            options={
                'verbose_name': 'Предложение поставщика',
                'verbose_name_plural': 'Предложения поставщиков',
                'ordering': ('created_at',),
            },
        ),
        migrations.AddField(
            model_name='paymentscheme',
            name='offer',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='payment_schemes', to='tender.offer'),
        ),
        migrations.AddConstraint(
            model_name='paymentscheme',
            constraint=models.UniqueConstraint(condition=models.Q(('offer__isnull', False)), fields=('offer',), name='uq_tender_offer_payment_scheme'),
        ),
        migrations.AddField(
            model_name='offerextra',
            name='offer',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='extras', to='tender.offer'),
        ),
        migrations.AddField(
            model_name='offerline',
            name='item',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='offer_lines', to='tender.tenderrequestitem'),
        ),
        migrations.AddField(
            model_name='offerline',
            name='offer',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lines', to='tender.offer'),
        ),
        migrations.AddConstraint(
            model_name='offer',
            constraint=models.UniqueConstraint(condition=models.Q(('status', 'draft')), fields=('invitation',), name='uq_tender_offer_draft'),
        ),
        migrations.AddConstraint(
            model_name='offer',
            constraint=models.UniqueConstraint(condition=models.Q(('number__isnull', False)), fields=('invitation', 'number'), name='uq_tender_offer_number'),
        ),
        migrations.AddConstraint(
            model_name='offer',
            constraint=models.CheckConstraint(condition=models.Q(('delivery_cost__isnull', True), ('delivery_cost__gte', 0), _connector='OR'), name='ck_tender_offer_delivery_cost'),
        ),
        migrations.AddConstraint(
            model_name='offer',
            constraint=models.CheckConstraint(condition=models.Q(('works_cost__isnull', True), ('works_cost__gte', 0), _connector='OR'), name='ck_tender_offer_works_cost'),
        ),
        migrations.AddConstraint(
            model_name='offerextra',
            constraint=models.UniqueConstraint(fields=('offer', 'kind'), name='uq_tender_offer_extra'),
        ),
        migrations.AddConstraint(
            model_name='offerextra',
            constraint=models.CheckConstraint(condition=models.Q(('amount__isnull', True), ('amount__gte', 0), _connector='OR'), name='ck_tender_offer_extra_amount'),
        ),
        migrations.AddConstraint(
            model_name='offerline',
            constraint=models.UniqueConstraint(fields=('offer', 'item'), name='uq_tender_offer_line'),
        ),
        migrations.AddConstraint(
            model_name='offerline',
            constraint=models.CheckConstraint(condition=models.Q(('price__isnull', True), ('price__gt', 0), _connector='OR'), name='ck_tender_offer_line_price'),
        ),
        migrations.AddConstraint(
            model_name='offerline',
            constraint=models.CheckConstraint(condition=models.Q(('qty__isnull', True), ('qty__gt', 0), _connector='OR'), name='ck_tender_offer_line_qty'),
        ),
    ]

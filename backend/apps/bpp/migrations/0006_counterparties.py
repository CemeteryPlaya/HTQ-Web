"""Контрагенты и настройки модуля (A2.3, ТЗ §18, D-20)."""

import django.db.models.deletion
import django.db.models.functions.datetime
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bpp', '0005_accountable'),
    ]

    operations = [
        migrations.CreateModel(
            name='ModuleSetting',
            fields=[
                ('key', models.CharField(max_length=64, primary_key=True, serialize=False)),
                ('value', models.JSONField()),
                ('updated_at', models.DateTimeField(auto_now=True, db_default=django.db.models.functions.datetime.Now())),
                ('updated_by', models.IntegerField(blank=True, null=True)),
            ],
            options={
                'verbose_name': 'Настройка модуля',
                'verbose_name_plural': 'Настройки модуля',
            },
        ),
        migrations.CreateModel(
            name='Counterparty',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_default=django.db.models.functions.datetime.Now())),
                ('created_by', models.IntegerField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True, db_default=django.db.models.functions.datetime.Now())),
                ('updated_by', models.IntegerField(blank=True, null=True)),
                ('version', models.PositiveIntegerField(db_default=1, default=1)),
                ('name', models.CharField(max_length=500)),
                ('short_name', models.CharField(blank=True, default='', max_length=255)),
                ('kind', models.CharField(choices=[('legal', 'Юридическое лицо'), ('ip', 'Индивидуальный предприниматель'), ('individual', 'Физическое лицо'), ('nonresident', 'Нерезидент')], max_length=16)),
                ('country_code', models.CharField(max_length=2)),
                ('reg_number', models.CharField(max_length=30)),
                ('is_vat_payer', models.BooleanField(db_default=False, default=False)),
                ('vat_cert_series', models.CharField(blank=True, default='', max_length=32)),
                ('vat_cert_number', models.CharField(blank=True, default='', max_length=32)),
                ('legal_address', models.TextField(blank=True, default='')),
                ('contact_person', models.CharField(blank=True, default='', max_length=255)),
                ('phone', models.CharField(blank=True, default='', max_length=64)),
                ('email', models.CharField(blank=True, default='', max_length=254)),
                ('status', models.CharField(choices=[('active', 'Активен'), ('blocked', 'Заблокирован'), ('archived', 'Архив')], db_default='active', default='active', max_length=16)),
                ('block_reason', models.TextField(blank=True, default='')),
                ('blocked_at', models.DateTimeField(blank=True, null=True)),
                ('blocked_by', models.IntegerField(blank=True, null=True)),
                ('successful_documents', models.PositiveIntegerField(db_default=0, default=0)),
                ('verified_override', models.BooleanField(blank=True, null=True)),
                ('ext_1c_ref', models.CharField(blank=True, default='', max_length=64)),
            ],
            options={
                'verbose_name': 'Контрагент',
                'verbose_name_plural': 'Контрагенты',
                'ordering': ('name',),
                'indexes': [models.Index(fields=['status', 'name'], name='ix_bpp_counterparty_status')],
                'constraints': [models.UniqueConstraint(fields=('country_code', 'reg_number'), name='uq_bpp_counterparty_reg')],
            },
        ),
        migrations.CreateModel(
            name='CounterpartyBankAccount',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_default=django.db.models.functions.datetime.Now())),
                ('created_by', models.IntegerField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True, db_default=django.db.models.functions.datetime.Now())),
                ('updated_by', models.IntegerField(blank=True, null=True)),
                ('iban', models.CharField(max_length=34)),
                ('bank_name', models.CharField(blank=True, default='', max_length=255)),
                ('bic', models.CharField(max_length=11)),
                ('currency', models.CharField(db_default='KZT', default='KZT', max_length=3)),
                ('is_primary', models.BooleanField(db_default=False, default=False)),
                ('is_active', models.BooleanField(db_default=True, default=True)),
                ('counterparty', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='bank_accounts', to='bpp.counterparty')),
            ],
            options={
                'verbose_name': 'Банковский счёт контрагента',
                'verbose_name_plural': 'Банковские счета контрагентов',
                'ordering': ('-is_primary', 'created_at'),
            },
        ),
        migrations.AddConstraint(
            model_name='counterpartybankaccount',
            constraint=models.UniqueConstraint(fields=('iban',), name='uq_bpp_cp_account_iban'),
        ),
        migrations.AddConstraint(
            model_name='counterpartybankaccount',
            constraint=models.UniqueConstraint(condition=models.Q(('is_primary', True)), fields=('counterparty',), name='uq_bpp_cp_account_primary'),
        ),
    ]

"""Удаление секции «Сертификаты / СРО» из карточки Т-2.

Снимает четыре колонки, заведённые 0012_employeecard: sro_permit_number,
sro_permit_expiry, safety_cert_number, safety_cert_expiry. Вместе с ними
из кода ушли секция ``certs`` (services/employee_card_t2_service.py),
схема ``CardCerts`` и права hr.card.certs.view/edit.

Необратимо по данным: реверс миграции вернёт колонки, но не их содержимое.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0015_document_uploaded_by_nullable"),
    ]

    operations = [
        migrations.RemoveField(model_name="employeecard", name="sro_permit_number"),
        migrations.RemoveField(model_name="employeecard", name="sro_permit_expiry"),
        migrations.RemoveField(model_name="employeecard", name="safety_cert_number"),
        migrations.RemoveField(model_name="employeecard", name="safety_cert_expiry"),
    ]

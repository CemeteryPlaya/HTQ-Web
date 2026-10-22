"""Типы файлов приёмки тендерного модуля (T5.5; спека этапа 5, §2).

Владелец — ``tender.receipt`` (``apps/tender/file_owners.py``): сканы
накладной, акта и счёт-фактуры и фото поставки. Свои коды, а не ``waybill``/
``act``/``vat_invoice`` счёта БЗО: у типа справочника один владелец. На счёт
БЗО скан уходит копией с типом счёта (``bpp.attach_closing_docs``, D-13).
Справочник живёт в ``public`` — поэтому строка здесь (как ``0006``, ``0007``).
"""

from django.db import migrations

IMAGES = [".jpg", ".jpeg", ".png"]
SCANS = [".pdf", *IMAGES]

TYPES = (
    # (код, владелец, название, форматы, МБ, порядок)
    ("tender_waybill", "tender.receipt", "Накладная", SCANS, 20, 20),
    ("tender_act", "tender.receipt", "Акт выполненных работ", SCANS, 20, 21),
    ("tender_vat_invoice", "tender.receipt", "Счёт-фактура", SCANS, 20, 22),
    ("tender_photo", "tender.receipt", "Фото поставки", IMAGES, 20, 23),
)


def seed(apps, schema_editor):
    FileType = apps.get_model("files", "FileType")
    for code, owner_type, name, formats, max_mb, order in TYPES:
        row, created = FileType.objects.get_or_create(code=code, defaults={
            "owner_type": owner_type, "name": name, "formats": formats,
            "max_mb": max_mb, "sort_order": order})
        if not created:
            row.owner_type, row.name, row.formats, row.sort_order = (
                owner_type, name, formats, order)
            row.save(update_fields=["owner_type", "name", "formats", "sort_order"])


def unseed(apps, schema_editor):
    FileType = apps.get_model("files", "FileType")
    FileType.objects.filter(code__in=[code for code, *_rest in TYPES],
                            files__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("files", "0007_tender_offer_type")]
    operations = [migrations.RunPython(seed, unseed)]

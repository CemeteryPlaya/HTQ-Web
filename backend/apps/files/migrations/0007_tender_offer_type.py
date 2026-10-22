"""Тип файла «Коммерческое предложение» поставщика с портала тендерного
модуля (T3.4; план этапа 3, §2 T3.4).

Владелец — ``tender.offer`` (``apps/tender/file_owners.py``), до 10
документов на предложение. PDF, DOCX, XLSX, JPG, PNG до 20 МБ; ни XML, ни
исполняемых — портал анонимный. Справочник живёт в ``public``, а миграции
тенантной ``tender`` идут по схемам компаний — поэтому строка здесь (как
``0006``). Существующая строка обновляется во всём, кроме ``max_mb`` (его
правит администратор); ``seed`` зовут и transaction=True-тесты.
"""

from django.db import migrations

IMAGES = [".jpg", ".jpeg", ".png"]

TYPES = (
    # (код, владелец, название, форматы, МБ, порядок)
    ("tender_offer", "tender.offer", "Коммерческое предложение",
     [".pdf", ".docx", ".xlsx", *IMAGES], 20, 10),
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
    dependencies = [("files", "0006_tender_file_types")]
    operations = [migrations.RunPython(seed, unseed)]

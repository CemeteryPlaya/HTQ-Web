"""Тип файла «ТЗ и чертежи» заявки тендерного модуля (T1.1; план этапов 0–2,
§3.4).

Владелец — ``tender.request`` (``apps/tender/file_owners.py``), до 20
документов на заявку. Справочник живёт в ``public``, а миграции тенантной
``tender`` идут по схемам компаний — поэтому строка здесь, как у БЗО (``0003``).
Правила строки — как в ``0003``–``0005``: существующая строка обновляется во
всём, кроме ``max_mb`` (его правит администратор). ``seed`` зовут и
transaction=True-тесты, которым нужен справочник.

DWG из плана (§3.4) не заведён: подсистема и media не знают его типа
(``files/services/documents.EXT_MIME``, scope ``file_object``) — с ним
загрузка чертежа отвечала бы отказом media. Добавить — вместе с этими местами.
"""

from django.db import migrations

IMAGES = [".jpg", ".jpeg", ".png"]

TYPES = (
    # (код, владелец, название, форматы, МБ, порядок)
    ("tender_spec", "tender.request", "ТЗ и чертежи",
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
    dependencies = [("files", "0005_bpp_alternative_offer_type")]
    operations = [migrations.RunPython(seed, unseed)]

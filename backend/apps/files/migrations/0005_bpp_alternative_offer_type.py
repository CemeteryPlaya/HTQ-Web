"""Тип файла «КП альтернативы» (ТЗ §12.3, §21; план этапа 5 A, задача 1).

Владелец — ``bpp.alternative_offer`` (``apps/bpp/services/alternatives/
file_owner.py``), до 5 документов на АП. Форматы и размер — по ТЗ §12.3
(«PDF / JPG / PNG / DOCX, до 10 МБ»), решение контроллера этапа 5: строка
§21 «КП … Заявка» (с XLSX и 20 МБ) — про КП во вложениях заявки, это тип
``request_attachment`` из ``0003``. Правила строки — как в ``0003``/
``0004``: существующая строка обновляется во всём, кроме ``max_mb`` (его
правит администратор). ``seed`` зовут и transaction=True-тесты, которым
нужен справочник.
"""

from django.db import migrations

IMAGES = [".jpg", ".jpeg", ".png"]

TYPES = (
    # (код, владелец, название, форматы, МБ, порядок)
    ("alternative_offer", "bpp.alternative_offer", "КП",
     [".pdf", ".docx", *IMAGES], 10, 10),
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
    dependencies = [("files", "0004_bpp_stage3_file_types")]
    operations = [migrations.RunPython(seed, unseed)]

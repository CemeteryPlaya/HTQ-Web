"""Справочник «Типы файлов»: типы документов модуля БЗО (ТЗ §21).

Строки для владельцев, которых регистрирует ``apps/bpp/file_owners.py``:
документы заявки на закупку и подтверждающий документ авансового отчёта.
Правила количества (квота «до 20», «1 действующий + версии») — там же, в
``FileTypeSpec``; здесь только то, что хранит справочник: название,
форматы и размер.

**Почему миграцией ``files``, а не ``bpp``.** Справочник живёт в ``public``,
а ``bpp`` — тенантная аппка: её миграции идут по схеме каждой компании
(``migrate_companies``) и в ``public`` не выполняются вовсе
(``migrate_shared`` тенантные аппки пропускает). Сид в миграции ``bpp``
либо не дошёл бы до справочника, либо прошёл бы по нему столько раз,
сколько компаний. Подсистема по-прежнему не импортирует ни одного
владельца: здесь только строки с его ``owner_type``.

Существующая строка обновляется во всём, кроме ``max_mb``: размер правит
администратор (ТЗ стр. 61: «Нет / размеры / нет»), и повторный прогон его
не сбрасывает. Типы договора, счёта и остальных документов §21 заводятся
вместе с их владельцами (этап 3).

``seed`` вызывается и тестами, которым нужен справочник после очистки
базы (transaction=True-тесты чистят ``public`` целиком).
"""

from django.db import migrations

IMAGES = [".jpg", ".jpeg", ".png"]

TYPES = (
    # (код, владелец, название, форматы, МБ, порядок)
    ("request_attachment", "bpp.purchase_request", "КП, ТЗ, спецификация",
     [".pdf", ".docx", ".xlsx", *IMAGES], 20, 10),
    ("advance_report", "bpp.advance_report", "Авансовый отчёт",
     [".pdf", *IMAGES], 10, 10),
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
    # Тип с уже приложенными файлами не удаляется (FK PROTECT): откат не
    # должен уносить сведения о настоящих документах.
    FileType.objects.filter(code__in=[code for code, *_rest in TYPES],
                            files__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("files", "0002_fileevent_append_only"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]

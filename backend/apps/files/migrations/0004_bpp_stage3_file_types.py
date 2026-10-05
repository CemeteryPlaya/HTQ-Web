"""Справочник «Типы файлов»: документы договора, счёта и выписки (ТЗ §21).

Этап 3 модуля БЗО (план этапа 3 A, задача 1, решение D-S3-1): типы
заводятся здесь заранее, а владельцев регистрируют сами документы —
``apps/bpp/services/<подмодуль>/file_owner.py::register()``, которые
``apps/bpp/file_owners.py`` подключает сам. Договор (``bpp.agreement``) и
счёт (``bpp.invoice``) пишет исполнитель B, загрузку выписки
(``bpp.bank_import``) — A. Правила количества (до 30, до 10, «1 действующий
+ версии») — в ``FileTypeSpec`` владельца; здесь только то, что хранит
справочник: название, форматы и размер.

Почему миграцией ``files``, а не ``bpp``, — см. ``0003_bpp_file_types``:
справочник живёт в ``public``, а миграции тенантной ``bpp`` идут по схемам
компаний.

Как и в ``0003``, существующая строка обновляется во всём, кроме
``max_mb``: размер правит администратор (ТЗ стр. 61: «Нет / размеры /
нет»), и повторный прогон его не сбрасывает. Тип ``alternative_offer``
(КП альтернативы) заводится с альтернативами (A5.1).

Форматы выписки — TXT (1CClientBankExchange), XLSX и CSV: scope
``file_object`` в ``media_files`` принимает для них ``text/plain`` и
``text/csv`` с этого же этапа.

``seed`` вызывается и тестами, которым нужен справочник после очистки
базы (transaction=True-тесты чистят ``public`` целиком).
"""

from django.db import migrations

IMAGES = [".jpg", ".jpeg", ".png"]

TYPES = (
    # (код, владелец, название, форматы, МБ, порядок)
    ("agreement", "bpp.agreement", "Договор",
     [".pdf", ".docx", *IMAGES], 20, 10),
    ("agreement_annex", "bpp.agreement", "Приложения, доп. соглашения",
     [".pdf", ".docx", *IMAGES], 20, 20),
    ("invoice", "bpp.invoice", "Счёт на оплату",
     [".pdf", *IMAGES], 10, 10),
    ("act", "bpp.invoice", "АВР",
     [".pdf", *IMAGES], 10, 20),
    ("waybill", "bpp.invoice", "Накладная",
     [".pdf", *IMAGES], 10, 30),
    # Счёт-фактура в xml (мастер-план БЗО, D-31 / ответ Q-C28).
    ("vat_invoice", "bpp.invoice", "Счёт-фактура",
     [".pdf", *IMAGES, ".xml"], 10, 40),
    # 1С — текстовый файл 1CClientBankExchange (.txt); Excel и CSV — по
    # шаблону банка (план этапа 3 A, задача 2).
    ("bank_statement", "bpp.bank_import", "Выписка банка",
     [".txt", ".xlsx", ".csv"], 20, 10),
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
        ("files", "0003_bpp_file_types"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]

"""Свободная строка ``Counterparty.contacts`` → три поля.

Разбор старого текста — best-effort и делается один раз, здесь: e-mail и
телефон вынимаются регулярками (их форма узнаваема), а весь остаток идёт в
ФИО контактного лица. Именно так контакты и записывали: placeholder формы
был «Петров П., директор, +7 700 000 00 00, info@alfa.kz».

Должность отдельным полем не заводится (см. докстринг модели), поэтому
слово «директор» из такой строки останется частью ФИО — «Петров П.,
директор». Разносить это по колонкам было бы угадыванием: в остатке
одинаково законно и второе контактное лицо, и комментарий «звонить днём».

Что не влезает в 200 символов ФИО — обрезается: настоящие значения заведомо
короче, а строка длиннее — уже не ФИО. Обратная миграция склеивает три поля
назад в одну строку, так что `migrate contracts 0006` проходит без потери
того, что удалось разобрать.
"""

from __future__ import annotations

import re

from django.db import migrations, models

# Адрес: без пробелов и разделителей вокруг «@», с точкой в домене.
_EMAIL_RE = re.compile(r"[^\s,;<>()]+@[^\s,;<>()]+\.[A-Za-z]{2,}")
# Телефон: от 7 цифр, разрешены «+», пробелы, дефисы и скобки внутри.
_PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{5,}\d")
_SPLIT_RE = re.compile(r"[,;\n]")


def _split_contacts(text: str) -> dict[str, str]:
    email_match = _EMAIL_RE.search(text)
    email = email_match.group(0) if email_match else ""
    rest = text.replace(email, " ") if email else text

    phone_match = _PHONE_RE.search(rest)
    phone = phone_match.group(0).strip() if phone_match else ""
    rest = rest.replace(phone, " ") if phone else rest

    chunks = [chunk.strip(" \t-–—") for chunk in _SPLIT_RE.split(rest)]
    chunks = [chunk for chunk in chunks if chunk]

    return {
        "contact_name": ", ".join(chunks)[:200],
        "phone": phone[:30],
        # Адрес мог оказаться длиннее колонки только в мусорной строке —
        # хранить его обрезанным всё равно бессмысленно, поэтому такой
        # отбрасывается целиком, а не кладётся битым.
        "email": email if len(email) <= 254 else "",
    }


def split_contacts(apps, schema_editor):
    Counterparty = apps.get_model("contracts", "Counterparty")
    updated = []
    for row in Counterparty.objects.exclude(contacts="").only("id", "contacts"):
        for field, value in _split_contacts(row.contacts).items():
            setattr(row, field, value)
        updated.append(row)
    if updated:
        Counterparty.objects.bulk_update(
            updated, ["contact_name", "phone", "email"], batch_size=500)


def join_contacts(apps, schema_editor):
    Counterparty = apps.get_model("contracts", "Counterparty")
    updated = []
    for row in Counterparty.objects.all():
        parts = [row.contact_name, row.phone, row.email]
        joined = ", ".join(part for part in parts if part)
        if joined:
            row.contacts = joined
            updated.append(row)
    if updated:
        Counterparty.objects.bulk_update(updated, ["contacts"], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0006_alter_counterparty_options'),
    ]

    operations = [
        migrations.AddField(
            model_name='counterparty',
            name='contact_name',
            field=models.CharField(blank=True, db_default='', default='',
                                   max_length=200,
                                   verbose_name='Контактное лицо'),
        ),
        migrations.AddField(
            model_name='counterparty',
            name='phone',
            field=models.CharField(blank=True, db_default='', default='',
                                   max_length=30, verbose_name='Телефон'),
        ),
        migrations.AddField(
            model_name='counterparty',
            name='email',
            field=models.EmailField(blank=True, db_default='', default='',
                                    max_length=254, verbose_name='E-mail'),
        ),
        migrations.RunPython(split_contacts, join_contacts),
        migrations.RemoveField(
            model_name='counterparty',
            name='contacts',
        ),
    ]

"""Предзаполнение справочников (ТЗ §18, мастер-план A1.2).

Ставки НДС и МРП — «сверить с законодательством» перед выкаткой [У]:
значения взяты из ТЗ (РК 16% с 01.01.2026, МРП 2026 — 4 325 тг). Литералы, а
не константы кода: миграция обязана давать один результат всегда.
"""

from datetime import date
from decimal import Decimal

from django.db import migrations

COUNTRIES = [("KZ", "Казахстан"), ("RU", "Россия"), ("KG", "Кыргызстан"), ("UZ", "Узбекистан")]
CURRENCIES = [("KZT", "Казахстанский тенге", "₸"), ("USD", "Доллар США", "$"),
              ("EUR", "Евро", "€"), ("RUB", "Российский рубль", "₽"),
              ("CNY", "Китайский юань", "¥"), ("KGS", "Киргизский сом", "с"),
              ("UZS", "Узбекский сум", "сўм")]
VAT = [("KZ", "12.00", date(2020, 1, 1), date(2025, 12, 31)),
       ("KZ", "16.00", date(2026, 1, 1), None),
       ("RU", "20.00", date(2020, 1, 1), date(2025, 12, 31)),
       ("RU", "22.00", date(2026, 1, 1), None),
       ("KG", "12.00", date(2020, 1, 1), None),
       ("UZ", "12.00", date(2020, 1, 1), None)]
MRP = [(date(2025, 1, 1), "3932.00"), (date(2026, 1, 1), "4325.00")]
UOMS = [("pcs", "шт", "Штука"), ("kg", "кг", "Килограмм"), ("t", "т", "Тонна"),
        ("m", "м", "Метр"), ("m2", "м²", "Квадратный метр"),
        ("m3", "м³", "Кубический метр"), ("l", "л", "Литр"),
        ("set", "компл", "Комплект"), ("service", "усл.", "Услуга"), ("h", "ч", "Час")]
GROUPS = [("supply", "Снабжение", "bpp.articles.supply"),
          ("pm", "Проектное управление", "bpp.articles.pm")]


def seed(apps, schema_editor):
    Country = apps.get_model("refdata", "Country")
    Currency = apps.get_model("refdata", "Currency")
    VatRate = apps.get_model("refdata", "VatRate")
    MrpValue = apps.get_model("refdata", "MrpValue")
    Uom = apps.get_model("refdata", "Uom")
    ArticleGroup = apps.get_model("refdata", "ArticleGroup")
    for code, name in COUNTRIES:
        Country.objects.get_or_create(code=code, defaults={"name": name})
    for code, name, symbol in CURRENCIES:
        Currency.objects.get_or_create(code=code, defaults={"name": name, "symbol": symbol})
    for country, rate, date_from, date_to in VAT:
        VatRate.objects.get_or_create(country_code=country, date_from=date_from,
                                      defaults={"rate": Decimal(rate), "date_to": date_to})
    for date_from, value in MRP:
        MrpValue.objects.get_or_create(date_from=date_from, defaults={"value": Decimal(value)})
    for code, short, name in UOMS:
        Uom.objects.get_or_create(code=code, defaults={"short_name": short, "name": name})
    for code, name, node in GROUPS:
        ArticleGroup.objects.get_or_create(code=code, defaults={"name": name, "node_key": node})


class Migration(migrations.Migration):

    dependencies = [("refdata", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]

"""Короткие адреса действующим компаниям группы (блок I.2, решение 22.09.2026).

Идемпотентна: трогает только строку, которая есть и у которой псевдоним
пуст. Компании, заведённой позже, псевдоним ставит администратор —
``company_create --subdomain`` или правка компании.
"""
from django.db import migrations

SUBDOMAINS = {
    "hi-tech-qazaqstan": "htq",
    "hi-tech-systems": "hts",
    "kazakhstan-engineering-group": "keg",
    "hi-tech-group": "group",
}


def set_subdomains(apps, schema_editor):
    Company = apps.get_model("companies", "Company")
    for slug, label in SUBDOMAINS.items():
        Company.objects.filter(slug=slug, subdomain__isnull=True).update(subdomain=label)


def unset_subdomains(apps, schema_editor):
    Company = apps.get_model("companies", "Company")
    for slug, label in SUBDOMAINS.items():
        Company.objects.filter(slug=slug, subdomain=label).update(subdomain=None)


class Migration(migrations.Migration):
    dependencies = [("companies", "0005_company_subdomain")]
    operations = [migrations.RunPython(set_subdomains, unset_subdomains)]

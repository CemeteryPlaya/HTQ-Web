"""Проставить компанию уже заведённым именным ролям (блок I.2, R2).

Код именной роли — ``hr-custom-<slug>-<position_id>``; слаг лежит между
префиксом и последним дефисом с числом. Идемпотентна: трогает только строки
с пустым ``company_slug``.
"""
import re

from django.db import migrations

CUSTOM_CODE = re.compile(r"^hr-custom-(?P<slug>.+)-(?P<position_id>\d+)$")


def fill(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    for role in Role.objects.filter(code__startswith="hr-custom-",
                                    company_slug__isnull=True):
        match = CUSTOM_CODE.match(role.code)
        if match:
            role.company_slug = match.group("slug")
            role.save(update_fields=["company_slug"])


def unfill(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    Role.objects.filter(code__startswith="hr-custom-").update(company_slug=None)


class Migration(migrations.Migration):
    dependencies = [("access", "0009_role_company_slug")]
    operations = [migrations.RunPython(fill, unfill)]

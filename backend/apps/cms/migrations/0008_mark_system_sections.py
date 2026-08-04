"""Пометить девять исходных секций системными.

У каждой из них свой React-компонент со своей вёрсткой (HeroSection,
ActivityDirections, …). Строка в БД лишь питает этот компонент текстами, а не
описывает его целиком, поэтому удалять их из интерфейса нельзя: пересоздать
такую секцию оттуда не выйдет — новая получила бы generic-макет и выглядела бы
иначе. Прятать, двигать и править по-прежнему можно.

Ключи перечислены явно, а не «всё, что уже есть в таблице»: миграция должна
давать один и тот же результат и на пустой базе после сида, и на боевой, где
редактор мог успеть создать свои блоки — их помечать системными нельзя.
"""
from django.db import migrations

SYSTEM_KEYS = [
    "hero", "directions", "invest", "projects",
    "services", "stats", "mission", "about", "partners",
]


def mark(apps, schema_editor):
    Section = apps.get_model("cms", "HomeSection")
    Section.objects.filter(key__in=SYSTEM_KEYS).update(is_system=True)


def unmark(apps, schema_editor):
    Section = apps.get_model("cms", "HomeSection")
    Section.objects.filter(key__in=SYSTEM_KEYS).update(is_system=False)


class Migration(migrations.Migration):

    dependencies = [("cms", "0007_homesection_is_system_homesection_layout")]

    operations = [migrations.RunPython(mark, unmark)]

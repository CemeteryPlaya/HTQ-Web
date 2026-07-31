"""``Equipment.category``: свободный текст → FK на ``EquipmentCategory``.

Четыре шага в одной миграции, потому что данные обязаны пережить конверсию:
переименовать текстовую колонку во временную, добавить рядом FK, разложить
текст по строкам справочника и только потом снести временную. Прямолинейное
``RemoveField`` + ``AddField``, которое сгенерировал бы ``makemigrations``,
потеряло бы категорию у всего парка.

Транслитерация продублирована из ``services/reference_service.slugify_name``
намеренно, а не импортирована. Миграция обязана быть замороженной: если
сервисный слагификатор потом поправят, у мигрировавшей раньше базы и у
поднятой с нуля разъедутся слаги одних и тех же категорий. Двенадцать строк
дубля — честная цена за это свойство.

Обратима: ``backward`` возвращает в текстовую колонку ИМЯ категории, то есть
ровно то, из чего слаг и делался. Строки справочника при откате остаются —
их мог успеть использовать кто-то ещё, а ``PROTECT`` на них молча не даст
удалить.
"""

from django.db import migrations, models
import django.db.models.deletion

_CYRILLIC_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ә": "a", "ғ": "g", "қ": "k", "ң": "n", "ө": "o", "ұ": "u", "ү": "u",
    "һ": "h", "і": "i",
}


def _slugify(name: str) -> str:
    out: list[str] = []
    for ch in name.strip().lower():
        if ch in _CYRILLIC_MAP:
            out.append(_CYRILLIC_MAP[ch])
        elif ch.isalnum() and ch.isascii():
            out.append(ch)
        elif ch in (" ", "-", "_"):
            out.append("-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "category"


def forward(apps, schema_editor):
    Equipment = apps.get_model("tasks", "Equipment")
    EquipmentCategory = apps.get_model("tasks", "EquipmentCategory")

    # Один проход по таблице: за время свободного ввода в парке могли
    # завестись «Спецтехника» и «спецтехника ». Схлопываем их по
    # strip+casefold, но показываемое имя берём как ввели в первый раз.
    ids_by_key: dict[str, list[int]] = {}
    display_by_key: dict[str, str] = {}
    for eq_id, text in (Equipment.objects
                        .exclude(category_text__isnull=True)
                        .values_list("id", "category_text")):
        cleaned = (text or "").strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        display_by_key.setdefault(key, cleaned)
        ids_by_key.setdefault(key, []).append(eq_id)

    used_slugs: set[str] = set()
    for key in sorted(display_by_key):
        display = display_by_key[key]
        base = _slugify(display)
        slug, suffix = base, 2
        while slug in used_slugs:
            slug = f"{base}-{suffix}"
            suffix += 1
        used_slugs.add(slug)
        row = EquipmentCategory.objects.create(slug=slug, name=display,
                                               is_active=True)
        Equipment.objects.filter(id__in=ids_by_key[key]).update(category_id=row.id)


def backward(apps, schema_editor):
    Equipment = apps.get_model("tasks", "Equipment")
    for eq_id, name in (Equipment.objects.exclude(category__isnull=True)
                        .values_list("id", "category__name")):
        Equipment.objects.filter(id=eq_id).update(category_text=name)


class Migration(migrations.Migration):

    dependencies = [("tasks", "0007_work_references")]

    operations = [
        migrations.RenameField(
            model_name="equipment", old_name="category",
            new_name="category_text",
        ),
        migrations.AddField(
            model_name="equipment", name="category",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="equipment", to="tasks.equipmentcategory",
            ),
        ),
        migrations.RunPython(forward, backward),
        migrations.RemoveField(model_name="equipment", name="category_text"),
    ]

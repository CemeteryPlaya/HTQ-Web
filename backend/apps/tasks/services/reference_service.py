"""Reference-data CRUD: labels, task types, equipment.

Ported from ``services/task/app/api/v1/{labels,task_types,equipment}.py`` and
the ``TaskTypeRepository`` slug helpers. These three are plain CRUD; the only
real logic is slug generation and the two deletion rules (system task types
are undeletable, equipment is soft-disabled rather than deleted).
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.http import Http404

from ..models import (Equipment, EquipmentCategory, Label, TaskType, WorkRole,
                      WorkVolumeType)

# Romanisation table for slug generation. Copied from the original's
# ``_CYRILLIC_MAP`` so an existing type keeps generating the same slug —
# "Обслуживание" must stay "obsluzhivanie", not become something new.
_CYRILLIC_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    # Kazakh-specific letters
    "ә": "a", "ғ": "g", "қ": "k", "ң": "n", "ө": "o", "ұ": "u", "ү": "u",
    "һ": "h", "і": "i",
}


def slugify_name(name: str) -> str:
    """Transliterate + slugify a display name into an ascii slug.

    Falls back to ``"type"`` when the name has no slug-able characters —
    an empty slug would collide with itself on the next such name.
    """
    out: list[str] = []
    for ch in name.strip().lower():
        if ch in _CYRILLIC_MAP:
            out.append(_CYRILLIC_MAP[ch])
        elif ch.isalnum() and ch.isascii():
            out.append(ch)
        elif ch in (" ", "-", "_"):
            out.append("-")
        # everything else (punctuation, non-mapped unicode) is dropped
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "type"


def generate_unique_slug(name: str, model=TaskType) -> str:
    """Свободный слаг для справочной строки ``model``.

    ``model`` по умолчанию ``TaskType``, чтобы старые вызовы читались как
    раньше; уникальность слага всегда в пределах СВОЕЙ таблицы, поэтому
    «кран» как тип техники и «кран» как вид работ друг другу не мешают.
    """
    base = slugify_name(name)
    candidate = base
    suffix = 2
    while model.objects.filter(slug=candidate).exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


# ── labels ──────────────────────────────────────────────────────────────

def list_labels() -> list[Label]:
    return list(Label.objects.order_by("id"))


def create_label(*, name: str, color: str) -> Label:
    return Label.objects.create(name=name, color=color)


def update_label(label_id: int, changes: dict) -> Label:
    label = Label.objects.filter(pk=label_id).first()
    if label is None:
        raise Http404("Label not found")
    for field, value in changes.items():
        setattr(label, field, value)
    label.save()
    return label


def delete_label(label_id: int) -> None:
    label = Label.objects.filter(pk=label_id).first()
    if label is None:
        raise Http404("Label not found")
    label.delete()


# ── task types ──────────────────────────────────────────────────────────

def list_task_types() -> list[TaskType]:
    return list(TaskType.objects.order_by("id"))


def create_task_type(*, slug: str | None, name: str, color: str,
                     icon: str | None) -> TaskType:
    """Create a user-defined type. Raises ``ValueError`` on slug collision —
    the view maps it to the original's 409."""
    resolved = slug or generate_unique_slug(name)
    if TaskType.objects.filter(slug=resolved).exists():
        raise ValueError(f"Task type with slug '{resolved}' already exists")
    return TaskType.objects.create(slug=resolved, name=name, color=color,
                                   icon=icon, is_system=False)


def update_task_type(type_id: int, changes: dict) -> TaskType:
    row = TaskType.objects.filter(pk=type_id).first()
    if row is None:
        raise Http404("Task type not found")
    # ``slug`` is absent from TaskTypeUpdate, so it can never arrive here —
    # system rows can have name/colour/icon changed but keep their slug.
    for field, value in changes.items():
        setattr(row, field, value)
    row.save()
    return row


def delete_task_type(type_id: int) -> None:
    row = TaskType.objects.filter(pk=type_id).first()
    if row is None:
        raise Http404("Task type not found")
    if row.is_system:
        # Task.task_type is SET_NULL: deleting a system row would silently
        # untype every historical task pointing at it.
        raise PermissionDenied("System task types cannot be deleted")
    row.delete()


def resolve_task_type_id(type_id: int | None, slug: str | None) -> int | None:
    """FK id for the given input — explicit id wins, else slug, else the
    seeded ``task`` row, so the form's optional Type field never yields a
    NULL classification."""
    if type_id is not None:
        return type_id
    target = (slug or "task").strip().lower()
    return (TaskType.objects.filter(slug=target)
            .values_list("id", flat=True).first())


# ── плоские справочники (типы техники, роли, виды объёмов) ──────────────
#
# Три таблицы одинаковой формы (slug, name, is_active) с одинаковыми
# правилами, поэтому CRUD написан один раз. Параметр — не класс модели, а
# ``kind``: ровно та строка, что стоит в URL. Так вьюхи остаются тонкими
# диспетчерами и по-прежнему не импортируют модели, а единственное место,
# где вид справочника превращается в таблицу, — словарь ниже.

_REFERENCE_MODELS = {
    "equipment-categories": EquipmentCategory,
    "work-roles": WorkRole,
    "volume-types": WorkVolumeType,
}


def _reference_model(kind: str):
    try:
        return _REFERENCE_MODELS[kind]
    except KeyError:  # pragma: no cover — kind приходит из urls.py, не от клиента
        raise ValueError(f"Unknown reference kind '{kind}'") from None


def list_reference_rows(kind: str, active_only: bool = True) -> list:
    model = _reference_model(kind)
    qs = model.objects.filter(is_active=True) if active_only else model.objects.all()
    return list(qs.order_by("name"))


def create_reference_row(kind: str, *, name: str, slug: str | None = None,
                         **extra):
    """Создать строку справочника. ``ValueError`` на занятый слаг/имя —
    вьюха превращает его в 409, как у типов задач."""
    model = _reference_model(kind)
    cleaned = name.strip()
    resolved = slug or generate_unique_slug(cleaned, model)
    if model.objects.filter(slug=resolved).exists():
        raise ValueError(f"Slug '{resolved}' already exists")
    if model.objects.filter(name__iexact=cleaned).exists():
        raise ValueError(f"Name '{cleaned}' already exists")
    # ``unit=None`` приезжает из ReferenceRowUpdate-подобных схем, где поле
    # необязательное; пусть решает db_default, а не NULL в NOT NULL колонке.
    extra = {key: value for key, value in extra.items() if value is not None}
    return model.objects.create(slug=resolved, name=cleaned, **extra)


def update_reference_row(kind: str, row_id: int, changes: dict):
    model = _reference_model(kind)
    row = model.objects.filter(pk=row_id).first()
    if row is None:
        raise Http404(f"{model.__name__} not found")
    for field, value in changes.items():
        setattr(row, field, value)
    row.save()
    return row


def delete_reference_row(kind: str, row_id: int) -> None:
    """Мягкое отключение, а не удаление — по той же причине, что у техники:
    на строку ссылаются потребности и уже заведённая номенклатура, а FK
    стоят ``PROTECT``, так что настоящее удаление упёрлось бы в базу."""
    model = _reference_model(kind)
    row = model.objects.filter(pk=row_id).first()
    if row is None:
        raise Http404(f"{model.__name__} not found")
    row.is_active = False
    row.save(update_fields=["is_active", "updated_at"])


def build_reference_row(row) -> dict:
    out = {"id": row.id, "slug": row.slug, "name": row.name,
           "is_active": row.is_active}
    if isinstance(row, WorkVolumeType):
        out["unit"] = str(row.unit)
    return out


def resolve_equipment_category(category_id: int | None,
                               name: str | None) -> int | None:
    """FK id категории техники по вводу пользователя.

    Явный ``category_id`` (выпадающий список) выигрывает. Имя строкой —
    легаси-путь опубликованного контракта (``EquipmentResponse.category``
    это ``str|null``, и фронт до сих пор шлёт текст): ищем без учёта
    регистра, а незнакомое имя ЗАВОДИМ. Ручка админская, и «купили машину
    нового типа» — законный сценарий, ради которого гонять администратора
    сначала в справочник значит мешать работать. Пустая строка — это
    «категории нет», а не категория с пустым именем.
    """
    if category_id is not None:
        return category_id
    cleaned = (name or "").strip()
    if not cleaned:
        return None
    existing = (EquipmentCategory.objects.filter(name__iexact=cleaned)
                .values_list("id", flat=True).first())
    if existing is not None:
        return existing
    return EquipmentCategory.objects.create(
        slug=generate_unique_slug(cleaned, EquipmentCategory),
        name=cleaned,
    ).id


# ── equipment ───────────────────────────────────────────────────────────

def list_equipment(active_only: bool = True, *,
                   ownership: str | None = None,
                   contractor_id: int | None = None,
                   category_id: int | None = None) -> list[Equipment]:
    # select_related: без него имя владельца и название категории в каждой
    # строке справочника стоили бы по отдельному запросу.
    qs = Equipment.objects.select_related("contractor", "category")
    if active_only:
        qs = qs.filter(is_active=True)
    if ownership:
        qs = qs.filter(ownership=ownership)
    if contractor_id is not None:
        qs = qs.filter(contractor_id=contractor_id)
    if category_id is not None:
        qs = qs.filter(category_id=category_id)
    return list(qs.order_by("name"))


def build_equipment(row: Equipment) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "inventory_no": row.inventory_no,
        # Строкой, а не объектом: ``category`` в опубликованном контракте
        # это ``str|null``, и менять его форму ради внутренней нормализации
        # незачем. Кому нужен id для выпадающего списка — берёт category_id.
        "category": row.category.name if row.category else None,
        "category_id": row.category_id,
        "is_active": row.is_active,
        "ownership": str(row.ownership),
        "contractor_id": row.contractor_id,
        "contractor_name": row.contractor.name if row.contractor else None,
    }


def create_equipment(*, category: str | None = None,
                     category_id: int | None = None, **fields) -> Equipment:
    row = Equipment.objects.create(
        category_id=resolve_equipment_category(category_id, category), **fields)
    # Перечитываем со связями: build_equipment сразу зовут на результате, а
    # без этого он сходит в БД за именами владельца и категории по одному.
    return (Equipment.objects.select_related("contractor", "category")
            .get(pk=row.pk))


def update_equipment(equipment_id: int, changes: dict) -> Equipment:
    obj = Equipment.objects.filter(pk=equipment_id).first()
    if obj is None:
        raise Http404("Equipment not found")
    # ``exclude_unset`` во вьюхе означает, что ключ здесь есть только если
    # его прислали. Пустую строку/None трактуем как «снять категорию».
    if "category" in changes or "category_id" in changes:
        obj.category_id = resolve_equipment_category(
            changes.pop("category_id", None), changes.pop("category", None))
    for field, value in changes.items():
        setattr(obj, field, value)
    obj.save()
    return (Equipment.objects.select_related("contractor", "category")
            .get(pk=obj.pk))


def delete_equipment(equipment_id: int) -> None:
    """Soft-disable rather than hard delete — historical ``ResourceAllocation``
    rows reference this equipment and a real delete would cascade them away."""
    obj = Equipment.objects.filter(pk=equipment_id).first()
    if obj is None:
        raise Http404("Equipment not found")
    obj.is_active = False
    obj.save(update_fields=["is_active", "updated_at"])

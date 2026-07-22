"""Reference-data CRUD: labels, task types, equipment.

Ported from ``services/task/app/api/v1/{labels,task_types,equipment}.py`` and
the ``TaskTypeRepository`` slug helpers. These three are plain CRUD; the only
real logic is slug generation and the two deletion rules (system task types
are undeletable, equipment is soft-disabled rather than deleted).
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.http import Http404

from ..models import Equipment, Label, TaskType

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


def generate_unique_slug(name: str) -> str:
    base = slugify_name(name)
    candidate = base
    suffix = 2
    while TaskType.objects.filter(slug=candidate).exists():
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


# ── equipment ───────────────────────────────────────────────────────────

def list_equipment(active_only: bool = True) -> list[Equipment]:
    qs = Equipment.objects.all()
    if active_only:
        qs = qs.filter(is_active=True)
    return list(qs.order_by("name"))


def create_equipment(**fields) -> Equipment:
    return Equipment.objects.create(**fields)


def update_equipment(equipment_id: int, changes: dict) -> Equipment:
    obj = Equipment.objects.filter(pk=equipment_id).first()
    if obj is None:
        raise Http404("Equipment not found")
    for field, value in changes.items():
        setattr(obj, field, value)
    obj.save()
    return obj


def delete_equipment(equipment_id: int) -> None:
    """Soft-disable rather than hard delete — historical ``TaskAssignment``
    rows reference this equipment and a real delete would cascade them away."""
    obj = Equipment.objects.filter(pk=equipment_id).first()
    if obj is None:
        raise Http404("Equipment not found")
    obj.is_active = False
    obj.save(update_fields=["is_active", "updated_at"])

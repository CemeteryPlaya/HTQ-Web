"""Seed the five system task types (PLAN.md §6.1).

Carried over verbatim from the FastAPI original's alembic migration
``013_projects_and_task_types.py`` (its ``SEED_TYPES`` list) — slug, display
name, colour and icon all match, so tasks migrated in phase 10 keep resolving
their type and the UI keeps its familiar chips.

These rows are ``is_system=True``: the API refuses to delete them
(``apps.tasks.services.task_type_service.delete_task_type`` -> 403), because
``Task.task_type`` is ``SET_NULL`` and dropping "Задача" would silently
untype every historical task pointing at it.

Reversible on purpose — ``unseed`` removes exactly these five slugs and
nothing else, so a rollback doesn't take user-defined types with it. It is
also safe to re-run: ``update_or_create`` keyed on the slug means a second
forward pass repairs drifted display fields instead of raising on the unique
index.
"""

from django.db import migrations

# (slug, name, color, icon)
SEED_TYPES = [
    ("task", "Задача", "#3b82f6", "check-square"),
    ("bug", "Баг", "#ef4444", "bug"),
    ("story", "История", "#22c55e", "book-open"),
    ("epic", "Эпик", "#8b5cf6", "layers"),
    ("subtask", "Подзадача", "#6b7280", "list-todo"),
]


def seed(apps, schema_editor):
    TaskType = apps.get_model("tasks", "TaskType")
    for slug, name, color, icon in SEED_TYPES:
        TaskType.objects.update_or_create(
            slug=slug,
            defaults={"name": name, "color": color, "icon": icon,
                      "is_system": True},
        )


def unseed(apps, schema_editor):
    TaskType = apps.get_model("tasks", "TaskType")
    TaskType.objects.filter(slug__in=[slug for slug, *_ in SEED_TYPES],
                            is_system=True).delete()


class Migration(migrations.Migration):

    dependencies = [("tasks", "0001_initial")]

    operations = [migrations.RunPython(seed, unseed)]

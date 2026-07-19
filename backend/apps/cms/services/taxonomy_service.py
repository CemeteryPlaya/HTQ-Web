"""Domain logic for taxonomy (categories, tags) — kept out of ``views.py``.

Ported from ``services/cms/app/api/v1/taxonomy.py`` (the FastAPI route
bodies). Read endpoints are public in the FastAPI original (the public news
feed needs the lists for filters); mutating endpoints require admin — the
same split ``views.py`` implements.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.utils import IntegrityError
from django.http import Http404

from apps.cms.models import Category, Tag


class ConflictError(Exception):
    """Raised on a unique-constraint violation (slug conflicts)."""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


# --- Categories --------------------------------------------------------------


def list_categories() -> list[Category]:
    return list(Category.objects.order_by("name"))


def get_category_or_404(category_id: int) -> Category:
    try:
        return Category.objects.get(pk=category_id)
    except Category.DoesNotExist as exc:
        raise Http404("Category not found") from exc


def create_category(values: dict[str, Any]) -> Category:
    cat = Category(**values)
    try:
        with transaction.atomic():
            cat.save()
    except IntegrityError as exc:
        raise ConflictError("Slug already exists") from exc
    return cat


def update_category(cat: Category, changes: dict[str, Any]) -> Category:
    for key, value in changes.items():
        setattr(cat, key, value)
    try:
        with transaction.atomic():
            cat.save()
    except IntegrityError as exc:
        raise ConflictError("Slug conflict") from exc
    return cat


def delete_category(cat: Category) -> None:
    cat.delete()


# --- Tags ----------------------------------------------------------------


def list_tags() -> list[Tag]:
    return list(Tag.objects.order_by("name"))


def get_tag_or_404(tag_id: int) -> Tag:
    try:
        return Tag.objects.get(pk=tag_id)
    except Tag.DoesNotExist as exc:
        raise Http404("Tag not found") from exc


def create_tag(values: dict[str, Any]) -> Tag:
    tag = Tag(**values)
    try:
        with transaction.atomic():
            tag.save()
    except IntegrityError as exc:
        raise ConflictError("Slug already exists") from exc
    return tag


def update_tag(tag: Tag, changes: dict[str, Any]) -> Tag:
    for key, value in changes.items():
        setattr(tag, key, value)
    try:
        with transaction.atomic():
            tag.save()
    except IntegrityError as exc:
        raise ConflictError("Slug conflict") from exc
    return tag


def delete_tag(tag: Tag) -> None:
    tag.delete()

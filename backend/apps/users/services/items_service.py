"""Item CRUD — user-owned notes/drafts, strictly scoped to the owner.

Ported from ``services/user/app/api/v1/items.py`` (the FastAPI original).
Every query filters on ``owner_id == <caller>`` in the WHERE clause itself
(not "fetch then check owner"), so an item that exists but belongs to a
different user is indistinguishable from an item that doesn't exist at
all — reproduced here the same way: a non-owner (or anyone unauthenticated)
addressing another user's item id gets ``ItemNotFound`` (404), never 403.
"""

from __future__ import annotations

from apps.users.models import Item


class ItemNotFound(Exception):
    """No item with this id owned by this caller. Maps to 404."""


def list_items(owner_id: int) -> list[Item]:
    """``GET items/`` — only the caller's own items, newest first."""
    return list(Item.objects.filter(owner_id=owner_id).order_by("-created_at"))


def create_item(owner_id: int, *, title: str, description: str = "") -> Item:
    """``POST items/`` — always owned by the caller (``owner_id`` comes from
    the token, never from the request body)."""
    return Item.objects.create(title=title, description=description, owner_id=owner_id)


def get_item_or_404(owner_id: int, item_id: int) -> Item:
    """Shared lookup for GET/PATCH/DELETE ``items/{id}/`` — scoped to the
    owner at the query level, matching the source's ``.where(Item.id ==
    item_id, Item.owner_id == current_user.user_id)``."""
    item = Item.objects.filter(id=item_id, owner_id=owner_id).first()
    if item is None:
        raise ItemNotFound()
    return item


def update_item(item: Item, changes: dict) -> Item:
    """``PATCH items/{id}/`` — partial update; ``changes`` is the request's
    ``model_dump(exclude_unset=True)``. Item has no ``updated_at`` column
    (the source model doesn't either), so nothing extra to touch."""
    touched = set(changes)
    for field, value in changes.items():
        setattr(item, field, value)
    if touched:
        item.save(update_fields=list(touched))
    return item


def delete_item(item: Item) -> None:
    item.delete()


def serialize(item: Item) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "description": item.description,
        "owner_id": item.owner_id,
        "created_at": item.created_at.isoformat(),
    }

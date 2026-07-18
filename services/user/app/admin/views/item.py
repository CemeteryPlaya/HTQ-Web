"""sqladmin view for the Item model (per-user content)."""

from sqladmin import ModelView

from app.models.item import Item


class ItemAdmin(ModelView, model=Item):
    name = "Item"
    name_plural = "Items"
    icon = "fa-solid fa-note-sticky"

    column_list = [Item.id, Item.title, Item.owner_id, Item.created_at]
    column_searchable_list = [Item.title]
    column_sortable_list = [Item.id, Item.created_at, Item.owner_id]
    column_default_sort = [(Item.created_at, True)]

"""sqladmin ModelView for ContactRequest."""

from sqladmin import ModelView

from app.models.contact_request import ContactRequest


class ContactRequestAdmin(ModelView, model=ContactRequest):
    column_list = [
        ContactRequest.id,
        ContactRequest.email,
        ContactRequest.first_name,
        ContactRequest.last_name,
        ContactRequest.handled,
        ContactRequest.replied_at,
        ContactRequest.created_at,
    ]
    column_searchable_list = [ContactRequest.email, ContactRequest.first_name, ContactRequest.last_name]
    column_sortable_list = [
        ContactRequest.id,
        ContactRequest.email,
        ContactRequest.handled,
        ContactRequest.created_at,
    ]
    column_default_sort = ("created_at", True)
    page_size = 25
    name = "Contact Request"
    name_plural = "Contact Requests"
    icon = "fa-solid fa-envelope"

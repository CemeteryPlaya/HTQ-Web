"""Domain logic for contact-requests — kept out of ``views.py``.

Ported from ``services/cms/app/api/v1/contact_requests.py`` (the FastAPI
route bodies), minus the audit-log / Dramatiq-notification side effects:
those depend on infrastructure (``app.services.audit``, the email-service
worker actor) that has no Django-port equivalent yet and is out of scope for
Task 1.4 (HTTP-layer scaffolding + the contact-requests contract itself).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from django.http import Http404

from apps.cms.models import ContactRequest


def create_contact_request(*, first_name: str, last_name: str, email: str, message: str) -> ContactRequest:
    return ContactRequest.objects.create(
        first_name=first_name, last_name=last_name, email=email, message=message,
    )


def list_contact_requests(*, handled: Optional[bool], limit: int, offset: int) -> list[ContactRequest]:
    qs = ContactRequest.objects.order_by("-created_at")
    if handled is not None:
        qs = qs.filter(handled=handled)
    return list(qs[offset:offset + limit])


def contact_request_stats() -> int:
    """Unhandled contact-request count for the admin badge."""
    return ContactRequest.objects.filter(handled=False).count()


def get_contact_request_or_404(contact_id: int) -> ContactRequest:
    try:
        return ContactRequest.objects.get(pk=contact_id)
    except ContactRequest.DoesNotExist as exc:
        raise Http404("Contact request not found") from exc


def update_contact_request(entry: ContactRequest, changes: dict) -> ContactRequest:
    for key, value in changes.items():
        setattr(entry, key, value)
    # An empty `changes` (PATCH body with nothing set) must stay a true
    # no-op — Django's save(update_fields=[]) skips the query entirely,
    # mirroring the FastAPI original's empty for-loop + flush().
    entry.save(update_fields=list(changes))
    return entry


def reply_to_contact_request(entry: ContactRequest, *, reply_message: str, admin_user_id: int) -> ContactRequest:
    entry.reply_message = reply_message
    entry.replied_at = datetime.now(timezone.utc)
    entry.replied_by_id = admin_user_id
    entry.handled = True
    entry.save(update_fields=["reply_message", "replied_at", "replied_by_id", "handled"])
    return entry


def delete_contact_request(entry: ContactRequest) -> None:
    entry.delete()

"""Registration + moderation business logic — register, approve, reject.

Ported from ``services/user/app/api/v1/registration.py`` (the FastAPI
original inlines this directly in the router; split out here per this app's
"business logic in a ``<domain>_service.py``" convention — see
``apps.users.services.auth_service``).

**Decision Р2 (dropped):** the FastAPI source publishes ``user_upserted``/
``user_deactivated`` Redis pub/sub events after approve/reject so
messenger/task/HR replicas stay in sync with the canonical user row. This
port does NOT re-publish those — per the customer decision, neighbouring
services will read user data through ``apps.users.interface`` instead of a
fan-out. See the task 2.4 report for the full list of dropped broadcasts.
"""

from __future__ import annotations

from apps.users.models import User, UserStatus


class DuplicateEmail(Exception):
    """Email already registered. Maps to 400 at the view layer — the
    FastAPI original raises ``HTTPException(400, "Email already
    registered")`` here, NOT 409."""


class PendingRegistrationNotFound(Exception):
    """No PENDING user with this id — maps to 404 (approve/reject)."""


def _split_full_name(full_name: str) -> tuple[str, str]:
    """Ported verbatim from the FastAPI original's inline split:
    ``request.full_name.strip().split(maxsplit=1)``."""
    parts = full_name.strip().split(maxsplit=1)
    first_name = parts[0] if len(parts) > 0 else ""
    last_name = parts[1] if len(parts) > 1 else ""
    return first_name, last_name


def register(*, email: str, password: str, full_name: str) -> User:
    """``POST register/`` — create a PENDING user awaiting admin approval.

    ``username`` is generated from the (lower-cased) email, same as the
    FastAPI original. Password is hashed via ``User.set_password`` (PBKDF2)
    rather than the source's standalone ``hash_password`` helper — this
    Django port's established convention (Task 2.1/2.3).
    """
    email_norm = email.lower()
    if User.objects.filter(email=email_norm).exists():
        raise DuplicateEmail()

    first_name, last_name = _split_full_name(full_name)

    user = User(
        username=email_norm,
        email=email_norm,
        first_name=first_name,
        last_name=last_name,
        display_name=full_name.strip(),
        status=UserStatus.PENDING,
    )
    user.set_password(password)
    user.save()
    return user


def list_pending() -> list[User]:
    """``GET pending-registrations/`` — all PENDING users, oldest first."""
    return list(User.objects.filter(status=UserStatus.PENDING).order_by("date_joined"))


def approve(user_id: int) -> User:
    """``POST pending-registrations/{id}/approve/`` — PENDING -> ACTIVE.

    Raises ``PendingRegistrationNotFound`` if no PENDING user matches
    ``user_id`` (already-approved/rejected/unknown ids all 404, matching
    the source's single combined query filter).
    """
    user = User.objects.filter(id=user_id, status=UserStatus.PENDING).first()
    if user is None:
        raise PendingRegistrationNotFound()
    user.status = UserStatus.ACTIVE
    user.save(update_fields=["status", "updated_at"])
    return user


def reject(user_id: int) -> User:
    """``POST pending-registrations/{id}/reject/`` — PENDING -> REJECTED."""
    user = User.objects.filter(id=user_id, status=UserStatus.PENDING).first()
    if user is None:
        raise PendingRegistrationNotFound()
    user.status = UserStatus.REJECTED
    user.save(update_fields=["status", "updated_at"])
    return user

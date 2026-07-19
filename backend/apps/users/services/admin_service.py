"""Admin user-management business logic — list/create/update/delete/set-password.

Ported from ``services/user/app/api/v1/admin.py`` (the FastAPI original).

Three things the source does that this port intentionally DROPS (customer
decisions Р2/Р3 — see the task 2.4 report for the full inventory):

* **Redis pub/sub broadcasts** (``user_upserted``/``user_deactivated``/
  ``user_deleted``) after create/update/delete — neighbouring services will
  read user data through ``apps.users.interface`` instead of a fan-out (Р2).
  The view layer notes each dropped call site.
* **The S2S mailbox-archive call** in ``delete_user``
  (``_archive_user_mailbox``, an ``httpx`` call to email-service) — Р3, no
  S2S. ``delete_user``'s LOCAL effect (``status=SUSPENDED``, strip elevated
  flags) is still performed below.
* **Mailcow mailbox *provisioning*** in ``create_user``
  (``_provision_mailbox``, also an S2S email-service call) — dropped for
  the same Р3 reason. ``create_mailbox``/``mailbox_local_part``/
  ``mailbox_password``/``mailbox_quota_mb`` request fields and the
  ``mailbox``/``mailbox_error`` response fields from the source's
  ``AdminUserCreateRequest``/``AdminUserCreatedResponse`` are not part of
  this port's schema (``apps.users.schemas.AdminUserCreateRequest``).
"""

from __future__ import annotations

import json

from apps.users.models import User, UserStatus
from apps.users.services.profile_service import roles_for


class DuplicateEmail(Exception):
    """Email already in use by another user. Maps to 400."""


class DuplicateUsername(Exception):
    """Username already in use by another user. Maps to 400."""


class InvalidStatus(Exception):
    """``status`` string isn't a valid ``UserStatus`` value. Maps to 400
    with the source's exact message shape."""

    def __init__(self, value: str):
        self.value = value
        super().__init__(f"Invalid status: {value}")


class UserNotFound(Exception):
    """No user with this id. Maps to 404."""


class InvalidSettingsJSON(Exception):
    """``settings`` was a string but not valid-JSON-object text. Maps to 400."""


def list_users() -> list[User]:
    """``GET admin/users/`` — every user, newest first."""
    return list(User.objects.order_by("-date_joined"))


def create_user(
    *,
    username: str,
    email: str,
    password: str,
    first_name: str = "",
    last_name: str = "",
    patronymic: str = "",
    display_name: str = "",
    bio: str = "",
    phone: str = "",
    status: str = "active",
    is_staff: bool = False,
    is_superuser: bool = False,
    must_change_password: bool = True,
) -> User:
    """``POST admin/users/`` — admin-created user, bypassing self-registration.

    Uniqueness on both ``email`` and ``username`` is checked explicitly (two
    separate error messages, ported verbatim from the source) rather than
    relying on the DB's unique-constraint IntegrityError.
    """
    email_norm = email.strip().lower()
    username_norm = username.strip()

    if User.objects.filter(email=email_norm).exists():
        raise DuplicateEmail()
    if User.objects.filter(username=username_norm).exists():
        raise DuplicateUsername()
    if status not in UserStatus.values:
        raise InvalidStatus(status)

    user = User(
        username=username_norm,
        email=email_norm,
        first_name=first_name,
        last_name=last_name,
        patronymic=patronymic,
        display_name=display_name or f"{first_name} {last_name}".strip(),
        bio=bio,
        phone=phone,
        status=status,
        is_staff=is_staff,
        is_superuser=is_superuser,
        must_change_password=must_change_password,
    )
    user.set_password(password)
    user.save()
    return user


def get_user_or_404(user_id: int) -> User:
    user = User.objects.filter(id=user_id).first()
    if user is None:
        raise UserNotFound()
    return user


def update_user(user: User, changes: dict) -> User:
    """``PATCH admin/users/{id}/`` — apply an admin partial update.

    ``changes`` is the request's ``model_dump(exclude_unset=True)`` — only
    explicitly-sent fields land. Only ``email``/``username`` (uniqueness)
    and ``settings`` (JSON parsing) get special handling; everything else
    is a direct ``setattr``, ported verbatim from the source's field loop.

    Note: unlike ``create_user``, an invalid ``status`` string is NOT
    validated here — the FastAPI original doesn't guard ``UserStatus(value)``
    with a try/except in ``update_user`` either (only in ``create_user``),
    so this mirrors that omission rather than inventing stricter behaviour
    the source doesn't have.
    """
    update_data = dict(changes)

    new_email = update_data.get("email")
    if new_email is not None:
        new_email = new_email.strip().lower()
        if new_email != user.email and User.objects.filter(email=new_email).exclude(pk=user.pk).exists():
            raise DuplicateEmail()
        update_data["email"] = new_email

    new_username = update_data.get("username")
    if new_username is not None:
        new_username = new_username.strip()
        if new_username != user.username and User.objects.filter(username=new_username).exclude(pk=user.pk).exists():
            raise DuplicateUsername()
        update_data["username"] = new_username

    touched: set[str] = set()
    for field, value in update_data.items():
        if field == "settings" and value is not None:
            if isinstance(value, str):
                try:
                    parsed = json.loads(value) if value else {}
                except json.JSONDecodeError as exc:
                    raise InvalidSettingsJSON("settings must be valid JSON") from exc
                if not isinstance(parsed, dict):
                    raise InvalidSettingsJSON("settings must be a JSON object")
                user.settings = parsed
            else:
                user.settings = value
        else:
            setattr(user, field, value)
        touched.add(field)

    if touched:
        touched.add("updated_at")
        user.save(update_fields=list(touched))
    return user


def set_password(user: User, *, new_password: str, must_change_password: bool = True) -> None:
    """``POST admin/users/{id}/set-password/`` — admin-initiated reset,
    bypasses the current-password check (pairs with ``must_change_password``
    to force the target user through the change-password screen)."""
    user.set_password(new_password)
    user.must_change_password = must_change_password
    user.save(update_fields=["password", "must_change_password", "updated_at"])


def delete_user(user: User) -> None:
    """``DELETE admin/users/{id}/`` — soft-delete: ``status=SUSPENDED`` +
    strip elevated flags so the user can no longer log in or retain admin
    access. The mailbox-archive S2S call and the user.deactivated/
    user.deleted broadcasts from the source are intentionally NOT performed
    here — see the module docstring (Р2/Р3)."""
    user.status = UserStatus.SUSPENDED
    user.is_staff = False
    user.is_superuser = False
    user.save(update_fields=["status", "is_staff", "is_superuser", "updated_at"])


def serialize_admin_user(user: User) -> dict:
    """Build the ``AdminUserResponse`` payload — ported field-for-field from
    the source's ``_admin_user_response``. ``roles_for`` is reused from
    ``profile_service`` rather than duplicated (identical rule)."""
    first_name = user.first_name or ""
    last_name = user.last_name or ""
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "first_name": first_name,
        "last_name": last_name,
        "firstName": first_name,
        "lastName": last_name,
        "patronymic": user.patronymic or "",
        "display_name": user.display_name or "",
        "bio": user.bio or "",
        "phone": user.phone or "",
        "avatar_url": user.avatar_url,
        "avatarUrl": user.avatar_url,
        "settings": user.settings or {},
        "roles": roles_for(user),
        "status": user.status,
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
        "must_change_password": bool(user.must_change_password),
        "date_joined": user.date_joined.isoformat() if user.date_joined else "",
        "last_login": user.last_login.isoformat() if user.last_login else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }

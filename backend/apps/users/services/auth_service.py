"""Authentication business logic — login, refresh, admin-session.

Ported from ``services/user/app/api/v1/auth.py`` (the FastAPI original
inlines this directly in the router; split out here into
``app/services/<domain>_service.py`` per this app's convention — see
``apps.cms.services.contact_requests_service`` for the established shape).
"""

from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from apps.users.models import User, UserStatus


class InvalidCredentials(Exception):
    """Unknown user, or a known user with a wrong password."""


class AccountNotActivated(Exception):
    """User found (and password not yet checked) but ``status != ACTIVE``."""


class NotAnAdminUser(Exception):
    """User found, active, correct credentials, but no elevated flag."""


def _find_user(login_id: str) -> User | None:
    """Login by email OR username — case-sensitive on username, the email
    side lower-cased to match ``User.email``'s normalized storage. Ported
    verbatim from the FastAPI original's ``select(User).where((User.email ==
    request.email.lower()) | (User.username == request.email))``."""
    return User.objects.filter(Q(email=login_id.lower()) | Q(username=login_id)).first()


def authenticate(login_id: str, password: str) -> User:
    """``POST token/`` login.

    Reproduces the FastAPI original's check order exactly
    (``obtain_token``): unknown user -> ``InvalidCredentials``; user found
    but not ``ACTIVE`` -> ``AccountNotActivated`` (checked *before* the
    password, so an inactive account with a wrong password still reports
    "not activated", not "invalid credentials"); active user + wrong
    password -> ``InvalidCredentials``. On success, updates ``last_login``.
    """
    user = _find_user(login_id)
    if user is None:
        raise InvalidCredentials()
    if user.status != UserStatus.ACTIVE:
        raise AccountNotActivated()
    if not user.check_password(password):
        raise InvalidCredentials()

    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])
    return user


def authenticate_admin(login_id: str, password: str) -> User:
    """``POST admin-session/login``.

    Different check order/error set than ``authenticate`` above — ported
    verbatim from the FastAPI original's ``admin_login``: missing user OR
    not ``ACTIVE`` -> ``InvalidCredentials``; active but neither
    ``is_staff`` nor ``is_superuser`` -> ``NotAnAdminUser``; active +
    elevated but wrong password -> ``InvalidCredentials``. Does not touch
    ``last_login`` (the source doesn't either).
    """
    user = _find_user(login_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise InvalidCredentials()
    if not (user.is_staff or user.is_superuser):
        raise NotAnAdminUser()
    if not user.check_password(password):
        raise InvalidCredentials()
    return user

"""Active-user picker options — ``GET users/options/``.

Ported from ``services/user/app/api/v1/users.py`` (the FastAPI original).
Drives any "pick a colleague" UI: any authenticated user may call this
(no admin gate), and the result excludes suspended/pending/rejected
accounts — only ``UserStatus.ACTIVE``. ``query`` filters case-insensitively
across first/last name, email, username, and display_name — the same five
columns the source ORs together.
"""

from __future__ import annotations

from django.db.models import Q

from apps.users.models import User, UserStatus


def list_user_options(*, query: str | None, limit: int) -> list[User]:
    qs = User.objects.filter(status=UserStatus.ACTIVE)
    if query:
        qs = qs.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
            | Q(username__icontains=query)
            | Q(display_name__icontains=query)
        )
    return list(qs.order_by("last_name", "first_name")[:limit])


def full_name_for(user: User) -> str:
    """Mirrors the source's ``f"{first_name} {last_name}".strip() or
    display_name or username`` fallback chain."""
    name = f"{user.first_name} {user.last_name}".strip()
    return name or user.display_name or user.username

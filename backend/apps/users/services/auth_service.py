"""Authentication business logic — login, refresh.

Ported from ``services/user/app/api/v1/auth.py`` (the FastAPI original
inlines this directly in the router; split out here into
``app/services/<domain>_service.py`` per this app's convention — see
``apps.cms.services.contact_requests_service`` for the established shape).
"""

from __future__ import annotations

from django.contrib.auth.hashers import make_password
from django.db.models import Q
from django.utils import timezone

from apps.users.models import User, UserStatus


class InvalidCredentials(Exception):
    """Unknown user, or a known user with a wrong password."""


class AccountNotActivated(Exception):
    """Пароль верен, но ``status != ACTIVE`` (поднимается только после проверки пароля)."""


def find_user(login_id: str) -> User | None:
    """Публичный поиск по логину входа (``auth_unlock`` использует тот же)."""
    return _find_user(login_id)


def _find_user(login_id: str) -> User | None:
    """Login by email OR username — case-sensitive on username, the email
    side lower-cased to match ``User.email``'s normalized storage. Ported
    verbatim from the FastAPI original's ``select(User).where((User.email ==
    request.email.lower()) | (User.username == request.email))``."""
    return User.objects.filter(Q(email=login_id.lower()) | Q(username=login_id)).first()


def authenticate(login_id: str, password: str) -> User:
    """``POST token/`` login.

    Порядок проверок (D-S7-3; у FastAPI-оригинала статус шёл ДО пароля, и
    это выдавало существование логина): неизвестный логин ->
    ``InvalidCredentials``; неверный пароль (в том числе у неактивной учётки)
    -> ``InvalidCredentials``; верный пароль, но статус не ``ACTIVE`` ->
    ``AccountNotActivated``. «Не активирована» слышит только тот, кто знает
    пароль. Для неизвестного логина хеш всё равно считается, чтобы время
    ответа не выдавало существование. При успехе обновляется ``last_login``.
    """
    user = _find_user(login_id)
    if user is None:
        make_password(password)
        raise InvalidCredentials()
    if not user.check_password(password):
        raise InvalidCredentials()
    if user.status != UserStatus.ACTIVE:
        raise AccountNotActivated()

    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])
    return user


def reset_lockout(user: User) -> None:
    """Снять блокировку входа по обоим логинам пользователя (имя и e-mail)."""
    from htqweb import ratelimit

    for login in {user.username, user.email}:
        if login:
            ratelimit.reset_login(login)

import secrets
from datetime import datetime, timedelta, timezone

import jwt
from django.conf import settings

from .payload import TokenPayload


class AuthError(Exception):
    pass


def _base_claims(user) -> dict:
    # Локальный импорт: htqweb.authn грузится очень рано, а apps.companies —
    # обычная аппка, чьи модели к тому моменту ещё не готовы.
    from apps.companies.interface import default_company_slug

    return {
        "sub": str(user.id),
        "user_id": user.id,
        "username": user.username,
        "email": user.email,
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
        "is_admin": user.is_staff or user.is_superuser,
        # Компания по умолчанию. При переключении компании фронт получает
        # новый access-токен обменом refresh-cookie — см. задачу 13.
        "company": default_company_slug(user.id),
        "iss": settings.JWT_ISSUER,
    }


def _refresh_claims(user) -> dict:
    """Minimal claim set for refresh tokens.

    Mirrors ``services/user/app/services/auth_service.py``'s
    ``create_token_pair``: a refresh token is long-lived (7 days), so it
    deliberately does NOT carry privilege flags or PII (username/email/
    is_staff/is_superuser/is_admin) — only enough to look the user back up.
    Auth claims are re-derived from the DB on every ``token/refresh/`` call
    (see ``apps.users.views.refresh_token``), so a refresh token can't hand
    out stale privileges even if it outlives a role change.
    """
    return {
        "sub": str(user.id),
        "user_id": user.id,
        "iss": settings.JWT_ISSUER,
    }


def _encode(claims: dict, ttl: timedelta, token_type: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {**claims, "token_type": token_type,
         "iat": int(now.timestamp()),
         "exp": int((now + ttl).timestamp())},
        settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def issue_token_pair(user) -> dict:
    return {
        "access": _encode(_base_claims(user), timedelta(minutes=settings.JWT_ACCESS_TTL_MIN), "access"),
        "refresh": _encode(_refresh_claims(user), timedelta(days=settings.JWT_REFRESH_TTL_DAYS), "refresh"),
        "token_type": "Bearer",
    }


def issue_guest_token(*, room_id: str, display_name: str,
                      ttl_minutes: int | None = None) -> tuple[str, int]:
    """Токен внешнего участника конференции. Возвращает ``(токен, ttl_сек)``.

    Гость — человек без учётки в платформе: открыл ссылку-приглашение, ввёл
    имя, вошёл в звонок. Токен подписан тем же секретом, что и обычные, —
    иначе SFU его не примет (он валидирует подпись сам, см. sfu/src/auth.ts),
    — но отличается от них двумя вещами, и обе несут нагрузку:

    * ``token_type="guest"`` — API платформы такой токен не пускает никуда.
      Проверка стоит в ``htqweb.http._authenticate_jwt`` (пускает только
      ``"access"``), а SFU разрешает гостю ровно одно действие — войти в
      свою комнату.
    * ``room_id`` — токен привязан к ОДНОЙ комнате. Без этого гостевая
      ссылка на планёрку открывала бы любое совещание в компании: SFU не
      знает, кого куда звали, и до сих пор верил любому валидному токену.

    ``user_id`` не выдаётся намеренно, и это вторая линия обороны: даже если
    когда-нибудь ослабят проверку ``token_type``, ``TokenPayload`` без
    обязательного ``user_id`` не соберётся и авторизация всё равно откажет.
    """
    ttl = timedelta(minutes=ttl_minutes or settings.CONFERENCE_GUEST_TOKEN_TTL_MIN)
    claims = {
        # Уникальный sub на каждого гостя: по нему различаются участники в
        # логах SFU, а имя человек вводит сам и оно не уникально.
        "sub": f"guest:{secrets.token_hex(8)}",
        "username": display_name,
        "room_id": room_id,
        "is_staff": False,
        "is_superuser": False,
        "is_admin": False,
        "iss": settings.JWT_ISSUER,
    }
    return _encode(claims, ttl, "guest"), int(ttl.total_seconds())


def decode_token(token: str) -> TokenPayload:
    try:
        raw = jwt.decode(token, settings.JWT_SECRET,
                         algorithms=[settings.JWT_ALGORITHM],
                         issuer=settings.JWT_ISSUER)
    except jwt.PyJWTError as exc:
        raise AuthError(str(exc)) from exc
    return TokenPayload(**raw)

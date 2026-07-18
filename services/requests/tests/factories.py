import time

import jwt

from app.core.settings import settings


def make_token(user_id: int, *, is_staff: bool = False, is_superuser: bool = False) -> str:
    payload = {
        "user_id": user_id,
        "username": f"user{user_id}",
        "email": f"user{user_id}@x.kz",
        "is_staff": is_staff,
        "is_superuser": is_superuser,
        "is_admin": is_staff or is_superuser,
        "token_type": "access",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "iss": settings.jwt_issuer,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def auth(user_id: int, **flags) -> dict:
    return {"Authorization": f"Bearer {make_token(user_id, **flags)}"}

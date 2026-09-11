"""Кто спрашивает права.

Разрешение прав вызывается из двух мест с РАЗНЫМИ объектами пользователя:
гейт ``api_view`` держит только ``htqweb.authn.payload.TokenPayload`` (там
``user_id``), а профиль и django-admin — модель ``auth.User`` (там ``id``).
Приводить одно к другому запросом в БД нельзя: гейт срабатывает на каждом
запросе, и лишний ``SELECT`` там стоил бы дороже самой проверки.

Поэтому принимаются оба, а разбор формы собран в одну функцию — иначе каждый
вызывающий начал бы разбираться сам, и первый же ``user.id`` на токене дал бы
``AttributeError`` в проде, а не в тесте.
"""

from __future__ import annotations


def identity(user) -> tuple[int, bool]:
    """``(user_id, is_superuser)`` из Django-модели либо из ``TokenPayload``."""
    user_id = getattr(user, "id", None)
    if user_id is None:
        user_id = getattr(user, "user_id", None)
    if user_id is None:
        raise TypeError(
            f"{type(user).__name__} не похож ни на auth.User, ни на TokenPayload: "
            "нет ни id, ни user_id"
        )
    return int(user_id), bool(getattr(user, "is_superuser", False))

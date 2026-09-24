"""Общие помощники HTTP-тестов cms под гейтом модуля (блок L, задача 8).

Ручки ``/api/cms/v1/*`` с ``auth="jwt"`` стоят под ``api_view(module="cms",
level=…)``: правка контента — ``write``, приглашения и конфиг конференции —
``read``. Им нужны заголовок ``X-HTQ-Company``, claim ``company`` в токене,
совпадающий с ним, действующая строка ``Company`` и роль в этой компании.
Публичные ручки (``auth=None``) гейта не несут; заголовок компании им не мешает.
"""
from __future__ import annotations

import jwt as pyjwt
from django.conf import settings

#: Компания тестов ручек под гейтом ``module="cms"``. Своя, а не общая:
#: строка заводится лениво из ``auth_header``, чтобы не попадать в
#: ``active_company_slugs()`` тестов веера по компаниям.
COMPANY = "t-cms-gate"


def token(**over) -> str:
    """Токен рядового пользователя 7 с компанией тестов; ``over`` перекрывает."""
    claims = {
        "user_id": 7, "username": "u", "email": "u@htq.test",
        "is_staff": False, "is_superuser": False, "is_admin": False,
        "token_type": "access", "iat": 1, "exp": 9_999_999_999,
        "iss": "htqweb-auth", "sub": "7", "company": COMPANY,
        **over,
    }
    return pyjwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")


def admin_token(**over) -> str:
    """Редактор контента — пользователь 9 (бывший ``admin_token``)."""
    return token(user_id=9, sub="9", is_admin=True, **over)


def auth_header(tok: str) -> dict:
    """Заголовки вызывающего: токен, заголовок компании и роль в ней.

    Роль выводится из claim'ов самого токена, чтобы тесты, писавшиеся до
    блока L, не переписывать вызов за вызовом: редактор (``is_admin``/
    ``is_staff`` в токене — бывший ``admin_token``) получает ``cms:full``,
    рядовой — ``cms:read`` (уровень ``employee-basic``). Флаг в токене сам
    по себе гейт НЕ проходит — это закрепляет ``test_gate_roles.py``;
    здесь он лишь метка «кому выдать роль редактора». Зовётся только из
    тестов с доступом к БД.
    """
    from apps.access.tests.helpers import gate_company

    claims = pyjwt.decode(tok, options={"verify_signature": False})
    editor = bool(claims.get("is_admin") or claims.get("is_staff"))
    gate_company(COMPANY, {int(claims["user_id"]): {"cms": "full" if editor else "read"}})
    return {"HTTP_AUTHORIZATION": f"Bearer {tok}", "HTTP_X_HTQ_COMPANY": COMPANY}

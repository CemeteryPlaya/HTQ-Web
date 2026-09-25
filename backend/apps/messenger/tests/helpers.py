"""Общие помощники HTTP-тестов мессенджера под гейтом модуля (блок L).

Ручки ``/api/messenger/v1/*`` стоят под ``api_view(module="messenger",
level=…)``: им нужны заголовок ``X-HTQ-Company``, claim ``company`` в токене,
совпадающий с ним, действующая строка ``Company`` и роль в этой компании.
"""
from __future__ import annotations

from htqweb.authn.jwt import issue_token_pair

#: Компания тестов ручек под гейтом ``module="messenger"``. Своя, а не общая:
#: строка заводится лениво из ``auth_header``, чтобы не попадать в
#: ``active_company_slugs()`` тестов веера по компаниям.
COMPANY = "t-messenger-gate"


def auth_header(user, level: str = "write") -> dict:
    """Заголовки вызывающего: токен с компанией, заголовок компании и роль.

    По умолчанию — ``messenger:write`` (уровень ``employee-basic``), в том
    числе «постороннему»: отказ не-участнику комнаты или не-автору сообщения
    обязана давать собственная проверка сервиса, а не гейт. Администратор
    модерации — ``level="full"``: ``is_staff`` сам по себе гейт больше не
    проходит. ``issue_token_pair`` членства не проверяет (см. его докстринг),
    поэтому ``CompanyMembership`` не нужен.
    """
    from apps.access.tests.helpers import gate_company

    gate_company(COMPANY, {user.id: {"messenger": level}})
    access = issue_token_pair(user, company_slug=COMPANY)["access"]
    return {"HTTP_AUTHORIZATION": f"Bearer {access}", "HTTP_X_HTQ_COMPANY": COMPANY}

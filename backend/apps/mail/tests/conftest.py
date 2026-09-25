"""Общие для домена ``mail`` фикстуры.

Автофикстура здесь одна — запрет живых сокетов в проверке доступности
почтового сервера (``verify_endpoint_reachable``): она сидит в ручке
``connect-corporate``, а ту зовут из трёх разных файлов. Оставь фикстуру в
одном из них — и тесты остальных пошли бы на настоящий mail.htq.group, то
есть стали бы зависеть от сети и от того, жив ли сервер компании.

Подменяется именно ``verify_endpoint_reachable``, а НЕ ``_tcp_reachable``:
последним пользуется ещё и диагностическая цепочка ``run_check``, у которой
свои фикстуры сокетов и свои ожидания про закрытые порты.

Кроме неё — помощник ``gate_auth`` для ручек под гейтом модуля ``mail``
(блок L): его зовут фикстуры авторизации нескольких файлов, по образцу
``apps/conference/tests/conftest.py``.
"""
from __future__ import annotations

import pytest

#: Компания тестов ручек под гейтом ``module="mail"`` (блок L). Своя, а не
#: общая: строка заводится лениво из ``gate_auth``, чтобы не попадать в
#: ``active_company_slugs()`` тестов веера по компаниям.
COMPANY = "t-mail-gate"


def gate_auth(user, level: str) -> dict:
    """Заголовки вызывающего под гейтом модуля ``mail``: токен с компанией,
    заголовок компании и роль ``{"mail": level}`` в ней.

    Не фикстура и не автоматика — зовётся из фикстур авторизации файлов,
    которые ходят в ручки под гейтом (ящики, реквизиты сервера, сверка,
    подсказка IMAP). Уровни: администратор — ``"full"`` (гейт ``mail:admin``
    бывших ``admin=True``), рядовой — ``"read"`` (уровень ``employee-basic``
    в модуле ``mail``): его 403 на админской ручке даёт уже гейт — ровно ту
    проверку, что раньше давал ``admin=True``. Ручкам личной почты (реестр
    самообслуживания) гейт не нужен, но заголовок им не мешает: claim
    ``company`` токена совпадает с ним. ``issue_token_pair`` членства не
    проверяет, поэтому ``CompanyMembership`` не нужен.
    """
    from apps.access.tests.helpers import gate_company
    from htqweb.authn.jwt import issue_token_pair

    gate_company(COMPANY, {user.id: {"mail": level}})
    access = issue_token_pair(user, company_slug=COMPANY)["access"]
    return {"HTTP_AUTHORIZATION": f"Bearer {access}", "HTTP_X_HTQ_COMPANY": COMPANY}


@pytest.fixture(autouse=True)
def mail_server_reachable(monkeypatch):
    """Почтовый сервер по умолчанию отвечает.

    Переключатель для тестов:

    * ``mail_server_reachable(False)`` — сервер лежит;
    * ``mail_server_reachable(None)``  — вернуть настоящую реализацию (нужно
      тем, кто проверяет саму проверку: кэш, выбор цели по режиму).
    """
    from apps.mail.services import connection_check

    original = connection_check.verify_endpoint_reachable
    state = {"up": True}
    monkeypatch.setattr(
        connection_check, "verify_endpoint_reachable",
        lambda **kw: state["up"],
    )

    def _set(up: bool | None) -> None:
        if up is None:
            monkeypatch.setattr(
                connection_check, "verify_endpoint_reachable", original,
            )
            return
        state["up"] = up

    return _set

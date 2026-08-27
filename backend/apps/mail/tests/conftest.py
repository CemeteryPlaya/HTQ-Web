"""Общие для домена ``mail`` фикстуры.

Здесь только то, что обязано действовать на ВСЕ тесты домена. Сейчас это одна
вещь — запрет живых сокетов в проверке доступности почтового сервера
(``verify_endpoint_reachable``): она сидит в ручке ``connect-corporate``, а ту
зовут из трёх разных файлов. Оставь фикстуру в одном из них — и тесты
остальных пошли бы на настоящий mail.htq.group, то есть стали бы зависеть от
сети и от того, жив ли сервер компании.

Подменяется именно ``verify_endpoint_reachable``, а НЕ ``_tcp_reachable``:
последним пользуется ещё и диагностическая цепочка ``run_check``, у которой
свои фикстуры сокетов и свои ожидания про закрытые порты.
"""
from __future__ import annotations

import pytest


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

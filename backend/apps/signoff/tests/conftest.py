"""Изоляция тестов signoff от процесс-глобального состояния реестра.

``registry._SUBJECTS`` — обычный модульный словарь: он наполняется один раз
из ``AppConfig.ready()`` и НЕ откатывается вместе с транзакцией теста, в
отличие от БД. Любой тест, который что-то регистрирует (а таких тут
несколько — реестр в том числе и проверяется), иначе протекает в следующий:
перерегистрация ``testapp.probedoc`` без колбэков оставляет всем
последующим тестам тип без ``on_approved``.

Ровно та же природа, что у ``clear_service_status_cache`` в корневом
``conftest.py``, и лечится так же — снимком до и восстановлением после.
"""

import pytest

from apps.signoff.services import registry


@pytest.fixture(autouse=True)
def restore_subject_registry():
    snapshot = dict(registry._SUBJECTS)
    yield
    registry._SUBJECTS.clear()
    registry._SUBJECTS.update(snapshot)

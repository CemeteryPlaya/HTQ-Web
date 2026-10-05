import pytest

from .helpers import FakeStorage
from .testapp import hooks


@pytest.fixture(autouse=True)
def storage(monkeypatch):
    """Настоящий пайплайн media_files поверх хранилища в памяти."""
    from apps.media_files import views as media_views
    from apps.media_files.services import upload_service

    fake = FakeStorage()
    monkeypatch.setattr(upload_service, "get_storage", lambda bucket=None: fake)
    monkeypatch.setattr(media_views, "get_storage", lambda bucket=None: fake)
    return fake


@pytest.fixture(autouse=True)
def probe_owners(request):
    """Строки справочника для пробных владельцев и чистый журнал их событий.

    Справочник наполняет владелец своей миграцией; у тестовой аппки миграций
    нет, поэтому строки заводятся здесь — только там, где тесту нужна БД.
    """
    hooks.reset()
    if "django_db" in request.keywords or request.node.get_closest_marker("django_db"):
        request.getfixturevalue("db")
        hooks.seed_types()
    yield
    hooks.reset()

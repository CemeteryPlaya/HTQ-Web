"""Пробелы по краям ФИО срезаются при создании и правке учётки.

Прод 12.10: учётка, заведённая из кадровой формы, получила фамилию
«Ауелбаева  » — с двумя пробелами на конце, и та же фамилия уехала в кадровую
карточку. Точный поиск по фамилии такого человека не находит.
"""
import pytest

from apps.users.models import User, UserStatus
from apps.users.services import admin_service, profile_service


def _user(username: str) -> User:
    return User.objects.create(username=username, email=f"{username}@htq.test",
                               password="x", status=UserStatus.ACTIVE)


@pytest.mark.django_db
def test_create_user_strips_names():
    user = admin_service.create_user(
        username="tolkyn", email="tolkyn@htq.test", password="S3cret!pass",
        first_name=" Толкын ", last_name="Ауелбаева  ", patronymic=" Мамбетовна",
    )
    user.refresh_from_db()
    assert (user.first_name, user.last_name, user.patronymic) == (
        "Толкын", "Ауелбаева", "Мамбетовна")
    assert user.display_name == "Толкын Ауелбаева"


@pytest.mark.django_db
def test_admin_update_strips_names():
    user = _user("upd")
    admin_service.update_user(user, {"first_name": " Толкын", "last_name": "Ауелбаева  "})
    user.refresh_from_db()
    assert (user.first_name, user.last_name) == ("Толкын", "Ауелбаева")


@pytest.mark.django_db
def test_own_profile_update_strips_names():
    user = _user("self")
    profile_service.apply_profile_fields(
        user, display_name=" Ерболат ", first_name=" Ерболат", last_name="Гайбуллаев ",
        patronymic=None, bio=None, phone=None, settings_json=None,
    )
    assert (user.display_name, user.first_name, user.last_name) == (
        "Ерболат", "Ерболат", "Гайбуллаев")

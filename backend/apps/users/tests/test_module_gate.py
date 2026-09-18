"""Блок I, задача 4: ручки ``users`` под гейтом ``module=``/``level=``.

Вторая из четырёх аппок блока (первая — ``apps.access``). Здесь проверяется
ПОВЕДЕНИЕ настоящих ручек; наличие декоратора у каждой из них сторожит
``apps/access/tests/test_gate.py`` по реестру ``apps.access.self_service``.

Что закрыто проверками:

1. без права на модуль — 403, с правом нужного уровня — 200;
2. уровень различается: ``view`` не заменяет ``full`` там, где ручка
   администрирует учётки;
3. ручки самообслуживания (свой профиль, свой пароль) остаются доступны
   человеку вообще без ролей — реестр ``self_service``, причина ``self``;
4. ``admin=True`` НЕ снят: роль на модуль не делает обычного пользователя
   администратором платформы;
5. держатель системной роли ``employee-basic`` не теряет подбор коллег — она
   несёт ``users.profile``, а уровень модуля считается по ВСЕМУ поддереву
   (``apps.access.services.resolve.permissions_for``), поэтому выдавать ей
   узел ``users`` целиком не требуется.

Компания — ``company_row`` (строка реестра без физической схемы): учётки и
права живут в ``public``.
"""

import json

import pytest
from django.test import Client

from apps.access.models import Role, RoleAssignment, ScopeKind
from apps.access.tests.helpers import assign
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/users/v1"


@pytest.fixture
def client():
    return Client()


def _mk(username: str, **flags) -> User:
    user = User.objects.create(username=username, email=f"{username}@htq.test",
                               password="x", status=UserStatus.ACTIVE,
                               first_name="Имя", last_name="Фамилия", **flags)
    user.set_password("S3cret!")
    user.save()
    return user


@pytest.fixture
def plain(company_row):
    return _mk("plain")


@pytest.fixture
def staff(company_row):
    """Администратор платформы «широкого» толка: ``is_staff``, не суперпользователь."""
    return _mk("staffer", is_staff=True)


@pytest.fixture
def root(company_row):
    return _mk("root", is_staff=True, is_superuser=True)


def headers(user: User, slug: str) -> dict:
    """Заголовки как их ставит шлюз: слаг компании + токен, выданный на неё."""
    token = issue_token_pair(user, company_slug=slug)["access"]
    return {"HTTP_X_HTQ_COMPANY": slug, "HTTP_AUTHORIZATION": f"Bearer {token}"}


def give_seeded_role(user: User, slug: str, code: str) -> None:
    """Назначить УЖЕ существующую роль каталога — засеянную миграцией."""
    RoleAssignment.objects.create(company_slug=slug, user_id=user.id,
                                  role=Role.objects.get(code=code),
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)


# ── Чтение: подбор коллег ─────────────────────────────────────────────────


@pytest.mark.django_db
def test_options_are_closed_without_the_module(client, company_row, plain):
    resp = client.get(f"{BASE}/users/options/?query=фам",
                      **headers(plain, company_row))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_options_open_with_read_level(client, company_row, plain):
    assign(company_row, plain.id, "users", "view")
    resp = client.get(f"{BASE}/users/options/?query=фам",
                      **headers(plain, company_row))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_employee_basic_keeps_the_picker(client, company_row, plain):
    """Системная роль сотрудника несёт ``users.profile`` — этого достаточно.

    Уровень модуля считается по всему поддереву, поэтому узел-функция внутри
    ``users`` открывает модуль на своём уровне: рядовой сотрудник не теряет
    подбор коллег, и «чинить» это выдачей ему узла ``users`` целиком не нужно
    (такая выдача открыла бы ему весь модуль, включая администрирование).
    """
    give_seeded_role(plain, company_row, "employee-basic")
    resp = client.get(f"{BASE}/users/options/?query=фам",
                      **headers(plain, company_row))
    assert resp.status_code == 200


# ── Администрирование учёток ──────────────────────────────────────────────


@pytest.mark.django_db
def test_admin_list_is_closed_without_the_module(client, company_row, staff):
    resp = client.get(f"{BASE}/admin/users/", **headers(staff, company_row))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_admin_list_needs_admin_level(client, company_row, staff):
    """``view`` на модуль — это чтение справочников, а не правка учёток."""
    assign(company_row, staff.id, "users", "view")
    resp = client.get(f"{BASE}/admin/users/", **headers(staff, company_row))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_admin_list_opens_with_admin_level(client, company_row, staff):
    assign(company_row, staff.id, "users", "full")
    resp = client.get(f"{BASE}/admin/users/", **headers(staff, company_row))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_pending_registrations_need_admin_level(client, company_row, staff):
    assign(company_row, staff.id, "users", "view")
    assert client.get(f"{BASE}/pending-registrations/",
                      **headers(staff, company_row)).status_code == 403
    assign(company_row, staff.id, "users", "full")
    assert client.get(f"{BASE}/pending-registrations/",
                      **headers(staff, company_row)).status_code == 200


@pytest.mark.django_db
def test_set_password_needs_admin_level(client, company_row, staff, plain):
    assign(company_row, staff.id, "users", "view")
    resp = client.post(f"{BASE}/admin/users/{plain.id}/set-password/",
                       data=json.dumps({"new_password": "N3wP@ssw0rd",
                                        "must_change_password": True}),
                       content_type="application/json",
                       **headers(staff, company_row))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_module_right_does_not_replace_the_platform_admin_gate(client, company_row,
                                                               plain):
    """Ничего не расширяем: ``admin=True`` остался на месте.

    Полная роль на модуль ``users`` не делает рядового пользователя
    администратором платформы — вторая дверь по-прежнему заперта.
    """
    assign(company_row, plain.id, "users", "full")
    resp = client.get(f"{BASE}/admin/users/", **headers(plain, company_row))
    assert resp.status_code == 403


# ── Самообслуживание и платформенный администратор ────────────────────────


@pytest.mark.django_db
def test_own_profile_is_open_without_any_role(client, company_row, plain):
    """Реестр ``self_service`` (причина ``self``): своё — без гейта модуля."""
    resp = client.get(f"{BASE}/profile/me", **headers(plain, company_row))
    assert resp.status_code == 200
    assert resp.json()["username"] == "plain"


@pytest.mark.django_db
def test_own_password_change_is_open_without_any_role(client, company_row, plain):
    resp = client.post(f"{BASE}/profile/change-password",
                       data=json.dumps({"current_password": "S3cret!",
                                        "new_password": "N3wP@ssw0rd"}),
                       content_type="application/json",
                       **headers(plain, company_row))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_superuser_passes_every_handle(client, company_row, root, plain):
    head = headers(root, company_row)
    assert client.get(f"{BASE}/admin/users/", **head).status_code == 200
    assert client.get(f"{BASE}/pending-registrations/", **head).status_code == 200
    assert client.get(f"{BASE}/users/options/?query=фам", **head).status_code == 200
    assert client.get(f"{BASE}/profile/me", **head).status_code == 200

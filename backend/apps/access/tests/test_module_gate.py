"""Блок I, задача 4: ручки ``access`` под гейтом ``module=``/``level=``.

Первая из четырёх аппок, на которую гейт реально навешен (до этого он был
объявлен в ``htqweb/http.py`` и проверялся только на пробных вьюхах
``test_gate.py``). Здесь проверяется ПОВЕДЕНИЕ настоящих ручек, а не наличие
декоратора: наличие сторожит ``test_gate.py`` по реестру
``apps.access.self_service``.

Четыре вопроса, по одному на решение задачи:

1. без права на модуль — 403, с правом нужного уровня — 200;
2. уровень различается: ``view`` не пускает туда, где нужен ``full``;
3. ``/me`` остаётся доступной человеку вообще без ролей (реестр
   ``self_service``, причина ``self``);
4. платформенный админ-гейт (``admin=True``) НЕ снят — держатель роли без
   ``is_staff``/``is_superuser`` по-прежнему не проходит.

Компания — ``company_row`` (строка реестра без физической схемы): права и
учётки живут в ``public``, схема этому файлу не нужна вовсе (докстринг
фикстуры в ``backend/conftest.py`` объясняет, почему это безопасно).
"""

import pytest
from django.test import Client

from apps.access.tests.helpers import (
    BASE,
    assign,
    auth,
    put_json,
    staff_token,
    superuser_token,
    token,
)


@pytest.fixture
def client():
    return Client()


def headers(slug: str, tok: str) -> dict:
    """Заголовки как их ставит шлюз: слаг компании + токен, выданный на неё."""
    return {"HTTP_X_HTQ_COMPANY": slug, **auth(tok)}


# ── Чтение ────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_roles_are_closed_without_the_module(client, company_row):
    resp = client.get(f"{BASE}/roles", **headers(company_row, token(company=company_row)))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_roles_open_with_read_level(client, company_row):
    assign(company_row, 7, "access", "view")
    resp = client.get(f"{BASE}/roles", **headers(company_row, token(company=company_row)))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_functions_registry_is_closed_without_the_module(client, company_row):
    """Реестр функций — материал редактора ролей, а не общий справочник."""
    resp = client.get(f"{BASE}/functions",
                      **headers(company_row, token(company=company_row)))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_functions_registry_opens_with_read_level(client, company_row):
    assign(company_row, 7, "access", "view")
    resp = client.get(f"{BASE}/functions",
                      **headers(company_row, token(company=company_row)))
    assert resp.status_code == 200


# ── Уровень: read не заменяет admin ───────────────────────────────────────


@pytest.mark.django_db
def test_assignments_are_closed_without_the_module(client, company_row):
    """Платформенный админ без роли на модуль доступа — тоже мимо."""
    resp = put_json(client, f"{BASE}/assignments/42", [],
                    **headers(company_row, staff_token(company=company_row)))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_assignments_need_admin_level(client, company_row):
    """Личные назначения — администрирование: ``view`` до них не доводит."""
    assign(company_row, 8, "access", "view")
    resp = put_json(client, f"{BASE}/assignments/42", [],
                    **headers(company_row, staff_token(company=company_row)))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_assignments_open_with_admin_level(client, company_row):
    assign(company_row, 8, "access", "full")
    resp = put_json(client, f"{BASE}/assignments/42", [],
                    **headers(company_row, staff_token(company=company_row)))
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.django_db
def test_module_right_does_not_replace_the_platform_admin_gate(client, company_row):
    """Ничего не расширяем: ``admin=True`` остался на месте.

    Держатель полной роли на модуль ``access``, но без ``is_staff``/
    ``is_superuser``, к личным назначениям по-прежнему не допускается.
    """
    assign(company_row, 7, "access", "full")
    resp = put_json(client, f"{BASE}/assignments/42", [],
                    **headers(company_row, token(company=company_row)))
    assert resp.status_code == 403


# ── Самообслуживание и платформенный администратор ────────────────────────


@pytest.mark.django_db
def test_me_is_open_to_a_user_without_any_role(client, company_row):
    """``/me`` — реестр ``self_service`` (причина ``self``): гейта нет.

    Нужна КАЖДОМУ вошедшему, включая держателя ``employee-basic``, у которой
    нет ни одного узла ``access.*``: без неё человек не узнал бы даже, что
    ему доступно.
    """
    resp = client.get(f"{BASE}/me", **headers(company_row, token(company=company_row)))
    assert resp.status_code == 200
    assert resp.json()["company"] == company_row
    assert resp.json()["permissions"] == {}


@pytest.mark.django_db
def test_superuser_passes_every_handle(client, company_row):
    head = headers(company_row, superuser_token(company=company_row))
    assert client.get(f"{BASE}/roles", **head).status_code == 200
    assert client.get(f"{BASE}/functions", **head).status_code == 200
    assert client.get(f"{BASE}/me", **head).status_code == 200
    assert put_json(client, f"{BASE}/assignments/42", [], **head).status_code == 200

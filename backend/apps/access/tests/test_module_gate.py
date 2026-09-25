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

from apps.access.models import Role
from apps.access.tests.helpers import (
    BASE,
    assign,
    auth,
    patch_json,
    post_json,
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
def test_role_permissions_are_closed_without_the_module(client, company_row):
    role = Role.objects.create(code="r", title="Роль")
    resp = client.get(f"{BASE}/roles/{role.id}/permissions",
                      **headers(company_row, token(company=company_row)))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_role_permissions_open_with_read_level(client, company_row):
    role = Role.objects.create(code="r", title="Роль")
    assign(company_row, 7, "access", "view")
    resp = client.get(f"{BASE}/roles/{role.id}/permissions",
                      **headers(company_row, token(company=company_row)))
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


# ── Две ручки объявлены ``open``: читает любой вошедший ────────────────────
#
# Раунд правок 1: каталог ролей и роли должности до перевода читал ЛЮБОЙ
# вошедший, и читает их не только редактор ролей, но и кадровый экран
# должностей (HRPositions.tsx -> PositionRolesDialog.tsx). Гейт там оказался
# сужением, а выдать кадровым ролям узел access.* нельзя — один узел открыл
# бы им весь домен прав (уровень модуля считается по всему поддереву).
# Обоснование целиком — в apps/access/self_service.py.


@pytest.mark.django_db
def test_role_catalog_is_readable_without_any_role(client, company_row):
    resp = client.get(f"{BASE}/roles", **headers(company_row, token(company=company_row)))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_position_roles_are_readable_without_any_role(client, company_row):
    """404 (должности нет), а НЕ 403 — значит ручка дошла до вьюхи.

    Гейт модуля отвечает раньше вьюхи, поэтому «дошло до 404» и есть проверка
    того, что гейта на ручке нет: с ним человек без единого узла ``access.*``
    получил бы 403 независимо от того, существует ли должность.
    """
    resp = client.get(f"{BASE}/positions/999999/roles",
                      **headers(company_row, token(company=company_row)))
    assert resp.status_code == 404


# ── Каталог ролей остаётся ПЛАТФОРМЕННОЙ операцией ────────────────────────
#
# Раунд правок 1, пункт 4: гейт модуля отвечает раньше, чем
# ``deny_unless_platform_admin`` внутри метода, поэтому прежние тесты этой
# проверки (они звали ручки ролью-пустышкой) стали получать 403 от гейта, не
# доходя до неё — страховки на саму проверку не осталось. Тесты ниже дают
# вызывающему ПОЛНЫЙ уровень на модуль access, то есть проводят его сквозь
# гейт, и требуют 403 уже от самой проверки: снимите её — и они покраснеют.


@pytest.mark.django_db
def test_role_catalog_writes_stay_platform_only(client, company_row):
    """Роль уровня admin на модуль ``access`` не даёт править ОБЩИЙ каталог.

    Каталог один на все компании (§4.1): правка меняет доступ во всех сразу, и
    обратной силы у ошибки нет — поэтому её делает только платформенный
    администратор (``is_superuser``), а не держатель роли в одной компании.
    """
    assign(company_row, 7, "access", "full")
    role = Role.objects.create(code="victim", title="Жертва")
    head = headers(company_row, token(company=company_row))

    assert post_json(client, f"{BASE}/roles", {"code": "x", "title": "X"},
                     **head).status_code == 403
    assert patch_json(client, f"{BASE}/roles/{role.id}", {"title": "Новое"},
                      **head).status_code == 403
    assert post_json(client, f"{BASE}/roles/{role.id}/copy",
                     {"code": "c", "title": "C"}, **head).status_code == 403
    assert put_json(client, f"{BASE}/roles/{role.id}/permissions",
                    [{"node": "hr", "preset": "view"}], **head).status_code == 403
    assert client.delete(f"{BASE}/roles/{role.id}", **head).status_code == 403

    # Ни одна из пяти попыток ничего не изменила.
    assert not Role.objects.filter(code__in=("x", "c")).exists()
    role.refresh_from_db()
    assert role.title == "Жертва"


@pytest.mark.django_db
def test_role_catalog_writes_need_access_admin_at_the_gate(client, company_row):
    """T4 финальной волны блока I: правка общего каталога — ``admin``.

    Держатель ``access:write`` (без admin) останавливается уже ГЕЙТОМ
    (``Forbidden``), а не проверкой суперпользователя внутри метода — до
    правки гейт его пропускал, и 403 приходил только от
    ``deny_unless_platform_admin`` (другой ``detail``). Поведение для
    пользователя то же — 403, — поэтому проверяется именно источник отказа.
    """
    assign(company_row, 7, "access", "edit")
    role = Role.objects.create(code="victim-t4", title="Жертва")
    head = headers(company_row, token(company=company_row))

    responses = [
        post_json(client, f"{BASE}/roles", {"code": "x", "title": "X"}, **head),
        patch_json(client, f"{BASE}/roles/{role.id}", {"title": "Новое"}, **head),
        post_json(client, f"{BASE}/roles/{role.id}/copy", {"code": "c", "title": "C"}, **head),
        put_json(client, f"{BASE}/roles/{role.id}/permissions",
                 [{"node": "hr", "preset": "view"}], **head),
    ]
    assert [r.status_code for r in responses] == [403] * 4
    assert [r.json()["detail"] for r in responses] == ["Forbidden"] * 4


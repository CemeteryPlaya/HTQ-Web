"""Контракт /api/hr/v1/employees/{id}/card/{t2,groups} — паритет с
services/hr/app/api/v1/employee_card.py.

Провенанс: app/services/employee_card_t2_service.py (гейтинг СЕКЦИОННЫЙ —
financial/personal/certs, каждая своим view/edit-ключом), app/services/
employee_groups_service.py (education/experience/relatives — единственный
ключ hr.card.groups.view/edit на весь ресурс), app/auth/hr_access.py
(_visible_employee роутера исходника: require_hr_access + can_see_department
-> 404 "Employee not found" для скрытого отдела).

Зафиксированные ловушки паритета (проверяются тестами ниже):
  * auth — ТА ЖЕ пара require_hr_access + _require_visible_employee, что и
    history/documents/pmos (apps/hr/views.py::_visible_access, переиспользуется
    буквально, не дублируется) — 403 "HR access required" без HR-доступа
    вообще, 404 "Employee not found" за скрытый отдел;
  * t2 GET — секция ПОЛНОСТЬЮ отсутствует в ответе (не null-значения) без
    соответствующего view-ключа;
  * t2 PATCH — 403 "Missing permission: hr.card.<section>.edit" за секцию без
    edit-ключа; ПАТЧ НЕ атомарен построчно, а атомарен ЦЕЛИКОМ: если
    PermissionError всплывает в середине multi-секционного патча, НИ ОДНА
    секция (включая уже обработанные раньше по порядку financial/personal/
    certs) не сохраняется — buffer в памяти, .save() только после всего цикла;
  * денежные поля (salary/bonus) сериализуются СТРОКОЙ; невалидное значение
    -> 422 "Invalid decimal for <field>: <value>";
  * groups GET/PUT — единственный ключ на весь ресурс, PUT — ПОЛНАЯ замена
    (не глубокий merge — см. test_groups_put_is_full_replace_not_merge).

План: docs/plans/2026-07-20-hr-domain.md
"""
from __future__ import annotations

import datetime

import pytest
from django.test import Client

from apps.hr.models import Department, Employee, EmployeeCard, EmployeeGroups, Position
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/hr/v1/employees"


def _dep(name, path, **kw):
    return Department.objects.create(name=name, path=path, **kw)


def _pos(title, dep, weight, **kw):
    return Position.objects.create(title=title, department=dep, weight=weight, **kw)


def _emp(dep, pos, email, **kw):
    kw.setdefault("hire_date", datetime.date(2024, 1, 9))
    kw.setdefault("first_name", "И")
    kw.setdefault("last_name", "И")
    return Employee.objects.create(email=email, department=dep, position=pos, **kw)


def _user_auth(email, *, is_staff=False):
    user = User.objects.create(
        username=email.split("@")[0], email=email, password="x", status=UserStatus.ACTIVE,
        is_staff=is_staff,
    )
    user.set_password("S3cret!Pass1")
    user.save()
    return user, {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def hr_dep(db):
    return _dep("HR", "hr")


@pytest.fixture
def other_dep(db):
    return _dep("Финансы", "fin")


@pytest.fixture
def auth(db):
    """Обычный вошедший без Employee-профиля — нет HR-доступа вообще."""
    _user, headers = _user_auth("plain-card@htq.test")
    return headers


@pytest.fixture
def admin_auth(db):
    """is_staff=True — elevated -> HRAccess(level='lead', permissions={'*'})."""
    _user, headers = _user_auth("card-admin@htq.test", is_staff=True)
    return headers


@pytest.fixture
def junior(db, hr_dep):
    """Без единого hr.card.* ключа."""
    pos = _pos("HR Assistant", hr_dep, weight=210)
    user, headers = _user_auth("card-junior@htq.test")
    emp = _emp(hr_dep, pos, "card-junior@htq.test", user_id=user.id)
    return emp, headers


@pytest.fixture
def middle(db, hr_dep):
    """certs.view/edit + groups.view/edit — БЕЗ financial/personal."""
    pos = _pos("HR Manager", hr_dep, weight=220)
    user, headers = _user_auth("card-middle@htq.test")
    emp = _emp(hr_dep, pos, "card-middle@htq.test", user_id=user.id)
    return emp, headers


@pytest.fixture
def senior(db, hr_dep):
    """Все 8 hr.card.* ключей (наследует middle + financial/personal)."""
    pos = _pos("Senior HR Manager", hr_dep, weight=230)
    user, headers = _user_auth("card-senior@htq.test")
    emp = _emp(hr_dep, pos, "card-senior@htq.test", user_id=user.id)
    return emp, headers


@pytest.fixture
def financial_edit_only(db, hr_dep):
    """Явная матрица permissions (position.permissions.permissions) —
    ТОЛЬКО hr.card.financial.view/edit, НИ personal, НИ certs. Нужна, чтобы
    проверить partial-failure atomicity PATCH (ни один пресет не расщепляет
    financial и personal по отдельности — оба садятся вместе на senior)."""
    pos = _pos(
        "Custom Financial Clerk", hr_dep, weight=240,
        permissions={"permissions": ["hr.employees.view", "hr.card.financial.view", "hr.card.financial.edit"]},
    )
    user, headers = _user_auth("card-fin-only@htq.test")
    emp = _emp(hr_dep, pos, "card-fin-only@htq.test", user_id=user.id)
    return emp, headers


# ── auth: require_hr_access + _require_visible_employee (t2) ────────────────

@pytest.mark.django_db
def test_card_t2_requires_jwt():
    assert Client().get(f"{BASE}/1/card/t2").status_code == 401


@pytest.mark.django_db
def test_card_t2_forbidden_without_any_hr_access(auth, hr_dep):
    target = _emp(hr_dep, _pos("A", hr_dep, weight=201), "t2-target1@htq.test")
    resp = Client().get(f"{BASE}/{target.id}/card/t2", **auth)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "HR access required"


@pytest.mark.django_db
def test_card_t2_missing_employee_404(admin_auth):
    resp = Client().get(f"{BASE}/999999/card/t2", **admin_auth)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Employee not found"


@pytest.mark.django_db
def test_card_t2_other_department_404_not_403(middle, other_dep):
    _owner, headers = middle
    target = _emp(other_dep, _pos("Other", other_dep, weight=202), "t2-target2@htq.test")
    resp = Client().get(f"{BASE}/{target.id}/card/t2", **headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Employee not found"


# ── GET card/t2 — полевой (секционный) гейтинг view-ключей ──────────────────

@pytest.mark.django_db
def test_card_t2_get_empty_for_level_without_any_card_key(junior):
    emp, headers = junior
    resp = Client().get(f"{BASE}/{emp.id}/card/t2", **headers)
    assert resp.status_code == 200
    assert resp.json() == {}


@pytest.mark.django_db
def test_card_t2_get_shows_only_certs_for_middle(middle):
    emp, headers = middle
    resp = Client().get(f"{BASE}/{emp.id}/card/t2", **headers)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"certs"}
    assert body["certs"] == {
        "sro_permit_number": None, "sro_permit_expiry": None,
        "safety_cert_number": None, "safety_cert_expiry": None,
    }


@pytest.mark.django_db
def test_card_t2_get_shows_all_three_sections_for_senior(senior):
    emp, headers = senior
    resp = Client().get(f"{BASE}/{emp.id}/card/t2", **headers)
    assert resp.status_code == 200
    assert set(resp.json().keys()) == {"financial", "personal", "certs"}


@pytest.mark.django_db
def test_card_t2_get_never_leaks_field_masked_by_missing_view_key(middle):
    """Ключевой security-инвариант: секция без view-ключа ОТСУТСТВУЕТ в теле
    ответа целиком (не null/пустая строка), даже если данные существуют в
    БД — middle не видит financial, даже когда карта заполнена сениором."""
    emp, headers = middle
    EmployeeCard.objects.create(employee=emp, salary="5000.00")
    resp = Client().get(f"{BASE}/{emp.id}/card/t2", **headers)
    assert resp.status_code == 200
    assert "financial" not in resp.json()


# ── PATCH card/t2 — полевой (секционный) гейтинг edit-ключей ────────────────

@pytest.mark.django_db
def test_card_t2_patch_rejects_section_without_edit_key(middle):
    emp, headers = middle
    resp = Client().patch(
        f"{BASE}/{emp.id}/card/t2", data={"financial": {"salary": "1000"}},
        content_type="application/json", **headers,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing permission: hr.card.financial.edit"


@pytest.mark.django_db
def test_card_t2_patch_allows_certs_for_middle(middle):
    emp, headers = middle
    resp = Client().patch(
        f"{BASE}/{emp.id}/card/t2", data={"certs": {"sro_permit_number": "SRO-1"}},
        content_type="application/json", **headers,
    )
    assert resp.status_code == 200
    assert resp.json()["certs"]["sro_permit_number"] == "SRO-1"


@pytest.mark.django_db
def test_card_t2_patch_then_get_roundtrip_admin(admin_auth, hr_dep):
    target = _emp(hr_dep, _pos("R", hr_dep, weight=203), "t2-roundtrip@htq.test")
    resp = Client().patch(
        f"{BASE}/{target.id}/card/t2",
        data={
            "financial": {"salary": "1234.50", "bonus": "200", "bank_account": "KZ123"},
            "personal": {"birth_place": "Astana", "citizenship": "KZ"},
            "certs": {"sro_permit_number": "SRO-9"},
        },
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["financial"]["salary"] == "1234.50"
    assert body["financial"]["bonus"] == "200.00"
    assert body["personal"]["birth_place"] == "Astana"
    assert body["certs"]["sro_permit_number"] == "SRO-9"

    get_resp = Client().get(f"{BASE}/{target.id}/card/t2", **admin_auth)
    assert get_resp.json() == body


@pytest.mark.django_db
def test_card_t2_patch_invalid_decimal_422(admin_auth, hr_dep):
    target = _emp(hr_dep, _pos("D", hr_dep, weight=204), "t2-decimal@htq.test")
    resp = Client().patch(
        f"{BASE}/{target.id}/card/t2", data={"financial": {"salary": "not-a-number"}},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 422
    assert "Invalid decimal for salary" in resp.json()["detail"]


@pytest.mark.django_db
def test_card_t2_patch_partial_failure_persists_nothing(financial_edit_only):
    """financial (порядок схемы — ПЕРВАЯ секция) применяется в памяти, ЗАТЕМ
    personal рвётся PermissionError-ом ДО .save() — ни одна секция не должна
    осесть в БД (буквальный порт: session.add() без commit() до конца цикла).
    """
    emp, headers = financial_edit_only
    resp = Client().patch(
        f"{BASE}/{emp.id}/card/t2",
        data={"financial": {"salary": "999.00"}, "personal": {"citizenship": "KZ"}},
        content_type="application/json", **headers,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing permission: hr.card.personal.edit"
    assert not EmployeeCard.objects.filter(employee=emp).exists()


@pytest.mark.django_db
def test_card_t2_patch_requires_visible_employee(auth, hr_dep):
    target = _emp(hr_dep, _pos("V", hr_dep, weight=205), "t2-visible@htq.test")
    resp = Client().patch(
        f"{BASE}/{target.id}/card/t2", data={"certs": {"sro_permit_number": "X"}},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "HR access required"


@pytest.mark.django_db
def test_card_t2_trailing_slash_variant(admin_auth, hr_dep):
    target = _emp(hr_dep, _pos("S", hr_dep, weight=206), "t2-slash@htq.test")
    assert Client().get(f"{BASE}/{target.id}/card/t2/", **admin_auth).status_code == 200


# ── card/groups — единственный ключ на весь ресурс ───────────────────────────

@pytest.mark.django_db
def test_card_groups_get_requires_view_key(junior):
    emp, headers = junior
    resp = Client().get(f"{BASE}/{emp.id}/card/groups", **headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing permission: hr.card.groups.view"


@pytest.mark.django_db
def test_card_groups_get_empty_lists_when_no_data(middle):
    emp, headers = middle
    resp = Client().get(f"{BASE}/{emp.id}/card/groups", **headers)
    assert resp.status_code == 200
    assert resp.json() == {"education": [], "experience": [], "relatives": []}


@pytest.mark.django_db
def test_card_groups_put_requires_edit_key(junior, hr_dep):
    """junior не имеет ни view, ни edit — 403 на PUT происходит на ПРОВЕРКЕ
    edit-ключа (groups.edit), а не позже — та же 403-точка, что и GET."""
    emp, headers = junior
    resp = Client().put(
        f"{BASE}/{emp.id}/card/groups", data={"education": []},
        content_type="application/json", **headers,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing permission: hr.card.groups.edit"


@pytest.mark.django_db
def test_card_groups_put_replaces_and_get_reflects(middle):
    emp, headers = middle
    body = {
        "education": [{"institution": "KBTU", "degree": "BSc", "field": "CS",
                        "year_from": 2018, "year_to": 2022}],
        "experience": [{"org": "HTQ", "position": "Dev", "date_from": "2022-06-01",
                         "date_to": None, "note": "backend"}],
        "relatives": [{"relation": "spouse", "full_name": "А. А.",
                        "birth_date": "1995-05-05", "note": ""}],
    }
    resp = Client().put(
        f"{BASE}/{emp.id}/card/groups", data=body,
        content_type="application/json", **headers,
    )
    assert resp.status_code == 200
    assert resp.json() == body

    get_resp = Client().get(f"{BASE}/{emp.id}/card/groups", **headers)
    assert get_resp.json() == body
    assert EmployeeGroups.objects.filter(employee_id=emp.id).count() == 1


@pytest.mark.django_db
def test_card_groups_put_is_full_replace_not_merge(middle):
    """СТРАННОСТЬ исходника, перенесённая буквально: PUT сериализует ВСЕ 3
    списка через ``model_dump(mode="json")`` БЕЗ ``exclude_unset`` (в отличие
    от PATCH /card/t2) — поле модели по умолчанию ``[]``, а не ``None``, так
    что даже "непереданный" список приходит как пустой и стирает то, что уже
    было сохранено. Это НЕ глубокий merge между вызовами, а полная замена
    каждый раз — воспроизведено как есть, не "исправлено" при переносе."""
    emp, headers = middle
    Client().put(
        f"{BASE}/{emp.id}/card/groups",
        data={"education": [{"institution": "KBTU", "degree": "", "field": "",
                              "year_from": None, "year_to": None}],
              "experience": [], "relatives": []},
        content_type="application/json", **headers,
    )
    resp = Client().put(
        f"{BASE}/{emp.id}/card/groups",
        data={"experience": [{"org": "HTQ", "position": "", "date_from": None,
                               "date_to": None, "note": ""}]},
        content_type="application/json", **headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["experience"][0]["org"] == "HTQ"
    # education, ранее сохранённый, стёрт полной заменой — не смержен.
    assert body["education"] == []

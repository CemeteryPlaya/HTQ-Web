"""Контракт /api/hr/v1/employees/{prefill,match-suggestions,bulk-import,…}.

Задача: «подтянуть уже имеющиеся данные из Пользователей в Сотрудников, и
также по другим параметрам». Логика — apps/hr/services/
employee_prefill_service.py.

Что здесь закрывается тестами (по убыванию цены ошибки):

  * **заполненное поле не перезаписывается молча** — расхождение приходит как
    ``conflict``, и применяется, только если его явно перечислили;
  * **применяется ровно показанное** — поле, которого не было в
    предпросмотре, игнорируется, чем бы ни было набито тело запроса;
  * привязка учётки: занятая другим сотрудником — 409, а не IntegrityError;
  * выключенная аппка mail — пустой список ящиков, а НЕ 503 на всю форму;
  * перевод через префилл требует того же права, что и через PATCH;
  * массовый импорт частично успешен: сбойный сосед не откатывает пачку.
"""
from __future__ import annotations

import datetime

import pytest
from django.core.cache import cache
from django.test import Client

from apps.core.models import ServiceStatus
from apps.hr.models import AuditLog, Department, Employee, Position
from apps.mail.models import ProvisionedMailbox
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/hr/v1/employees"


# ── фикстуры (те же приёмы, что в test_employees_api.py) ────────────────────

def _dep(name, path, **kw):
    return Department.objects.create(name=name, path=path, **kw)


def _pos(title, dep, weight, **kw):
    return Position.objects.create(title=title, department=dep, weight=weight, **kw)


def _emp(dep, pos, email, **kw):
    kw.setdefault("hire_date", datetime.date(2024, 1, 9))
    kw.setdefault("first_name", "Иван")
    kw.setdefault("last_name", "Иванов")
    return Employee.objects.create(email=email, department=dep, position=pos, **kw)


def _user(email, **kw):
    kw.setdefault("first_name", "Пётр")
    kw.setdefault("last_name", "Петров")
    user = User.objects.create(
        username=email.split("@")[0], email=email, password="x",
        status=UserStatus.ACTIVE, **kw,
    )
    user.set_password("S3cret!Pass1")
    user.save()
    return user


def _auth(user):
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def hr_dep(db):
    return _dep("HR", "hr")


@pytest.fixture
def other_dep(db):
    return _dep("Финансы", "fin")


@pytest.fixture
def senior(db, hr_dep):
    """senior => can_create_employee + can_list_user_options, без transfer? нет —
    у senior transfer есть; отсутствие transfer проверяется на middle."""
    pos = _pos("Senior HR Manager", hr_dep, weight=30)
    user = _user("hr-senior@htq.test")
    emp = _emp(hr_dep, pos, "hr-senior@htq.test", user_id=user.id)
    return emp, _auth(user)


@pytest.fixture
def middle(db, hr_dep):
    """middle => can_write_basic, но НЕ can_transfer_employee и НЕ users.list."""
    pos = _pos("HR Manager", hr_dep, weight=20)
    user = _user("hr-middle@htq.test")
    emp = _emp(hr_dep, pos, "hr-middle@htq.test", user_id=user.id)
    return emp, _auth(user)


@pytest.fixture
def admin_auth(db):
    user = _user("hr-admin@htq.test", is_staff=True)
    return _auth(user)


@pytest.fixture
def target(db, hr_dep):
    """Карточка, в которую подтягивают: телефон заполнен, отчества нет."""
    pos = _pos("Инженер", hr_dep, weight=50)
    return _emp(hr_dep, pos, "target@htq.test", phone="+7 (700) 111-11-11",
                first_name="Иван", last_name="Иванов")


def _post(path, payload, headers):
    import json as _json

    return Client().post(path, data=_json.dumps(payload),
                         content_type="application/json", **headers)


def _fields(body):
    return {row["field"]: row for row in body["fields"]}


# ── предпросмотр: источник «пользователь» ───────────────────────────────────

@pytest.mark.django_db
def test_prefill_requires_jwt():
    assert Client().post(f"{BASE}/prefill/").status_code == 401


@pytest.mark.django_db
def test_preview_from_user_on_create_marks_everything_fillable(admin_auth):
    user = _user("new@htq.test", first_name="Пётр", last_name="Петров",
                 patronymic="Сергеевич", phone="+7 700 222 33 44", bio="Про меня")

    resp = _post(f"{BASE}/prefill/", {"source": {"type": "user", "id": user.id}}, admin_auth)
    assert resp.status_code == 200
    body = resp.json()

    assert body["source"]["type"] == "user"
    assert body["source"]["id"] == user.id
    assert body["conflicts"] == 0
    rows = _fields(body)
    # Карточки ещё нет — сравнивать не с чем, всё «просто заполнить».
    assert {row["state"] for row in rows.values()} == {"fill"}
    assert rows["middle_name"]["incoming"] == "Сергеевич"
    assert rows["phone"]["incoming"] == "+7 700 222 33 44"
    assert rows["user_id"]["incoming"] == user.id


@pytest.mark.django_db
def test_preview_splits_states_against_existing_employee(admin_auth, target):
    """Главный сценарий: пусто -> fill, расходится -> conflict, совпало -> same."""
    user = _user("u2@htq.test", first_name="Иван", last_name="Иванов",
                 patronymic="Петрович", phone="+7 (700) 999-99-99")

    resp = _post(f"{BASE}/prefill/",
                 {"source": {"type": "user", "id": user.id}, "employee_id": target.id},
                 admin_auth)
    assert resp.status_code == 200
    rows = _fields(resp.json())

    assert rows["first_name"]["state"] == "same"       # Иван == Иван
    assert rows["last_name"]["state"] == "same"
    assert rows["middle_name"]["state"] == "fill"      # у карточки отчества нет
    assert rows["phone"]["state"] == "conflict"        # телефоны разные
    assert rows["phone"]["current"] == "+7 (700) 111-11-11"
    assert rows["phone"]["incoming"] == "+7 (700) 999-99-99"
    # Почта у карточки своя (target@) и у учётки своя (u2@) — тоже расхождение,
    # и оно обязано быть конфликтом, а не тихой заменой рабочего адреса.
    assert rows["email"]["state"] == "conflict"
    assert resp.json()["conflicts"] == 2


@pytest.mark.django_db
def test_preview_omits_fields_the_source_cannot_offer(admin_auth):
    """Пустое значение источника — не предложение стереть заполненное."""
    user = _user("empty@htq.test", first_name="А", last_name="Б", phone="", bio="")

    body = _post(f"{BASE}/prefill/", {"source": {"type": "user", "id": user.id}},
                 admin_auth).json()
    rows = _fields(body)
    assert "phone" not in rows
    assert "bio" not in rows


@pytest.mark.django_db
def test_preview_unknown_source_type_422(admin_auth):
    resp = _post(f"{BASE}/prefill/", {"source": {"type": "ldap", "id": 1}}, admin_auth)
    assert resp.status_code == 422


@pytest.mark.django_db
def test_preview_missing_source_404(admin_auth):
    resp = _post(f"{BASE}/prefill/", {"source": {"type": "user", "id": 999999}}, admin_auth)
    assert resp.status_code == 404


# ── предпросмотр: источники «сотрудник» и «ящик» ───────────────────────────

@pytest.mark.django_db
def test_preview_from_employee_gives_org_fields_only(admin_auth, target, other_dep):
    """Соседняя карточка — шаблон места в оргструктуре, не личных данных."""
    pos = _pos("Финансист", other_dep, weight=60)
    donor = _emp(other_dep, pos, "donor@htq.test", first_name="Донор",
                 last_name="Донорский", phone="+7 700 555 55 55")

    body = _post(f"{BASE}/prefill/", {"source": {"type": "employee", "id": donor.id}},
                 admin_auth).json()
    rows = _fields(body)
    assert set(rows) == {"department_id", "position_id"}
    assert rows["department_id"]["incoming"] == other_dep.id
    # Названия, а не голые id: «department_id: 3 → 7» человеку не говорит ничего.
    assert rows["department_id"]["incoming_display"] == "Финансы"


@pytest.mark.django_db
def test_preview_from_mailbox_takes_address(admin_auth):
    mb = ProvisionedMailbox.objects.create(
        local_part="s.sidorov", domain="htq.group", address="s.sidorov@htq.group",
        display_name="Семён Сидоров",
    )
    body = _post(f"{BASE}/prefill/", {"source": {"type": "mailbox", "id": mb.id}},
                 admin_auth).json()
    rows = _fields(body)
    assert rows["email"]["incoming"] == "s.sidorov@htq.group"
    # display_name платформа пишет как "{first_name} {last_name}".
    assert rows["first_name"]["incoming"] == "Семён"
    assert rows["last_name"]["incoming"] == "Сидоров"


@pytest.mark.django_db
def test_preview_from_mailbox_ignores_unparseable_display_name(admin_auth):
    mb = ProvisionedMailbox.objects.create(
        local_part="sales", domain="htq.group", address="sales@htq.group",
        display_name="Отдел продаж и маркетинга",
    )
    rows = _fields(_post(f"{BASE}/prefill/", {"source": {"type": "mailbox", "id": mb.id}},
                         admin_auth).json())
    assert "first_name" not in rows
    assert rows["email"]["incoming"] == "sales@htq.group"


@pytest.mark.django_db
def test_mailbox_sources_empty_when_mail_disabled(admin_auth):
    """Выключенная почта = «источника нет», а не сломанная форма сотрудника."""
    ProvisionedMailbox.objects.create(
        local_part="x", domain="htq.group", address="x@htq.group",
    )
    ServiceStatus.objects.update_or_create(app_label="mail", defaults={"enabled": False})
    cache.clear()  # service_status кэширует флаг на 5 секунд
    try:
        resp = Client().get(f"{BASE}/sources/mailboxes/", **admin_auth)
        assert resp.status_code == 200
        assert resp.json() == []
    finally:
        ServiceStatus.objects.filter(app_label="mail").update(enabled=True)
        cache.clear()


@pytest.mark.django_db
def test_mailbox_sources_unassigned_filter(admin_auth):
    owner = _user("owner@htq.test")
    ProvisionedMailbox.objects.create(local_part="free", domain="htq.group",
                                      address="free@htq.group")
    ProvisionedMailbox.objects.create(local_part="taken", domain="htq.group",
                                      address="taken@htq.group", user_id=owner.id)

    everything = Client().get(f"{BASE}/sources/mailboxes/", **admin_auth).json()
    assert {row["address"] for row in everything} >= {"free@htq.group", "taken@htq.group"}

    free_only = Client().get(f"{BASE}/sources/mailboxes/?unassigned=1", **admin_auth).json()
    assert [row["address"] for row in free_only] == ["free@htq.group"]


# ── применение ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_apply_writes_only_selected_fields(admin_auth, target):
    user = _user("apply@htq.test", first_name="Иван", last_name="Иванов",
                 patronymic="Петрович", phone="+7 (700) 999-99-99")

    resp = _post(f"{BASE}/{target.id}/prefill/apply",
                 {"source": {"type": "user", "id": user.id},
                  "fields": ["middle_name"]},
                 admin_auth)
    assert resp.status_code == 200

    target.refresh_from_db()
    assert target.middle_name == "Петрович"
    # Конфликтный телефон не отмечали — он обязан остаться прежним.
    assert target.phone == "+7 (700) 111-11-11"


@pytest.mark.django_db
def test_apply_can_take_conflicting_field_when_asked(admin_auth, target):
    user = _user("apply2@htq.test", first_name="Иван", last_name="Иванов",
                 phone="+7 (700) 999-99-99")

    _post(f"{BASE}/{target.id}/prefill/apply",
          {"source": {"type": "user", "id": user.id}, "fields": ["phone"]},
          admin_auth)

    target.refresh_from_db()
    assert target.phone == "+7 (700) 999-99-99"


@pytest.mark.django_db
def test_apply_ignores_fields_absent_from_the_preview(admin_auth, target):
    """Белый список сверяется с diff'ом, а не принимается на веру.

    ``bio`` у источника пустое, значит в предпросмотре его не было — и
    попытка «применить» его не должна ничего записать. Так же с полем, не
    входящим в TRANSFERABLE_FIELDS вовсе (``status``).
    """
    user = _user("apply3@htq.test", first_name="Иван", last_name="Иванов", bio="")
    target.bio = "Своё описание"
    target.save()

    resp = _post(f"{BASE}/{target.id}/prefill/apply",
                 {"source": {"type": "user", "id": user.id},
                  "fields": ["bio", "status", "hire_date"]},
                 admin_auth)
    assert resp.status_code == 200

    target.refresh_from_db()
    assert target.bio == "Своё описание"
    assert target.status == "active"


@pytest.mark.django_db
def test_apply_nothing_selected_is_not_an_error(admin_auth, target):
    user = _user("apply4@htq.test", first_name="Иван", last_name="Иванов")
    before = AuditLog.objects.filter(entity_type="employee", entity_id=target.id).count()

    resp = _post(f"{BASE}/{target.id}/prefill/apply",
                 {"source": {"type": "user", "id": user.id}, "fields": []},
                 admin_auth)
    assert resp.status_code == 200
    # Снятые галочки — это решение человека, а не событие в жизни карточки.
    assert AuditLog.objects.filter(entity_type="employee", entity_id=target.id).count() == before


@pytest.mark.django_db
def test_apply_writes_audit_with_source(admin_auth, target):
    user = _user("apply5@htq.test", first_name="Иван", last_name="Иванов",
                 patronymic="Петрович")

    _post(f"{BASE}/{target.id}/prefill/apply",
          {"source": {"type": "user", "id": user.id}, "fields": ["middle_name"]},
          admin_auth)

    log = (AuditLog.objects.filter(entity_type="employee", entity_id=target.id,
                                   action="prefill").order_by("-created_at").first())
    assert log is not None
    assert log.new_values["_source"] == f"user:{user.id}"
    assert log.new_values["middle_name"] == "Петрович"


@pytest.mark.django_db
def test_apply_links_user_account(admin_auth, target):
    user = _user("link@htq.test", first_name="Иван", last_name="Иванов")

    resp = _post(f"{BASE}/{target.id}/prefill/apply",
                 {"source": {"type": "user", "id": user.id}, "fields": ["user_id"]},
                 admin_auth)
    assert resp.status_code == 200

    target.refresh_from_db()
    assert target.user_id == user.id


@pytest.mark.django_db
def test_apply_refuses_user_taken_by_another_employee(admin_auth, target, hr_dep):
    """Молча переклеить учётку нельзя — первый сотрудник потерял бы доступ."""
    user = _user("taken@htq.test", first_name="Иван", last_name="Иванов")
    pos = _pos("Другой", hr_dep, weight=70)
    _emp(hr_dep, pos, "other@htq.test", user_id=user.id)

    resp = _post(f"{BASE}/{target.id}/prefill/apply",
                 {"source": {"type": "user", "id": user.id}, "fields": ["user_id"]},
                 admin_auth)
    assert resp.status_code == 409

    target.refresh_from_db()
    assert target.user_id is None


@pytest.mark.django_db
def test_apply_refuses_email_taken(admin_auth, target, hr_dep):
    pos = _pos("Занятый", hr_dep, weight=80)
    _emp(hr_dep, pos, "busy@htq.test")
    user = _user("busy@htq.test".replace("busy", "busy2"), first_name="Иван",
                 last_name="Иванов")
    User.objects.filter(id=user.id).update(email="busy@htq.test")

    resp = _post(f"{BASE}/{target.id}/prefill/apply",
                 {"source": {"type": "user", "id": user.id}, "fields": ["email"]},
                 admin_auth)
    assert resp.status_code == 409


@pytest.mark.django_db
def test_apply_transfer_fields_need_transfer_permission(middle, target, other_dep):
    """Префилл не должен становиться обходным путём для перевода."""
    _emp_middle, headers = middle
    pos = _pos("Финансист", other_dep, weight=90)
    donor = _emp(other_dep, pos, "donor2@htq.test")

    resp = _post(f"{BASE}/{target.id}/prefill/apply",
                 {"source": {"type": "employee", "id": donor.id},
                  "fields": ["department_id", "position_id"]},
                 headers)
    assert resp.status_code == 403

    target.refresh_from_db()
    assert target.department_id != other_dep.id


@pytest.mark.django_db
def test_apply_transfer_fields_allowed_for_senior(senior, target, other_dep):
    _emp_senior, headers = senior
    pos = _pos("Финансист", other_dep, weight=91)
    donor = _emp(other_dep, pos, "donor3@htq.test")

    resp = _post(f"{BASE}/{target.id}/prefill/apply",
                 {"source": {"type": "employee", "id": donor.id},
                  "fields": ["department_id", "position_id"]},
                 headers)
    assert resp.status_code == 200

    target.refresh_from_db()
    assert target.department_id == other_dep.id
    assert target.position_id == pos.id


@pytest.mark.django_db
def test_user_source_needs_users_list_permission(middle, target):
    """middle умеет править анкету, но справочник учёток ему не открыт."""
    _emp_middle, headers = middle
    user = _user("hidden@htq.test", first_name="Иван", last_name="Иванов")

    resp = _post(f"{BASE}/prefill/",
                 {"source": {"type": "user", "id": user.id}, "employee_id": target.id},
                 headers)
    assert resp.status_code == 403


# ── подсказка о совпадении ─────────────────────────────────────────────────

@pytest.mark.django_db
def test_match_suggestions_empty_query_returns_nothing(admin_auth):
    _user("someone@htq.test")
    body = Client().get(f"{BASE}/match-suggestions/", **admin_auth).json()
    assert body == {"users": [], "employees": []}


@pytest.mark.django_db
def test_match_suggestions_finds_user_by_email(admin_auth):
    user = _user("match@htq.test", first_name="Мария", last_name="Маркова")

    body = Client().get(f"{BASE}/match-suggestions/?email=MATCH@htq.test",
                        **admin_auth).json()
    assert [row["id"] for row in body["users"]] == [user.id]
    assert body["users"][0]["match_on"] == ["email"]
    assert body["users"][0]["match_kind"] == "exact"
    assert body["users"][0]["employee_id"] is None


@pytest.mark.django_db
def test_match_suggestions_matches_phone_across_formatting(admin_auth):
    """Один номер, записанный по-разному, обязан совпасть."""
    user = _user("phone@htq.test", phone="+7 (700) 483-55-81")

    body = Client().get(f"{BASE}/match-suggestions/?phone=87004835581", **admin_auth).json()
    assert [row["id"] for row in body["users"]] == [user.id]
    assert body["users"][0]["match_on"] == ["phone"]


@pytest.mark.django_db
def test_match_suggestions_ignores_too_short_phone(admin_auth):
    _user("short@htq.test", phone="+7 (700) 483-55-81")
    body = Client().get(f"{BASE}/match-suggestions/?phone=5581", **admin_auth).json()
    assert body["users"] == []


@pytest.mark.django_db
def test_match_suggestions_warns_about_existing_employee(admin_auth, hr_dep):
    """Тот самый дубль, который раньше ловился только уникальностью email."""
    pos = _pos("Инженер", hr_dep, weight=95)
    existing = _emp(hr_dep, pos, "dup@htq.test", first_name="Семён", last_name="Семёнов",
                    phone="+7 (700) 777-77-77")

    body = Client().get(
        f"{BASE}/match-suggestions/?first_name=Семён&last_name=Семёнов", **admin_auth,
    ).json()
    assert [row["id"] for row in body["employees"]] == [existing.id]
    assert body["employees"][0]["match_kind"] == "similar"


@pytest.mark.django_db
def test_match_suggestions_marks_user_that_already_has_a_card(admin_auth, hr_dep):
    user = _user("linked@htq.test", first_name="Лидия", last_name="Лидина")
    pos = _pos("Аналитик", hr_dep, weight=96)
    emp = _emp(hr_dep, pos, "linked@htq.test", user_id=user.id,
               first_name="Лидия", last_name="Лидина")

    body = Client().get(f"{BASE}/match-suggestions/?email=linked@htq.test",
                        **admin_auth).json()
    assert body["users"][0]["employee_id"] == emp.id


@pytest.mark.django_db
def test_match_suggestions_excludes_the_employee_being_edited(admin_auth, hr_dep):
    pos = _pos("Инженер", hr_dep, weight=97)
    emp = _emp(hr_dep, pos, "self@htq.test", first_name="Олег", last_name="Олегов")

    body = Client().get(
        f"{BASE}/match-suggestions/?email=self@htq.test&exclude_employee_id={emp.id}",
        **admin_auth,
    ).json()
    assert body["employees"] == []


# ── импорт ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_import_candidates_excludes_linked_and_same_email(admin_auth, hr_dep):
    free = _user("free@htq.test", first_name="Свободный", last_name="Пользователь")
    linked = _user("linked2@htq.test")
    by_email = _user("by-email@htq.test")

    pos = _pos("Инженер", hr_dep, weight=98)
    _emp(hr_dep, pos, "someone-else@htq.test", user_id=linked.id)
    # Карточка заведена раньше привязки — находят друг друга по email.
    _emp(hr_dep, pos, "by-email@htq.test")

    body = Client().get(f"{BASE}/import-candidates/", **admin_auth).json()
    ids = {row["id"] for row in body}
    assert free.id in ids
    assert linked.id not in ids
    assert by_email.id not in ids


@pytest.mark.django_db
def test_bulk_import_creates_cards_and_reports_skipped(admin_auth, hr_dep):
    pos = _pos("Инженер", hr_dep, weight=99)
    ok1 = _user("bulk1@htq.test", first_name="Первый", last_name="Пользователь")
    ok2 = _user("bulk2@htq.test", first_name="Второй", last_name="Пользователь")
    already = _user("bulk3@htq.test")
    _emp(hr_dep, pos, "already@htq.test", user_id=already.id)

    resp = _post(f"{BASE}/bulk-import/", {
        "user_ids": [ok1.id, ok2.id, already.id, 999999],
        "department_id": hr_dep.id,
        "position_id": pos.id,
        "hire_date": "2026-01-15",
    }, admin_auth)
    assert resp.status_code == 200
    body = resp.json()

    assert body["created_count"] == 2
    assert {row["email"] for row in body["created"]} == {"bulk1@htq.test", "bulk2@htq.test"}
    reasons = {row["user_id"]: row["reason"] for row in body["skipped"]}
    assert reasons[already.id] == "already_linked"
    assert reasons[999999] == "user_not_found"

    created = Employee.objects.get(email="bulk1@htq.test")
    assert created.user_id == ok1.id
    assert created.department_id == hr_dep.id
    assert created.hire_date == datetime.date(2026, 1, 15)


@pytest.mark.django_db
def test_bulk_import_requires_create_permission(middle, hr_dep):
    _emp_middle, headers = middle
    pos = _pos("Инженер", hr_dep, weight=100)
    resp = _post(f"{BASE}/bulk-import/", {
        "user_ids": [1], "department_id": hr_dep.id,
        "position_id": pos.id, "hire_date": "2026-01-15",
    }, headers)
    assert resp.status_code == 403


@pytest.mark.django_db
def test_bulk_import_rejects_empty_selection(admin_auth, hr_dep):
    pos = _pos("Инженер", hr_dep, weight=101)
    resp = _post(f"{BASE}/bulk-import/", {
        "user_ids": [], "department_id": hr_dep.id,
        "position_id": pos.id, "hire_date": "2026-01-15",
    }, admin_auth)
    assert resp.status_code == 422


# ── создание сотрудника: валидация user_id (раньше был IntegrityError) ─────

@pytest.mark.django_db
def test_create_employee_rejects_unknown_user_id(admin_auth, hr_dep):
    pos = _pos("Инженер", hr_dep, weight=102)
    resp = _post(f"{BASE}/", {
        "first_name": "Новый", "last_name": "Сотрудник", "email": "fresh@htq.test",
        "department_id": hr_dep.id, "position_id": pos.id,
        "hire_date": "2026-02-01", "user_id": 999999,
    }, admin_auth)
    assert resp.status_code == 422


@pytest.mark.django_db
def test_create_employee_rejects_user_id_taken_by_another(admin_auth, hr_dep):
    pos = _pos("Инженер", hr_dep, weight=103)
    user = _user("dup-link@htq.test")
    _emp(hr_dep, pos, "first@htq.test", user_id=user.id)

    resp = _post(f"{BASE}/", {
        "first_name": "Второй", "last_name": "Сотрудник", "email": "second@htq.test",
        "department_id": hr_dep.id, "position_id": pos.id,
        "hire_date": "2026-02-01", "user_id": user.id,
    }, admin_auth)
    assert resp.status_code == 409

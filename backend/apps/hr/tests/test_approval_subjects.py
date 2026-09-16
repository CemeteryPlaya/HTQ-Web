"""Кадровые предметы согласования (HR-FRM-004).

Движок согласования — чужой (apps.signoff) и в этом блоке не трогается.
Проверяется ровно то, за что отвечает домен кадров: предмет объявлен
согласуемым, зарегистрирован под своим типом, отдаёт факты, по которым
маршрут ветвится, и отправляется на согласование одной ручкой.

Факты — не украшение: именно по ним второй разработчик строит условия
маршрута (roadmap §6.2 просит сумму премии, срок отпуска и категорию
должности). Поэтому набор ключей фактов пинится точным сравнением: лишний
или переименованный ключ — это сломанное условие в чужом маршруте.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.test import Client

from apps.hr.models import Department, Position, StaffingPosition
from apps.hr.services import staffing_service as staffing_svc
from apps.signoff import interface as signoff
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/hr/v1"

# Три состояния, в которых предмет заперт для правки (Approvable.editable()
# белым списком отпускает только draft/rework), и два, в которых он открыт —
# ровно все пять значений ApprovalState.
LOCKED_STATES = (
    signoff.ApprovalState.PENDING,
    signoff.ApprovalState.APPROVED,
    signoff.ApprovalState.REJECTED,
)
EDITABLE_STATES = (
    signoff.ApprovalState.DRAFT,
    signoff.ApprovalState.REWORK,
)


@pytest.fixture
def dep(db):
    return Department.objects.create(name="Дирекция по финансам", path="fin")


@pytest.fixture
def auth(db):
    """Обычный вошедший пользователь — годится для reads, НЕ годится для writes."""
    user = User.objects.create(
        username="hr-user", email="hr-user@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    user.set_password("S3cret!")
    user.save()
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def staffing_line(dep):
    position = Position.objects.create(title="Главный бухгалтер", department=dep, weight=610)
    return StaffingPosition.objects.create(
        position=position, department=dep, headcount=1, salary=800000, grade=8)


@pytest.mark.django_db
def test_staffing_position_is_approvable(staffing_line):
    """Примесь даёт колонку состояния на самой таблице предмета —
    межаппного FK при этом не возникает."""
    assert staffing_line.approval_state == signoff.ApprovalState.DRAFT
    assert staffing_line.SIGNOFF_SUBJECT_TYPE == "hr.staffing_position"
    assert staffing_line.is_approved is False


@pytest.mark.django_db
def test_subject_is_registered_under_its_type():
    registered = {s["subject_type"]: s for s in signoff.registered_subjects()}
    assert "hr.staffing_position" in registered
    assert registered["hr.staffing_position"]["label"] == "Штатная единица"


@pytest.mark.django_db
def test_facts_carry_exactly_the_agreed_keys(staffing_line):
    from apps.hr import approval_hooks

    facts = approval_hooks._staffing_facts(staffing_line.id)
    assert set(facts) == {"department_id", "position_id", "position_level",
                          "headcount", "salary", "payroll"}
    assert facts["salary"] == 800000
    # Фонд оплаты труда строки — это оклад, умноженный на число единиц:
    # примечание документа «ФОТ — в пределах бюджета» ветвится именно по нему,
    # а не по окладу одного человека.
    assert facts["payroll"] == 800000
    assert facts["position_level"] == staffing_line.position.level


@pytest.mark.django_db
def test_facts_of_a_deleted_subject_are_empty_not_an_error():
    """Объект удалили между отправкой и запуском — условный маршрут откажет
    внятным «не сошлось ни одно условие», а не упадёт."""
    from apps.hr import approval_hooks

    assert approval_hooks._staffing_facts(10_000_000) == {}


@pytest.mark.django_db
def test_fact_fields_describe_every_fact(staffing_line):
    """Редактор маршрута предлагает поля из fact_fields; поле, которого нет
    в фактах, даст условие, падающее уже в руках пользователя."""
    from apps.hr import approval_hooks

    facts = approval_hooks._staffing_facts(staffing_line.id)
    declared = {f["key"] for f in approval_hooks._staffing_fact_fields()}
    assert declared == set(facts)


@pytest.mark.django_db
def test_describe_names_the_subject_for_the_approver(staffing_line):
    from apps.hr import approval_hooks

    card = approval_hooks._describe_staffing(staffing_line.id)
    assert "Главный бухгалтер" in card["title"]
    assert card["url"].endswith(str(staffing_line.id))
    assert approval_hooks._describe_staffing(10_000_000) is None


# ── ручка «отправить на согласование» ────────────────────────────────────

@pytest.mark.django_db
def test_submit_requires_jwt(staffing_line):
    resp = Client().post(f"{BASE}/approvals/hr.staffing_position/{staffing_line.id}/submit")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_submit_without_a_route_is_409_and_says_so(staffing_line, auth):
    """Маршрута нет — это не поломка, а незаконченная настройка; человеку
    надо сказать словами, а не 500."""
    resp = Client().post(
        f"{BASE}/approvals/hr.staffing_position/{staffing_line.id}/submit", **auth)
    assert resp.status_code == 409
    assert "маршрут" in resp.json()["detail"].lower()


@pytest.mark.django_db
def test_submit_of_unknown_subject_type_is_404(staffing_line, auth):
    resp = Client().post(f"{BASE}/approvals/hr.no_such_thing/1/submit", **auth)
    assert resp.status_code == 404


@pytest.mark.django_db
def test_submit_of_missing_object_is_404(auth):
    resp = Client().post(f"{BASE}/approvals/hr.staffing_position/10000000/submit", **auth)
    assert resp.status_code == 404


@pytest.mark.django_db
def test_both_url_spellings_work(staffing_line, auth):
    for url in (f"{BASE}/approvals/hr.staffing_position/{staffing_line.id}/submit",
                f"{BASE}/approvals/hr.staffing_position/{staffing_line.id}/submit/"):
        assert Client().post(url, **auth).status_code != 404


# ── замок согласования на строке штатного расписания (Task 8a) ──────────
#
# StaffingPosition наследует Approvable, но задача 1 пропустила четвёртый
# шаг подключения (STRUCTURE.md): assert_editable() первой строкой каждой
# операции правки/удаления. Без него строку на согласовании можно менять
# посреди маршрута — согласующие подписывают факты, которых уже нет.

@pytest.mark.django_db
@pytest.mark.parametrize("state", LOCKED_STATES)
def test_update_line_is_locked_while_subject_is_pending_or_decided(staffing_line, state):
    StaffingPosition.objects.filter(pk=staffing_line.pk).update(approval_state=state)

    with pytest.raises(signoff.SubjectLocked):
        staffing_svc.update_line(staffing_line.id, {"salary": "999999"})

    staffing_line.refresh_from_db()
    assert staffing_line.salary == Decimal("800000.00")


@pytest.mark.django_db
@pytest.mark.parametrize("state", LOCKED_STATES)
def test_delete_line_is_locked_while_subject_is_pending_or_decided(staffing_line, state):
    StaffingPosition.objects.filter(pk=staffing_line.pk).update(approval_state=state)

    with pytest.raises(signoff.SubjectLocked):
        staffing_svc.delete_line(staffing_line.id)

    assert StaffingPosition.objects.filter(pk=staffing_line.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("state", EDITABLE_STATES)
def test_update_line_still_works_in_draft_and_rework(staffing_line, state):
    StaffingPosition.objects.filter(pk=staffing_line.pk).update(approval_state=state)

    line = staffing_svc.update_line(staffing_line.id, {"salary": "999999"})

    assert line.salary == Decimal("999999.00")


@pytest.mark.django_db
@pytest.mark.parametrize("state", EDITABLE_STATES)
def test_delete_line_still_works_in_draft_and_rework(staffing_line, state):
    StaffingPosition.objects.filter(pk=staffing_line.pk).update(approval_state=state)

    staffing_svc.delete_line(staffing_line.id)

    assert not StaffingPosition.objects.filter(pk=staffing_line.pk).exists()

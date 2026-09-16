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

import datetime as dt
from decimal import Decimal

import pytest
from django.test import Client

from apps.hr.models import (
    Bonus,
    BusinessTrip,
    Department,
    Employee,
    JobDescription,
    LeaveRequest,
    OrgChangeRequest,
    PersonnelOrder,
    Policy,
    Position,
    Reprimand,
    StaffingPosition,
    VacationSchedule,
    VacationScheduleLine,
)
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


# ── сводные сторожа блока G ─────────────────────────────────────────────
#
# Десять предметов делались семью задачами, и каждая пинила СВОИ ключи в
# своём файле. Эти три теста держат картину целиком: список типов, набор
# ключей у каждого и единственность автоматического эффекта. Контракт
# уезжает в чужой код (roadmap §6.4) — менять его в одиночку нельзя.

# Ровно то, что записано в roadmap §6.4. Дублирование с per-subject тестами
# намеренное: там проверяется «предмет отдаёт свои ключи», здесь — «список
# предметов и ключей целиком такой, каким его получил второй разработчик».
MATRIX_SUBJECTS = {
    "hr.org_change": {"kind", "department_id", "effective_date", "headcount_delta"},
    "hr.staffing_position": {"department_id", "position_id", "position_level",
                             "headcount", "salary", "payroll"},
    "hr.policy": {"kind", "version", "effective_from"},
    "hr.job_description": {"position_id", "position_level", "department_id",
                           "version", "effective_from"},
    "hr.personnel_order": {"kind", "position_id", "position_level", "is_manager",
                           "target_company_slug", "salary", "effective_date"},
    "hr.bonus": {"employee_id", "department_id", "position_level", "amount",
                 "period", "kind"},
    "hr.reprimand": {"employee_id", "department_id", "position_level",
                     "severity", "event_date"},
    "hr.vacation_schedule": {"year", "lines_count", "employees_count", "total_days"},
    "hr.leave_request": {"employee_id", "department_id", "kind", "days",
                         "date_from", "date_to"},
    "hr.business_trip": {"employee_id", "department_id", "destination", "country",
                         "days", "estimated_cost", "date_from", "date_to"},
}


@pytest.mark.django_db
def test_every_matrix_row_has_its_subject_and_facts():
    """Контракт со вторым разработчиком (roadmap §6.4): список типов и
    ключей фактов. Он уезжает в чужой код маршрутами и условиями —
    переименовать ключ молча значит сломать настроенный маршрут.
    """
    from apps.hr import approval_hooks

    assert set(approval_hooks.SUBJECT_MODELS) == set(MATRIX_SUBJECTS)
    assert set(approval_hooks.SUBJECT_SPECS) == set(MATRIX_SUBJECTS)
    for subject_type, keys in MATRIX_SUBJECTS.items():
        declared = {f["key"]
                    for f in approval_hooks.SUBJECT_SPECS[subject_type]["fact_fields"]()}
        assert declared == keys, subject_type


@pytest.mark.django_db
def test_only_the_personnel_order_has_an_automatic_effect():
    """Решение 11: единственный автоматический эффект во всём блоке —
    запись в кадровую историю при утверждении приказа. Появление второго
    обязано быть осознанным, а не случайным."""
    from apps.hr import approval_hooks

    with_effects = {t for t, spec in approval_hooks.SUBJECT_SPECS.items()
                    if {"on_approved", "on_rejected", "on_rework",
                        "on_started", "on_cancelled"} & set(spec)}
    assert with_effects == {"hr.personnel_order"}


@pytest.mark.django_db
def test_every_subject_gives_the_engine_only_values_it_can_normalize(every_subject):
    """Факты уходят в условия маршрута, а те сравнивают ТОЛЬКО скаляры:
    ``apps/signoff/services/conditions.py::normalize_facts`` переводит
    ``Decimal`` в ``float`` и даты в ISO-строку, а на любом другом
    нескалярном значении поднимает ``ConditionError`` — то есть ошибка
    вылезет в чужом коде, на живом маршруте, а не здесь.

    Список типов повторён здесь, а не спрошен у signoff: валидатора фактов
    интерфейс соседа не экспортирует (запрошено в roadmap §6.2), а
    импортировать его внутренности домен кадров не вправе. Если движок
    сузит набор — этот тест придётся сверить руками.

    Сторож не теоретический: у графика отпусков ``total_days`` собирается
    агрегатом по датам, и в первой редакции приезжал ``timedelta``.
    """
    from apps.hr import approval_hooks

    allowed = (str, int, float, bool, type(None), Decimal, dt.date, dt.datetime)
    for subject_type, subject_id in every_subject.items():
        facts = approval_hooks.SUBJECT_SPECS[subject_type]["facts"](subject_id)
        assert set(facts) == MATRIX_SUBJECTS[subject_type], subject_type
        for key, value in facts.items():
            assert isinstance(value, allowed), f"{subject_type}.{key}: {type(value)}"


@pytest.fixture
def every_subject(db):
    """По одной живой строке каждого из десяти предметов — {тип: id}.

    Нужна ровно одному тесту (типы значений в фактах), но заводится
    фикстурой, а не внутри него: следующий сводный сторож — «у каждого
    предмета есть describe» или «карточка каждого предмета непуста» —
    возьмёт её же, вместо того чтобы завести второй набор из десяти строк.
    """
    dep = Department.objects.create(name="Дирекция по эксплуатации", path="ops")
    position = Position.objects.create(
        title="Ведущий инженер", department=dep, weight=650, level=3)
    employee = Employee.objects.create(
        first_name="Асель", last_name="Нурланова", email="a.n@htq.kz",
        department=dep, position=position, hire_date="2022-03-01")
    schedule = VacationSchedule.objects.create(year=2027)
    VacationScheduleLine.objects.create(
        schedule=schedule, employee=employee,
        date_from=dt.date(2027, 6, 1), date_to=dt.date(2027, 6, 14))
    rows = {
        "hr.staffing_position": StaffingPosition.objects.create(
            position=position, department=dep, headcount=1, salary=700000, grade=7),
        "hr.personnel_order": PersonnelOrder.objects.create(
            employee=employee, position=position, department=dep,
            effective_date=dt.date(2026, 10, 1), salary=700000),
        "hr.bonus": Bonus.objects.create(
            employee=employee, amount=Decimal("120000.00"), period="2026-09"),
        "hr.reprimand": Reprimand.objects.create(
            employee=employee, event_date=dt.date(2026, 9, 10),
            reason="Нарушение регламента выдачи пропусков"),
        "hr.leave_request": LeaveRequest.objects.create(
            employee=employee, date_from=dt.date(2026, 10, 5),
            date_to=dt.date(2026, 10, 18)),
        "hr.business_trip": BusinessTrip.objects.create(
            employee=employee, destination="Астана",
            date_from=dt.date(2026, 11, 2), date_to=dt.date(2026, 11, 6),
            estimated_cost=Decimal("350000.00")),
        "hr.vacation_schedule": schedule,
        "hr.policy": Policy.objects.create(
            title="Положение о пропускном режиме", version="1.0",
            effective_from=dt.date(2026, 10, 1)),
        "hr.job_description": JobDescription.objects.create(
            position=position, version="1.0", effective_from=dt.date(2026, 10, 1)),
        "hr.org_change": OrgChangeRequest.objects.create(
            department=dep, description="Ввести вторую единицу ведущего инженера",
            headcount_delta=1, effective_date=dt.date(2026, 12, 1)),
    }
    return {subject_type: row.id for subject_type, row in rows.items()}


@pytest.mark.django_db
def test_every_subject_declares_fields_the_engine_accepts(dep):
    """Объявления полей прогоняются через САМ движок, а не сверяются с
    локальным списком типов.

    Сторож завёлся по находке финального ревью: у кадрового приказа тип поля
    был написан как ``"boolean"``, а движок знает только ``"bool"``
    (``conditions.FIELD_TYPES``). Падало это молча и далеко: редактор
    маршрутов (``signoff.views.SubjectsView._fields``) глотает исключение и
    показывает предмет БЕЗ условий, то есть строки 5–7 матрицы нельзя было
    развести ветвлением — ровно то, ради чего факты и объявлялись.

    Импорт внутренностей соседа — сознательный и ровно такой же, как в
    ``apps/contracts/tests/test_approval_facts.py``: проверять объявления
    полей больше нечем, пока signoff не вынес валидатор в свой interface
    (запрошено в roadmap §6.2). Сторож границ каталоги ``tests/`` не
    сканирует, так что правило аппок этим не нарушается.

    Фикстура ``dep`` здесь обязательна, и это не деталь теста: шесть из
    десяти предметов объявляют ``department_id`` полем типа ``choice``, а
    движок требует у ``choice`` непустой список вариантов. В компании БЕЗ
    подразделений объявление полей поэтому не проходит проверку целиком —
    известная ловушка платформы (STRUCTURE.md, «пустой справочник»), теперь
    распространяющаяся и на кадры. Самолечится данными: без подразделения не
    завести ни должность, ни сотрудника, то есть и предмета согласования не
    возникнет. Ниже это зафиксировано отдельным тестом, чтобы поведение было
    описано, а не обнаружено.
    """
    from apps.signoff.services import registry

    for subject_type in MATRIX_SUBJECTS:
        fields = registry.fields_for(subject_type)
        assert {f["key"] for f in fields} == MATRIX_SUBJECTS[subject_type], subject_type


@pytest.mark.django_db
def test_a_long_basis_survives_approval(every_subject):
    """Основание приказа (255) должно влезать в номер приказа в истории.

    Вторая находка финального ревью: колонка истории была 64, и на обычном
    тексте «Приказ Генерального директора № …» запись падала ``DataError``.
    Колбэк идёт ВНУТРИ транзакции движка, поэтому вместе с записью
    откатывалось решение согласующего — приказ нельзя было утвердить вовсе.
    Тест держит равенство длин: разъедутся — упадёт здесь, а не на бою.
    """
    from apps.hr import approval_hooks
    from apps.hr.models import PersonnelHistory, PersonnelOrder

    order_id = every_subject["hr.personnel_order"]
    basis = "Приказ Генерального директора № 123-К от 01.10.2026 «" + "О" * 200 + "»"
    PersonnelOrder.objects.filter(pk=order_id).update(basis=basis[:255])

    approval_hooks._personnel_order_on_approved(order_id)

    row = PersonnelHistory.objects.get(employee_id=PersonnelOrder.objects.get(
        pk=order_id).employee_id)
    assert row.order_number == basis[:255]


@pytest.mark.django_db
def test_approving_the_same_order_twice_does_not_duplicate_history(every_subject):
    """Утвердить приказ дважды можно штатным путём: согласующий возвращает
    завершённый процесс на доработку (``engine.reopen``), приказ правят и
    отправляют заново — новым процессом, с новым ``on_approved``. Через
    ``create`` сотрудник получал бы две записи «Уволен», а кадровую историю
    читают карточка, стаж и отчёты."""
    from apps.hr import approval_hooks
    from apps.hr.models import PersonnelHistory

    order_id = every_subject["hr.personnel_order"]

    approval_hooks._personnel_order_on_approved(order_id)
    approval_hooks._personnel_order_on_approved(order_id)

    assert PersonnelHistory.objects.count() == 1


@pytest.mark.django_db
def test_without_departments_the_route_editor_sees_no_conditions():
    """Обратная сторона предыдущего теста, описанная явно.

    В компании без активных подразделений ``_department_options()`` пуст,
    движок отвергает объявление полей целиком (``choice`` без вариантов), а
    редактор маршрутов (``signoff.views.SubjectsView._fields``) глотает
    исключение и показывает предмет без условий. Это НЕ бессимптомная
    поломка блока: без подразделения в компании нет ни должностей, ни
    сотрудников, ни самих кадровых заявок. Тест здесь затем, чтобы тот, кто
    настраивает маршруты на пустой компании и видит предмет без условий,
    нашёл объяснение, а не считал редактор сломанным.
    """
    from apps.signoff.services import conditions, registry

    with pytest.raises(conditions.ConditionError):
        registry.fields_for("hr.staffing_position")

    # Предметы без ``choice``-полей от пустого справочника не страдают.
    assert {f["key"] for f in registry.fields_for("hr.vacation_schedule")} == \
        MATRIX_SUBJECTS["hr.vacation_schedule"]

"""Стык contracts ↔ signoff: подача заявки, последствия решения, гейт.

Механику самого движка проверяет ``apps/signoff/tests``; здесь — ровно то,
что добавляет эта аппка: свои эндпоинты отправки, перевод договора по его
машине статусов и правило «несогласованное не расходуется».

Маршруты собираются прямой записью в модели signoff. Тесты — единственное
место, где это допустимо: ``test_app_isolation`` пропускает всё под
``tests/``, а гонять настройку маршрута через HTTP в каждом тесте значило бы
проверять чужой эндпоинт вместо своего.
"""

from __future__ import annotations

import pytest

from apps.contracts.models import (
    Agreement,
    AgreementStatus,
    Budget,
    Counterparty,
    Invoice,
    InvoiceStatus,
    AdvanceReport,
)
from apps.contracts.services import budget_calc
from apps.contracts.tests.helpers import (
    BASE,
    admin_token,
    auth,
    make_administrator,
    make_agreement,
    make_invoice,
    make_line,
    make_counterparty,
    make_program,
    patch_json,
    post_json,
    token,
)
from apps.core.models import ServiceStatus
from apps.signoff.models import (
    ApprovalRoute,
    ApprovalRouteStage,
    ApprovalRouteStageRole,
    ApprovalState,
    ApprovalTask,
    ProcessState,
    Quorum,
    TaskState,
)
from apps.signoff.services import engine
from apps.hr.models import Department, Employee, EmployeeStatus, Position
from apps.users.models import User, UserStatus

pytestmark = pytest.mark.django_db


def make_user(username: str = "approver") -> User:
    user = User.objects.create(username=username, email=f"{username}@htq.test",
                               password="x", status=UserStatus.ACTIVE)
    department, _ = Department.objects.get_or_create(
        path="contracts-signoff-tests", defaults={"name": "Contracts signoff tests"})
    position = Position.objects.filter(pk=user.pk).first()
    if position is None:
        position = Position.objects.create(
            id=user.pk, title=f"Contracts {username}", department=department,
            weight=user.pk + 20_000,
        )
    Employee.objects.create(
        user_id=user.pk, first_name=username, last_name="Tester",
        email=f"employee-{username}@htq.test", department=department,
        position=position, hire_date="2024-01-01", status=EmployeeStatus.ACTIVE,
    )
    return user


def route_for(subject_type: str, *user_ids: int) -> ApprovalRoute:
    """Одноэтапный активный маршрут — минимум, включающий согласование."""
    route = ApprovalRoute.objects.create(subject_type=subject_type,
                                         name=f"Маршрут {subject_type}")
    stage = ApprovalRouteStage.objects.create(route=route, order=1,
                                              name="Единственный этап",
                                              quorum=Quorum.ALL)
    for user_id in user_ids:
        ApprovalRouteStageRole.objects.create(stage=stage, position_id=user_id)
    return route


def user_token(user: User) -> str:
    return token(user_id=user.pk, sub=str(user.pk), username=user.username)


def decide(process, user: User, decision: str):
    task = ApprovalTask.objects.get(stage__process=process, user_id=user.pk,
                                    state=TaskState.PENDING)
    return engine.act(task_id=task.pk, actor_id=user.pk, decision=decision)


def approve(subject) -> None:
    """Провести объект через согласование до конца — чтобы дальше проверять
    то, ради чего тест написан, а не повторять подачу заявки."""
    approver = make_user(f"approver-{subject.pk}-{type(subject).__name__}")
    route_for(subject.SIGNOFF_SUBJECT_TYPE, approver.pk)
    process = subject.submit_for_approval()
    decide(process, approver, engine.APPROVE)
    subject.refresh_from_db()


# ═══════════════════════════════════════════════════════════════════════
# Регистрация типов
# ═══════════════════════════════════════════════════════════════════════

def test_all_contract_models_are_registered_as_approvable(client):
    listed = client.get("/api/signoff/v1/subjects", **auth(token())).json()
    by_type = {row["subject_type"]: row for row in listed}

    assert by_type["contracts.budget"]["label"] == "Бюджет"
    assert by_type["contracts.counterparty"]["label"] == "Контрагент"
    assert by_type["contracts.agreement"]["label"] == "Договор"
    assert by_type["contracts.invoice"]["label"] == "Счёт на оплату"
    assert by_type["contracts.advance_payment"]["label"] == "Предоплата на основании договора"
    assert by_type["contracts.advance_report"]["label"] == "Авансовый отчёт"
    assert by_type["contracts.completion_act"]["label"] == "Акт выполненных работ"


def test_the_process_card_shows_a_human_readable_subject(client):
    approver = make_user()
    line = make_line()
    route_for(Budget.SIGNOFF_SUBJECT_TYPE, approver.pk)

    submitted = post_json(client, f"{BASE}/budgets/{line.budget_id}/submit", {},
                          **auth(token()))
    assert submitted.status_code == 201, submitted.content
    body = submitted.json()
    # describe() из approval_hooks: signoff сам не умеет назвать чужую строку.
    assert line.budget.administrator.display_name in body["subject_title"]
    assert body["subject_url"] == f"/contracts/budgets/{line.budget_id}"


# ═══════════════════════════════════════════════════════════════════════
# Подача заявки
# ═══════════════════════════════════════════════════════════════════════

def test_an_ordinary_employee_can_create_and_submit_a_budget(client):
    """Смысл всей связки: заявку подаёт сотрудник, решает согласование.
    Если бы завести бюджет мог только администратор, маршрут был бы не нужен."""
    approver = make_user()
    route_for(Budget.SIGNOFF_SUBJECT_TYPE, approver.pk)

    created = post_json(client, f"{BASE}/budgets/full", {
        "administrator": {"id": make_administrator().pk},
        "programs": [{"program": {"id": make_program().pk},
                      "amount": "1000000.00"}],
        "period_year": 2030,
    }, **auth(token()))
    assert created.status_code == 201, created.content
    assert created.json()["approval_state"] == ApprovalState.DRAFT

    submitted = post_json(client, f"{BASE}/budgets/{created.json()['id']}/submit",
                          {}, **auth(token()))
    assert submitted.status_code == 201
    assert submitted.json()["state"] == ProcessState.PENDING

    budget = Budget.objects.get(pk=created.json()["id"])
    assert budget.approval_state == ApprovalState.PENDING


def test_editing_a_budget_still_needs_an_admin(client):
    """Ослаблено только СОЗДАНИЕ: правка остаётся административной."""
    line = make_line()
    forbidden = client.patch(f"{BASE}/budgets/{line.budget_id}",
                             data='{"amount": "1.00"}',
                             content_type="application/json", **auth(token()))
    assert forbidden.status_code == 403


def test_submitting_without_a_route_is_409(client):
    line = make_line()
    bad = post_json(client, f"{BASE}/budgets/{line.budget_id}/submit", {},
                    **auth(token()))
    assert bad.status_code == 409
    assert "маршрут" in bad.json()["detail"].lower()


def test_submitting_twice_is_409(client):
    approver = make_user()
    line = make_line()
    route_for(Budget.SIGNOFF_SUBJECT_TYPE, approver.pk)

    assert post_json(client, f"{BASE}/budgets/{line.budget_id}/submit", {},
                     **auth(token())).status_code == 201
    clash = post_json(client, f"{BASE}/budgets/{line.budget_id}/submit", {},
                      **auth(token()))
    assert clash.status_code == 409


def test_a_closed_budget_is_not_submitted(client):
    approver = make_user()
    line = make_line()
    budget = line.budget
    budget.status = "closed"
    budget.save(update_fields=["status"])
    route_for(Budget.SIGNOFF_SUBJECT_TYPE, approver.pk)

    bad = post_json(client, f"{BASE}/budgets/{line.budget_id}/submit", {},
                    **auth(token()))
    assert bad.status_code == 409
    assert "Закрытый" in bad.json()["detail"]


def test_a_blocked_counterparty_is_not_submitted(client):
    approver = make_user()
    counterparty = make_counterparty(status="blocked")
    route_for(Counterparty.SIGNOFF_SUBJECT_TYPE, approver.pk)

    bad = post_json(client, f"{BASE}/counterparties/{counterparty.pk}/submit",
                    {}, **auth(token()))
    assert bad.status_code == 409


# ═══════════════════════════════════════════════════════════════════════
# Гейт: несогласованное не расходуется
# ═══════════════════════════════════════════════════════════════════════

def test_an_unapproved_budget_cannot_fund_an_agreement(client):
    approver = make_user()
    line = make_line()
    counterparty = make_counterparty()
    route_for(Budget.SIGNOFF_SUBJECT_TYPE, approver.pk)

    bad = post_json(client, f"{BASE}/agreements", {
        "number": "Д-100", "name": "Поставка", "budget_line_id": line.pk,
        "counterparty_id": counterparty.pk, "amount": "100000.00",
        "payment_type": "postpayment", "currency": "KZT",
    }, **auth(admin_token()))
    assert bad.status_code == 409
    assert "не согласован" in bad.json()["detail"]


def test_an_approved_budget_funds_an_agreement(client):
    line = make_line()
    counterparty = make_counterparty()
    approve(line.budget)
    assert line.budget.approval_state == ApprovalState.APPROVED

    created = post_json(client, f"{BASE}/agreements", {
        "number": "Д-101", "name": "Поставка", "budget_line_id": line.pk,
        "counterparty_id": counterparty.pk, "amount": "100000.00",
        "payment_type": "postpayment", "currency": "KZT",
    }, **auth(admin_token()))
    assert created.status_code == 201, created.content


def test_an_unapproved_counterparty_is_not_contractable(client):
    approver = make_user()
    line = make_line()
    counterparty = make_counterparty()
    route_for(Counterparty.SIGNOFF_SUBJECT_TYPE, approver.pk)

    bad = post_json(client, f"{BASE}/agreements", {
        "number": "Д-102", "name": "Поставка", "budget_line_id": line.pk,
        "counterparty_id": counterparty.pk, "amount": "100000.00",
        "payment_type": "postpayment", "currency": "KZT",
    }, **auth(admin_token()))
    assert bad.status_code == 409
    assert "не согласован" in bad.json()["detail"]


def test_without_a_route_the_gate_does_not_apply(client):
    """Установка, где согласование не настроено, продолжает работать как
    раньше: все существующие записи — draft, и безусловная проверка
    запретила бы вообще всё."""
    line = make_line()
    counterparty = make_counterparty()
    assert line.budget.approval_state == ApprovalState.DRAFT

    created = post_json(client, f"{BASE}/agreements", {
        "number": "Д-103", "name": "Поставка", "budget_line_id": line.pk,
        "counterparty_id": counterparty.pk, "amount": "100000.00",
        "payment_type": "postpayment", "currency": "KZT",
    }, **auth(admin_token()))
    assert created.status_code == 201, created.content


def test_the_gate_does_not_lock_edits_of_an_existing_agreement(client):
    """Согласование бюджета, отозванное задним числом, не должно запирать
    правку названия у давно заключённого договора."""
    line = make_line()
    counterparty = make_counterparty()
    agreement = make_agreement(line=line, counterparty=counterparty)
    make_user()
    route_for(Budget.SIGNOFF_SUBJECT_TYPE, make_user("later").pk)

    renamed = client.patch(f"{BASE}/agreements/{agreement.pk}",
                           data='{"name": "Новое название"}',
                           content_type="application/json",
                           **auth(admin_token()))
    assert renamed.status_code == 200, renamed.content


def test_disabling_signoff_lifts_the_gate_instead_of_breaking_contracts(client):
    """Выключенный модуль согласования перестаёт ТРЕБОВАТЬ согласования, а не
    роняет предметную аппку, которая его подключила. Иначе ``service --off``
    для signoff означал бы заодно остановку всего реестра договоров."""
    approver = make_user()
    line = make_line()
    counterparty = make_counterparty()
    route_for(Budget.SIGNOFF_SUBJECT_TYPE, approver.pk)
    ServiceStatus.objects.update_or_create(
        app_label="signoff", defaults={"enabled": False, "message": "off"})

    created = post_json(client, f"{BASE}/agreements", {
        "number": "Д-104", "name": "Поставка", "budget_line_id": line.pk,
        "counterparty_id": counterparty.pk, "amount": "100000.00",
        "payment_type": "postpayment", "currency": "KZT",
    }, **auth(admin_token()))
    assert created.status_code == 201, created.content

    # Сама отправка на согласование при этом честно отдаёт 503 — общий
    # контракт платформы для выключенного сервиса.
    off = post_json(client, f"{BASE}/budgets/{line.budget_id}/submit", {},
                    **auth(token()))
    assert off.status_code == 503
    assert off.json()["code"] == "service_disabled"


def test_the_budget_list_can_be_filtered_by_approval_state(client):
    approved = make_line(period_year=2031)
    make_line(program=make_program(expense_item="Услуги"), period_year=2032)
    approve(approved.budget)

    rows = client.get(f"{BASE}/budgets?approval_state=approved",
                      **auth(token())).json()
    assert [row["id"] for row in rows] == [approved.budget_id]


# ═══════════════════════════════════════════════════════════════════════
# Договор: результат согласования двигает его собственный статус
# ═══════════════════════════════════════════════════════════════════════

def _draft_agreement() -> Agreement:
    line = make_line()
    counterparty = make_counterparty()
    return make_agreement(line=line, counterparty=counterparty,
                          status=AgreementStatus.DRAFT)


def test_submitting_an_agreement_moves_it_to_on_review(client):
    approver = make_user()
    agreement = _draft_agreement()
    route_for(Agreement.SIGNOFF_SUBJECT_TYPE, approver.pk)

    submitted = post_json(client, f"{BASE}/agreements/{agreement.pk}/submit",
                          {}, **auth(token()))
    assert submitted.status_code == 201, submitted.content

    agreement.refresh_from_db()
    assert agreement.status == AgreementStatus.ON_REVIEW
    assert agreement.approval_state == ApprovalState.PENDING


def test_approval_moves_the_agreement_to_approved(client):
    approver = make_user()
    agreement = _draft_agreement()
    route_for(Agreement.SIGNOFF_SUBJECT_TYPE, approver.pk)
    process = agreement.submit_for_approval()

    decide(process, approver, engine.APPROVE)

    agreement.refresh_from_db()
    assert agreement.status == AgreementStatus.APPROVED
    assert agreement.approval_state == ApprovalState.APPROVED


def test_rejection_returns_the_agreement_to_draft(client):
    """Отклонённый договор дорабатывают и отправляют снова — «расторгнут»
    было бы состоянием без выхода."""
    approver = make_user()
    agreement = _draft_agreement()
    route_for(Agreement.SIGNOFF_SUBJECT_TYPE, approver.pk)
    process = agreement.submit_for_approval()

    decide(process, approver, engine.REJECT)

    agreement.refresh_from_db()
    assert agreement.status == AgreementStatus.DRAFT
    assert agreement.approval_state == ApprovalState.REJECTED


def test_cancelling_returns_the_agreement_to_draft(client):
    approver = make_user()
    initiator = make_user("initiator")
    agreement = _draft_agreement()
    route_for(Agreement.SIGNOFF_SUBJECT_TYPE, approver.pk)
    process = agreement.submit_for_approval(initiator_id=initiator.pk)

    engine.cancel(process_id=process.pk, actor_id=initiator.pk)

    agreement.refresh_from_db()
    assert agreement.status == AgreementStatus.DRAFT
    # Отзыв — не отказ: объект снова черновик и по обеим осям.
    assert agreement.approval_state == ApprovalState.DRAFT


def test_only_a_draft_agreement_is_submitted(client):
    approver = make_user()
    line = make_line()
    agreement = make_agreement(line=line, status=AgreementStatus.SIGNED)
    route_for(Agreement.SIGNOFF_SUBJECT_TYPE, approver.pk)

    bad = post_json(client, f"{BASE}/agreements/{agreement.pk}/submit", {},
                    **auth(token()))
    assert bad.status_code == 409
    assert "черновик" in bad.json()["detail"]


def test_an_agreement_that_does_not_fit_the_budget_is_not_submitted(client):
    """Договор «на согласовании» уже занимает бюджет
    (``budget_calc.COMMITTING_STATUSES``), поэтому лимит проверяется ДО
    запуска процесса, а не после."""
    approver = make_user()
    line = make_line(amount="500000.00")
    counterparty = make_counterparty()
    make_agreement(line=line, counterparty=counterparty, number="Д-200",
                   amount="400000.00", status=AgreementStatus.SIGNED)
    overflow = make_agreement(line=line, counterparty=counterparty,
                              number="Д-201", amount="300000.00",
                              status=AgreementStatus.DRAFT)
    route_for(Agreement.SIGNOFF_SUBJECT_TYPE, approver.pk)

    bad = post_json(client, f"{BASE}/agreements/{overflow.pk}/submit", {},
                    **auth(token()))
    assert bad.status_code == 409
    assert "превышает остаток" in bad.json()["detail"]

    overflow.refresh_from_db()
    # Процесс не запущен — и статус договора не сдвинулся.
    assert overflow.status == AgreementStatus.DRAFT
    assert overflow.approval_state == ApprovalState.DRAFT


# ═══════════════════════════════════════════════════════════════════════
# Объект на согласовании не редактируется
# ═══════════════════════════════════════════════════════════════════════
#
# Почему это вообще правило: ветвление маршрута разбирается ОДИН раз, на
# запуске, из снимка ``subject_facts``, и согласующие решают по тому, что
# видели тогда. Правка посреди процесса означает подписи под одним
# документом при другом содержимом карточки — причём этап, который новую
# сумму не пропустил бы, к тому моменту уже пройден по старой.
#
# Проверяется через HTTP, а не вызовом сервиса: половина смысла в том, что
# ``SubjectLocked`` доезжает до 409 сам, не будучи дописанным в
# ``views.CONFLICTS`` (он наследник ``SignoffError``, который там уже есть).


def _pending_budget() -> Budget:
    """Бюджет, отправленный на согласование и ждущий решения."""
    line = make_line()
    route_for(Budget.SIGNOFF_SUBJECT_TYPE, make_user("budget-approver").pk)
    line.budget.submit_for_approval()
    return line.budget


def test_a_budget_on_approval_is_not_editable(client):
    budget = _pending_budget()

    locked = patch_json(client, f"{BASE}/budgets/{budget.pk}",
                        {"period_year": 2035}, **auth(admin_token()))
    assert locked.status_code == 409, locked.content
    assert "на согласовании" in locked.json()["detail"]

    budget.refresh_from_db()
    assert budget.period_year != 2035


def test_cancelling_the_approval_unlocks_the_budget(client):
    """Отзыв — выход из блокировки для того, кто ЕЩЁ не получил решения."""
    budget = _pending_budget()
    engine.cancel(process_id=budget.approval_process().pk)

    freed = patch_json(client, f"{BASE}/budgets/{budget.pk}",
                       {"period_year": 2035}, **auth(admin_token()))
    assert freed.status_code == 200, freed.content


def test_a_counterparty_on_approval_is_not_editable(client):
    counterparty = make_counterparty()
    route_for(Counterparty.SIGNOFF_SUBJECT_TYPE, make_user("cp").pk)
    counterparty.submit_for_approval()

    locked = patch_json(client, f"{BASE}/counterparties/{counterparty.pk}",
                        {"name": "ТОО «Другое»"}, **auth(admin_token()))
    assert locked.status_code == 409, locked.content
    assert "на согласовании" in locked.json()["detail"]


def test_an_agreement_on_approval_is_not_editable(client):
    """Своя машина статусов запирает только терминальные состояния, а на
    согласовании договор живёт в ``on_review`` — под неё он не попадал."""
    agreement = _draft_agreement()
    before = agreement.amount
    route_for(Agreement.SIGNOFF_SUBJECT_TYPE, make_user("agr").pk)
    agreement.submit_for_approval()

    locked = patch_json(client, f"{BASE}/agreements/{agreement.pk}",
                        {"amount": "50000000.00"}, **auth(admin_token()))
    assert locked.status_code == 409, locked.content
    assert "на согласовании" in locked.json()["detail"]

    agreement.refresh_from_db()
    assert agreement.status == AgreementStatus.ON_REVIEW
    assert agreement.amount == before


def test_budget_lines_are_locked_by_the_parent_budget(client):
    """Строка не ``Approvable`` и своего состояния не имеет — её запирает
    бюджет, содержимым которого она является."""
    budget = _pending_budget()
    line = budget.lines.get()

    added = post_json(client, f"{BASE}/budgets/{budget.pk}/lines",
                      {"program_id": make_program(name="Вторая").pk,
                       "amount": "100000.00"}, **auth(admin_token()))
    assert added.status_code == 409, added.content

    edited = patch_json(client, f"{BASE}/budget-lines/{line.pk}",
                        {"amount": "999.00"}, **auth(admin_token()))
    assert edited.status_code == 409, edited.content

    removed = client.delete(f"{BASE}/budget-lines/{line.pk}",
                            **auth(admin_token()))
    assert removed.status_code == 409, removed.content


def test_deleting_is_blocked_while_on_approval(client):
    budget = _pending_budget()
    counterparty = make_counterparty(bin_iin="987654321098")
    route_for(Counterparty.SIGNOFF_SUBJECT_TYPE, make_user("cp-del").pk)
    counterparty.submit_for_approval()

    assert client.delete(f"{BASE}/budgets/{budget.pk}",
                         **auth(admin_token())).status_code == 409
    assert client.delete(f"{BASE}/counterparties/{counterparty.pk}",
                         **auth(admin_token())).status_code == 409


def test_a_rejected_object_stays_locked(client):
    """Отказ — не приглашение доработать, а «документ не годится». Правка
    после него открывается только возвратом на доработку: иначе отклонённый
    документ переписывался бы молча, и отказ бы ничего не значил."""
    approver = make_user("rejector")
    line = make_line()
    route_for(Budget.SIGNOFF_SUBJECT_TYPE, approver.pk)
    process = line.budget.submit_for_approval()
    decide(process, approver, engine.REJECT)

    line.budget.refresh_from_db()
    assert line.budget.approval_state == ApprovalState.REJECTED

    locked = patch_json(client, f"{BASE}/budgets/{line.budget_id}",
                        {"period_year": 2035}, **auth(admin_token()))
    assert locked.status_code == 409, locked.content
    assert "отклонён" in locked.json()["detail"]


def test_an_approved_object_is_not_editable(client):
    """Главное, ради чего замок вообще существует: документ, под которым
    собраны подписи, обязан остаться тем, который согласовывали."""
    line = make_line()
    approve(line.budget)

    locked = patch_json(client, f"{BASE}/budgets/{line.budget_id}",
                        {"period_year": 2035}, **auth(admin_token()))
    assert locked.status_code == 409, locked.content
    assert "согласован" in locked.json()["detail"]

    line.budget.refresh_from_db()
    assert line.budget.period_year != 2035


def test_returning_for_rework_unlocks_the_object(client):
    """Единственный ключ от замка — и он же возвращает договор в черновик по
    его собственной оси статусов."""
    approver = make_user("reworker")
    agreement = _draft_agreement()
    route_for(Agreement.SIGNOFF_SUBJECT_TYPE, approver.pk)
    process = agreement.submit_for_approval()
    decide(process, approver, engine.REWORK)

    agreement.refresh_from_db()
    assert agreement.approval_state == ApprovalState.REWORK
    assert agreement.status == AgreementStatus.DRAFT

    reworked = patch_json(client, f"{BASE}/agreements/{agreement.pk}",
                          {"amount": "150000.00"}, **auth(admin_token()))
    assert reworked.status_code == 200, reworked.content


def test_reopening_an_approved_agreement_unlocks_it(client):
    """Возврат УЖЕ СОГЛАСОВАННОГО (``engine.reopen``). Проверяется вместе со
    статусом договора: переход ``approved → draft`` заведён в
    ``ALLOWED_TRANSITIONS`` ровно ради этого случая, и без него колбэк
    ронял бы транзакцию движка."""
    approver = make_user("reopener")
    agreement = _draft_agreement()
    route_for(Agreement.SIGNOFF_SUBJECT_TYPE, approver.pk)
    process = agreement.submit_for_approval()
    decide(process, approver, engine.APPROVE)

    agreement.refresh_from_db()
    assert agreement.status == AgreementStatus.APPROVED

    engine.reopen(process_id=process.pk, actor_id=approver.pk,
                  comment="не та программа")

    agreement.refresh_from_db()
    assert agreement.approval_state == ApprovalState.REWORK
    assert agreement.status == AgreementStatus.DRAFT

    reworked = patch_json(client, f"{BASE}/agreements/{agreement.pk}",
                          {"amount": "150000.00"}, **auth(admin_token()))
    assert reworked.status_code == 200, reworked.content


def test_a_manual_status_change_is_blocked_while_on_approval(client):
    """Статус — такая же правка, как всякая другая: пока идёт согласование,
    его ведёт решение согласующих, а не ручной ``POST /status``.

    Без этого сдвиг ``on_review → terminated`` из-под висящего процесса
    заклинил бы движок — перехода ``terminated → approved`` нет, и колбэк
    одобрения ронял бы транзакцию на каждом решении согласующего, а из
    ``terminated`` договор уже не вытащить."""
    approver = make_user("mid-approval")
    agreement = _draft_agreement()
    route_for(Agreement.SIGNOFF_SUBJECT_TYPE, approver.pk)
    process = agreement.submit_for_approval()

    agreement.refresh_from_db()
    assert agreement.status == AgreementStatus.ON_REVIEW

    blocked = post_json(client, f"{BASE}/agreements/{agreement.pk}/status",
                        {"status": AgreementStatus.TERMINATED.value},
                        **auth(admin_token()))
    assert blocked.status_code == 409, blocked.content
    assert "на согласовании" in blocked.json()["detail"]

    agreement.refresh_from_db()
    assert agreement.status == AgreementStatus.ON_REVIEW

    # Процесс цел: согласующий по-прежнему доводит договор до approved.
    decide(process, approver, engine.APPROVE)
    agreement.refresh_from_db()
    assert agreement.status == AgreementStatus.APPROVED
    assert agreement.approval_state == ApprovalState.APPROVED


def test_the_lifecycle_advances_by_hand_after_approval(client):
    """Замок держит РОВНО ``pending``, а не всё, что держит ``assert_editable``.

    Согласованный договор ведут дальше руками — ``approved → signed →
    executed``, — и это законный ручной ``POST /status`` уже ПОСЛЕ
    согласования. Запри гейт и ``approved`` (как ``assert_editable``), этот
    путь оборвался бы на первом же шаге."""
    agreement = _draft_agreement()
    approve(agreement)
    assert agreement.status == AgreementStatus.APPROVED

    signed = post_json(client, f"{BASE}/agreements/{agreement.pk}/status",
                       {"status": AgreementStatus.SIGNED.value},
                       **auth(admin_token()))
    assert signed.status_code == 200, signed.content
    assert signed.json()["status"] == AgreementStatus.SIGNED.value


def test_disabling_signoff_unlocks_a_manual_status_change(client):
    """Тот же escape-hatch, что у правки (``test_disabling_signoff_unlocks_
    pending_objects``): выключенный модуль согласования перестаёт запирать —
    иначе застигнутый в ``pending`` договор нельзя было бы расторгнуть после
    ``service signoff --off``."""
    agreement = _draft_agreement()
    route_for(Agreement.SIGNOFF_SUBJECT_TYPE, make_user("agr-off").pk)
    agreement.submit_for_approval()
    ServiceStatus.objects.update_or_create(
        app_label="signoff", defaults={"enabled": False, "message": "off"})

    freed = post_json(client, f"{BASE}/agreements/{agreement.pk}/status",
                      {"status": AgreementStatus.TERMINATED.value},
                      **auth(admin_token()))
    assert freed.status_code == 200, freed.content
    assert freed.json()["status"] == AgreementStatus.TERMINATED.value


def test_a_decided_object_is_not_submitted_again(client):
    """Отправлять решённое нечего: оно заперто, и на новый круг ушло бы ровно
    тем же, каким его уже видели."""
    line = make_line()
    approve(line.budget)

    again = post_json(client, f"{BASE}/budgets/{line.budget_id}/submit", {},
                      **auth(token()))
    assert again.status_code == 409, again.content
    assert "верните объект на доработку" in again.json()["detail"]


def test_a_reworked_object_is_submitted_again(client):
    """Обратная сторона того же правила: доработанный уходит на новый круг —
    именно новым процессом, а не продолжением старого."""
    approver = make_user("second-round")
    line = make_line()
    route_for(Budget.SIGNOFF_SUBJECT_TYPE, approver.pk)
    first = line.budget.submit_for_approval()
    decide(first, approver, engine.REWORK)

    again = post_json(client, f"{BASE}/budgets/{line.budget_id}/submit", {},
                      **auth(token()))
    assert again.status_code == 201, again.content
    assert again.json()["id"] != first.pk

    line.budget.refresh_from_db()
    assert line.budget.approval_state == ApprovalState.PENDING


def test_disabling_signoff_unlocks_pending_objects(client):
    """Выключенный модуль согласования перестаёт ТРЕБОВАТЬ согласования — и
    перестаёт запирать. Иначе ``service signoff --off`` навсегда заморозил
    бы всё, что застигнуто в ``pending``: отзыв процесса сам стоит за
    ``require_service("signoff")``, то есть разблокировать было бы нечем."""
    budget = _pending_budget()
    ServiceStatus.objects.update_or_create(
        app_label="signoff", defaults={"enabled": False, "message": "off"})

    freed = patch_json(client, f"{BASE}/budgets/{budget.pk}",
                       {"period_year": 2035}, **auth(admin_token()))
    assert freed.status_code == 200, freed.content


def test_the_engine_can_still_move_the_agreement_it_locked(client):
    """Договор доходит до ``approved``, хотя в момент колбэка формально
    заперт: ``engine._finish`` зовёт ``on_approved`` ДО того, как снимет
    ``pending``. Guard ручного перевода включается флагом
    ``enforce_approval_lock`` только на HTTP-пути (``AgreementStatusView``);
    колбэк зовёт ``change_status`` без него — иначе движок заблокировал бы
    сам себя."""
    approver = make_user("finisher")
    agreement = _draft_agreement()
    route_for(Agreement.SIGNOFF_SUBJECT_TYPE, approver.pk)
    process = agreement.submit_for_approval()
    decide(process, approver, engine.APPROVE)

    agreement.refresh_from_db()
    assert agreement.status == AgreementStatus.APPROVED
    assert agreement.approval_state == ApprovalState.APPROVED


# ═══════════════════════════════════════════════════════════════════════
# Счёт: то же согласование, что у договора, с двумя отличиями
# ═══════════════════════════════════════════════════════════════════════
#
# Устроен как договор (те же колбэки on_started/approved/rejected/rework/
# cancelled, тот же возврат в ``draft`` на отказе), но счёт занимает бюджет
# только после одобрения, а скан обязателен уже на отправке, потому что счёт
# без договора и ЕСТЬ платёжный документ. Черновик для отправки заводится
# СРАЗУ со сканом (``file_id``) — иначе submit упрётся в гейт скана, который
# проверяется отдельным тестом.

def _draft_invoice(**over) -> Invoice:
    line = make_line()
    counterparty = make_counterparty()
    over.setdefault("file_id", "scan-invoice")
    over.setdefault("status", InvoiceStatus.DRAFT)
    return make_invoice(line=line, counterparty=counterparty, **over)


def test_submitting_an_invoice_moves_it_to_on_review(client):
    approver = make_user()
    invoice = _draft_invoice()
    route_for(Invoice.SIGNOFF_SUBJECT_TYPE, approver.pk)

    submitted = post_json(client, f"{BASE}/invoices/{invoice.pk}/submit",
                          {}, **auth(token()))
    assert submitted.status_code == 201, submitted.content

    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.ON_REVIEW
    assert invoice.approval_state == ApprovalState.PENDING


def test_approval_moves_the_invoice_to_approved(client):
    approver = make_user()
    invoice = _draft_invoice()
    route_for(Invoice.SIGNOFF_SUBJECT_TYPE, approver.pk)
    process = invoice.submit_for_approval()

    decide(process, approver, engine.APPROVE)

    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.APPROVED
    assert invoice.approval_state == ApprovalState.APPROVED


def test_invoice_approval_reduces_the_program_remaining_budget(client):
    approver = make_user()
    line = make_line(amount="500000.00")
    invoice = make_invoice(line=line, amount="200000.00", file_id="scan-invoice")
    route_for(Invoice.SIGNOFF_SUBJECT_TYPE, approver.pk)

    assert budget_calc.remaining_for(line) == 500000
    process = invoice.submit_for_approval()
    decide(process, approver, engine.APPROVE)

    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.APPROVED
    assert budget_calc.remaining_for(line) == 300000


def test_rejection_returns_the_invoice_to_draft(client):
    """Отклонённый счёт дорабатывают и отправляют снова — ``cancelled`` было
    бы «счёт не оплачиваем», а не «поправьте»."""
    approver = make_user()
    invoice = _draft_invoice()
    route_for(Invoice.SIGNOFF_SUBJECT_TYPE, approver.pk)
    process = invoice.submit_for_approval()

    decide(process, approver, engine.REJECT)

    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.DRAFT
    assert invoice.approval_state == ApprovalState.REJECTED


def test_cancelling_returns_the_invoice_to_draft(client):
    approver = make_user()
    initiator = make_user("initiator")
    invoice = _draft_invoice()
    route_for(Invoice.SIGNOFF_SUBJECT_TYPE, approver.pk)
    process = invoice.submit_for_approval(initiator_id=initiator.pk)

    engine.cancel(process_id=process.pk, actor_id=initiator.pk)

    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.DRAFT
    # Отзыв — не отказ: счёт снова черновик по обеим осям.
    assert invoice.approval_state == ApprovalState.DRAFT


def test_only_a_draft_invoice_is_submitted(client):
    approver = make_user()
    invoice = _draft_invoice(status=InvoiceStatus.PAID)
    route_for(Invoice.SIGNOFF_SUBJECT_TYPE, approver.pk)

    bad = post_json(client, f"{BASE}/invoices/{invoice.pk}/submit", {},
                    **auth(token()))
    assert bad.status_code == 409
    assert "черновик" in bad.json()["detail"]


def test_an_invoice_without_a_scan_is_not_submitted(client):
    """Отличие от договора: счёт без договора и ЕСТЬ тот документ, по которому
    платят — согласующему без скана нечего смотреть. Проверяется на отправке,
    адресным сообщением, а не отказом из середины транзакции движка."""
    approver = make_user()
    invoice = _draft_invoice(file_id=None)
    route_for(Invoice.SIGNOFF_SUBJECT_TYPE, approver.pk)

    bad = post_json(client, f"{BASE}/invoices/{invoice.pk}/submit", {},
                    **auth(token()))
    assert bad.status_code == 409
    assert "скан" in bad.json()["detail"]
    # Процесс не запустился — счёт остался нетронутым черновиком.
    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.DRAFT
    assert invoice.approval_state == ApprovalState.DRAFT


def test_a_submitted_invoice_is_locked_for_editing(client):
    """Пока идёт согласование, счёт править нельзя — ``assert_editable`` по
    ``approval_state=pending`` (та же ось, что запирает договор)."""
    approver = make_user()
    invoice = _draft_invoice()
    route_for(Invoice.SIGNOFF_SUBJECT_TYPE, approver.pk)
    invoice.submit_for_approval()

    locked = patch_json(client, f"{BASE}/invoices/{invoice.pk}",
                        {"name": "Правка на согласовании"}, **auth(admin_token()))
    assert locked.status_code == 409
    assert "согласовани" in locked.json()["detail"]


def test_the_invoice_process_card_shows_a_human_readable_subject(client):
    approver = make_user()
    invoice = _draft_invoice(name="Картриджи")
    route_for(Invoice.SIGNOFF_SUBJECT_TYPE, approver.pk)

    submitted = post_json(client, f"{BASE}/invoices/{invoice.pk}/submit",
                          {}, **auth(token())).json()
    assert "Картриджи" in submitted["subject_title"]
    assert submitted["subject_url"] == f"/contracts/invoices/{invoice.pk}"

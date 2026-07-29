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

from apps.contracts.models import Agreement, AgreementStatus, Budget, Counterparty
from apps.contracts.tests.helpers import (
    BASE,
    admin_token,
    auth,
    make_administrator,
    make_agreement,
    make_budget,
    make_counterparty,
    make_program,
    post_json,
    token,
)
from apps.core.models import ServiceStatus
from apps.signoff.models import (
    ApprovalRoute,
    ApprovalRouteStage,
    ApprovalRouteStageApprover,
    ApprovalState,
    ApprovalTask,
    ProcessState,
    Quorum,
    TaskState,
)
from apps.signoff.services import engine
from apps.users.models import User, UserStatus

pytestmark = pytest.mark.django_db


def make_user(username: str = "approver") -> User:
    return User.objects.create(username=username, email=f"{username}@htq.test",
                               password="x", status=UserStatus.ACTIVE)


def route_for(subject_type: str, *user_ids: int) -> ApprovalRoute:
    """Одноэтапный активный маршрут — минимум, включающий согласование."""
    route = ApprovalRoute.objects.create(subject_type=subject_type,
                                         name=f"Маршрут {subject_type}")
    stage = ApprovalRouteStage.objects.create(route=route, order=1,
                                              name="Единственный этап",
                                              quorum=Quorum.ALL)
    for user_id in user_ids:
        ApprovalRouteStageApprover.objects.create(stage=stage, user_id=user_id)
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

def test_all_three_models_are_registered_as_approvable(client):
    listed = client.get("/api/signoff/v1/subjects", **auth(token())).json()
    by_type = {row["subject_type"]: row for row in listed}

    assert by_type["contracts.budget"]["label"] == "Бюджетная строка"
    assert by_type["contracts.counterparty"]["label"] == "Контрагент"
    assert by_type["contracts.agreement"]["label"] == "Договор"


def test_the_process_card_shows_a_human_readable_subject(client):
    approver = make_user()
    budget = make_budget()
    route_for(Budget.SIGNOFF_SUBJECT_TYPE, approver.pk)

    submitted = post_json(client, f"{BASE}/budgets/{budget.pk}/submit", {},
                          **auth(token()))
    assert submitted.status_code == 201, submitted.content
    body = submitted.json()
    # describe() из approval_hooks: signoff сам не умеет назвать чужую строку.
    assert "Иванов И." in body["subject_title"]
    assert body["subject_url"] == f"/contracts/budgets/{budget.pk}"


# ═══════════════════════════════════════════════════════════════════════
# Подача заявки
# ═══════════════════════════════════════════════════════════════════════

def test_an_ordinary_employee_can_create_and_submit_a_budget(client):
    """Смысл всей связки: заявку подаёт сотрудник, решает согласование.
    Если бы завести бюджет мог только администратор, маршрут был бы не нужен."""
    approver = make_user()
    route_for(Budget.SIGNOFF_SUBJECT_TYPE, approver.pk)

    created = post_json(client, f"{BASE}/budgets", {
        "administrator_id": make_administrator().pk,
        "program_id": make_program().pk,
        "amount": "1000000.00", "period_year": 2030,
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
    budget = make_budget()
    forbidden = client.patch(f"{BASE}/budgets/{budget.pk}",
                             data='{"amount": "1.00"}',
                             content_type="application/json", **auth(token()))
    assert forbidden.status_code == 403


def test_submitting_without_a_route_is_409(client):
    budget = make_budget()
    bad = post_json(client, f"{BASE}/budgets/{budget.pk}/submit", {},
                    **auth(token()))
    assert bad.status_code == 409
    assert "маршрут" in bad.json()["detail"].lower()


def test_submitting_twice_is_409(client):
    approver = make_user()
    budget = make_budget()
    route_for(Budget.SIGNOFF_SUBJECT_TYPE, approver.pk)

    assert post_json(client, f"{BASE}/budgets/{budget.pk}/submit", {},
                     **auth(token())).status_code == 201
    clash = post_json(client, f"{BASE}/budgets/{budget.pk}/submit", {},
                      **auth(token()))
    assert clash.status_code == 409


def test_a_closed_budget_is_not_submitted(client):
    approver = make_user()
    budget = make_budget()
    budget.status = "closed"
    budget.save(update_fields=["status"])
    route_for(Budget.SIGNOFF_SUBJECT_TYPE, approver.pk)

    bad = post_json(client, f"{BASE}/budgets/{budget.pk}/submit", {},
                    **auth(token()))
    assert bad.status_code == 409
    assert "Закрытая" in bad.json()["detail"]


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
    budget = make_budget()
    counterparty = make_counterparty()
    route_for(Budget.SIGNOFF_SUBJECT_TYPE, approver.pk)

    bad = post_json(client, f"{BASE}/agreements", {
        "number": "Д-100", "name": "Поставка", "budget_id": budget.pk,
        "counterparty_id": counterparty.pk, "amount": "100000.00",
        "payment_type": "postpayment", "currency": "KZT",
    }, **auth(admin_token()))
    assert bad.status_code == 409
    assert "не согласована" in bad.json()["detail"]


def test_an_approved_budget_funds_an_agreement(client):
    budget = make_budget()
    counterparty = make_counterparty()
    approve(budget)
    assert budget.approval_state == ApprovalState.APPROVED

    created = post_json(client, f"{BASE}/agreements", {
        "number": "Д-101", "name": "Поставка", "budget_id": budget.pk,
        "counterparty_id": counterparty.pk, "amount": "100000.00",
        "payment_type": "postpayment", "currency": "KZT",
    }, **auth(admin_token()))
    assert created.status_code == 201, created.content


def test_an_unapproved_counterparty_is_not_contractable(client):
    approver = make_user()
    budget = make_budget()
    counterparty = make_counterparty()
    route_for(Counterparty.SIGNOFF_SUBJECT_TYPE, approver.pk)

    bad = post_json(client, f"{BASE}/agreements", {
        "number": "Д-102", "name": "Поставка", "budget_id": budget.pk,
        "counterparty_id": counterparty.pk, "amount": "100000.00",
        "payment_type": "postpayment", "currency": "KZT",
    }, **auth(admin_token()))
    assert bad.status_code == 409
    assert "не согласован" in bad.json()["detail"]


def test_without_a_route_the_gate_does_not_apply(client):
    """Установка, где согласование не настроено, продолжает работать как
    раньше: все существующие записи — draft, и безусловная проверка
    запретила бы вообще всё."""
    budget = make_budget()
    counterparty = make_counterparty()
    assert budget.approval_state == ApprovalState.DRAFT

    created = post_json(client, f"{BASE}/agreements", {
        "number": "Д-103", "name": "Поставка", "budget_id": budget.pk,
        "counterparty_id": counterparty.pk, "amount": "100000.00",
        "payment_type": "postpayment", "currency": "KZT",
    }, **auth(admin_token()))
    assert created.status_code == 201, created.content


def test_the_gate_does_not_lock_edits_of_an_existing_agreement(client):
    """Согласование бюджета, отозванное задним числом, не должно запирать
    правку названия у давно заключённого договора."""
    budget = make_budget()
    counterparty = make_counterparty()
    agreement = make_agreement(budget=budget, counterparty=counterparty)
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
    budget = make_budget()
    counterparty = make_counterparty()
    route_for(Budget.SIGNOFF_SUBJECT_TYPE, approver.pk)
    ServiceStatus.objects.update_or_create(
        app_label="signoff", defaults={"enabled": False, "message": "off"})

    created = post_json(client, f"{BASE}/agreements", {
        "number": "Д-104", "name": "Поставка", "budget_id": budget.pk,
        "counterparty_id": counterparty.pk, "amount": "100000.00",
        "payment_type": "postpayment", "currency": "KZT",
    }, **auth(admin_token()))
    assert created.status_code == 201, created.content

    # Сама отправка на согласование при этом честно отдаёт 503 — общий
    # контракт платформы для выключенного сервиса.
    off = post_json(client, f"{BASE}/budgets/{budget.pk}/submit", {},
                    **auth(token()))
    assert off.status_code == 503
    assert off.json()["code"] == "service_disabled"


def test_the_budget_list_can_be_filtered_by_approval_state(client):
    approved = make_budget(period_year=2031)
    make_budget(program=make_program(expense_item="Услуги"), period_year=2032)
    approve(approved)

    rows = client.get(f"{BASE}/budgets?approval_state=approved",
                      **auth(token())).json()
    assert [row["id"] for row in rows] == [approved.pk]


# ═══════════════════════════════════════════════════════════════════════
# Договор: результат согласования двигает его собственный статус
# ═══════════════════════════════════════════════════════════════════════

def _draft_agreement() -> Agreement:
    budget = make_budget()
    counterparty = make_counterparty()
    return make_agreement(budget=budget, counterparty=counterparty,
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
    budget = make_budget()
    agreement = make_agreement(budget=budget, status=AgreementStatus.SIGNED)
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
    budget = make_budget(amount="500000.00")
    counterparty = make_counterparty()
    make_agreement(budget=budget, counterparty=counterparty, number="Д-200",
                   amount="400000.00", status=AgreementStatus.SIGNED)
    overflow = make_agreement(budget=budget, counterparty=counterparty,
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

"""Контрактные тесты ``/api/contracts/v1/agreements/*`` и бюджетов.

Проверяют сквозной сценарий из спецификации: завели бюджет → зарегистрировали
договор → остаток бюджета уменьшился на сумму договора.
"""

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.contracts.models import Agreement, AgreementStatus, BudgetStatus, CounterpartyStatus

from .helpers import (
    BASE,
    admin_token,
    auth,
    make_agreement,
    make_line,
    make_counterparty,
    post_json,
    patch_json,
    token,
)


def _agreement_body(line, counterparty, **over) -> dict:
    body = {
        "number": "Д-100",
        "name": "Поставка ноутбуков",
        "budget_line_id": line.pk,
        "counterparty_id": counterparty.pk,
        "amount": "400000.00",
        "payment_type": "postpayment",
        "currency": line.budget.currency,
        "status": AgreementStatus.SIGNED.value,
    }
    body.update(over)
    return body


# ── Сквозной сценарий ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_agreement_reduces_budget_remaining_end_to_end():
    line = make_line(amount="5000000.00")
    counterparty = make_counterparty(country=line.budget.administrator.country)
    client = Client()

    resp = post_json(client, f"{BASE}/agreements",
                     _agreement_body(line, counterparty),
                     **auth(admin_token()))
    assert resp.status_code == 201, resp.content
    created = resp.json()
    assert created["administrator_name"] == line.budget.administrator.display_name
    assert created["program_name"] == line.program.display_name
    assert created["expense_item"] == line.program.expense_item

    budget_resp = client.get(f"{BASE}/budgets/{line.pk}", **auth(token()))
    assert budget_resp.status_code == 200
    body = budget_resp.json()
    assert Decimal(body["committed"]) == Decimal("400000.00")
    assert Decimal(body["remaining"]) == Decimal("4600000.00")


@pytest.mark.django_db
def test_created_agreement_records_the_author():
    line = make_line()
    counterparty = make_counterparty(country=line.budget.administrator.country)
    resp = post_json(Client(), f"{BASE}/agreements",
                     _agreement_body(line, counterparty),
                     **auth(admin_token()))
    assert resp.json()["created_by"] == 9


# ── Отказы ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_agreement_over_budget_is_rejected_with_409():
    line = make_line(amount="1000000.00")
    counterparty = make_counterparty(country=line.budget.administrator.country)
    make_agreement(line=line, counterparty=counterparty, number="Д-001",
                   amount="800000.00", status=AgreementStatus.SIGNED)

    resp = post_json(Client(), f"{BASE}/agreements",
                     _agreement_body(line, counterparty, number="Д-002",
                                     amount="300000.00"),
                     **auth(admin_token()))
    assert resp.status_code == 409, resp.content
    assert "остаток" in resp.json()["detail"].lower()
    assert Agreement.objects.filter(number="Д-002").count() == 0


@pytest.mark.django_db
def test_draft_over_budget_is_allowed():
    """Черновик лимит не занимает — значит и проверять его не должен."""
    line = make_line(amount="100000.00")
    counterparty = make_counterparty(country=line.budget.administrator.country)

    resp = post_json(Client(), f"{BASE}/agreements",
                     _agreement_body(line, counterparty, amount="900000.00",
                                     status=AgreementStatus.DRAFT.value),
                     **auth(admin_token()))
    assert resp.status_code == 201, resp.content


@pytest.mark.django_db
def test_currency_mismatch_is_rejected():
    line = make_line(amount="5000000.00", currency="KZT")
    counterparty = make_counterparty(country=line.budget.administrator.country)

    resp = post_json(Client(), f"{BASE}/agreements",
                     _agreement_body(line, counterparty, currency="USD"),
                     **auth(admin_token()))
    assert resp.status_code == 409
    assert "алют" in resp.json()["detail"]  # «валюта» / «Валюта»


@pytest.mark.django_db
def test_closed_budget_rejects_new_agreements():
    line = make_line(amount="5000000.00")
    budget = line.budget
    budget.status = BudgetStatus.CLOSED
    budget.save(update_fields=["status"])
    counterparty = make_counterparty(country=line.budget.administrator.country)

    resp = post_json(Client(), f"{BASE}/agreements",
                     _agreement_body(line, counterparty),
                     **auth(admin_token()))
    assert resp.status_code == 409


@pytest.mark.django_db
def test_blocked_counterparty_rejects_new_agreements():
    line = make_line(amount="5000000.00")
    counterparty = make_counterparty(country=line.budget.administrator.country,
                                     status=CounterpartyStatus.BLOCKED)

    resp = post_json(Client(), f"{BASE}/agreements",
                     _agreement_body(line, counterparty),
                     **auth(admin_token()))
    assert resp.status_code == 409


@pytest.mark.django_db
def test_duplicate_number_is_409_not_500():
    line = make_line()
    counterparty = make_counterparty(country=line.budget.administrator.country)
    body = _agreement_body(line, counterparty, amount="1000.00")
    client = Client()

    assert post_json(client, f"{BASE}/agreements", body, **auth(admin_token())).status_code == 201
    second = post_json(client, f"{BASE}/agreements", body, **auth(admin_token()))
    assert second.status_code == 409, second.content


# ── Смена статуса ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_status_transition_follows_the_allowed_table():
    line = make_line()
    agreement = make_agreement(line=line, amount="1000.00",
                               status=AgreementStatus.DRAFT)
    client = Client()

    ok = post_json(client, f"{BASE}/agreements/{agreement.pk}/status",
                   {"status": AgreementStatus.ON_REVIEW.value}, **auth(admin_token()))
    assert ok.status_code == 200
    assert ok.json()["status"] == AgreementStatus.ON_REVIEW.value

    # on_review → executed нет в таблице переходов.
    bad = post_json(client, f"{BASE}/agreements/{agreement.pk}/status",
                    {"status": AgreementStatus.EXECUTED.value}, **auth(admin_token()))
    assert bad.status_code == 409, bad.content
    agreement.refresh_from_db()
    assert agreement.status == AgreementStatus.ON_REVIEW


@pytest.mark.django_db
def test_moving_out_of_draft_checks_the_limit():
    """Черновик бюджет не занимал; переход в занимающий статус — занимает,
    и именно здесь проверяется лимит."""
    line = make_line(amount="500000.00")
    counterparty = make_counterparty(country=line.budget.administrator.country)
    make_agreement(line=line, counterparty=counterparty, number="Д-001",
                   amount="400000.00", status=AgreementStatus.SIGNED)
    draft = make_agreement(line=line, counterparty=counterparty, number="Д-002",
                           amount="300000.00", status=AgreementStatus.DRAFT)

    resp = post_json(Client(), f"{BASE}/agreements/{draft.pk}/status",
                     {"status": AgreementStatus.ON_REVIEW.value}, **auth(admin_token()))
    assert resp.status_code == 409, resp.content
    draft.refresh_from_db()
    assert draft.status == AgreementStatus.DRAFT


@pytest.mark.django_db
def test_patch_cannot_smuggle_a_status_change():
    """Статус меняется только через /status, где проверяется переход. PATCH
    его игнорирует — иначе таблица переходов обходилась бы одним полем."""
    line = make_line()
    agreement = make_agreement(line=line, amount="1000.00",
                               status=AgreementStatus.DRAFT)

    resp = patch_json(Client(), f"{BASE}/agreements/{agreement.pk}",
                      {"status": AgreementStatus.EXECUTED.value, "name": "Новое имя"},
                      **auth(admin_token()))
    assert resp.status_code == 200
    agreement.refresh_from_db()
    assert agreement.status == AgreementStatus.DRAFT
    assert agreement.name == "Новое имя"


# ── Редактирование и удаление ────────────────────────────────────────────

@pytest.mark.django_db
def test_agreement_can_grow_within_its_own_budget():
    line = make_line(amount="1000000.00")
    agreement = make_agreement(line=line, amount="900000.00",
                               status=AgreementStatus.SIGNED)

    resp = patch_json(Client(), f"{BASE}/agreements/{agreement.pk}",
                      {"amount": "950000.00"}, **auth(admin_token()))
    assert resp.status_code == 200, resp.content
    assert Decimal(resp.json()["amount"]) == Decimal("950000.00")


@pytest.mark.django_db
def test_editing_survives_a_counterparty_blocked_after_the_fact():
    """Контрагента заблокировали уже после подписания — договор всё равно
    должен оставаться редактируемым. Иначе опечатку в названии стало бы
    нечем исправить именно тогда, когда правки и нужны."""
    line = make_line()
    agreement = make_agreement(line=line, amount="1000.00",
                               status=AgreementStatus.SIGNED)
    counterparty = agreement.counterparty
    counterparty.status = CounterpartyStatus.BLOCKED
    counterparty.save(update_fields=["status"])

    resp = patch_json(Client(), f"{BASE}/agreements/{agreement.pk}",
                      {"name": "Исправленное название"}, **auth(admin_token()))
    assert resp.status_code == 200, resp.content

    # Но ПЕРЕВЕСТИ договор на заблокированного контрагента по-прежнему нельзя.
    other = make_counterparty(country=line.budget.administrator.country,
                              bin_iin="999999999999", name="ТОО «Бета»",
                              status=CounterpartyStatus.BLOCKED)
    moved = patch_json(Client(), f"{BASE}/agreements/{agreement.pk}",
                       {"counterparty_id": other.pk}, **auth(admin_token()))
    assert moved.status_code == 409, moved.content


@pytest.mark.django_db
def test_only_drafts_can_be_deleted():
    line = make_line()
    signed = make_agreement(line=line, number="Д-001", amount="1000.00",
                            status=AgreementStatus.SIGNED)
    client = Client()

    assert client.delete(f"{BASE}/agreements/{signed.pk}",
                         **auth(admin_token())).status_code == 409

    draft = make_agreement(line=line, counterparty=signed.counterparty,
                           number="Д-002", amount="1000.00",
                           status=AgreementStatus.DRAFT)
    assert client.delete(f"{BASE}/agreements/{draft.pk}",
                         **auth(admin_token())).status_code == 204


# ── Права ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_reading_needs_a_token_creating_does_not_need_an_admin():
    """Заводить договор может любой сотрудник — контролем служит
    согласование (``apps.signoff``), а не админский флаг. Правка и удаление
    при этом остались административными (проверяется ниже)."""
    line = make_line()
    counterparty = make_counterparty(country=line.budget.administrator.country)
    client = Client()

    assert client.get(f"{BASE}/agreements").status_code == 401
    assert client.get(f"{BASE}/agreements", **auth(token())).status_code == 200

    resp = post_json(client, f"{BASE}/agreements",
                     _agreement_body(line, counterparty), **auth(token()))
    assert resp.status_code == 201, resp.content


def _upload(client, agreement_id: int, tok: str):
    return client.post(
        f"{BASE}/agreements/{agreement_id}/file",
        {"file": SimpleUploadedFile("scan.pdf", b"%PDF-1.4", "application/pdf")},
        **auth(tok),
    )


@pytest.fixture
def stub_storage(monkeypatch):
    """Хранилище подменяется: проверяются права и запись ``file_id``, а не
    работоспособность MinIO — за неё отвечают тесты media_files."""
    monkeypatch.setattr(
        "apps.contracts.services.agreement_service.media.store_file",
        lambda **kw: {"id": "stored-1"},
    )


@pytest.mark.django_db
def test_the_author_attaches_a_scan_to_their_own_draft(stub_storage):
    """Право завести договор без права приложить к нему скан — половина
    права: на согласование уходит договор с файлом."""
    line = make_line()
    agreement = make_agreement(line=line, status=AgreementStatus.DRAFT,
                               created_by=7)

    resp = _upload(Client(), agreement.pk, token())
    assert resp.status_code == 200, resp.content
    assert resp.json()["file_id"] == "stored-1"


@pytest.mark.django_db
def test_a_stranger_cannot_attach_a_scan(stub_storage):
    line = make_line()
    agreement = make_agreement(line=line, status=AgreementStatus.DRAFT,
                               created_by=999)

    resp = _upload(Client(), agreement.pk, token())
    assert resp.status_code == 403
    assert "автор договора или администратор" in resp.json()["detail"]


@pytest.mark.django_db
def test_the_author_cannot_replace_the_scan_once_it_left_draft(stub_storage):
    """Повторная загрузка ЗАМЕЩАЕТ ссылку, поэтому после отправки на
    согласование подмена скана означала бы, что согласующие одобрили не тот
    документ, который в итоге лежит в карточке."""
    line = make_line()
    agreement = make_agreement(line=line, status=AgreementStatus.ON_REVIEW,
                               created_by=7)

    resp = _upload(Client(), agreement.pk, token())
    assert resp.status_code == 403
    assert "только администратор" in resp.json()["detail"]


@pytest.mark.django_db
def test_an_admin_attaches_a_scan_to_anyones_agreement(stub_storage):
    line = make_line()
    agreement = make_agreement(line=line, status=AgreementStatus.SIGNED,
                               created_by=999)

    assert _upload(Client(), agreement.pk, admin_token()).status_code == 200


@pytest.mark.django_db
def test_editing_and_deleting_an_agreement_still_need_an_admin():
    line = make_line()
    agreement = make_agreement(line=line, status=AgreementStatus.DRAFT)
    client = Client()

    edited = patch_json(client, f"{BASE}/agreements/{agreement.pk}",
                        {"name": "Другое"}, **auth(token()))
    assert edited.status_code == 403
    assert client.delete(f"{BASE}/agreements/{agreement.pk}",
                         **auth(token())).status_code == 403


@pytest.mark.django_db
def test_unsupported_method_returns_the_json_405_envelope():
    """У CBV 405 отдаёт ``View.dispatch`` → ``ApiView.http_method_not_allowed``,
    а не рукописный диспетчер, как в функциональных аппках. Дефолт Django
    здесь — HTML-тело, поэтому переопределение проверяется явно."""
    line = make_line()
    agreement = make_agreement(line=line, amount="1000.00",
                               status=AgreementStatus.DRAFT)
    client = Client()

    resp = client.put(f"{BASE}/agreements/{agreement.pk}", **auth(admin_token()))
    assert resp.status_code == 405
    assert resp.json() == {"detail": "Method Not Allowed"}

    # OPTIONS убран из http_method_names: иначе Django ответил бы на него
    # сам, в обход авторизации.
    assert client.options(f"{BASE}/agreements").status_code == 405


@pytest.mark.django_db
def test_both_slash_spellings_resolve():
    """APPEND_SLASH=False — Django сам не редиректит, оба написания
    зарегистрированы явно (правило №4)."""
    client = Client()
    for path in (f"{BASE}/agreements", f"{BASE}/agreements/",
                 f"{BASE}/budgets", f"{BASE}/budgets/",
                 f"{BASE}/counterparties", f"{BASE}/counterparties/"):
        assert client.get(path, **auth(token())).status_code == 200, path

"""Заморозка раздела «Договоры» после переноса в БЗО (A6.2, D-S6-4).

Review Focus 1 плана этапа 6 A: заморозка не ломает чтение и не пропускает
запись.

- ``GET`` списков и карточек замороженной компании — 200;
- любой ``POST``/``PATCH``/``PUT``/``DELETE`` под ``/api/contracts/`` — 403
  ``contracts_frozen`` с текстом: по одному запросу каждого метода на три
  разные ручки и обход всего ``urls.py``;
- соседняя незамороженная компания пишет как раньше;
- ``contracts_freeze`` идемпотентна, ``--undo`` возвращает запись;
- согласования: заморозку не пускают идущие процессы (``--revoke-pending``
  отзывает), запуск и возврат на доработку в замороженной компании — 403;
- до ``migrate_companies`` (нет таблицы) раздел считается незамороженным;
- карточки договора, счёта и контрагента несут ``migrated_to``.

Компании — две настоящие схемы (``two_company_schemas``): признак лежит в
схеме компании, и на ``company_row`` обе «компании» делили бы одну
таблицу ``public``.
"""

from __future__ import annotations

import json
import logging
import re

import pytest
from django.core.management import CommandError, call_command
from django.test import Client

from apps.contracts import urls as contracts_urls
from apps.contracts.services import freeze
from htqweb.tenancy.db import use_company

from .helpers import (
    BASE,
    admin_token,
    make_agreement,
    make_counterparty,
    make_invoice,
    make_line,
)

FROZEN_TEXT = "Раздел перенесён в «Закупки и оплаты». Данные доступны только для чтения."
WRITE_METHODS = ("post", "put", "patch", "delete")


def _headers(slug: str) -> dict:
    return {"HTTP_X_HTQ_COMPANY": slug,
            "HTTP_AUTHORIZATION": f"Bearer {admin_token(company=slug)}"}


def _send(client: Client, method: str, path: str, slug: str, body: dict | None = None):
    return getattr(client, method)(path, data=json.dumps(body or {}),
                                   content_type="application/json", **_headers(slug))


def _assert_frozen(resp) -> None:
    assert resp.status_code == 403, resp.content
    assert resp.json() == {"detail": FROZEN_TEXT, "code": "contracts_frozen"}


@pytest.fixture
def frozen(two_company_schemas):
    """Компания A заморожена командой, B — нет; в A — договор, счёт, контрагент."""
    alpha, beta = two_company_schemas
    with use_company(alpha):
        line = make_line()
        cp = make_counterparty()
        agreement = make_agreement(line=line, counterparty=cp)
        invoice = make_invoice(line=line, counterparty=cp)
    call_command("contracts_freeze", company=alpha, comment="перенос сверен")
    return {"alpha": alpha, "beta": beta, "agreement": agreement.pk,
            "invoice": invoice.pk, "counterparty": cp.pk}


# ── Чтение остаётся ────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_reads_stay_open(frozen):
    client, slug = Client(), frozen["alpha"]
    for path in ("/countries", "/budgets", "/counterparties", "/agreements", "/invoices",
                 f"/agreements/{frozen['agreement']}", f"/invoices/{frozen['invoice']}",
                 f"/counterparties/{frozen['counterparty']}", "/enums"):
        resp = client.get(f"{BASE}{path}", **_headers(slug))
        assert resp.status_code == 200, (path, resp.content)


@pytest.mark.django_db(transaction=True)
def test_freeze_endpoint_reports_state(frozen):
    client = Client()
    body = client.get(f"{BASE}/freeze", **_headers(frozen["alpha"])).json()
    assert body["frozen"] is True
    assert body["frozen_at"]
    assert body["comment"] == "перенос сверен"

    body = client.get(f"{BASE}/freeze", **_headers(frozen["beta"])).json()
    assert body == {"frozen": False, "frozen_at": None, "comment": ""}


# ── Запись закрыта ─────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("method", WRITE_METHODS)
def test_every_write_method_on_three_handles_is_403(frozen, method):
    client, slug = Client(), frozen["alpha"]
    for path in ("/countries", f"/agreements/{frozen['agreement']}",
                 f"/invoices/{frozen['invoice']}/submit"):
        _assert_frozen(_send(client, method, f"{BASE}{path}", slug, {"name": "X"}))


@pytest.mark.django_db(transaction=True)
def test_write_is_403_even_without_token(frozen):
    """До аутентификации, как запись в архив компании: признак — свойство
    компании, а не прав пришедшего."""
    resp = Client().post(f"{BASE}/countries", data="{}", content_type="application/json",
                         HTTP_X_HTQ_COMPANY=frozen["alpha"])
    _assert_frozen(resp)


def _concrete_paths() -> list[str]:
    paths = []
    for pattern in contracts_urls.urlpatterns:
        route = re.sub(r"<int:[a-z_]+>", "1", str(pattern.pattern))
        assert "<" not in route, route
        paths.append(f"{BASE}/{route}")
    return paths


@pytest.mark.django_db(transaction=True)
def test_walk_urls_every_write_is_403(frozen):
    client, slug = Client(), frozen["alpha"]
    paths = _concrete_paths()
    assert len(paths) > 100   # обход действительно идёт по всему urls.py
    for path in paths:
        for method in WRITE_METHODS:
            resp = _send(client, method, path, slug)
            assert resp.status_code == 403, (method, path, resp.content)
            assert resp.json()["code"] == "contracts_frozen", (method, path)


@pytest.mark.django_db(transaction=True)
def test_neighbour_company_writes_as_before(frozen):
    resp = _send(Client(), "post", f"{BASE}/countries", frozen["beta"],
                 {"name": "Узбекистан", "iso_code": "UZ"})
    assert resp.status_code == 201, resp.content


@pytest.mark.django_db(transaction=True)
def test_frozen_company_reads_freeze_flag_but_not_neighbours(frozen):
    with use_company(frozen["alpha"]):
        assert freeze.is_frozen()
    with use_company(frozen["beta"]):
        assert not freeze.is_frozen()


# ── Команда ────────────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_freeze_is_idempotent(frozen):
    slug = frozen["alpha"]
    with use_company(slug):
        first = freeze.info()["frozen_at"]
    call_command("contracts_freeze", company=slug, comment="второй прогон")
    with use_company(slug):
        again = freeze.info()
    assert again["frozen_at"] == first          # дата первой заморозки не сдвинулась
    assert again["comment"] == "перенос сверен"


@pytest.mark.django_db(transaction=True)
def test_undo_reopens_writes(frozen):
    slug = frozen["alpha"]
    call_command("contracts_freeze", company=slug, undo=True)
    resp = _send(Client(), "post", f"{BASE}/countries", slug,
                 {"name": "Кыргызстан", "iso_code": "KG"})
    assert resp.status_code == 201, resp.content
    # Повторный --undo ничего не ломает.
    call_command("contracts_freeze", company=slug, undo=True)
    with use_company(slug):
        assert not freeze.is_frozen()


@pytest.mark.django_db(transaction=True)
def test_unknown_company_is_refused(two_company_schemas):
    with pytest.raises(CommandError):
        call_command("contracts_freeze", company="no-such-company")


# ── Согласования (signoff мимо префикса /api/contracts/) ────────────────

def _start_agreement_process(slug: str, agreement_id: int) -> int:
    """Запускает согласование договора; возвращает id согласующего."""
    from apps.contracts.models import Agreement
    from apps.signoff import interface as signoff

    from .test_approval_wiring import make_user

    with use_company(slug):
        approver = make_user("freeze-approver")
        signoff.configure_route(subject_type=Agreement.SIGNOFF_SUBJECT_TYPE, name="Договор",
                                stages=[{"order": 1, "name": "ФД", "quorum": "any",
                                         "approver_kind": "users", "user_ids": [approver.id]}])
        signoff.start_process(subject_type=Agreement.SIGNOFF_SUBJECT_TYPE,
                              subject_id=agreement_id, initiator_id=5)
    return approver.id


@pytest.fixture
def unfrozen_with_process(two_company_schemas):
    alpha, beta = two_company_schemas
    with use_company(alpha):
        agreement = make_agreement(line=make_line(), counterparty=make_counterparty(),
                                   status="draft")
    _start_agreement_process(alpha, agreement.pk)
    return {"alpha": alpha, "beta": beta, "agreement": agreement.pk}


@pytest.mark.django_db(transaction=True)
def test_freeze_refuses_while_approvals_run(unfrozen_with_process, capsys):
    slug = unfrozen_with_process["alpha"]
    with pytest.raises(CommandError) as err:
        call_command("contracts_freeze", company=slug)
    assert f"contracts.agreement #{unfrozen_with_process['agreement']}" in str(err.value)
    with use_company(slug):
        assert not freeze.is_frozen()      # откат: раздел остался открытым


@pytest.mark.django_db(transaction=True)
def test_revoke_pending_cancels_and_freezes(unfrozen_with_process):
    from apps.contracts.models import Agreement
    from apps.signoff import interface as signoff

    slug, agreement_id = unfrozen_with_process["alpha"], unfrozen_with_process["agreement"]
    call_command("contracts_freeze", company=slug, revoke_pending=True)
    with use_company(slug):
        assert freeze.is_frozen()
        assert Agreement.objects.get(pk=agreement_id).status == "draft"
        assert signoff.get_process_for(Agreement.SIGNOFF_SUBJECT_TYPE,
                                       agreement_id)["state"] == "cancelled"


@pytest.mark.django_db(transaction=True)
def test_start_process_is_403_in_frozen_company(frozen):
    from apps.contracts.models import Agreement
    from apps.signoff import interface as signoff

    from .test_approval_wiring import make_user

    slug = frozen["alpha"]
    with use_company(slug):
        approver = make_user("freeze-start-approver")
        signoff.configure_route(subject_type=Agreement.SIGNOFF_SUBJECT_TYPE, name="Договор",
                                stages=[{"order": 1, "name": "ФД", "quorum": "any",
                                         "approver_kind": "users", "user_ids": [approver.id]}])
        with pytest.raises(freeze.ContractsFrozen) as err:
            signoff.start_process(subject_type=Agreement.SIGNOFF_SUBJECT_TYPE,
                                  subject_id=frozen["agreement"], initiator_id=5)
        assert err.value.status == 403 and err.value.code == "contracts_frozen"
        # Процесс не создан: транзакция движка откатилась.
        assert signoff.get_process_for(Agreement.SIGNOFF_SUBJECT_TYPE,
                                       frozen["agreement"]) is None


@pytest.mark.django_db(transaction=True)
def test_rework_of_closed_document_is_403_in_frozen_company(two_company_schemas):
    """Возврат согласованного документа на доработку тянул бы его из архива."""
    from apps.contracts.models import Agreement
    from apps.signoff import interface as signoff

    alpha = two_company_schemas[0]
    with use_company(alpha):
        agreement = make_agreement(line=make_line(), counterparty=make_counterparty(),
                                   status="draft")
    approver_id = _start_agreement_process(alpha, agreement.pk)
    with use_company(alpha):
        (item,) = signoff.pending_for_user(approver_id)
        signoff.decide_many(actor_id=approver_id,
                            items=[{"task_id": item["task_id"], "decision": "approve"}])
        process = signoff.get_process_for(Agreement.SIGNOFF_SUBJECT_TYPE, agreement.pk)
        assert process["state"] == "approved"
    call_command("contracts_freeze", company=alpha)
    with use_company(alpha):
        with pytest.raises(freeze.ContractsFrozen):
            signoff.rework_process(process_id=process["id"], actor_id=1)


# ── Таблицы заморозки ещё нет (код выкачен, migrate_companies не прогнан) ──

@pytest.mark.django_db(transaction=True)
def test_missing_table_means_not_frozen_and_keeps_the_transaction(two_company_schemas,
                                                                  settings, monkeypatch):
    """Запрос признака настоящий: он обращается к несуществующей таблице и
    получает от Postgres ``UndefinedTable`` — без точки сохранения транзакция
    была бы отравлена и следующий запрос упал бы."""
    from types import SimpleNamespace

    from django.db import connection, transaction

    class _MissingTable:
        def exists(self):
            with connection.cursor() as cur:
                cur.execute("SELECT 1 FROM contracts_freezestate_no_such_table")

    alpha = two_company_schemas[0]
    settings.FALLBACK_MODE = "strict"      # expected=True strict не роняет
    monkeypatch.setattr(freeze.FreezeState, "objects",
                        SimpleNamespace(filter=lambda *a, **k: _MissingTable()))
    with use_company(alpha):
        with transaction.atomic():
            assert freeze.is_frozen() is False
            # транзакция не отравлена: следующий запрос проходит
            assert make_counterparty().pk
    resp = _send(Client(), "post", f"{BASE}/countries", alpha,
                 {"name": "Армения", "iso_code": "AM"})
    assert resp.status_code == 201, resp.content


@pytest.mark.django_db(transaction=True)
def test_command_without_freeze_table_says_run_migrate_companies(two_company_schemas,
                                                                monkeypatch):
    """M-4 итогового ревью: до migrate_companies команда отвечает понятным
    CommandError, а не трассировкой ProgrammingError.

    Таблицу не переименовываем: в тестовой БД такая же лежит в ``public``, и
    ``search_path`` нашёл бы её там. Запрос настоящий — к несуществующей
    таблице, Postgres отвечает ``UndefinedTable``, как на схеме без миграции."""
    from django.core.management.base import CommandError
    from django.db import connection

    def missing_table(*args, **kwargs):
        with connection.cursor() as cur:
            cur.execute("SELECT 1 FROM contracts_freezestate_no_such_table")

    monkeypatch.setattr(freeze, "freeze", missing_table)
    monkeypatch.setattr(freeze, "unfreeze", missing_table)
    alpha = two_company_schemas[0]
    for kwargs in ({}, {"undo": True}):
        with pytest.raises(CommandError, match="migrate_companies"):
            call_command("contracts_freeze", company=alpha, **kwargs)


# ── «Перенесён в …» ────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
def test_cards_carry_migrated_to(frozen, monkeypatch):
    """Карточка показывает документ того же рода; техническая заявка
    переноса (``bpp.purchase_request``) в подпись не попадает."""
    calls = []

    def fake(source_type, source_ids):
        calls.append(source_type)
        key = str(list(source_ids)[0])
        target = {"contracts.agreement": ("bpp.agreement", "ДГ-2026-000001"),
                  "contracts.invoice": ("bpp.invoice", "СЧ-2026-000001"),
                  "contracts.counterparty": ("bpp.counterparty", None)}[source_type]
        return {key: [
            {"target_type": "bpp.purchase_request", "target_id": "r-1", "number": "ЗЗ-1"},
            {"target_type": target[0], "target_id": "t-1", "number": target[1]},
        ]}

    monkeypatch.setattr("apps.bpp.interface.migrated_targets", fake)
    client, slug = Client(), frozen["alpha"]
    agreement = client.get(f"{BASE}/agreements/{frozen['agreement']}", **_headers(slug)).json()
    invoice = client.get(f"{BASE}/invoices/{frozen['invoice']}", **_headers(slug)).json()
    cp = client.get(f"{BASE}/counterparties/{frozen['counterparty']}", **_headers(slug)).json()

    assert agreement["migrated_to"] == [
        {"target_type": "bpp.agreement", "target_id": "t-1", "number": "ДГ-2026-000001"}]
    assert invoice["migrated_to"] == [
        {"target_type": "bpp.invoice", "target_id": "t-1", "number": "СЧ-2026-000001"}]
    assert cp["migrated_to"] == [
        {"target_type": "bpp.counterparty", "target_id": "t-1", "number": None}]
    # Карточки договора и счёта спрашивают по одному разу; контрагента —
    # и своя карточка, и проверка связи с партнёром задач на карточке договора.
    assert calls.count("contracts.agreement") == 1
    assert calls.count("contracts.invoice") == 1
    assert "contracts.counterparty" in calls

    # Списки соседа не спрашивают — поле пустое.
    rows = client.get(f"{BASE}/agreements", **_headers(slug)).json()
    assert all(row["migrated_to"] == [] for row in rows)


@pytest.mark.django_db(transaction=True)
def test_migrated_to_reads_real_migration_links(frozen):
    """Без подмены: связь переноса в схеме компании → подпись на карточке."""
    from apps.bpp.models import MigrationLink

    slug = frozen["alpha"]
    with use_company(slug):
        MigrationLink.objects.create(source_type="contracts.counterparty",
                                     source_id=str(frozen["counterparty"]),
                                     target_type="bpp.counterparty", target_id="cp-uuid")
    body = Client().get(f"{BASE}/counterparties/{frozen['counterparty']}",
                        **_headers(slug)).json()
    assert body["migrated_to"] == [
        {"target_type": "bpp.counterparty", "target_id": "cp-uuid", "number": None}]
    # Неперенесённый договор — пусто.
    body = Client().get(f"{BASE}/agreements/{frozen['agreement']}", **_headers(slug)).json()
    assert body["migrated_to"] == []


@pytest.mark.django_db(transaction=True)
def test_migrated_to_empty_when_bpp_disabled(frozen, monkeypatch):
    def boom(*args, **kwargs):  # pragma: no cover — звать нельзя
        raise AssertionError("bpp выключен — его интерфейс не спрашивается")

    monkeypatch.setattr("apps.bpp.interface.migrated_targets", boom)
    monkeypatch.setattr("apps.contracts.services.migrated.service_enabled",
                        lambda name: name != "bpp")
    body = Client().get(f"{BASE}/agreements/{frozen['agreement']}",
                        **_headers(frozen["alpha"])).json()
    assert body["migrated_to"] == []


@pytest.mark.django_db(transaction=True)
def test_revoke_pending_reports_documents_pending_without_a_process(two_company_schemas):
    """Документ «на согласовании» без процесса (после неудачного отзыва или
    ручной правки) отзывать нечем: движок его не знает, и заморозка запирала
    его в этом состоянии молча. Команда обязана назвать такие документы."""
    from io import StringIO

    from apps.contracts.models import Agreement

    slug, _ = two_company_schemas
    with use_company(slug):
        agreement = make_agreement(line=make_line(), counterparty=make_counterparty(),
                                   status="draft")
        Agreement.objects.filter(pk=agreement.pk).update(approval_state="pending")
    out = StringIO()
    call_command("contracts_freeze", company=slug, revoke_pending=True, stdout=out)
    text = out.getvalue()
    assert "без процесса" in text
    assert f"contracts.agreement #{agreement.pk}" in text
    with use_company(slug):
        assert freeze.is_frozen()

"""Заявка на закупку (ТЗ §07, §15.2, задача B2.2): AC-001…AC-004, резерв, отзыв."""

from __future__ import annotations

import json
import threading
from decimal import Decimal

import pytest
from django.db import connection
from django.test import Client

from apps.bpp.models import AuditLog, ItemStatus, PurchaseRequest, RequestStatus
from apps.bpp.services.budget import balance
from apps.bpp.services.plan import service as plan
from apps.bpp.services.requests import requests as service
from apps.bpp.tests import stage2 as s
from htqweb.errors import DomainError
from htqweb.tenancy.db import use_company

BASE = "/api/bpp/v1"


def _setup(slug, limit=2_400_000):
    proj, art = s.project(), s.metal()
    s.approved_budget(slug, proj, {art: limit})
    s.request_route()
    return proj, art, s.actor(slug, s.SN, "bpp-sn")


def _draft(sn, proj, art, *amounts, **over):
    return service.create_draft(sn, {**s.header(proj, art), **over,
                                     "items": s.items(*[(1, a) for a in amounts])})


@pytest.mark.django_db
def test_ac001_over_the_balance_is_e_bud_01_and_stays_draft(company_context):
    slug = company_context["slug"]
    proj, art, sn = _setup(slug)
    req = _draft(sn, proj, art, 3_650_000)
    with pytest.raises(DomainError) as exc:
        service.submit(sn, req.id, expected_version=None)
    assert exc.value.code == "E-BUD-01"
    assert exc.value.message == (
        "Сумма заявки 3 650 000,00 KZT превышает доступный остаток статьи „Металлопрокат“ "
        "(2 400 000,00 KZT) на 1 250 000,00 KZT. Уменьшите сумму или обратитесь к "
        "финансовому директору за корректировкой лимита.")
    req.refresh_from_db()
    assert req.status == RequestStatus.DRAFT


@pytest.mark.django_db
def test_ac002_sn_cannot_take_a_pm_article(company_context):
    slug = company_context["slug"]
    proj = s.project()
    s.approved_budget(slug, proj, {s.metal(): 100, s.design(): 100})
    sn = s.actor(slug, s.SN, "bpp-sn")
    with pytest.raises(DomainError) as exc:
        _draft(sn, proj, s.design(), 10)
    assert (exc.value.code, exc.value.status) == ("E-REQ-04", 403)


@pytest.mark.django_db
def test_ac003_td_alone_does_not_approve_od_does(company_context):
    slug = company_context["slug"]
    proj, art, sn = _setup(slug)
    req = service.submit(sn, _draft(sn, proj, art, 1000).id, expected_version=None)
    assert req.status == RequestStatus.IN_APPROVAL

    assert s.decide(req, s.TD, "approve")["ok"]
    req.refresh_from_db()
    assert req.status == RequestStatus.IN_APPROVAL
    assert plan.plan_items(sn)["items"] == []

    assert s.decide(req, s.OD, "approve")["ok"]
    req.refresh_from_db()
    assert req.status == RequestStatus.APPROVED
    assert [row["sys_number"] for row in plan.plan_items(sn)["items"]] == [f"{req.number}-01"]


@pytest.mark.django_db
def test_reserve_is_taken_on_submit_and_released_by_rework_and_reject(company_context):
    slug = company_context["slug"]
    proj, art, sn = _setup(slug)
    first = service.submit(sn, _draft(sn, proj, art, 1000).id, expected_version=None)
    second = service.submit(sn, _draft(sn, proj, art, 500).id, expected_version=None)
    assert balance.balance(proj.id, art.id)["committed"] == Decimal("1500.00")

    assert s.decide(first, s.TD, "rework", "Уточните характеристики")["ok"]
    assert s.decide(second, s.TD, "reject", "Закупка не требуется")["ok"]
    assert balance.balance(proj.id, art.id)["committed"] == Decimal("0.00")
    first.refresh_from_db(), second.refresh_from_db()
    assert (first.status, second.status) == (RequestStatus.REWORK, RequestStatus.REJECTED)
    assert set(second.items.values_list("status", flat=True)) == {ItemStatus.ANNULLED}


@pytest.mark.django_db
def test_short_rework_comment_is_refused_by_the_route_flag(company_context):
    slug = company_context["slug"]
    proj, art, sn = _setup(slug)
    req = service.submit(sn, _draft(sn, proj, art, 10).id, expected_version=None)
    result = s.decide(req, s.TD, "rework", "123456789")
    assert not result["ok"]
    req.refresh_from_db()
    assert req.status == RequestStatus.IN_APPROVAL


@pytest.mark.django_db
def test_withdraw_before_any_decision_but_not_after(company_context):
    slug = company_context["slug"]
    proj, art, sn = _setup(slug)
    req = service.submit(sn, _draft(sn, proj, art, 10).id, expected_version=None)
    req = service.withdraw(sn, req.id, expected_version=None)
    assert req.status == RequestStatus.DRAFT

    req = service.submit(sn, req.id, expected_version=None)
    s.decide(req, s.TD, "approve")
    with pytest.raises(DomainError) as exc:
        service.withdraw(sn, req.id, expected_version=None)
    assert (exc.value.code, exc.value.status) == ("E-STS-01", 409)


@pytest.mark.django_db
def test_cancel_and_close_remainder_need_a_comment_and_release_the_reserve(company_context):
    slug = company_context["slug"]
    proj, art, sn = _setup(slug)
    req = service.submit(sn, _draft(sn, proj, art, 700).id, expected_version=None)
    s.decide(req, s.TD, "approve"), s.decide(req, s.OD, "approve")
    fd = s.actor(slug, s.FD, "bpp-fd")
    with pytest.raises(DomainError):
        service.cancel(fd, req.id, expected_version=None, comment="мало")
    service.cancel(fd, req.id, expected_version=None, comment="Проект заморожен заказчиком")
    req.refresh_from_db()
    assert req.status == RequestStatus.CANCELLED
    assert balance.balance(proj.id, art.id)["committed"] == Decimal("0.00")


@pytest.mark.django_db
def test_201_items_are_refused(company_context):
    slug = company_context["slug"]
    proj, art, sn = _setup(slug)
    with pytest.raises(DomainError) as exc:
        _draft(sn, proj, art, *([1] * 201))
    assert exc.value.code == "E-REQ-06"


@pytest.mark.django_db
def test_number_is_given_once_and_items_follow_it(company_context):
    slug = company_context["slug"]
    proj, art, sn = _setup(slug)
    req = _draft(sn, proj, art, 10, 20)
    number = req.number
    assert number.startswith("ЗЗ-") and len(number) == len("ЗЗ-2026-000001")
    req = service.update_draft(sn, req.id, expected_version=None,
                               data={"items": s.items((1, 30))})
    assert req.number == number
    assert list(req.items.values_list("sys_number", flat=True)) == [f"{number}-01"]
    assert req.total_amount == Decimal("30.00")


@pytest.mark.django_db
def test_no_approved_budget_is_e_bud_02(company_context):
    slug = company_context["slug"]
    proj = s.project()
    sn = s.actor(slug, s.SN, "bpp-sn")
    with pytest.raises(DomainError) as exc:
        _draft(sn, proj, s.metal(), 10)
    assert exc.value.code == "E-BUD-02"


@pytest.mark.django_db
def test_pm_works_only_on_member_projects(company_context):
    slug = company_context["slug"]
    proj = s.project()
    s.approved_budget(slug, proj, {s.design(): 100})
    pm = s.actor(slug, s.PM, "bpp-pm")
    with pytest.raises(DomainError) as exc:
        _draft(pm, proj, s.design(), 10, initiator_role="pm")
    assert exc.value.status == 403


@pytest.mark.django_db
def test_required_fields_are_checked_on_submit(company_context):
    slug = company_context["slug"]
    proj, art, sn = _setup(slug)
    req = service.create_draft(sn, {"project_id": str(proj.id)})
    with pytest.raises(DomainError) as exc:
        service.submit(sn, req.id, expected_version=None)
    assert exc.value.code == "E-REQ-01"
    assert "„Статья бюджета“" in exc.value.message


@pytest.mark.django_db
def test_other_sn_does_not_see_the_request(company_context):
    slug = company_context["slug"]
    proj, art, sn = _setup(slug)
    req = _draft(sn, proj, art, 10)
    other = s.actor(slug, s.SN2, "bpp-sn")
    with pytest.raises(DomainError) as exc:
        service.get_visible(other, req.id)
    assert exc.value.status == 404
    td = s.actor(slug, s.TD, "bpp-td")
    assert service.get_visible(td, req.id) == req


@pytest.mark.django_db
def test_http_submit_twice_with_one_key_is_one_transition(company_context):
    slug = company_context["slug"]
    proj, art, sn = _setup(slug)
    req = _draft(sn, proj, art, 10)
    headers = {**s.auth(slug, s.SN), "HTTP_IDEMPOTENCY_KEY": "submit-1"}
    client = Client()
    first = client.post(f"{BASE}/requests/{req.id}/submit", json.dumps({}), **headers)
    again = client.post(f"{BASE}/requests/{req.id}/submit", json.dumps({}), **headers)
    assert first.status_code == 200, first.json()
    assert again.status_code == 200 and again["Idempotent-Replay"] == "true"
    with use_company(slug):  # запрос вернул search_path в public
        assert AuditLog.objects.filter(object_id=str(req.id), action="submitted").count() == 1
    assert first.json()["status"] == "in_approval"
    assert first.json()["current_holders"]["users"][0]["id"] == s.TD


@pytest.mark.django_db(transaction=True)
def test_ac004_two_parallel_submits_share_one_balance():
    """Две заявки по 2 000 000 при остатке 3 000 000 — одна проходит, вторая
    E-BUD-01; задействовано 2 000 000. Каждая — в своём потоке и соединении
    (таблицы модуля в тестовой БД есть и в ``public``)."""
    proj, art = s.project(), s.metal()
    s.approved_budget(None, proj, {art: 3_000_000}, superuser=True)
    s.request_route()
    sn = s.actor(None, s.SN, superuser=True)
    ids = [_draft(sn, proj, art, 2_000_000, initiator_role="sn").id for _ in range(2)]
    outcome: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    def worker(request_id):
        try:
            barrier.wait()
            service.submit(sn, request_id, expected_version=None)
            result = "ok"
        except DomainError as exc:
            result = exc.code
        finally:
            connection.close()
        with lock:
            outcome.append(result)

    threads = [threading.Thread(target=worker, args=(rid,)) for rid in ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcome) == ["E-BUD-01", "ok"]
    assert balance.balance(proj.id, art.id)["committed"] == Decimal("2000000.00")
    assert PurchaseRequest.objects.filter(status=RequestStatus.IN_APPROVAL).count() == 1


@pytest.mark.django_db
def test_card_budget_counts_the_request_once(company_context):
    """Блок «Бюджет» карточки: черновик ещё не занял ничего и вычитается из
    остатка; отправленная заявка уже внутри «Задействовано»."""
    from apps.bpp.services.requests import read

    slug = company_context["slug"]
    proj, art, sn = _setup(slug, limit=1000)
    req = _draft(sn, proj, art, 300)
    figures = read.card(sn, req)["budget"]
    assert (figures["committed"], figures["available"], figures["after_request"]) \
        == (Decimal("0.00"), Decimal("1000.00"), Decimal("700.00"))

    req = service.submit(sn, req.id, expected_version=None)
    figures = read.card(sn, req)["budget"]
    assert figures["reserved"] is True
    assert (figures["committed"], figures["available"], figures["after_request"]) \
        == (Decimal("300.00"), Decimal("700.00"), Decimal("700.00"))


@pytest.mark.django_db
def test_approver_gets_a_bell_and_an_email_with_the_tz_text(company_context):
    """ТЗ §22: «Заявка ЗЗ-… на … KZT по проекту П-015 ждёт вашего согласования» —
    в колокольчик и по e-mail (документы БЗО доставляются, план этапа 2)."""
    from apps.notifications.models import Notification

    slug = company_context["slug"]
    proj, art, sn = _setup(slug)
    req = service.submit(sn, _draft(sn, proj, art, 2_400_000).id, expected_version=None)
    row = Notification.objects.get(recipient_id=s.TD, event="signoff.awaiting_you")
    assert row.title == (f"Заявка {req.number} на 2 400 000,00 KZT по проекту П-015 "
                         f"ждёт вашего согласования")
    assert row.url == f"/bpp/requests/{req.pk}"
    assert list(row.deliveries.values_list("channel", flat=True)) == ["email"]


# ── Review Focus 3 плана этапа 2 и соседние случаи ──────────────────────

@pytest.mark.django_db
def test_dual_role_article_follows_initiator_role(company_context):
    """СН и ПМ одновременно: статья привязана к роли инициатора, смена роли
    очищает статью, статья чужой для роли группы — 403 E-REQ-04."""
    slug = company_context["slug"]
    proj = s.project(members=[s.SN])
    s.approved_budget(slug, proj, {s.metal(): 1000, s.design(): 1000})
    both = s.actor(slug, s.SN, "bpp-sn", "bpp-pm")
    with pytest.raises(DomainError) as exc:
        service.create_draft(both, {**s.header(proj, s.metal()), "initiator_role": None})
    assert exc.value.code == "E-REQ-01"  # две роли — выбрать обязательно

    req = _draft(both, proj, s.metal(), 10)
    assert req.initiator_role == "sn"
    req = service.update_draft(both, req.id, expected_version=None,
                               data={"initiator_role": "pm"})
    assert (req.initiator_role, req.article_id) == ("pm", None)
    with pytest.raises(DomainError) as exc:
        service.update_draft(both, req.id, expected_version=None,
                             data={"article_id": str(s.metal().id)})
    assert (exc.value.code, exc.value.status) == ("E-REQ-04", 403)


@pytest.mark.django_db
def test_archived_article_not_offered(company_context):
    from apps.bpp.services.budget import read as budget_read

    slug = company_context["slug"]
    proj, art, sn = _setup(slug)
    old = _draft(sn, proj, art, 10)
    art.is_active = False
    art.save(update_fields=["is_active"])
    assert budget_read.lines_for_request(sn, project_id=str(proj.id), role="sn") == []
    with pytest.raises(DomainError) as exc:
        _draft(sn, proj, art, 10)
    assert exc.value.code == "E-REF-03"
    # Старая заявка статью видит — с меткой «Архив».
    from apps.bpp.services.requests import read

    assert read.card(sn, old)["article"]["archived"] is True


@pytest.mark.django_db
def test_author_does_not_approve_own_request(company_context):
    """Флаг запрета самосогласования: автор на этапе ТД из группы уходит,
    этап без исполнителей закрывается сам, решение ждёт ОД."""
    from apps.signoff import interface as signoff

    slug = company_context["slug"]
    proj, art = s.project(), s.metal()
    s.approved_budget(slug, proj, {art: 1000})
    s.request_route(td=s.SN)  # автор — он же «ТД» маршрута
    sn = s.actor(slug, s.SN, "bpp-sn")
    req = service.submit(sn, _draft(sn, proj, art, 10).id, expected_version=None)
    process = signoff.get_process_for("bpp.purchase_request", str(req.pk))
    pending = [t["user_id"] for st in process["stages"] for t in st["tasks"]
               if t["state"] == "pending"]
    assert pending == [s.OD]


@pytest.mark.django_db
def test_repeated_callbacks_do_not_move_status_twice(company_context):
    slug = company_context["slug"]
    proj, art, sn = _setup(slug)
    req = service.submit(sn, _draft(sn, proj, art, 10).id, expected_version=None)
    s.decide(req, s.TD, "rework", "Уточните характеристики позиций")
    service.on_rework(req.pk)
    service.on_rework(req.pk)
    req.refresh_from_db()
    assert (req.status, req.rework_comment) == (RequestStatus.REWORK,
                                                "Уточните характеристики позиций")
    service.on_rejected(req.pk)
    service.on_rejected(req.pk)
    req.refresh_from_db()
    assert req.status == RequestStatus.REJECTED
    assert set(req.items.values_list("status", flat=True)) == {ItemStatus.ANNULLED}


@pytest.mark.django_db
def test_copy_with_a_foreign_group_article_is_403(company_context):
    """Копирует тот, кто заявку видит, но подаёт в другой роли: согласующим
    этапа назначен ПМ. Статья «Снабжения» для него чужая — 403 E-REQ-04, а не
    копия с молча выброшенной статьёй."""
    slug = company_context["slug"]
    proj = s.project(members=[s.PM])
    s.approved_budget(slug, proj, {s.metal(): 1000})
    s.request_route(td=s.PM)
    sn = s.actor(slug, s.SN, "bpp-sn")
    source = service.submit(sn, _draft(sn, proj, s.metal(), 10).id, expected_version=None)
    pm = s.actor(slug, s.PM, "bpp-pm")
    with pytest.raises(DomainError) as exc:
        service.copy(pm, source.id)
    assert (exc.value.code, exc.value.status) == ("E-REQ-04", 403)

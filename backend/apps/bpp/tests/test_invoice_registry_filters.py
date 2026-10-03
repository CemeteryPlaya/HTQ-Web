"""Фильтры реестра счетов L-06 для ссылок дашборда D-01 (D-S4-8; зона B,
правка A в задаче 5 этапа 4): автор, статус сверки, дата платежа по выписке,
«банк не подтвердил N рабочих дней».

Отдельный файл, а не ``test_invoices.py``: тот ведёт B. Счета — строками
модели (как в ``test_dashboard.py``): проверяется выборка реестра, а не
поток счёта.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.bpp.models import InvoiceStatus, PaymentMatchState, ReconStatus
from apps.bpp.services.invoices.read import bank_days_before
from apps.bpp.tests import stage2 as s
from apps.bpp.tests.test_dashboard import _inv, _mark, _Statement

pytestmark = pytest.mark.django_db
URL = "/api/bpp/v1/invoices"
OTHER_AUTHOR = 977


def _numbers(slug, **params) -> list[str]:
    s.grant(slug, s.FD, "bpp-fd")
    response = Client().get(URL, data=params, **s.auth(slug, s.FD))
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["total"] == len(body["items"])
    return sorted(row["number"] for row in body["items"])


def test_author_filter(company_context):
    slug = company_context["slug"]
    mine = _inv(InvoiceStatus.UNDER_REVIEW, 100)
    other = _inv(InvoiceStatus.UNDER_REVIEW, 200, author_id=OTHER_AUTHOR)

    assert _numbers(slug, author_id=s.SN) == [mine.number]
    assert _numbers(slug, author_id=OTHER_AUTHOR) == [other.number]
    assert _numbers(slug) == sorted([mine.number, other.number])


def test_author_filter_rejects_non_integer(company_context):
    slug = company_context["slug"]
    s.grant(slug, s.FD, "bpp-fd")
    response = Client().get(URL, data={"author_id": "SN"}, **s.auth(slug, s.FD))
    assert response.status_code == 422
    assert response.json()["fields"][0]["field"] == "author_id"


def test_recon_status_filter_is_repeatable(company_context):
    slug = company_context["slug"]
    # Все счета — ДО первого запроса: клиент после ответа возвращает
    # ``search_path`` на ``public``, и созданное после него легло бы туда.
    full = _inv(InvoiceStatus.PAID, 100, recon=ReconStatus.FULL, paid_bank=100)
    partial = _inv(InvoiceStatus.PAID, 200, recon=ReconStatus.PARTIAL, paid_bank=50)
    _inv(InvoiceStatus.PAID, 300)                                  # no_data
    over = _inv(InvoiceStatus.PAID, 400, recon=ReconStatus.OVERPAID, paid_bank=410)
    # «Платёж есть, отметки БУХ нет»: сверка есть, статус — «К оплате».
    no_mark = _inv(InvoiceStatus.TO_PAY, 500, recon=ReconStatus.PARTIAL, paid_bank=10)
    _inv(InvoiceStatus.TO_PAY, 600)                                # to_pay без сверки

    assert _numbers(slug, recon_status="full") == [full.number]
    assert _numbers(slug, recon_status=["partial", "overpaid"]) == sorted(
        [partial.number, over.number, no_mark.number])
    # Вместе со статусом счёта — оба фильтра сразу (так строится ссылка no_mark).
    assert _numbers(slug, recon_status="partial", status="to_pay") == [no_mark.number]


def test_unknown_recon_status_is_422(company_context):
    slug = company_context["slug"]
    s.grant(slug, s.FD, "bpp-fd")
    response = Client().get(URL, data={"recon_status": ["full", "paid"]},
                            **s.auth(slug, s.FD))
    assert response.status_code == 422
    assert response.json()["code"] == "E-VAL-01"
    assert response.json()["fields"][0]["field"] == "recon_status"


def test_bank_date_filter_takes_only_active_matches_in_period(company_context):
    slug = company_context["slug"]
    today = timezone.localdate()
    month_ago = today - timedelta(days=30)
    bank = _Statement()
    recent = _inv(InvoiceStatus.PAID, 100, recon=ReconStatus.FULL, paid_bank=100)
    bank.pay(recent, 100, today)
    old = _inv(InvoiceStatus.PAID, 200, recon=ReconStatus.FULL, paid_bank=200)
    bank.pay(old, 200, month_ago)
    review = _inv(InvoiceStatus.PAID, 300)
    bank.pay(review, 300, today, state=PaymentMatchState.REVIEW)

    week_ago = (today - timedelta(days=6)).isoformat()
    assert _numbers(slug, bank_date_from=week_ago) == [recent.number]
    assert _numbers(slug, bank_date_to=week_ago) == [old.number]
    assert _numbers(slug, bank_date_from=month_ago.isoformat(),
                    bank_date_to=today.isoformat()) == sorted([recent.number, old.number])


def test_bank_date_filter_rejects_bad_date(company_context):
    slug = company_context["slug"]
    s.grant(slug, s.FD, "bpp-fd")
    response = Client().get(URL, data={"bank_date_from": "01.09.2026"}, **s.auth(slug, s.FD))
    assert response.status_code == 422
    assert response.json()["fields"][0]["field"] == "bank_date_from"


def test_bank_wait_days_counts_working_days_from_last_mark(company_context):
    slug = company_context["slug"]
    today = timezone.localdate()
    stale = _inv(InvoiceStatus.PAID, 100)
    _mark(stale, bank_days_before(today, 4))
    edge = _inv(InvoiceStatus.PAID, 200)
    _mark(edge, bank_days_before(today, 3))

    assert _numbers(slug, tab="bank_unconfirmed", bank_wait_days=3) == [stale.number]
    assert _numbers(slug, tab="bank_unconfirmed", bank_wait_days=2) == sorted(
        [stale.number, edge.number])
    assert _numbers(slug, tab="bank_unconfirmed") == sorted([stale.number, edge.number])


def test_bank_wait_days_upper_bound_is_422(company_context):
    slug = company_context["slug"]
    s.grant(slug, s.FD, "bpp-fd")
    response = Client().get(URL, data={"bank_wait_days": 10**9}, **s.auth(slug, s.FD))
    assert response.status_code == 422
    assert response.json()["fields"][0]["field"] == "bank_wait_days"

"""Раздел ежедневной сводки «Ждут от вас закрывающих документов» (задача 8
плана этапа 3 A, A3.2, D-13; Review Focus 5).

Источник ``bpp.closing_docs`` регистрирует САМ ``BppConfig.ready()``
(``apps/bpp/digest.py``) — тест зовёт настоящую ``digest.send()``, без
подмены источника. Счета заводятся прямо строкой в «Ждёт закрывающих»:
путь «оплачено → запрос документов» проверяют тесты B (``test_invoices.py::
test_closing_docs_after_payment_only``) и сквозной сценарий этапа (задача 9);
здесь важен только раздел сводки поверх контракта B.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.bpp import digest as bpp_digest
from apps.bpp.models import Invoice, InvoiceStatus
from apps.bpp.tests import stage2 as s
from apps.companies.models import Company, CompanyMembership, CompanyModule
from apps.notifications import interface as notifications
from apps.notifications.models import Notification
from apps.notifications.services import digest
from htqweb.tenancy.db import use_company

HEADING = "Ждут от вас закрывающих документов:"


@pytest.fixture(autouse=True)
def _no_center_side_effects(monkeypatch):
    """Доставка (Celery) и мгновенный показ (Socket.IO) центру не нужны —
    тесту достаточно записи ``Notification`` (как test_bpp_signoff_e2e.py)."""
    from apps.notifications.services import center

    monkeypatch.setattr(center, "_enqueue", lambda ids: None)
    monkeypatch.setattr(center, "_realtime", lambda rows: None)


@pytest.fixture
def probe():
    """Нетенантный соседний источник: позиция только для ``SN2``. Снимается
    на выходе — ``digest._SOURCES`` общий на процесс."""
    def source(user_id: int) -> list[dict]:
        return ([{"title": "Внешняя проверка", "url": "/x", "since": ""}]
                if user_id == s.SN2 else [])

    notifications.register_digest_source("probe", source, tenant=False)
    yield
    digest._SOURCES.pop("probe", None)


def _member(slug: str, *user_ids: int) -> None:
    """Тенантный источник обходит компании ПОЛЬЗОВАТЕЛЯ (``digest._companies_of``)
    — нужна настоящая строка членства, а не только активная учётка."""
    company = Company.objects.get(slug=slug)
    for user_id in user_ids:
        s.user(user_id)
        CompanyMembership.objects.get_or_create(user_id=user_id, company=company)


def _invoice(slug: str, author_id: int, number: str, *, days: int = 3,
             status: str = InvoiceStatus.AWAITING_DOCS) -> Invoice:
    with use_company(slug):
        return Invoice.objects.create(
            number=number, project_id=uuid.uuid4(), article_id=uuid.uuid4(),
            author_id=author_id, amount=1000, status=status,
            docs_required={"avr": True, "waybill": False, "vat_invoice": False},
            docs_requested_at=timezone.now() - timedelta(days=days))


@pytest.mark.django_db
def test_source_is_registered_by_the_app_itself():
    fn, tenant, section, landing_url = digest._SOURCES[bpp_digest.SOURCE_KEY]
    assert fn is bpp_digest.closing_docs_items
    assert tenant is True
    assert section == bpp_digest.SECTION
    assert landing_url == "/bpp/invoices?tab=awaiting_docs"


@pytest.mark.django_db
def test_author_gets_the_section_with_a_company_subdomain_link(settings, company_schema):
    """Автор счёта в «Ждёт закрывающих» — раздел с пунктом «СЧ-… — ждёт
    закрывающих N дн.» и абсолютной ссылкой на счёт на поддомене компании."""
    settings.PUBLIC_BASE_URL = "https://htq.group"
    slug = company_schema["slug"]
    _member(slug, s.SN)
    inv = _invoice(slug, s.SN, "СЧ-2026-000001", days=3)

    # send() — без контекста компании, как из Celery-beat.
    assert digest.send() == 1

    note = Notification.objects.get(recipient_id=s.SN, event="digest.daily")
    lines = note.text.splitlines()
    assert HEADING in lines
    item = (f"• СЧ-2026-000001 — ждёт закрывающих 3 дн. — "
            f"https://{slug}.htq.group/bpp/invoices/{inv.pk}")
    assert lines.index(item) == lines.index(HEADING) + 1
    # Решений в сводке нет — не «Ждут вашего решения» и не /signoff:
    # единственная позиция — ссылка прямо на счёт.
    assert note.title == "Ждут вашего внимания: 1"
    assert note.url == f"/bpp/invoices/{inv.pk}"


@pytest.mark.django_db
def test_several_invoices_lead_to_the_invoice_registry(settings, company_schema):
    settings.PUBLIC_BASE_URL = "https://htq.group"
    slug = company_schema["slug"]
    _member(slug, s.SN)
    _invoice(slug, s.SN, "СЧ-2026-000001", days=5)
    _invoice(slug, s.SN, "СЧ-2026-000002", days=1)

    assert digest.send() == 1
    note = Notification.objects.get(recipient_id=s.SN, event="digest.daily")
    assert note.title == "Ждут вашего внимания: 2"
    assert note.url == "/bpp/invoices?tab=awaiting_docs"
    lines = note.text.splitlines()
    start = lines.index(HEADING)
    # Порядок — по дате запроса документов (старший первым), как отдаёт B.
    assert lines[start + 1].startswith("• СЧ-2026-000001 — ждёт закрывающих 5 дн.")
    assert lines[start + 2].startswith("• СЧ-2026-000002 — ждёт закрывающих 1 дн.")


@pytest.mark.django_db
def test_no_section_without_awaiting_invoices_and_no_foreign_invoices(
        settings, company_schema, probe):
    """У ``SN2`` — счёт в другом статусе («Документы предоставлены»), у ``SN``
    — в «Ждёт закрывающих». Сводка ``SN2`` уходит (соседний источник), но
    раздела в ней нет и чужой счёт в неё не попадает."""
    settings.PUBLIC_BASE_URL = "https://htq.group"
    slug = company_schema["slug"]
    _member(slug, s.SN, s.SN2)
    _invoice(slug, s.SN, "СЧ-2026-000001")
    _invoice(slug, s.SN2, "СЧ-2026-000002", status=InvoiceStatus.DOCS_PROVIDED)

    with use_company(slug):
        assert bpp_digest.closing_docs_items(s.SN2) == []

    assert digest.send() == 2
    note = Notification.objects.get(recipient_id=s.SN2, event="digest.daily")
    assert "Внешняя проверка" in note.text
    assert HEADING not in note.text
    assert "СЧ-2026-000001" not in note.text
    assert "СЧ-2026-000002" not in note.text


@pytest.mark.django_db
def test_bpp_disabled_at_the_company_does_not_break_the_digest(
        settings, company_schema, probe, monkeypatch):
    """``bpp`` выключен у компании (``CompanyModule``) — «ждать нечего», а не
    сбой источника: без ``fallback``, без позиции по счёту, а сводка
    остальным уходит как обычно (Review Focus 5)."""
    settings.PUBLIC_BASE_URL = "https://htq.group"
    slug = company_schema["slug"]
    _member(slug, s.SN, s.SN2)
    _invoice(slug, s.SN, "СЧ-2026-000001")
    CompanyModule.objects.create(company=Company.objects.get(slug=slug), app_label="bpp",
                                 enabled=False)
    # Рубильник компании кэшируется (TTL 5 с, companies.interface.module_enabled).
    cache.clear()

    with use_company(slug):
        assert bpp_digest.closing_docs_items(s.SN) == []

    failed: list[dict] = []
    monkeypatch.setattr(digest, "fallback",
                        lambda site, value, **kw: failed.append({"site": site, **kw}))

    assert digest.send() == 1  # только SN2 — по соседнему источнику
    assert failed == []
    assert not Notification.objects.filter(recipient_id=s.SN, event="digest.daily").exists()
    note = Notification.objects.get(recipient_id=s.SN2, event="digest.daily")
    assert "Внешняя проверка" in note.text

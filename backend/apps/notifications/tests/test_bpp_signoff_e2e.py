"""Сквозная проверка: согласование БЗО → центр уведомлений (задача 10,
docs/plans/2026-09-28-bpp-stage2-executor-a.md).

Три вещи проверяются end-to-end, на настоящей заявке ``bpp.purchase_request``
и настоящем маршруте (как в тестах Руслана — ``apps/bpp/tests/stage2.py``),
а не на подменённых источниках:

1. Ежедневная сводка (``digest.send()``) находит заявку, ждущую пользователя
   в компании A, через источник, который ``SignoffConfig.ready()`` регистрирует
   САМ (``holders.digest_items`` — docs/plans/2026-09-26-bpp-reconciliation-B.md
   §7.1), и пишет ссылку на ПОДДОМЕН компании A (``companies.interface.
   public_url``), а не на голый домен.
2. Выключенный у компании модуль ``signoff`` (``CompanyModule``) не роняет
   сводку и не выдаёт по нему позицию — прочие источники при этом
   отрабатывают как обычно.
3. Отправка заявки на первый этап маршрута создаёт получателю
   ``notifications.Notification`` и ``Delivery`` каналом ``email``. Движок
   (``apps/signoff/services/engine.py::_notify_center``) НЕ передаёт
   ``deliver=`` вовсе для bpp.* (и вообще ни для одного типа) — поэтому
   действует умолчание центра ``deliver=True``
   (``apps/notifications/services/center.py::notify``), и доставка
   заводится взаправду; xfail здесь не нужен (см. отчёт разработчика).
"""

from __future__ import annotations

import pytest
from django.core.cache import cache

from apps.bpp.services.requests import requests as request_service
from apps.bpp.tests import stage2 as s
from apps.companies.models import Company, CompanyMembership, CompanyModule
from apps.notifications import interface as notifications
from apps.notifications.models import Channel, Delivery, Notification
from apps.notifications.services import digest
from htqweb.tenancy.db import use_company


@pytest.fixture(autouse=True)
def _no_center_side_effects(monkeypatch):
    """Подавляем побочные эффекты центра — как соседние тесты (test_center.py,
    test_digest.py): доставка идёт через Celery (``_enqueue``), мгновенный
    показ — через Socket.IO мессенджера (``_realtime``); тестам нужна только
    сама запись (``Notification``/``Delivery``)."""
    from apps.notifications.services import center

    monkeypatch.setattr(center, "_enqueue", lambda ids: None)
    monkeypatch.setattr(center, "_realtime", lambda rows: None)


def _submitted_request(slug: str):
    """Проект, утверждённый бюджет, маршрут «ТД → ОД» (без HR-должностей,
    поимённо — ``stage2.request_route``) и отправленная заявка: после неё у
    ТД есть открытая задача первого этапа."""
    with use_company(slug):
        proj, art = s.project(), s.metal()
        s.approved_budget(slug, proj, {art: 2_000_000})
        s.request_route()
        sn = s.actor(slug, s.SN, "bpp-sn")
        draft = request_service.create_draft(
            sn, {**s.header(proj, art), "items": s.items((1, 1000))})
        return request_service.submit(sn, draft.id, expected_version=None)


@pytest.mark.django_db
def test_digest_notifies_the_waiting_user_with_a_company_subdomain_link(settings, company_schema):
    """Заявка ждёт ТД в компании A → ``digest.send()`` пишет ему уведомление
    со ссылкой на поддомен компании A, а не на голый ``PUBLIC_BASE_URL``."""
    settings.PUBLIC_BASE_URL = "https://htq.group"
    slug = company_schema["slug"]
    req = _submitted_request(slug)

    # Источник сводки — тенантный: он обходит компании ПОЛЬЗОВАТЕЛЯ
    # (``digest._companies_of``), а не текущий контекст, поэтому нужна
    # настоящая строка членства, а не просто активная учётка.
    company = Company.objects.get(slug=slug)
    CompanyMembership.objects.get_or_create(user_id=s.TD, company=company)

    # send() зовётся без контекста компании (как из Celery-beat) — сам
    # источник входит в каждую компанию пользователя через use_company().
    sent = digest.send()

    assert sent == 1
    note = Notification.objects.get(recipient_id=s.TD, event="digest.daily")
    assert note.url == "/signoff"  # входящие согласования — маршрут /signoff
    assert f"https://{slug}.htq.group/bpp/requests/{req.id}" in note.text
    assert note.title.startswith("Ждут вашего решения")


@pytest.mark.django_db
def test_disabled_company_module_does_not_break_the_digest(settings, company_schema):
    """Выключенный у компании ``signoff`` — «ждать нечего», а не сбой
    источника: сводка не падает и не пишет заявку в письмо, а прочие
    источники продолжают работать как ни в чём не бывало."""
    settings.PUBLIC_BASE_URL = "https://htq.group"
    slug = company_schema["slug"]
    req = _submitted_request(slug)

    company = Company.objects.get(slug=slug)
    CompanyMembership.objects.get_or_create(user_id=s.TD, company=company)
    CompanyModule.objects.create(company=company, app_label="signoff", enabled=False)
    # Отправка заявки уже закэшировала «signoff включён» (TTL 5 с,
    # apps.companies.interface.module_enabled): без сброса проверка ниже
    # прочитала бы устаревшее значение.
    cache.clear()

    # Низкий уровень — источник сам по себе, без сводки (докстринг
    # holders.digest_items): выключенный модуль гасит его молча, пустым
    # списком, а не ServiceDisabled.
    with use_company(slug):
        from apps.signoff.services import holders

        assert holders.digest_items(s.TD) == []

    # Соседний источник — не signoff и не БЗО, регистрируется на время
    # теста и снимается в finally, чтобы не протечь в остальные тесты
    # процесса (общий модульный словарь digest._SOURCES).
    probe_calls: list[int] = []

    def probe(user_id: int) -> list[dict]:
        probe_calls.append(user_id)
        return ([{"title": "Внешняя проверка", "url": "/x", "since": ""}]
                if user_id == s.TD else [])

    notifications.register_digest_source("probe", probe, tenant=False)
    try:
        sent = digest.send()
    finally:
        digest._SOURCES.pop("probe", None)

    # «probe» не тенантный — его зовут для КАЖДОГО активного получателя
    # (ФД/ТД/ОД/СН, заведённых внутри _submitted_request), безотносительно
    # членства в компании; позицию он отдаёт только по ТД.
    assert s.TD in probe_calls
    assert sent == 1  # только «probe» дал позицию: signoff молчит — модуль выключен
    note = Notification.objects.get(recipient_id=s.TD, event="digest.daily")
    assert "Внешняя проверка" in note.text
    assert f"/bpp/requests/{req.id}" not in note.text


@pytest.mark.django_db
def test_submit_creates_a_notification_and_an_email_delivery_for_the_first_stage(company_context):
    """Отправка заявки — «колокольчик» и e-mail получателям первого этапа
    (ТЗ §22, движок событий модуля). ``_notify_center`` в
    ``apps/signoff/services/engine.py`` не передаёт ``deliver=`` вовсе для
    bpp.*, поэтому применяется умолчание центра ``deliver=True``
    (``apps/notifications/services/center.py::notify``) — доставка
    заводится. Если движок когда-нибудь начнёт явно гасить доставку для
    bpp.*, этот тест обязан упасть, а не молча пройти как xfail."""
    slug = company_context["slug"]
    req = _submitted_request(slug)

    note = Notification.objects.get(
        recipient_id=s.TD, target_type="bpp.purchase_request", target_id=str(req.id))
    assert note.event == "signoff.awaiting_you"
    assert note.url == f"/bpp/requests/{req.id}"
    assert Delivery.objects.filter(notification=note, channel=Channel.EMAIL).exists()

    # ОД — второй этап, его задача ещё не активна: письма ему пока не будет.
    assert not Notification.objects.filter(
        recipient_id=s.OD, target_type="bpp.purchase_request", target_id=str(req.id)).exists()

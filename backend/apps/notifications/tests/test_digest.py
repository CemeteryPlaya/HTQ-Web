"""Сводка: одно сообщение со всем, что ждёт пользователя, по всем компаниям."""

import pytest

from apps.notifications import interface
from apps.notifications.models import Notification
from apps.notifications.services import digest


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    from apps.notifications.services import center

    monkeypatch.setattr(center, "_enqueue", lambda ids: None)
    monkeypatch.setattr(center, "_realtime", lambda rows: None)
    saved = dict(digest._SOURCES)
    digest._SOURCES.clear()
    yield
    digest._SOURCES.clear()
    digest._SOURCES.update(saved)


@pytest.mark.django_db
def test_one_message_with_links(monkeypatch):
    interface.register_digest_source(
        "probe", lambda user_id: [{"title": "Заявка ЗЗ-2026-000045", "url": "/bpp/r/45",
                                   "since": "2026-09-25"}] if user_id == 7 else [],
        tenant=False)
    monkeypatch.setattr(digest, "_recipients", lambda: [7, 8])
    assert digest.send() == 1
    note = Notification.objects.get(recipient_id=7)
    assert note.event == "digest.daily"
    assert "Заявка ЗЗ-2026-000045" in note.text and "/bpp/r/45" in note.text
    assert not Notification.objects.filter(recipient_id=8).exists()


@pytest.mark.django_db
def test_tenant_source_runs_per_company(monkeypatch):
    seen = []

    def source(user_id):
        from htqweb.tenancy.context import current_company

        seen.append(current_company())
        return []

    interface.register_digest_source("tenant-probe", source, tenant=True)
    monkeypatch.setattr(digest, "_recipients", lambda: [7])
    monkeypatch.setattr(digest, "_companies_of", lambda user_id: ["htq-kz", "htq-uz"])
    digest.send()
    assert seen == ["htq-kz", "htq-uz"]


@pytest.mark.django_db
def test_broken_source_does_not_stop_the_digest(monkeypatch, settings):
    settings.FALLBACK_MODE = "log"
    interface.register_digest_source("broken", lambda user_id: 1 / 0, tenant=False)
    interface.register_digest_source(
        "ok", lambda user_id: [{"title": "Договор", "url": "/x", "since": ""}], tenant=False)
    monkeypatch.setattr(digest, "_recipients", lambda: [7])
    assert digest.send() == 1


@pytest.mark.django_db
def test_links_are_absolute_and_lead_to_existing_pages(monkeypatch, settings):
    """В письме и Telegram относительный путь не кликабелен; позиция компании
    ведёт на её поддомен (там её таблицы), общая — на голый домен."""
    settings.PUBLIC_BASE_URL = "https://htq.group"
    interface.register_digest_source(
        "tenant", lambda user_id: [{"title": "Заявка", "url": "/bpp/r/45", "since": ""}],
        tenant=True)
    interface.register_digest_source(
        "common", lambda user_id: [{"title": "Общее", "url": "/x", "since": ""}], tenant=False)
    monkeypatch.setattr(digest, "_recipients", lambda: [7])
    monkeypatch.setattr(digest, "_companies_of", lambda user_id: ["htq-kz"])
    monkeypatch.setattr(digest.companies, "public_url",
                        lambda slug: f"https://{slug}.htq.group")
    digest.send()
    note = Notification.objects.get(recipient_id=7)
    assert "https://htq-kz.htq.group/bpp/r/45" in note.text
    assert "https://htq.group/x" in note.text
    assert note.url == "/signoff"  # входящие согласования — маршрут /signoff


@pytest.mark.django_db
def test_sectioned_source_goes_under_its_heading_after_plain_items(monkeypatch):
    """Источник с ``section`` — отдельный раздел письма после позиций без
    раздела; источник без позиций заголовка не печатает."""
    interface.register_digest_source(
        "docs", lambda user_id: [{"title": "СЧ-2026-000001", "url": "/a", "since": ""}],
        tenant=False, section="Ждут от вас закрывающих документов")
    interface.register_digest_source(
        "plain", lambda user_id: [{"title": "Заявка", "url": "/b", "since": ""}], tenant=False)
    interface.register_digest_source("empty", lambda user_id: [], tenant=False,
                                     section="Пустой раздел")
    monkeypatch.setattr(digest, "_recipients", lambda: [7])
    digest.send()
    note = Notification.objects.get(recipient_id=7)
    # Смешанная сводка — заголовок и ссылка решений, N — только решения.
    assert note.title == "Ждут вашего решения: 1"
    assert note.url == "/signoff"
    lines = note.text.splitlines()
    assert lines[0].startswith("• Заявка")
    assert lines[1:3] == ["", "Ждут от вас закрывающих документов:"]
    assert lines[3].startswith("• СЧ-2026-000001")
    assert not any("Пустой раздел" in line for line in lines)


@pytest.mark.django_db
def test_sections_only_digest_has_a_neutral_title_and_its_own_link(monkeypatch):
    """Без решений сводка не зовёт «решать» и не ведёт в /signoff: одна
    позиция — ссылка на неё, несколько — на страницу первого раздела."""
    items = {7: ["/bpp/invoices/1"], 8: ["/bpp/invoices/1", "/bpp/invoices/2"]}
    interface.register_digest_source(
        "docs", lambda user_id: [{"title": f"СЧ-{n}", "url": url, "since": ""}
                                 for n, url in enumerate(items[user_id])],
        tenant=False, section="Ждут от вас закрывающих документов",
        landing_url="/bpp/invoices")
    monkeypatch.setattr(digest, "_recipients", lambda: [7, 8])
    assert digest.send() == 2

    one = Notification.objects.get(recipient_id=7)
    assert one.title == "Ждут вашего внимания: 1"
    assert one.url == "/bpp/invoices/1"
    two = Notification.objects.get(recipient_id=8)
    assert two.title == "Ждут вашего внимания: 2"
    assert two.url == "/bpp/invoices"
    assert two.text.splitlines()[0] == "Ждут от вас закрывающих документов:"

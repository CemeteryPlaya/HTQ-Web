"""Контракт `hr.participant_position` — как сосед находит ОСУ.

Название должности зафиксировано ``is_system``, но сосед не должен
хардкодить строку «Участник (ОСУ)»: он спрашивает, и получает либо brief,
либо ``None`` там, где органа владельцев нет (дочерние компании — решение 5
плана блока F).
"""

from __future__ import annotations

import pytest

from apps.core.services import ServiceDisabled
from apps.hr import interface
from apps.hr.services import participant_service as svc


@pytest.mark.django_db
def test_returns_exactly_the_agreed_keys():
    position, _ = svc.ensure_participant()
    brief = interface.participant_position()
    assert set(brief) == {"id", "title", "is_active"}
    assert brief == {"id": position.id, "title": "Участник (ОСУ)", "is_active": True}


@pytest.mark.django_db
def test_company_without_a_participant_body_returns_none():
    assert interface.participant_position() is None


@pytest.mark.django_db
def test_disabled_hr_refuses(monkeypatch):
    from apps.core import services as core_services

    svc.ensure_participant()
    monkeypatch.setattr(core_services, "service_status",
                        lambda name: (False, "выключено для проверки"))
    with pytest.raises(ServiceDisabled):
        interface.participant_position()

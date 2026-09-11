"""Сводка встречи: на какой минуте участник вошёл и вышел."""

from datetime import timedelta

import pytest

from apps.conference.models import ConferenceParticipant
from apps.conference.services import history_service


@pytest.mark.django_db
def test_left_offset_counts_from_session_start(session):
    ConferenceParticipant.objects.create(
        session=session, user_id=1, display_name="Пётр", peer_id="p1",
        joined_at=session.started_at + timedelta(minutes=2),
        left_at=session.started_at + timedelta(minutes=17),
        joined_offset_ms=2 * 60 * 1000)

    detail = history_service.session_detail(session)

    assert detail.participants[0].joined_offset_ms == 2 * 60 * 1000
    assert detail.participants[0].left_offset_ms == 17 * 60 * 1000


@pytest.mark.django_db
def test_participant_who_never_left_has_no_offset(session):
    ConferenceParticipant.objects.create(
        session=session, user_id=2, display_name="Анна", peer_id="p2",
        joined_at=session.started_at, left_at=None, joined_offset_ms=0)

    detail = history_service.session_detail(session)

    assert detail.participants[0].left_offset_ms is None

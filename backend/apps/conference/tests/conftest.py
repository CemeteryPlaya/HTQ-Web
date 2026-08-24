"""Общие фикстуры тестов конференций."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.conference.models import ConferenceSession, RecordingState, TranscriptState
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

INTERNAL_TOKEN = "test-internal-secret"
BASE = "/api/conference/v1"


def auth_header(user: User) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def internal(settings) -> dict:
    """Заголовок канала SFU → Django плюс включённый секрет."""
    settings.CONFERENCE_INTERNAL_TOKEN = INTERNAL_TOKEN
    return {"HTTP_X_HTQ_INTERNAL_TOKEN": INTERNAL_TOKEN}


def make_user(username: str, *, staff: bool = False) -> User:
    return User.objects.create(
        username=username, email=f"{username}@htq.test", password="x",
        status=UserStatus.ACTIVE, is_staff=staff, is_superuser=False,
    )


@pytest.fixture
def organiser(db) -> User:
    return make_user("organiser")


@pytest.fixture
def attendee(db) -> User:
    return make_user("attendee")


@pytest.fixture
def outsider(db) -> User:
    """Сотрудник, которого на встрече не было."""
    return make_user("outsider")


@pytest.fixture
def admin_user(db) -> User:
    return make_user("boss", staff=True)


@pytest.fixture
def session(db, organiser) -> ConferenceSession:
    started = timezone.now() - timedelta(hours=2)
    return ConferenceSession.objects.create(
        room_id="daily-standup",
        title="Планёрка",
        created_by_id=organiser.pk,
        created_by_name=organiser.username,
        started_at=started,
        ended_at=started + timedelta(minutes=30),
        duration_sec=1800,
        peak_participants=2,
        recording_state=RecordingState.READY,
        transcript_state=TranscriptState.READY,
        expires_at=started + timedelta(days=25),
    )

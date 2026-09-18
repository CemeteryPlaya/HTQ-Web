"""Кто видит встречу: участники и админы, больше никто.

Отказ намеренно выглядит как 404, а не 403: иначе перебором id можно было бы
выяснить, что встреча была, кто её собирал и как она называлась, — а это ровно
те сведения, которые правило доступа и закрывает.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.conference.models import ConferenceParticipant, ConferenceSession
from apps.tasks.models import CalendarEvent, CalendarEventParticipant
from htqweb.authn.jwt import issue_guest_token

from .conftest import BASE, auth_header

pytestmark = pytest.mark.django_db


@pytest.fixture
def with_attendee(session, attendee):
    ConferenceParticipant.objects.create(
        session=session, user_id=attendee.pk, display_name=attendee.username,
        peer_id="peer-2", joined_at=session.started_at,
    )
    return session


def test_organiser_sees_own_meeting(client, with_attendee, organiser):
    response = client.get(f"{BASE}/sessions/{with_attendee.pk}", **auth_header(organiser))
    assert response.status_code == 200
    assert response.json()["title"] == "Планёрка"


def test_participant_sees_the_meeting(client, with_attendee, attendee):
    response = client.get(f"{BASE}/sessions/{with_attendee.pk}", **auth_header(attendee))
    assert response.status_code == 200


def test_outsider_gets_404_not_403(client, with_attendee, outsider):
    """Сотрудник, которого на встрече не было, не должен даже узнать, что
    встреча существует."""
    response = client.get(f"{BASE}/sessions/{with_attendee.pk}", **auth_header(outsider))
    assert response.status_code == 404


def test_admin_sees_everything(client, with_attendee, admin_user):
    response = client.get(f"{BASE}/sessions/{with_attendee.pk}",
                          **auth_header(admin_user))
    assert response.status_code == 200


def test_anonymous_is_rejected(client, with_attendee):
    assert client.get(f"{BASE}/sessions/{with_attendee.pk}").status_code == 401


def test_guest_token_cannot_read_history(client, with_attendee):
    """Гостя по ссылке отбивает сам api_view: гостевой JWT имеет
    token_type="guest", а _authenticate_jwt принимает только "access"."""
    token, _ = issue_guest_token(room_id=with_attendee.room_id, display_name="Клиент")
    response = client.get(f"{BASE}/sessions/{with_attendee.pk}",
                          HTTP_AUTHORIZATION=f"Bearer {token}")
    assert response.status_code == 401


# ── список ─────────────────────────────────────────────────────────────────

def test_list_shows_only_visible_sessions(client, with_attendee, outsider, attendee):
    hidden = client.get(f"{BASE}/sessions/", **auth_header(outsider)).json()
    assert hidden["items"] == []
    assert hidden["total"] == 0

    visible = client.get(f"{BASE}/sessions/", **auth_header(attendee)).json()
    assert [row["id"] for row in visible["items"]] == [with_attendee.pk]


def test_list_envelope_survives_axios_unwrapping(client, with_attendee, attendee):
    """Конверт обязан нести поля СВЕРХ пятёрки {items,total,page,pages,limit}.

    Фронтовый unwrapPaginatedEnvelope (api/client.ts) разворачивает ответ в
    голый массив ровно при этих пяти ключах — и страница истории осталась бы
    без пагинации.
    """
    body = client.get(f"{BASE}/sessions/", **auth_header(attendee)).json()
    assert set(body) > {"items", "total", "page", "pages", "limit"}
    assert "recorded_total" in body and "active_total" in body


def test_search_filters_by_title(client, with_attendee, attendee):
    found = client.get(f"{BASE}/sessions/?q=планёрка", **auth_header(attendee)).json()
    assert found["total"] == 1

    missing = client.get(f"{BASE}/sessions/?q=ретро", **auth_header(attendee)).json()
    assert missing["total"] == 0


def test_bad_page_param_is_422(client, attendee):
    response = client.get(f"{BASE}/sessions/?page=0", **auth_header(attendee))
    assert response.status_code == 422


# ── подписанные ссылки на медиа ────────────────────────────────────────────

def test_detail_hands_out_signed_playback_url(client, with_attendee, organiser,
                                              recording_row):
    """`<video>` не отправляет Authorization, поэтому ссылка должна нести
    подпись — иначе плеер получит 401 и запись будет «не открывается»."""
    body = client.get(f"{BASE}/sessions/{with_attendee.pk}",
                      **auth_header(organiser)).json()
    assert body["playable"] is True
    assert "sig=" in body["recording_url"] and "exp=" in body["recording_url"]
    assert body["download_url"].endswith("&download=1")


def test_recording_without_signature_or_token_is_refused(client, with_attendee,
                                                         recording_row):
    response = client.get(f"{BASE}/sessions/{with_attendee.pk}/recording")
    assert response.status_code in (401, 404)


def test_signature_of_one_meeting_does_not_open_another(client, with_attendee,
                                                        organiser, recording_row,
                                                        db):
    """Подпись привязана к конкретному объекту — иначе одна выданная ссылка
    открывала бы все записи подряд."""
    from apps.conference.services import signing

    other_url = signing.recording_url(with_attendee.pk)
    query = other_url.split("?", 1)[1]

    response = client.get(f"{BASE}/sessions/{with_attendee.pk + 999}/recording?{query}")
    assert response.status_code in (401, 404)


@pytest.fixture
def recording_row(with_attendee):
    from apps.conference.models import ConferenceRecording, RecordingKind

    return ConferenceRecording.objects.create(
        session=with_attendee, kind=RecordingKind.COMPOSED,
        storage_path="conference/sessions/2026/08/1/recording.mp4",
        size=1024, duration_sec=1800, mime="video/mp4",
    )


def test_purged_recording_answers_404_with_a_reason(client, with_attendee, organiser,
                                                    recording_row):
    from apps.conference.models import RecordingState

    with_attendee.recording_state = RecordingState.PURGED
    with_attendee.purged_at = timezone.now()
    with_attendee.save(update_fields=["recording_state", "purged_at"])

    response = client.get(f"{BASE}/sessions/{with_attendee.pk}/recording",
                          **auth_header(organiser))
    assert response.status_code == 404
    assert "сроку хранения" in response.json()["detail"]


def test_participant_count_is_not_narrowed_by_the_visibility_filter(
        client, with_attendee, attendee):
    """Счётчик участников показывает ВСЕХ, а не только смотрящего.

    Ловушка Django: фильтр по связи (`participants__user_id=...`) создаёт
    JOIN, который переиспользуется последующим `annotate(Count(...))`. Если
    видимость строить фильтром, а не подзапросом, у рядового сотрудника на
    каждой встрече стояло бы «1 участник» — тихо и правдоподобно.
    """
    ConferenceParticipant.objects.create(
        session=with_attendee, user_id=None, display_name="Гость",
        peer_id="peer-3", is_guest=True, joined_at=with_attendee.started_at,
    )
    ConferenceParticipant.objects.create(
        session=with_attendee, user_id=999, display_name="Третий",
        peer_id="peer-4", joined_at=with_attendee.started_at,
    )

    body = client.get(f"{BASE}/sessions/", **auth_header(attendee)).json()
    assert body["items"][0]["participant_count"] == 3


# ── третье основание видимости: приглашение из календаря ───────────────────

def test_invitee_sees_live_session_before_joining(client, attendee):
    """Приглашённый, который ещё не заходил, обязан видеть идущую встречу.

    До появления связи с календарём видимость держалась на факте участия —
    то есть узнать о встрече можно было, только уже находясь на ней.
    """
    start = timezone.now()
    event = CalendarEvent.objects.create(
        title="Планёрка", start_at=start, end_at=start + timedelta(hours=1),
        event_type="conference", conference_room_id="room-live",
        creator_id=999, is_all_day=False)
    CalendarEventParticipant.objects.create(event=event, user_id=attendee.pk)
    live = ConferenceSession.objects.create(
        room_id="room-live", title="Планёрка", created_by_id=999,
        created_by_name="boss", started_at=start,
        expires_at=start + timedelta(days=25), calendar_event_id=event.pk)

    response = client.get(f"{BASE}/sessions/", **auth_header(attendee))

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [live.pk]


def test_outsider_still_gets_404(client, outsider):
    start = timezone.now()
    event = CalendarEvent.objects.create(
        title="Планёрка", start_at=start, end_at=start + timedelta(hours=1),
        event_type="conference", conference_room_id="room-closed",
        creator_id=999, is_all_day=False)
    hidden = ConferenceSession.objects.create(
        room_id="room-closed", title="Планёрка", created_by_id=999,
        created_by_name="boss", started_at=start,
        expires_at=start + timedelta(days=25), calendar_event_id=event.pk)

    response = client.get(f"{BASE}/sessions/{hidden.pk}", **auth_header(outsider))

    assert response.status_code == 404


def test_disabled_tasks_app_does_not_break_the_list(client, attendee, monkeypatch):
    """Выключенный сосед — деградация до прежних оснований, а не 500."""
    from apps.conference.services import access

    def boom(*args, **kwargs):
        from apps.core.services import ServiceDisabled
        raise ServiceDisabled("tasks", "выключено")

    monkeypatch.setattr(
        "apps.tasks.interface.list_user_conference_events", boom)

    response = client.get(f"{BASE}/sessions/", **auth_header(attendee))

    assert response.status_code == 200


def test_unexpected_calendar_error_is_not_silently_swallowed(client, attendee, monkeypatch):
    """Настоящая поломка соседа (не ``ServiceDisabled``) не маскируется под
    предусмотренную деградацию.

    В отличие от выключенной аппки (см. предыдущий тест), это НЕ ожидаемая
    деградация: сосед включён, но упал по своей причине. Под pytest режим
    строгий (``FALLBACK_MODE=strict``), поэтому ``expected=False`` бросает
    ``FallbackNotAllowed`` — она долетает до общего `except Exception` в
    ``api_view`` и превращается в 500. Так и задумано: сломанный сосед должен
    быть громким у разработчика и попадать в алерт на проде (метка
    ``expected="false"``), а не тихо оседать в INFO-логе рядом с
    предусмотренными деградациями.
    """
    def boom(*args, **kwargs):
        raise RuntimeError("сосед сломался")

    monkeypatch.setattr(
        "apps.tasks.interface.list_user_conference_events", boom)

    response = client.get(f"{BASE}/sessions/", **auth_header(attendee))

    assert response.status_code == 500

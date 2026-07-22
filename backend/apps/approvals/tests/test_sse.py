"""SSE stream — ``/api/requests/v1/stream``.

The ASGI surface of Поток B (PLAN.md §1.4, §6.2). Redis is not stood up for
the suite, so the transport is exercised by injecting a subscriber; the wire
format and the auth rules are pure functions and tested directly.
"""

import asyncio
import json

import pytest
from asgiref.sync import async_to_sync
from django.test import AsyncClient, Client

from apps.core.models import ServiceStatus
from apps.approvals.services import sse

from .helpers import BASE, auth, token

STREAM = f"{BASE}/stream"


# ── wire format ─────────────────────────────────────────────────────────

def test_format_event_renders_an_sse_frame():
    raw = json.dumps({"event": "request_assigned", "request_id": 4})
    frame = sse.format_event(raw)
    assert frame.startswith("event: request_assigned\n")
    assert frame.endswith("\n\n")
    # data carries the original JSON verbatim, so the client parses one object
    assert f"data: {raw}\n" in frame


def test_format_event_defaults_the_event_name():
    assert sse.format_event(json.dumps({"request_id": 1})).startswith(
        "event: message\n")


@pytest.mark.parametrize("raw", ["not json", "", "[1,2]", "null"])
def test_format_event_drops_unparseable_payloads(raw):
    """A stray publish must not break the stream for a connected client."""
    assert sse.format_event(raw) is None


def test_format_event_sanitises_the_event_name():
    """SSE fields are newline-delimited: an unescaped newline in the name
    would let a publisher forge additional frames."""
    frame = sse.format_event(json.dumps({"event": "evil\ndata: forged"}))
    assert frame.count("\ndata: ") == 1
    assert "event: evil data_ forged\n" in frame


def test_heartbeat_and_opening_frames_are_comments():
    assert sse.heartbeat().startswith(":")
    assert sse.opening_frame().startswith(":")


# ── authentication ──────────────────────────────────────────────────────

def test_authenticate_accepts_the_query_token():
    assert sse.authenticate(query_token=token(), authorization=None) == 7


def test_authenticate_accepts_a_bearer_header():
    assert sse.authenticate(query_token=None,
                            authorization=f"Bearer {token()}") == 7


def test_query_token_wins_over_the_header():
    assert sse.authenticate(query_token=token(user_id=99, sub="99"),
                            authorization=f"Bearer {token()}") == 99


@pytest.mark.parametrize("query_token,authorization", [
    (None, None),
    (None, "Basic abc"),
    ("garbage", None),
    (None, "Bearer garbage"),
])
def test_authenticate_rejects_bad_credentials(query_token, authorization):
    with pytest.raises(sse.StreamAuthError):
        sse.authenticate(query_token=query_token, authorization=authorization)


def test_refresh_token_cannot_open_a_stream():
    """A 7-day refresh token must not buy a long-lived connection."""
    with pytest.raises(sse.StreamAuthError):
        sse.authenticate(query_token=token(token_type="refresh"),
                         authorization=None)


# ── the generator ───────────────────────────────────────────────────────

def _drain(agen):
    async def run():
        return [chunk async for chunk in agen]
    return asyncio.run(run())


def test_event_stream_opens_then_forwards_frames():
    async def fake(channel):
        yield json.dumps({"event": "approved_final", "request_id": 1})
        yield None                                   # idle tick
        yield json.dumps({"event": "rejected", "request_id": 2})

    chunks = _drain(sse.event_stream("c", subscriber=fake))
    assert chunks[0] == sse.opening_frame()
    assert chunks[1].startswith("event: approved_final\n")
    assert chunks[2] == sse.heartbeat()
    assert chunks[3].startswith("event: rejected\n")


def test_event_stream_skips_a_bad_payload_and_keeps_going():
    async def fake(channel):
        yield "}{ not json"
        yield json.dumps({"event": "ok"})

    chunks = _drain(sse.event_stream("c", subscriber=fake))
    assert len(chunks) == 2                          # opening + the good one
    assert chunks[1].startswith("event: ok\n")


def test_event_stream_survives_a_failing_source():
    """A broken subscriber ends the stream; it must not raise out of the
    response body and take the worker with it."""
    async def broken(channel):
        yield json.dumps({"event": "first"})
        raise RuntimeError("redis died")

    chunks = _drain(sse.event_stream("c", subscriber=broken))
    assert chunks[1].startswith("event: first\n")


def test_cancellation_propagates():
    """A disconnecting client must actually stop the generator, not be
    swallowed by the broad except."""
    async def hangs(channel):
        raise asyncio.CancelledError
        yield  # pragma: no cover

    with pytest.raises(asyncio.CancelledError):
        _drain(sse.event_stream("c", subscriber=hangs))


# ── the endpoint ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_stream_requires_a_token():
    resp = Client().get(STREAM)
    assert resp.status_code == 401
    assert resp.json() == {"detail": "missing token"}


@pytest.mark.django_db
def test_stream_rejects_a_bad_token():
    resp = Client().get(f"{STREAM}?token=garbage")
    assert resp.status_code == 401
    assert "invalid token" in resp.json()["detail"]


@pytest.mark.django_db
def test_stream_rejects_a_non_get_method():
    assert Client().post(f"{STREAM}?token={token()}").status_code == 405


@pytest.mark.django_db
def test_stream_is_gated_by_the_service_switch():
    """The gate matches on URL prefix before resolution, so the stream is
    refused with the same 503 envelope as every other route."""
    ServiceStatus.objects.update_or_create(app_label="approvals",
                                           defaults={"enabled": False})
    resp = Client().get(f"{STREAM}?token={token()}")
    assert resp.status_code == 503
    assert resp.json()["service"] == "approvals"


@pytest.mark.django_db
def test_stream_accepts_both_slash_spellings_and_sets_streaming_headers(
        monkeypatch):
    """Headers matter operationally: without ``X-Accel-Buffering: no`` nginx
    holds every frame until the response ends, which for a stream is never."""
    async def fake(channel):
        yield json.dumps({"event": "hello"})

    monkeypatch.setattr(sse, "default_subscriber", fake)

    async def call(path):
        return await AsyncClient().get(path)

    for path in (f"{STREAM}?token={token()}", f"{BASE}/stream/?token={token()}"):
        resp = async_to_sync(call)(path)
        assert resp.status_code == 200
        assert resp["Content-Type"] == "text/event-stream"
        assert resp["Cache-Control"] == "no-cache"
        assert resp["X-Accel-Buffering"] == "no"


@pytest.mark.django_db
def test_stream_body_carries_the_published_events(monkeypatch):
    async def fake(channel):
        assert channel == "requests:user:7"          # the caller's own channel
        yield json.dumps({"event": "request_assigned", "request_id": 3})

    monkeypatch.setattr(sse, "default_subscriber", fake)

    async def call():
        resp = await AsyncClient().get(f"{STREAM}?token={token()}")
        return b"".join([chunk async for chunk in resp.streaming_content])

    body = async_to_sync(call)().decode()
    assert body.startswith(": connected\n\n")
    assert "event: request_assigned\n" in body

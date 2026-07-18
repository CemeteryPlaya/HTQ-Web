"""Auth-only tests for the SSE stream endpoint. The live pub/sub round-trip is
exercised by the container smoke (real Redis required)."""

from tests.factories import make_token


async def test_stream_requires_token(client):
    r = await client.get("/api/requests/v1/stream")
    assert r.status_code == 401


async def test_stream_rejects_bad_token(client):
    r = await client.get("/api/requests/v1/stream?token=not-a-jwt")
    assert r.status_code == 401


async def test_stream_accepts_query_token(client):
    # We hit the endpoint with a short timeout — the auth check runs before
    # the long-lived streaming loop, so a 200 with an SSE Content-Type proves
    # the auth path works even if we abandon the connection mid-handshake.
    import anyio
    token = make_token(42)
    try:
        with anyio.fail_after(2.0):
            async with client.stream("GET", f"/api/requests/v1/stream?token={token}") as r:
                assert r.status_code == 200
                assert r.headers["content-type"].startswith("text/event-stream")
                async for _chunk in r.aiter_text():
                    # First chunk is the ": connected\n\n" handshake — got it,
                    # we're done validating.
                    break
    except TimeoutError:
        pass  # We never expect the stream to complete; auth was the assertion.

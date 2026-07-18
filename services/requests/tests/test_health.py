async def test_health_liveness(client):
    resp = await client.get("/health/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "requests-service"


async def test_readiness_reports_database_key(client):
    resp = await client.get("/health/ready/")
    assert resp.status_code == 200
    body = resp.json()
    # readiness must actually probe the DB, not return the placeholder "pending"
    assert body["database"] in ("ok", "error")

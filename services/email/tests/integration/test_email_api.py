"""Integration tests for Email API."""

import pytest
from datetime import datetime, timezone, timedelta
from tests.conftest import user_headers

from app.models.email import OAuthToken
from app.services.crypto import crypto_service

@pytest.mark.asyncio
async def test_dlp_scanner():
    from app.services.dlp_scanner import dlp_scanner
    assert dlp_scanner.scan("Here is my ssn: 123-45-6789") is True
    assert dlp_scanner.scan("Just a normal email.") is False


@pytest.mark.asyncio
async def test_email_api_flow(client, session):
    # Setup OAuth Token manually
    enc_token = crypto_service.encrypt("fake_access_token")
    token = OAuthToken(
        user_id=2,
        provider="google",
        provider_account_id="user@example.com",
        encrypted_access_token=enc_token,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
    )
    session.add(token)
    await session.commit()
    await session.refresh(token)

    # List Accounts
    resp = await client.get("/api/email/v1/oauth/accounts", headers=user_headers())
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    # Send Email
    resp = await client.post(
        "/api/email/v1/send",
        json={
            "account_id": token.id,
            "to_recipients": [{"email": "test@domain.com"}],
            "subject": "Hello FastAPI",
            "body_text": "This is a test message"
        },
        headers=user_headers()
    )
    assert resp.status_code == 202
    
    # List sent folder
    resp = await client.get("/api/email/v1/folder/sent", headers=user_headers())
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["subject"] == "Hello FastAPI"

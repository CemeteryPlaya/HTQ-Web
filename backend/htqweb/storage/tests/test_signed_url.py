"""Tests for htqweb.storage.signed_url — HMAC-signed URL helper.

Ported faithfully from services/cms/app/services/signed_url.py: same payload
layout (``f"{resource_id}|{exp}"``), same hash (HMAC-SHA256, base64 urlsafe,
padding stripped), same query param names (``sig``, ``exp``). No network, no
S3 — this module is pure stdlib (hmac/base64/time).
"""
from __future__ import annotations

import time

from django.test import override_settings

from htqweb.storage import signed_url


@override_settings(NEWS_SIGNED_URL_SECRET="test-secret", NEWS_SIGNED_URL_TTL=3600)
def test_fresh_signature_verifies():
    sig, exp = signed_url.sign("news/1/attachments/2_file.pdf")
    assert signed_url.verify("news/1/attachments/2_file.pdf", sig, exp) is True


@override_settings(NEWS_SIGNED_URL_SECRET="test-secret", NEWS_SIGNED_URL_TTL=3600)
def test_expired_exp_is_rejected():
    resource_id = "news/1/cover.png"
    expired_exp = int(time.time()) - 5
    sig = signed_url._digest(resource_id, expired_exp)
    assert signed_url.verify(resource_id, sig, expired_exp) is False


@override_settings(NEWS_SIGNED_URL_SECRET="test-secret", NEWS_SIGNED_URL_TTL=3600)
def test_tampered_signature_is_rejected():
    resource_id = "news/1/cover.png"
    sig, exp = signed_url.sign(resource_id)
    tampered = sig[:-1] + ("A" if sig[-1] != "A" else "B")
    assert signed_url.verify(resource_id, tampered, exp) is False


@override_settings(NEWS_SIGNED_URL_SECRET="test-secret", NEWS_SIGNED_URL_TTL=3600)
def test_signature_for_different_resource_is_rejected():
    sig, exp = signed_url.sign("news/1/cover.png")
    # Same signature/exp, but presented for a different resource (path/key) —
    # must not verify against a key it wasn't signed for.
    assert signed_url.verify("news/2/cover.png", sig, exp) is False


@override_settings(NEWS_SIGNED_URL_SECRET="test-secret", NEWS_SIGNED_URL_TTL=3600)
def test_verify_rejects_missing_sig_or_exp():
    assert signed_url.verify("news/1/cover.png", "", 9999999999) is False
    assert signed_url.verify("news/1/cover.png", "somesig", 0) is False


@override_settings(NEWS_SIGNED_URL_SECRET="test-secret", NEWS_SIGNED_URL_TTL=3600)
def test_sign_respects_explicit_ttl_over_default():
    _, exp_default = signed_url.sign("news/1/cover.png")
    _, exp_short = signed_url.sign("news/1/cover.png", ttl=10)
    assert exp_short < exp_default


@override_settings(NEWS_SIGNED_URL_SECRET="test-secret", NEWS_SIGNED_URL_TTL=3600)
def test_signed_query_format():
    query = signed_url.signed_query("news/1/cover.png")
    assert query.startswith("sig=")
    assert "&exp=" in query
    sig_part, exp_part = query.split("&")
    sig = sig_part.removeprefix("sig=")
    exp = int(exp_part.removeprefix("exp="))
    assert signed_url.verify("news/1/cover.png", sig, exp) is True


@override_settings(NEWS_SIGNED_URL_SECRET="secret-a")
def test_signature_depends_on_secret():
    sig, exp = signed_url.sign("news/1/cover.png")
    with override_settings(NEWS_SIGNED_URL_SECRET="secret-b"):
        assert signed_url.verify("news/1/cover.png", sig, exp) is False

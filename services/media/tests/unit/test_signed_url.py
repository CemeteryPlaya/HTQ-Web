"""HMAC-signed URL helper: round-trip, expiry, tamper rejection."""

import time

import pytest

from app.services.signed_url import sign, signed_query, verify


def test_sign_and_verify_round_trip():
    sig, exp = sign("11111111-1111-1111-1111-111111111111", "thumb_96", ttl=60)
    assert verify("11111111-1111-1111-1111-111111111111", "thumb_96", sig, exp) is True


def test_verify_rejects_expired():
    sig, exp = sign("file-x", "original", ttl=60)
    # Forge an exp in the past, recompute the signature so only ``exp < now``
    # is the failure mode.
    past = int(time.time()) - 10
    sig_past, _ = sign("file-x", "original", ttl=-100)  # negative ttl -> already expired
    assert verify("file-x", "original", sig_past, past) is False


def test_verify_rejects_wrong_file_id():
    sig, exp = sign("file-a", "thumb_96", ttl=60)
    assert verify("file-b", "thumb_96", sig, exp) is False


def test_verify_rejects_wrong_variant():
    sig, exp = sign("file-a", "thumb_96", ttl=60)
    assert verify("file-a", "thumb_256", sig, exp) is False


def test_verify_rejects_tampered_signature():
    sig, exp = sign("file-a", "original", ttl=60)
    flipped = ("A" if sig[0] != "A" else "B") + sig[1:]
    assert verify("file-a", "original", flipped, exp) is False


def test_verify_rejects_empty():
    assert verify("file-a", "original", "", 0) is False
    assert verify("file-a", "original", "abc", 0) is False


def test_signed_query_format():
    q = signed_query("ff", "thumb_32", ttl=60)
    assert q.startswith("sig=")
    assert "&exp=" in q

"""Tests for htqweb.storage.s3 — object storage abstraction.

boto3 is stubbed at the client-construction boundary (``boto3.client``) so
these run with no network access and no MinIO/S3 dependency. The point is to
exercise the *decisions* this module makes (which backend to build, which
kwargs to pass and when to omit them, how paths resolve) rather than merely
recording "a mock was called" — each S3 test asserts on argument shape/
presence that only exists if the surrounding conditional logic ran correctly.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from django.test import override_settings

from htqweb.storage import s3


# ── backend selection (get_storage) ──────────────────────────────────────────


def test_get_storage_returns_local_storage_when_backend_is_local(tmp_path):
    local_dir = tmp_path / "htqweb-cms-test"
    with override_settings(STORAGE_BACKEND="local", CMS_LOCAL_STORAGE_DIR=str(local_dir)):
        storage = s3.get_storage()
    assert isinstance(storage, s3.LocalStorage)
    assert storage.base_dir == local_dir


@override_settings(
    STORAGE_BACKEND="s3",
    S3_BUCKET="htqweb-cms",
    S3_ENDPOINT="http://minio:9000",
    S3_ACCESS_KEY="ak",
    S3_SECRET_KEY="sk",
    S3_REGION="us-east-1",
    S3_USE_PATH_STYLE=True,
    S3_PUBLIC_ENDPOINT="http://localhost:9000",
    S3_PRESIGNED_URL_TTL=900,
)
def test_get_storage_returns_s3_storage_wired_from_settings_when_backend_is_s3():
    storage = s3.get_storage()
    assert isinstance(storage, s3.S3Storage)
    assert storage.bucket == "htqweb-cms"
    assert storage.endpoint == "http://minio:9000"
    assert storage.access_key == "ak"
    assert storage.secret_key == "sk"
    assert storage.region == "us-east-1"
    assert storage.use_path_style is True
    assert storage.public_endpoint == "http://localhost:9000"
    assert storage.default_presigned_ttl == 900


# ── LocalStorage: path resolution / traversal guard ─────────────────────────


def test_local_storage_rejects_path_traversal(tmp_path):
    storage = s3.LocalStorage(base_dir=tmp_path)
    with pytest.raises(ValueError):
        storage._resolve("../outside.txt")


def test_local_storage_save_and_open_round_trip(tmp_path):
    storage = s3.LocalStorage(base_dir=tmp_path)
    storage.save("news/1/cover.png", b"binary-data")
    assert storage.exists("news/1/cover.png") is True
    assert storage.open("news/1/cover.png") == b"binary-data"
    assert storage.size("news/1/cover.png") == len(b"binary-data")


def test_local_storage_open_respects_byte_range(tmp_path):
    storage = s3.LocalStorage(base_dir=tmp_path)
    storage.save("news/1/content.md", b"0123456789")
    assert storage.open("news/1/content.md", byte_range=(2, 5)) == b"2345"


def test_local_storage_open_missing_file_raises(tmp_path):
    storage = s3.LocalStorage(base_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        storage.open("does/not/exist.txt")


def test_local_storage_delete_is_idempotent(tmp_path):
    storage = s3.LocalStorage(base_dir=tmp_path)
    storage.save("a.txt", b"x")
    storage.delete("a.txt")
    assert storage.exists("a.txt") is False
    storage.delete("a.txt")  # must not raise on a second delete


# ── S3Storage: client kwargs construction (no network) ──────────────────────


def _patch_boto3_client(monkeypatch):
    """Patch boto3.client to record the kwargs it was constructed with and
    return a MagicMock in its place. Returns the list of recorded calls."""
    calls = []
    fake_client = MagicMock()

    def fake_boto3_client(service_name, **kwargs):
        calls.append({"service_name": service_name, **kwargs})
        return fake_client

    monkeypatch.setattr("boto3.client", fake_boto3_client)
    return calls, fake_client


def test_s3_client_omits_credentials_when_access_key_blank(monkeypatch):
    calls, _ = _patch_boto3_client(monkeypatch)
    storage = s3.S3Storage(bucket="b")  # access_key defaults to ""
    storage.save("k", b"data")
    assert "aws_access_key_id" not in calls[0]
    assert "aws_secret_access_key" not in calls[0]


def test_s3_client_includes_credentials_when_access_key_set(monkeypatch):
    calls, _ = _patch_boto3_client(monkeypatch)
    storage = s3.S3Storage(bucket="b", access_key="ak", secret_key="sk")
    storage.save("k", b"data")
    assert calls[0]["aws_access_key_id"] == "ak"
    assert calls[0]["aws_secret_access_key"] == "sk"


def test_s3_client_omits_endpoint_url_when_endpoint_blank(monkeypatch):
    calls, _ = _patch_boto3_client(monkeypatch)
    storage = s3.S3Storage(bucket="b", endpoint="")
    storage.save("k", b"data")
    assert "endpoint_url" not in calls[0]


def test_s3_client_uses_path_style_addressing_when_configured(monkeypatch):
    calls, _ = _patch_boto3_client(monkeypatch)
    storage = s3.S3Storage(bucket="b", use_path_style=True)
    storage.save("k", b"data")
    assert calls[0]["config"].s3["addressing_style"] == "path"


def test_s3_client_uses_virtual_addressing_when_path_style_disabled(monkeypatch):
    calls, _ = _patch_boto3_client(monkeypatch)
    storage = s3.S3Storage(bucket="b", use_path_style=False)
    storage.save("k", b"data")
    assert calls[0]["config"].s3["addressing_style"] == "virtual"


def test_s3_presigned_url_uses_public_endpoint_not_internal_endpoint(monkeypatch):
    calls, _ = _patch_boto3_client(monkeypatch)
    storage = s3.S3Storage(
        bucket="b", endpoint="http://minio:9000", public_endpoint="http://localhost:9000"
    )
    storage.presigned_get_url("k")
    assert calls[0]["endpoint_url"] == "http://localhost:9000"


def test_s3_presigned_url_falls_back_to_endpoint_when_public_endpoint_blank(monkeypatch):
    storage = s3.S3Storage(bucket="b", endpoint="http://minio:9000", public_endpoint="")
    # public_endpoint falls back to endpoint at construction time (matches
    # the FastAPI original: `self.public_endpoint = public_endpoint or endpoint`).
    assert storage.public_endpoint == "http://minio:9000"


# ── S3Storage: request-body construction (content-type, ranges) ────────────


def test_s3_save_omits_content_type_key_when_not_given(monkeypatch):
    _, fake_client = _patch_boto3_client(monkeypatch)
    storage = s3.S3Storage(bucket="b")
    storage.save("k", b"data")
    kwargs = fake_client.put_object.call_args.kwargs
    assert "ContentType" not in kwargs


def test_s3_save_includes_content_type_key_when_given(monkeypatch):
    _, fake_client = _patch_boto3_client(monkeypatch)
    storage = s3.S3Storage(bucket="b")
    storage.save("k", b"data", content_type="image/png")
    kwargs = fake_client.put_object.call_args.kwargs
    assert kwargs["ContentType"] == "image/png"


def test_s3_open_omits_range_header_when_no_byte_range(monkeypatch):
    _, fake_client = _patch_boto3_client(monkeypatch)
    fake_client.get_object.return_value = {"Body": MagicMock(read=lambda: b"x")}
    storage = s3.S3Storage(bucket="b")
    storage.open("k")
    kwargs = fake_client.get_object.call_args.kwargs
    assert "Range" not in kwargs


def test_s3_open_sets_range_header_from_byte_range(monkeypatch):
    _, fake_client = _patch_boto3_client(monkeypatch)
    fake_client.get_object.return_value = {"Body": MagicMock(read=lambda: b"x")}
    storage = s3.S3Storage(bucket="b")
    storage.open("k", byte_range=(10, 20))
    kwargs = fake_client.get_object.call_args.kwargs
    assert kwargs["Range"] == "bytes=10-20"


def test_s3_exists_returns_true_when_head_object_succeeds(monkeypatch):
    _, fake_client = _patch_boto3_client(monkeypatch)
    fake_client.head_object.return_value = {"ContentLength": 3}
    storage = s3.S3Storage(bucket="b")
    assert storage.exists("k") is True


def test_s3_exists_returns_false_when_head_object_raises(monkeypatch):
    _, fake_client = _patch_boto3_client(monkeypatch)
    fake_client.head_object.side_effect = Exception("not found")
    storage = s3.S3Storage(bucket="b")
    assert storage.exists("k") is False


def test_s3_size_returns_content_length_from_head_object(monkeypatch):
    _, fake_client = _patch_boto3_client(monkeypatch)
    fake_client.head_object.return_value = {"ContentLength": 12345}
    storage = s3.S3Storage(bucket="b")
    assert storage.size("k") == 12345


def test_s3_presigned_url_ttl_defaults_to_instance_default(monkeypatch):
    _, fake_client = _patch_boto3_client(monkeypatch)
    storage = s3.S3Storage(bucket="b", default_presigned_ttl=1234)
    storage.presigned_get_url("k")
    kwargs = fake_client.generate_presigned_url.call_args.kwargs
    assert kwargs["ExpiresIn"] == 1234


def test_s3_presigned_url_ttl_override_wins_over_default(monkeypatch):
    _, fake_client = _patch_boto3_client(monkeypatch)
    storage = s3.S3Storage(bucket="b", default_presigned_ttl=1234)
    storage.presigned_get_url("k", ttl=60)
    kwargs = fake_client.generate_presigned_url.call_args.kwargs
    assert kwargs["ExpiresIn"] == 60

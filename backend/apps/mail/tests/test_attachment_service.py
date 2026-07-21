"""Вложения писем через apps.media_files.interface (mail-messages-brief.md
п.4 "РЕШЕНИЯ" пункт 4 — media.interface, НЕ прямой S3, duck-typing на
ValueError.status_code/detail для исключений media).

Storage мокается тем же паттерном, что apps/hr/tests/test_department_files_api.py
(``_FakeStorage`` + monkeypatch ``upload_service.get_storage``) — реальный
S3/MinIO недоступен в тестовом окружении.
"""
from __future__ import annotations

import datetime

import pytest

from apps.mail.models import EmailAttachment, EmailMessage
from apps.mail.services.attachment_service import (
    AttachmentUploadRejected,
    attachment_url,
    store_attachment,
)


class _FakeStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def save(self, path, data, content_type=None):
        self.objects[path] = data

    def open(self, path, byte_range=None):
        data = self.objects[path]
        if byte_range is not None:
            start, end = byte_range
            return data[start : end + 1]
        return data

    def delete(self, path):
        self.objects.pop(path, None)

    def exists(self, path):
        return path in self.objects

    def size(self, path):
        return len(self.objects[path])


@pytest.fixture(autouse=True)
def fake_media_storage(monkeypatch):
    from apps.media_files.services import upload_service as media_upload_service

    storage = _FakeStorage()
    monkeypatch.setattr(media_upload_service, "get_storage", lambda bucket=None: storage)
    return storage


def _message() -> EmailMessage:
    return EmailMessage.objects.create(
        user_id=1, sender_email="from@example.com",
        date=datetime.datetime.now(datetime.timezone.utc),
    )


@pytest.mark.django_db
def test_store_attachment_creates_row_via_media_interface():
    msg = _message()
    att = store_attachment(
        msg, data=b"%PDF-1.4 fake pdf bytes", filename="doc.pdf",
        mime="application/pdf", owner_id=1,
    )
    assert isinstance(att, EmailAttachment)
    assert att.message_id == msg.id
    assert att.filename == "doc.pdf"
    assert att.mime_type == "application/pdf"
    assert att.size == len(b"%PDF-1.4 fake pdf bytes")
    assert att.file_metadata_id is not None

    msg.refresh_from_db()
    assert msg.has_attachments is True


@pytest.mark.django_db
def test_store_attachment_uses_generic_scope_not_restricted():
    from apps.media_files.models import FileMetadata

    msg = _message()
    att = store_attachment(
        msg, data=b"hello world", filename="note.txt", mime="text/plain", owner_id=7,
    )
    meta = FileMetadata.objects.get(id=att.file_metadata_id)
    assert meta.scope == "generic"
    assert meta.owner_id == 7
    assert meta.is_public is False  # generic scope defaults private


@pytest.mark.django_db
def test_store_attachment_rejects_via_duck_typed_value_error(monkeypatch):
    """media_files raises a ``ValueError`` subclass (status_code/detail
    attrs) for rejected uploads — asserted here via duck-typing, without
    importing that class (test_app_isolation.py forbids it)."""
    from apps.media_files import interface as media_interface

    def _boom(**kwargs):
        raise ValueError("simulated rejection")

    monkeypatch.setattr(media_interface, "store_file", _boom)

    msg = _message()
    with pytest.raises(AttachmentUploadRejected) as exc_info:
        store_attachment(
            msg, data=b"x", filename="f.bin",
            mime="application/octet-stream", owner_id=1,
        )
    assert exc_info.value.status_code == 400
    assert "simulated rejection" in exc_info.value.detail


@pytest.mark.django_db
def test_attachment_url_none_when_file_metadata_id_missing():
    msg = _message()
    att = EmailAttachment.objects.create(
        message=msg, filename="a.txt", mime_type="text/plain", size=1,
    )
    assert attachment_url(att) is None


@pytest.mark.django_db
def test_attachment_url_resolves_via_media_interface():
    msg = _message()
    att = store_attachment(
        msg, data=b"hello", filename="a.txt", mime="text/plain", owner_id=1,
    )
    url = attachment_url(att)
    assert url is not None
    assert str(att.file_metadata_id) in url or url  # non-empty, resolvable

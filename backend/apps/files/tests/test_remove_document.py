"""``interface.remove_document`` — удаление документа из кода владельца (портал
поставщика tender, T3.4): те же правила, что у ручки удаления, без ``token``."""

from __future__ import annotations

import uuid

import pytest

from apps.files import interface as files
from apps.files.models import FileEvent, FileObject
from apps.media_files.models import FileMetadata

from .helpers import AUTHOR, OWNER, PDF
from .testapp.models import ProbeFolder

pytestmark = pytest.mark.django_db


def _attach(probe) -> dict:
    return files.attach_bytes(OWNER, probe.pk, file_type="probe.kp", data=PDF,
                              filename="kp.pdf", mime="application/pdf", actor_id=AUTHOR)


def test_never_sent_owner_loses_the_document_physically(django_capture_on_commit_callbacks):
    probe = ProbeFolder.objects.create()
    out = _attach(probe)
    media_id = FileObject.objects.get(pk=out["id"]).media_file_id
    with django_capture_on_commit_callbacks(execute=True):
        files.remove_document(OWNER, probe.pk, out["document_id"], actor_id=AUTHOR,
                              ip="10.0.0.9", user_agent="portal/1")
    assert not FileObject.objects.filter(owner_id=probe.pk).exists()
    # Байты вернулись в media после коммита.
    assert FileMetadata.objects.get(pk=media_id).deleted_at is not None
    event = FileEvent.objects.filter(owner_id=str(probe.pk), event="file_deleted").get()
    assert (event.actor_id, event.ip, event.user_agent) == (AUTHOR, "10.0.0.9", "portal/1")
    assert event.payload["physical"] is True


def test_sent_owner_keeps_the_rows_marked_deleted():
    probe = ProbeFolder.objects.create()
    out = _attach(probe)
    ProbeFolder.objects.filter(pk=probe.pk).update(
        sent_at="2026-10-01T00:00:00Z", status=ProbeFolder.SENT)
    files.remove_document(OWNER, probe.pk, out["document_id"], actor_id=AUTHOR)
    row = FileObject.objects.get(pk=out["id"])
    assert row.deleted_at is not None and row.deleted_by_id == AUTHOR
    assert files.live_document_count(OWNER, probe.pk) == 0
    # Повтор ничего не меняет и не пишет второе событие.
    files.remove_document(OWNER, probe.pk, out["document_id"], actor_id=AUTHOR)
    assert FileEvent.objects.filter(owner_id=str(probe.pk), event="file_deleted").count() == 1


def test_unknown_or_foreign_document_is_404():
    probe, other = ProbeFolder.objects.create(), ProbeFolder.objects.create()
    out = _attach(other)
    for document_id in (uuid.uuid4(), "не-uuid", out["document_id"]):
        with pytest.raises(files.FilesError) as exc:
            files.remove_document(OWNER, probe.pk, document_id, actor_id=AUTHOR)
        assert exc.value.status == 404
    assert FileObject.objects.filter(owner_id=other.pk).exists()

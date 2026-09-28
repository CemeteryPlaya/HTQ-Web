"""Загрузка и скачивание из кода владельца — ``interface.attach_bytes``,
``replace_bytes``, ``download_link``, ``find_version``.

Владелец (документ модуля БЗО) принимает файл своей ручкой и хранит его
здесь. Проверяется, что это тот же путь, что HTTP-загрузка: справочник
форматов и размеров, квота владельца, версии по ТЗ, журнал ``FileEvent`` и
лента владельца, папка в хранилище — и что файл после этого виден на панели
``/api/files/v1``. Отличия от HTTP — тоже здесь: права на объект не
спрашиваются (их проверил владелец), а откат сохранённых байтов —
физический, без «сирот» в хранилище.
"""

from __future__ import annotations

import dataclasses
import hashlib
import uuid

import pytest
from django.test import Client

from apps.files import interface as files
from apps.files.models import FileEvent, FileObject, FileType
from apps.files.services import registry
from apps.media_files.models import FileMetadata

from .helpers import AUTHOR, OWNER, PDF, UUID_OWNER, folder
from .testapp import hooks
from .testapp.models import ProbeFolder, UuidProbeFolder

pytestmark = pytest.mark.django_db


def _attach(probe, **over) -> dict:
    kwargs = {"file_type": "probe.kp", "data": PDF, "filename": "kp.pdf",
              "mime": "application/pdf", "actor_id": AUTHOR, **over}
    return files.attach_bytes(OWNER, probe.pk, **kwargs)


def _seed(probe: ProbeFolder, n: int) -> None:
    """``n`` действующих документов строками — ради квоты, без загрузки."""
    for i in range(n):
        FileObject.objects.create(
            owner_type=OWNER, owner_id=probe.pk,
            file_type_id="probe.other", document_id=uuid.uuid4(), version_no=1,
            name=f"f{i}.pdf", mime="application/pdf", size=1, sha256="0" * 64,
            storage_key=f"seed/{uuid.uuid4()}", media_file_id=f"seed-{uuid.uuid4()}",
            uploaded_by_id=AUTHOR)


def test_attach_bytes_creates_a_document_and_journals_it(storage):
    probe = ProbeFolder.objects.create()

    out = _attach(probe, ip="10.0.0.1", user_agent="agent/1.0")

    assert (out["version_no"], out["file_type"], out["name"]) == (1, "probe.kp", "kp.pdf")
    assert out["storage_key"].startswith(f"file_object/public/folder/{probe.pk}/")
    assert storage.objects[out["storage_key"]] == PDF
    row = FileObject.objects.get(pk=out["id"])
    assert row.sha256 == hashlib.sha256(PDF).hexdigest()
    assert row.uploaded_by_id == AUTHOR

    event = FileEvent.objects.get(owner_type=OWNER, owner_id=str(probe.pk))
    assert (event.event, event.file_id, event.actor_id, event.ip, event.user_agent) == (
        "file_attached", out["id"], AUTHOR, "10.0.0.1", "agent/1.0")
    # Лента владельца получает то же событие, что при HTTP-загрузке.
    assert [(owner_id, kind) for owner_id, kind, *_ in hooks.EVENTS] == [
        (probe.pk, "file_attached")]


def test_attached_file_is_seen_in_the_folder_and_by_the_owner(storage):
    probe = ProbeFolder.objects.create()
    out = _attach(probe)

    data = folder(Client(), probe.pk)
    assert [d["current"]["id"] for d in data["documents"]] == [out["id"]]
    assert [c["id"] for c in files.current_files(OWNER, probe.pk)] == [out["id"]]
    found = files.find_version(out["id"])
    assert (found["owner_type"], found["owner_id"], found["document_id"]) == (
        OWNER, str(probe.pk), out["document_id"])


def test_rights_are_the_owners_business(storage):
    """Из кода ``can_modify`` не спрашивается: объект уже отправлен, HTTP
    ответил бы 409, а владелец, проверивший свои правила, файл приложит."""
    probe = ProbeFolder.objects.create(status=ProbeFolder.SENT)
    assert _attach(probe)["version_no"] == 1


def test_quota_is_respected(storage):
    probe = ProbeFolder.objects.create()
    _seed(probe, hooks.MAX_DOCUMENTS)

    with pytest.raises(files.FilesError) as exc:
        _attach(probe)

    assert (exc.value.code, exc.value.status) == ("E-FIL-03", 409)
    assert exc.value.details["used"] == hooks.MAX_DOCUMENTS
    assert storage.objects == {}  # отказ — до записи в хранилище
    assert FileObject.objects.filter(owner_id=str(probe.pk)).count() == hooks.MAX_DOCUMENTS


def test_wrong_format_is_refused(storage):
    probe = UuidProbeFolder.objects.create()

    with pytest.raises(files.FilesError) as exc:
        files.attach_bytes(UUID_OWNER, probe.pk, file_type="probe.doc",
                           data=b"PK\x03\x04" + b"\x00" * 64, filename="a.docx",
                           mime="application/vnd.openxmlformats-officedocument."
                                "wordprocessingml.document", actor_id=AUTHOR)

    assert (exc.value.code, exc.value.status) == ("E-FIL-01", 415)
    assert "PDF" in exc.value.message
    assert storage.objects == {}
    assert not FileObject.objects.filter(owner_type=UUID_OWNER).exists()


def test_size_is_checked_against_the_reference(storage):
    FileType.objects.filter(pk="probe.kp").update(max_mb=1)
    probe = ProbeFolder.objects.create()

    with pytest.raises(files.FilesError) as exc:
        _attach(probe, data=PDF + b"0" * (1024 * 1024))

    assert (exc.value.code, exc.value.status) == ("E-FIL-02", 413)
    assert storage.objects == {}


def test_unknown_type_is_refused(storage):
    probe = ProbeFolder.objects.create()
    with pytest.raises(files.FilesError) as exc:
        _attach(probe, file_type="probe.nope")
    assert exc.value.code == "E-FIL-07"


def test_actor_is_required():
    probe = ProbeFolder.objects.create()
    with pytest.raises(ValueError):
        _attach(probe, actor_id=None)


def test_replace_bytes_adds_a_version(storage):
    probe = ProbeFolder.objects.create()
    first = _attach(probe)

    second = files.replace_bytes(OWNER, probe.pk, first["document_id"], data=PDF + b"v2",
                                 filename="kp-v2.pdf", mime="application/pdf",
                                 actor_id=AUTHOR, base_file_id=first["id"])

    assert (second["version_no"], second["document_id"]) == (2, first["document_id"])
    old = FileObject.objects.get(pk=first["id"])
    assert (old.is_replaced, old.replaced_by_id) == (True, second["id"])
    assert FileEvent.objects.filter(event="file_version_attached",
                                    file_id=second["id"]).count() == 1
    # Поверх уже заменённой версии — конфликт, как у HTTP.
    with pytest.raises(files.FilesError) as exc:
        files.replace_bytes(OWNER, probe.pk, first["document_id"], data=PDF,
                            filename="late.pdf", mime="application/pdf",
                            actor_id=AUTHOR, base_file_id=first["id"])
    assert (exc.value.code, exc.value.status) == ("E-CON-01", 409)
    # Без базы — поверх действующей.
    third = files.replace_bytes(OWNER, probe.pk, first["document_id"], data=PDF,
                                filename="kp-v3.pdf", mime="application/pdf",
                                actor_id=AUTHOR)
    assert third["version_no"] == 3


def test_download_link_is_journaled(storage):
    probe = ProbeFolder.objects.create()
    out = _attach(probe)

    url = files.download_link(OWNER, probe.pk, out["document_id"], actor_id=11,
                              ip="10.0.0.2", user_agent="agent/2.0")

    assert url
    event = FileEvent.objects.get(event="file_downloaded")
    assert (event.file_id, event.actor_id, event.ip, event.user_agent) == (
        out["id"], 11, "10.0.0.2", "agent/2.0")


def test_failed_link_leaves_no_bytes_behind(storage, monkeypatch):
    """Байты записаны, а строка не встала (здесь упала лента владельца) —
    объект стирается из хранилища сразу, а не через грейс media: загрузка из
    кода идёт в транзакции владельца, и пометка удаления откатилась бы
    вместе с ней."""
    def boom(*args, **kwargs):
        raise RuntimeError("лента владельца недоступна")

    monkeypatch.setitem(registry._OWNERS, OWNER,
                        dataclasses.replace(registry.get_owner(OWNER), on_event=boom))
    probe = ProbeFolder.objects.create()

    with pytest.raises(RuntimeError):
        _attach(probe)

    assert storage.objects == {}
    assert not FileObject.objects.filter(owner_id=str(probe.pk)).exists()
    assert not FileMetadata.objects.filter(scope="file_object",
                                           deleted_at__isnull=True).exists()

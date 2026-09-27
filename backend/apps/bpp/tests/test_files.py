"""Файлы документов: типы и лимиты ТЗ §21, версии, журнал скачиваний."""

import uuid

import pytest

from apps.bpp.models import DocumentFile, FileDownload
from apps.bpp.services.core import files
from htqweb.errors import DomainError

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


class _Owner:
    class _meta:  # noqa: N801
        label_lower = "bpp.probe"

    def __init__(self):
        self.pk = uuid.uuid4()


class _MemoryStorage:
    """S3 в памяти: тесты модуля не поднимают MinIO (тот же приём, что в hr)."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def save(self, path, data, content_type=None):
        self.objects[path] = data

    def exists(self, path):
        return path in self.objects

    def delete(self, path):
        self.objects.pop(path, None)


@pytest.fixture(autouse=True)
def memory_storage(monkeypatch):
    from apps.media_files.services import upload_service

    storage = _MemoryStorage()
    monkeypatch.setattr(upload_service, "get_storage", lambda bucket=None: storage)
    return storage


@pytest.fixture
def owner():
    return _Owner()


@pytest.mark.django_db
def test_attach_and_list(company_context, owner):
    row = files.attach(owner, "invoice", data=PDF, filename="счёт.pdf",
                       mime="application/pdf", actor_id=7)
    assert (row["file_type"], row["version"], row["replaced"]) == ("invoice", 1, False)
    assert row["sha256"] and row["size"] == len(PDF)
    assert [f["id"] for f in files.list_files(owner)] == [row["id"]]


@pytest.mark.django_db
def test_wrong_format_is_415(company_context, owner):
    with pytest.raises(DomainError) as exc:
        files.attach(owner, "invoice", data=b"PK\x03\x04docx", filename="a.docx",
                     mime="application/vnd.openxmlformats-officedocument."
                          "wordprocessingml.document", actor_id=7)
    assert (exc.value.code, exc.value.status) == ("E-FILE-01", 415)


@pytest.mark.django_db
def test_too_big_is_413(company_context, owner):
    big = PDF + b"0" * (10 * 1024 * 1024)
    with pytest.raises(DomainError) as exc:
        files.attach(owner, "invoice", data=big, filename="a.pdf",
                     mime="application/pdf", actor_id=7)
    assert (exc.value.code, exc.value.status) == ("E-FILE-02", 413)


@pytest.mark.django_db
def test_count_limit(company_context, owner):
    for n in range(5):
        files.attach(owner, "invoice", data=PDF, filename=f"{n}.pdf",
                     mime="application/pdf", actor_id=7)
    with pytest.raises(DomainError) as exc:
        files.attach(owner, "invoice", data=PDF, filename="6.pdf",
                     mime="application/pdf", actor_id=7)
    assert exc.value.code == "E-FILE-03"


@pytest.mark.django_db
def test_replace_makes_a_new_version(company_context, owner):
    first = files.attach(owner, "agreement", data=PDF, filename="v1.pdf",
                         mime="application/pdf", actor_id=7)
    second = files.replace(first["id"], data=PDF, filename="v2.pdf",
                           mime="application/pdf", actor_id=8)
    assert second["version"] == 2
    assert [f["filename"] for f in files.list_files(owner)] == ["v2.pdf"]
    assert DocumentFile.objects.get(pk=first["id"]).replaced is True


@pytest.mark.django_db
def test_download_is_logged(company_context, owner):
    row = files.attach(owner, "invoice", data=PDF, filename="a.pdf",
                       mime="application/pdf", actor_id=7)
    assert files.download_url(row["id"], user_id=9)
    assert FileDownload.objects.filter(file_id=row["id"], user_id=9).count() == 1


@pytest.mark.django_db
def test_scanner_can_reject(company_context, owner, settings):
    settings.BPP_FILE_SCANNER = "apps.bpp.tests.test_files._reject_all"
    with pytest.raises(DomainError) as exc:
        files.attach(owner, "invoice", data=PDF, filename="a.pdf",
                     mime="application/pdf", actor_id=7)
    assert exc.value.code == "E-FILE-04"
    assert not DocumentFile.objects.exists()


def _reject_all(data: bytes, filename: str) -> str | None:
    return "найден вирус EICAR"

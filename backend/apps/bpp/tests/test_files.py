"""Файлы документов модуля — обёртка ``services/core/files.py`` над
платформенной ``apps.files`` (план этапа 2 A, задача 1).

Поведение прежнее (ТЗ §21): предел количества и «1 действующий + версии»,
форматы и размер, новая версия вместо правки, журнал скачиваний, отказ
хранилища и антивируса — понятная ошибка с кодом, откат без «сирот» в S3,
параллельные загрузки не пробивают предел. Хранилище — ``apps.files``,
коды — её (``E-FIL-*``).

Общие правила проверяются на пробном владельце (``bpp.probe``): у заявки
предел — 20 документов одного вида, у авансового отчёта — один; пробный
документ даёт и «до 5», и «1 + версии» без подготовки бюджета и заявки.
Настоящие владельцы — в конце: правила ТЗ §21 в их регистрации и
``test_bpp_adapter_writes_into_apps_files`` (Review Focus 1 плана) — файл
заявки, приложенный кодом модуля, лежит в ``apps.files`` и виден на её
панели.

``PDF`` и фикстура ``memory_storage`` импортируются тестами заявки и
подотчёта.
"""

from __future__ import annotations

import random

import pytest
from django.test import Client, RequestFactory

from apps.bpp import file_owners
from apps.bpp.models import AuditLog
from apps.bpp.services.core import audit
from apps.bpp.services.core import files
from apps.files import interface as files_interface
from htqweb.errors import DomainError

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"

PROBE = "bpp.probe"
INVOICE = "bpp_probe.invoice"      # до 5 документов, PDF/JPG/PNG до 10 МБ
AGREEMENT = "bpp_probe.agreement"  # 1 действующий + версии
_PROBE_TYPES = (
    (INVOICE, "Счёт (проба)", [".pdf", ".jpg", ".jpeg", ".png"], 10),
    (AGREEMENT, "Договор (проба)", [".pdf", ".docx", ".jpg", ".jpeg", ".png"], 20),
)


class _Owner:
    """Документ-проба: целый ключ, строки в БД нет — владельцу файлов
    нужны только тип и ключ."""

    class _meta:  # noqa: N801
        label_lower = PROBE

    def __init__(self):
        self.pk = random.randint(10**6, 10**9)


class _MemoryStorage:
    """S3 в памяти: тесты модуля не поднимают MinIO (тот же приём, что в hr)."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def save(self, path, data, content_type=None):
        self.objects[path] = data

    def open(self, path, byte_range=None):
        return self.objects[path]

    def exists(self, path):
        return path in self.objects

    def size(self, path):
        return len(self.objects[path])

    def delete(self, path):
        self.objects.pop(path, None)


@pytest.fixture(autouse=True)
def memory_storage(monkeypatch):
    from apps.media_files.services import upload_service

    storage = _MemoryStorage()
    monkeypatch.setattr(upload_service, "get_storage", lambda bucket=None: storage)
    return storage


def _probe_lock(owner_id) -> None:
    """Строки у пробы нет — загрузки к одному документу сериализует
    advisory-блокировка до конца транзакции, как ``SELECT … FOR UPDATE``
    строки у настоящего владельца."""
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                       [f"{PROBE}:{owner_id}"])


def _seed_probe_types() -> None:
    from apps.files.models import FileType

    for code, name, formats, max_mb in _PROBE_TYPES:
        FileType.objects.get_or_create(code=code, defaults={
            "owner_type": PROBE, "name": name, "formats": formats, "max_mb": max_mb})


@pytest.fixture
def probe(monkeypatch, db):
    """Пробный владелец в apps.files — на время теста. ``db`` у теста с
    ``transaction=True`` сам становится транзакционным: строки справочника
    сеются уже после очистки базы."""
    from apps.files.services import registry

    files_interface.register_owner(
        PROBE, label="Пробный документ", service="bpp", tenant=False, folder="bpp-probe",
        file_types=(files_interface.FileTypeSpec(INVOICE, max_documents=5),
                    files_interface.FileTypeSpec(AGREEMENT,
                                                 cardinality=files_interface.SINGLE)),
        can_view=lambda *a: True, can_modify=lambda *a: None,
        was_sent=lambda *a: False, lock=_probe_lock,
        # «История изменений» — тем же колбэком, что у настоящих документов.
        on_event=file_owners.history_on_event(_Owner))
    monkeypatch.setitem(files._OWNER_TYPES, PROBE, PROBE)
    _seed_probe_types()
    yield
    registry._OWNERS.pop(PROBE, None)


@pytest.fixture
def owner(probe):
    return _Owner()


def _file_rows(owner):
    from apps.files.models import FileObject

    return FileObject.objects.filter(owner_type=PROBE, owner_id=str(owner.pk))


# ── пробный документ: правила подсистемы через обёртку ──────────────────

@pytest.mark.django_db
def test_attach_and_list(company_context, owner):
    row = files.attach(owner, INVOICE, data=PDF, filename="счёт.pdf",
                       mime="application/pdf", actor_id=7)
    assert (row["file_type"], row["version"], row["replaced"]) == (INVOICE, 1, False)
    assert row["sha256"] and row["size"] == len(PDF)
    assert row["filename"] == "счёт.pdf" and row["uploaded_by"] == 7
    assert [f["id"] for f in files.list_files(owner)] == [row["id"]]


@pytest.mark.django_db
def test_wrong_format_is_415(company_context, owner):
    with pytest.raises(DomainError) as exc:
        files.attach(owner, INVOICE, data=b"PK\x03\x04docx", filename="a.docx",
                     mime="application/vnd.openxmlformats-officedocument."
                          "wordprocessingml.document", actor_id=7)
    assert (exc.value.code, exc.value.status) == ("E-FIL-01", 415)
    assert "PDF" in exc.value.message
    assert not _file_rows(owner).exists()


@pytest.mark.django_db
def test_too_big_is_413(company_context, owner):
    big = PDF + b"0" * (10 * 1024 * 1024)
    with pytest.raises(DomainError) as exc:
        files.attach(owner, INVOICE, data=big, filename="a.pdf",
                     mime="application/pdf", actor_id=7)
    assert (exc.value.code, exc.value.status) == ("E-FIL-02", 413)


@pytest.mark.django_db
def test_count_limit(company_context, owner):
    for n in range(5):
        files.attach(owner, INVOICE, data=PDF, filename=f"{n}.pdf",
                     mime="application/pdf", actor_id=7)
    with pytest.raises(DomainError) as exc:
        files.attach(owner, INVOICE, data=PDF, filename="6.pdf",
                     mime="application/pdf", actor_id=7)
    assert (exc.value.code, exc.value.status) == ("E-FIL-03", 409)
    assert exc.value.payload()["details"] == {"file_type": INVOICE, "max": 5, "used": 5}


@pytest.mark.django_db
def test_name_without_extension_takes_it_from_mime(company_context, owner):
    row = files.attach(owner, INVOICE, data=PDF, filename="scan", mime="application/pdf",
                       actor_id=7)
    assert row["filename"] == "scan.pdf"


@pytest.mark.django_db
def test_replace_makes_a_new_version(company_context, owner):
    first = files.attach(owner, AGREEMENT, data=PDF, filename="v1.pdf",
                         mime="application/pdf", actor_id=7)
    second = files.replace(first["id"], data=PDF, filename="v2.pdf",
                           mime="application/pdf", actor_id=8)
    assert second["version"] == 2 and second["document_id"] == first["document_id"]
    assert [f["filename"] for f in files.list_files(owner)] == ["v2.pdf"]
    assert files.get_file(owner, first["id"])["replaced"] is True


@pytest.mark.django_db
def test_second_agreement_is_refused_but_a_version_is_not(company_context, owner):
    """«1 действующий + версии»: второй документ того же типа — отказ,
    новая версия — нет."""
    first = files.attach(owner, AGREEMENT, data=PDF, filename="v1.pdf",
                         mime="application/pdf", actor_id=7)
    with pytest.raises(DomainError) as exc:
        files.attach(owner, AGREEMENT, data=PDF, filename="other.pdf",
                     mime="application/pdf", actor_id=7)
    assert exc.value.code == "E-FIL-03"
    assert files.replace(first["id"], data=PDF, filename="v2.pdf",
                         mime="application/pdf", actor_id=7)["version"] == 2


@pytest.mark.django_db
def test_replacing_a_replaced_version_is_a_conflict(company_context, owner):
    first = files.attach(owner, AGREEMENT, data=PDF, filename="v1.pdf",
                         mime="application/pdf", actor_id=7)
    files.replace(first["id"], data=PDF, filename="v2.pdf", mime="application/pdf",
                  actor_id=8)
    with pytest.raises(DomainError) as exc:
        files.replace(first["id"], data=PDF, filename="v2-bis.pdf",
                      mime="application/pdf", actor_id=7)
    assert (exc.value.code, exc.value.status) == ("E-CON-01", 409)
    assert _file_rows(owner).count() == 2


@pytest.mark.django_db
def test_file_of_another_document_is_not_found(company_context, owner):
    row = files.attach(owner, INVOICE, data=PDF, filename="a.pdf",
                       mime="application/pdf", actor_id=7)
    assert files.get_file(_Owner(), row["id"]) is None
    assert files.get_file(owner, "999999999") is None
    with pytest.raises(DomainError) as exc:
        files.download_url("999999999", user_id=9)
    assert exc.value.status == 404


@pytest.mark.django_db
def test_download_is_logged(company_context, owner):
    from apps.files.models import FileEvent

    row = files.attach(owner, INVOICE, data=PDF, filename="a.pdf",
                       mime="application/pdf", actor_id=7)
    request = RequestFactory().get("/", HTTP_USER_AGENT="pytest-agent",
                                   REMOTE_ADDR="10.1.2.3")
    assert files.download_url(row["id"], user_id=9, request=request)
    event = FileEvent.objects.get(event="file_downloaded", file_id=int(row["id"]))
    assert (event.actor_id, event.ip, event.user_agent) == (9, "10.1.2.3", "pytest-agent")


@pytest.mark.django_db
def test_antivirus_rejection_is_a_domain_error(company_context, owner, monkeypatch,
                                               memory_storage):
    """Угроза — отказ с кодом, файла нет ни в хранилище, ни в папке, а
    попытка — в журнале. Прежний крючок ``BPP_FILE_SCANNER`` снят: один
    антивирус на платформу (флаг scope ``file_object`` в media)."""
    from apps.files.models import FileEvent
    from apps.media_files import interface as media

    def infected(**kwargs):
        raise media.FileInfected("Eicar-Test-Signature")

    monkeypatch.setattr(media, "store_file", infected)
    with pytest.raises(DomainError) as exc:
        files.attach(owner, INVOICE, data=PDF, filename="a.pdf",
                     mime="application/pdf", actor_id=7)
    assert (exc.value.code, exc.value.status) == ("E-FIL-08", 422)
    assert "Eicar-Test-Signature" in exc.value.message
    assert memory_storage.objects == {}
    assert not _file_rows(owner).exists()
    assert FileEvent.objects.filter(owner_type=PROBE, owner_id=str(owner.pk),
                                    event="file_rejected").count() == 1


@pytest.mark.django_db(transaction=True)
def test_parallel_attach_respects_the_limit(monkeypatch, owner, memory_storage):
    """Договор — один файл. Четыре одновременные загрузки: предел
    перепроверяется под блокировкой владельца, второго файла нет — ни в
    папке, ни в хранилище (отвергнутые байты стёрты сразу)."""
    import threading
    import time

    from django.db import connection

    from apps.files.services import documents

    real_store = documents._store

    def slow_store(*args, **kwargs):  # расширяет окно между проверкой и вставкой
        time.sleep(0.2)
        return real_store(*args, **kwargs)

    monkeypatch.setattr(documents, "_store", slow_store)
    codes: list[str] = []
    lock = threading.Lock()

    def worker(n):
        try:
            files.attach(owner, AGREEMENT, data=PDF, filename=f"{n}.pdf",
                         mime="application/pdf", actor_id=7)
            with lock:
                codes.append("ok")
        except DomainError as exc:
            with lock:
                codes.append(exc.code)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(codes) == ["E-FIL-03", "E-FIL-03", "E-FIL-03", "ok"]
    assert _file_rows(owner).count() == 1
    assert len(memory_storage.objects) == 1


@pytest.mark.django_db
def test_replace_is_audited(company_context, owner):
    first = files.attach(owner, AGREEMENT, data=PDF, filename="v1.pdf",
                         mime="application/pdf", actor_id=7)
    second = files.replace(first["id"], data=PDF, filename="v2.pdf",
                           mime="application/pdf", actor_id=8)
    row = AuditLog.objects.get(action="file_replaced")
    assert (row.object_type, row.object_id, row.actor_id) == (PROBE, str(owner.pk), 8)
    assert row.changes == {"file": second["id"], "previous": first["id"],
                           "file_type": AGREEMENT, "filename": "v2.pdf", "version": 2}


@pytest.mark.django_db
def test_media_rejection_is_a_domain_error(company_context, owner, monkeypatch):
    """Медиа не приняло файл (подпись не совпала с форматом, картинка битая) —
    понятная ошибка с кодом, а не 500."""
    from apps.media_files import interface as media

    def reject(**kwargs):
        raise media.UploadValidationError(415, "File content does not match declared type")

    monkeypatch.setattr(media, "store_file", reject)
    with pytest.raises(DomainError) as exc:
        files.attach(owner, INVOICE, data=PDF, filename="a.pdf", mime="application/pdf",
                     actor_id=7)
    assert (exc.value.code, exc.value.status) == ("E-FIL-01", 415)
    assert "a.pdf" in exc.value.message


@pytest.mark.django_db
def test_stored_object_is_removed_when_the_row_fails(company_context, owner, monkeypatch,
                                                      memory_storage):
    """Байты уже в S3, а запись не удалась (здесь — «История изменений»
    документа) — объект удаляется сразу, «сирот» нет."""
    def boom(*args, **kwargs):
        raise RuntimeError("журнал недоступен")

    monkeypatch.setattr(audit, "record_for", boom)
    with pytest.raises(RuntimeError):
        files.attach(owner, INVOICE, data=PDF, filename="a.pdf", mime="application/pdf",
                     actor_id=7)
    assert memory_storage.objects == {}
    assert not _file_rows(owner).exists()


# ── настоящие владельцы ─────────────────────────────────────────────────

@pytest.mark.django_db
def test_real_owners_carry_the_tz_rules():
    """ТЗ §21 в регистрации владельцев и в справочнике «Типы файлов»."""
    from apps.files.models import FileType
    from apps.files.services import registry

    request_owner = registry.get_owner(file_owners.REQUEST_OWNER)
    (spec,) = request_owner.file_types
    assert (spec.code, spec.quota_group) == ("request_attachment", "documents")
    assert request_owner.quotas == {"documents": 20}
    assert request_owner.tenant and request_owner.service == "bpp_requests"

    report_owner = registry.get_owner(file_owners.REPORT_OWNER)
    (spec,) = report_owner.file_types
    assert (spec.code, spec.cardinality) == ("advance_report", files_interface.SINGLE)

    types = {row.code: row for row in FileType.objects.filter(
        code__in=["request_attachment", "advance_report"])}
    assert types["request_attachment"].max_mb == 20
    assert set(types["request_attachment"].formats) == {
        ".pdf", ".docx", ".xlsx", ".jpg", ".jpeg", ".png"}
    assert types["advance_report"].max_mb == 10
    assert set(types["advance_report"].formats) == {".pdf", ".jpg", ".jpeg", ".png"}


@pytest.mark.django_db
def test_bpp_adapter_writes_into_apps_files(company_context, memory_storage):
    """Review Focus 1: заявка прикладывает КП загрузкой из кода модуля
    (``services/core/files.py``), а файл лежит в ``apps.files`` — виден через её интерфейс и на панели
    ``/api/files/v1``, записан в журнал с IP и user-agent и остаётся на
    месте после отправки заявки."""
    from apps.bpp.services.core import files as core_files
    from apps.bpp.services.requests import requests as service
    from apps.bpp.tests import stage2 as s
    from apps.files.models import FileEvent, FileObject
    from htqweb.tenancy.db import use_company

    slug = company_context["slug"]
    proj, art = s.project(), s.metal()
    s.approved_budget(slug, proj, {art: 10_000})
    s.request_route()
    sn = s.actor(slug, s.SN, "bpp-sn")
    sn.request.META.update(HTTP_USER_AGENT="pytest-agent", REMOTE_ADDR="10.9.8.7")
    req = service.create_draft(sn, {**s.header(proj, art), "items": s.items((1, 100))})

    row = core_files.attach(req, "request_attachment", data=PDF, filename="kp.pdf",
                            mime="application/pdf", actor_id=s.SN, request=sn.request)

    current = files_interface.current_files(file_owners.REQUEST_OWNER, req.id)
    assert [(c["id"], c["name"], c["file_type"]) for c in current] == [
        (int(row["id"]), "kp.pdf", "request_attachment")]
    stored = FileObject.objects.get(pk=int(row["id"]))
    assert (stored.company_slug, stored.owner_id) == (slug, str(req.id))
    assert stored.storage_key in memory_storage.objects
    event = FileEvent.objects.get(event="file_attached", file_id=stored.pk)
    assert (event.actor_id, event.ip, event.user_agent) == (s.SN, "10.9.8.7", "pytest-agent")

    service.submit(sn, req.id, expected_version=None)
    assert [f["filename"] for f in core_files.list_files(req)] == ["kp.pdf"]

    resp = Client().get(f"/api/files/v1/{file_owners.REQUEST_OWNER}/{req.id}/files/",
                        **s.auth(slug, s.SN))
    assert resp.status_code == 200, resp.content
    folder = resp.json()
    assert [d["current"]["name"] for d in folder["documents"]] == ["kp.pdf"]
    # После отправки файлы только читаются и физически уже не удаляются.
    assert folder["can_modify"] is False and folder["delete_is_physical"] is False

    with use_company(slug):  # запрос вернул search_path в public
        s.actor(slug, s.SN2, "bpp-sn")
    stranger = Client().get(f"/api/files/v1/{file_owners.REQUEST_OWNER}/{req.id}/files/",
                            **s.auth(slug, s.SN2))
    assert stranger.status_code == 404  # чужую заявку он и не видит
    with use_company(slug):
        assert FileObject.objects.filter(owner_id=str(req.id)).count() == 1

"""Файловая подсистема на пробном владельце — папке с правилами ТЗ §21.

Проверяется то, что пользователь видит: папка владельца в хранилище, версии
по ТЗ (номер не меняется, «Заменён», конфликт E-CON-01), повтор запроса,
квота «до 20», форматы и размер из справочника, удаление физическое или
пометкой, кто видит и кто меняет — и конверт ошибок (D-28) во всех отказах.
Владелец с UUID-ключом — отдельным блоком: так адресуются документы модуля
БЗО (мастер-план D-05).
"""

from __future__ import annotations

import dataclasses
import hashlib
import uuid

import pytest
from django.test import Client
from django.utils import timezone

from apps.files.models import FileEvent, FileObject, FileType
from apps.files.services import documents
from apps.media_files.models import FileMetadata

from .helpers import (
    APPROVER, AUTHOR, OWNER, PDF, STRANGER, UUID_OWNER, assert_tz_error, auth, delete,
    files_url, folder, superuser_token, token, upload, upload_version,
)
from .testapp import hooks
from .testapp.models import ProbeFolder, UuidProbeFolder

pytestmark = pytest.mark.django_db

DOCX = b"PK\x03\x04" + b"\x00" * 64


def _folder(**fields) -> ProbeFolder:
    return ProbeFolder.objects.create(**fields)


def _send(probe: ProbeFolder) -> None:
    """Владелец ушёл на согласование: файлы только читаются."""
    ProbeFolder.objects.filter(pk=probe.pk).update(status=ProbeFolder.SENT,
                                                   sent_at=timezone.now())


def _return(probe: ProbeFolder) -> None:
    """Возврат на доработку: файлы снова меняются (новыми версиями)."""
    ProbeFolder.objects.filter(pk=probe.pk).update(status=ProbeFolder.RETURNED)


def _events(probe: ProbeFolder, kind: str) -> list[tuple]:
    """События владельца (``on_event``) этого вида: ``(actor_id, payload)``."""
    return [(actor, payload) for owner_id, event, actor, payload in hooks.EVENTS
            if owner_id == probe.pk and event == kind]


def _seed(probe: ProbeFolder, n: int) -> None:
    """``n`` действующих документов строками — ради квоты, без загрузки."""
    for i in range(n):
        FileObject.objects.create(
            owner_type=OWNER, owner_id=probe.pk,
            file_type_id="probe.other", document_id=uuid.uuid4(), version_no=1,
            name=f"f{i}.pdf", mime="application/pdf", size=1, sha256="0" * 64,
            storage_key=f"seed/{uuid.uuid4()}", media_file_id=f"seed-{uuid.uuid4()}",
            uploaded_by_id=AUTHOR)


# ── папка и метаданные ──────────────────────────────────────────────────

def test_upload_lands_in_the_owner_folder(storage):
    probe = _folder()

    resp = upload(Client(), probe.pk)

    assert resp.status_code == 201, resp.content
    body = resp.json()
    prefix = f"file_object/public/folder/{probe.pk}/"
    assert body["storage_key"].startswith(prefix)
    assert body["storage_key"] in storage.objects
    assert body["version_no"] == 1 and body["is_replaced"] is False
    assert body["file_type"] == "probe.kp" and body["name"] == "kp.pdf"
    assert body["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert body["size"] == len(PDF) and body["mime"] == "application/pdf"
    assert body["uploaded_by_id"] == AUTHOR and body["uploaded_at"]
    # Готовой ссылки в ответе нет: скачивание — только через link (журнал).
    assert "url" not in body
    assert FileMetadata.objects.get(path=body["storage_key"]).scope == "file_object"

    data = folder(Client(), probe.pk)
    assert data["owner_id"] == str(probe.pk)  # ключ владельца — строкой
    assert data["storage_prefix"] == prefix
    assert data["can_modify"] is True and data["modify_reason"] is None
    assert data["delete_is_physical"] is True
    assert data["quotas"] == [{"group": "folder", "max": 20, "used": 1}]
    assert [t["code"] for t in data["types"]] == [
        "probe.kp", "probe.tz", "probe.spec", "probe.other"]
    kp = data["types"][0]
    assert kp["name"] == "КП" and kp["max_mb"] == 20 and kp["can_add"] is True
    assert ".docx" in kp["formats"] and kp["cardinality"] == "multi"
    document = data["documents"][0]
    assert document["file_type_name"] == "КП"
    assert document["current"]["id"] == body["id"]
    assert _events(probe, "file_attached")


def test_every_file_of_an_owner_shares_one_prefix():
    probe, other = _folder(), _folder()
    client = Client()

    first = upload(client, probe.pk).json()
    second = upload(client, probe.pk, name="spec.docx", content=DOCX,
                    mime="application/octet-stream", file_type="probe.spec").json()
    foreign = upload(client, other.pk).json()

    prefix = f"file_object/public/folder/{probe.pk}/"
    assert first["storage_key"].startswith(prefix)
    assert second["storage_key"].startswith(prefix)
    assert second["mime"].endswith("wordprocessingml.document")  # тип — по расширению
    assert not foreign["storage_key"].startswith(prefix)


# ── версии по ТЗ ────────────────────────────────────────────────────────

def test_new_version_replaces_the_current_one_and_numbers_never_change():
    probe = _folder()
    client = Client()
    v1 = upload(client, probe.pk).json()

    resp = upload_version(client, probe.pk, v1["document_id"], v1["id"])

    assert resp.status_code == 201, resp.content
    v2 = resp.json()
    assert v2["document_id"] == v1["document_id"] and v2["version_no"] == 2
    assert v2["file_type"] == "probe.kp"  # тип наследуется документом
    document = folder(client, probe.pk)["documents"][0]
    assert [v["version_no"] for v in document["versions"]] == [2, 1]
    old = document["versions"][1]
    assert old["is_replaced"] is True and old["replaced_by_id"] == v2["id"]
    assert old["id"] == v1["id"] and old["version_no"] == 1  # не перенумерован
    assert folder(client, probe.pk)["quotas"][0]["used"] == 1
    [(_actor, payload)] = _events(probe, "file_version_attached")
    assert payload["replaced_file_id"] == v1["id"]


def test_version_over_a_stale_base_is_a_conflict():
    """Двое грузят новую версию поверх одной и той же v1: второй получает
    E-CON-01 с именем и временем того, кто успел раньше, и ничего не пишет."""
    probe = _folder()
    client = Client()
    v1 = upload(client, probe.pk).json()
    upload_version(client, probe.pk, v1["document_id"], v1["id"])

    resp = upload_version(client, probe.pk, v1["document_id"], v1["id"],
                          name="late.pdf", content=PDF + b"late")

    body = assert_tz_error(resp, 409, "E-CON-01")
    assert "Документ изменён пользователем" in body["detail"]
    assert "Обновите страницу" in body["detail"]
    assert body["details"]["current_file_id"] != v1["id"]
    assert FileObject.objects.filter(owner_id=probe.pk).count() == 2
    assert not FileMetadata.objects.filter(original_filename="late.pdf").exists()


def test_conflict_detected_under_the_lock_returns_the_stored_file(monkeypatch):
    """Параллельная версия успела между предпроверкой и блокировкой: 409, и
    уже сохранённый файл возвращается в media — к документу он не привязан."""
    probe = _folder()
    client = Client()
    v1 = upload(client, probe.pk).json()
    real_uploader = documents._uploader
    fired = []

    def _meanwhile(tok):
        if not fired:  # вложенная загрузка сама пройдёт через _uploader
            fired.append(1)
            upload_version(client, probe.pk, v1["document_id"], v1["id"],
                           name="winner.pdf", content=PDF + b"winner")
        return real_uploader(tok)

    monkeypatch.setattr(documents, "_uploader", _meanwhile)
    resp = upload_version(client, probe.pk, v1["document_id"], v1["id"],
                          name="loser.pdf", content=PDF + b"loser")

    assert_tz_error(resp, 409, "E-CON-01")
    loser = FileMetadata.objects.get(original_filename="loser.pdf")
    assert loser.deleted_at is not None
    assert not FileObject.objects.filter(media_file_id=str(loser.pk)).exists()


def test_version_without_a_base_is_rejected():
    probe = _folder()
    v1 = upload(Client(), probe.pk).json()

    resp = upload_version(Client(), probe.pk, v1["document_id"], None)

    body = assert_tz_error(resp, 422, "E-FIL-07")
    assert body["fields"][0]["field"] == "base_file_id"


# ── повтор запроса ──────────────────────────────────────────────────────

def test_repeat_with_the_same_idempotency_key_returns_the_first_result():
    probe = _folder()
    client = Client()

    first = upload(client, probe.pk, key="k-1")
    again = upload(client, probe.pk, key="k-1", name="kp-again.pdf")

    assert first.status_code == again.status_code == 201
    assert again.json()["id"] == first.json()["id"]
    assert FileObject.objects.filter(owner_id=probe.pk).count() == 1
    assert FileMetadata.objects.filter(scope="file_object").count() == 1


def test_parallel_repeat_is_resolved_under_the_lock(monkeypatch,
                                                     django_capture_on_commit_callbacks):
    """Оба повтора прошли предпроверку: второй под блокировкой находит первую
    запись, отдаёт её и возвращает свой лишний файл в media."""
    probe = _folder()
    client = Client()
    real_uploader = documents._uploader
    calls = []

    def _meanwhile(tok):
        if not calls:
            calls.append(1)
            upload(client, probe.pk, key="k-par", name="first.pdf")
        return real_uploader(tok)

    monkeypatch.setattr(documents, "_uploader", _meanwhile)
    with django_capture_on_commit_callbacks(execute=True):
        resp = upload(client, probe.pk, key="k-par", name="second.pdf")

    assert resp.status_code == 201
    assert resp.json()["name"] == "first.pdf"
    assert FileObject.objects.filter(owner_id=probe.pk).count() == 1
    assert FileMetadata.objects.get(original_filename="second.pdf").deleted_at is not None


# ── квота, формат, размер ───────────────────────────────────────────────

def test_quota_is_twenty_documents_and_versions_do_not_count():
    probe = _folder()
    client = Client()
    _seed(probe, 19)
    twentieth = upload(client, probe.pk)
    assert twentieth.status_code == 201, twentieth.content

    over = upload(client, probe.pk, name="21.pdf")
    body = assert_tz_error(over, 409, "E-FIL-03")
    assert body["details"] == {"group": "folder", "max": 20, "used": 20}
    types = folder(client, probe.pk)["types"]
    assert all(t["can_add"] is False and "20 из 20" in t["reason"] for t in types)

    version = upload_version(client, probe.pk, twentieth.json()["document_id"],
                             twentieth.json()["id"])
    assert version.status_code == 201, version.content


def test_wrong_format_and_spoofed_content_are_E_FIL_01():
    probe = _folder()
    client = Client()

    exe = upload(client, probe.pk, name="schet.exe", content=b"MZ",
                 mime="application/x-msdownload")
    body = assert_tz_error(exe, 415, "E-FIL-01")
    # Текст — дословно ТЗ §13.2.
    assert body["detail"] == ("Файл schet.exe не загружен: допустимы PDF, DOCX, XLSX, "
                              "JPG, PNG до 20 МБ.")
    assert body["fields"] == [{"field": "file", "message": "Недопустимый формат"}]

    spoofed = upload(client, probe.pk, name="fake.pdf", content=b"not a pdf")
    assert "не соответствует формату PDF" in assert_tz_error(spoofed, 415, "E-FIL-01")["detail"]
    assert not FileObject.objects.exists()



def test_xml_is_accepted_and_served_only_as_an_attachment():
    """Счёт-фактура в xml (мастер-план БЗО, D-31 / ответ Q-C28): принимается,
    если тип владельца её разрешает, а отдаётся вложением, не инлайн."""
    FileType.objects.filter(pk="probe.other").update(formats=[".pdf", ".xml"])
    probe = _folder()
    client = Client()
    # BOM UTF-8 в начале — так пишут xml многие выгрузки (1С, ЭСФ).
    xml = bytes((0xEF, 0xBB, 0xBF)) + b'<?xml version="1.0" encoding="UTF-8"?><invoice/>'

    resp = upload(client, probe.pk, name="schet-faktura.xml", content=xml,
                  mime="text/xml", file_type="probe.other")

    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["mime"] == "application/xml"
    link = client.get(f"{files_url(probe.pk)}{body['document_id']}/versions/{body['id']}/link",
                      **auth()).json()
    download = Client().get(link["url"])
    assert download.status_code == 200 and download.content == xml
    assert download["Content-Disposition"].startswith("attachment")

    spoofed = upload(client, probe.pk, name="fake.xml", content=PDF, file_type="probe.other")
    assert_tz_error(spoofed, 415, "E-FIL-01")

def test_size_limit_comes_from_the_reference():
    FileType.objects.filter(pk="probe.kp").update(max_mb=1)
    probe = _folder()

    resp = upload(Client(), probe.pk, content=b"%PDF-" + b"0" * (1024 * 1024 + 10))

    body = assert_tz_error(resp, 413, "E-FIL-02")
    # Текст ТЗ §13.2 — один на формат и размер; вес файла — в details.
    assert body["detail"] == ("Файл kp.pdf не загружен: допустимы PDF, DOCX, XLSX, "
                              "JPG, PNG до 1 МБ.")
    assert body["details"]["max_mb"] == 1
    assert not FileMetadata.objects.exists()  # отказ — до записи в хранилище


def test_unknown_file_type_and_missing_file_are_E_FIL_07():
    probe = _folder()
    client = Client()

    unknown = upload(client, probe.pk, file_type="invoice.main")
    assert assert_tz_error(unknown, 422, "E-FIL-07")["fields"][0]["field"] == "file_type"
    missing = client.post(files_url(probe.pk), {"file_type": "probe.kp"}, **auth())
    assert assert_tz_error(missing, 422, "E-FIL-07")["fields"][0]["field"] == "file"


# ── удаление ────────────────────────────────────────────────────────────

def test_delete_in_a_never_sent_draft_is_physical(django_capture_on_commit_callbacks):
    probe = _folder()
    client = Client()
    v1 = upload(client, probe.pk).json()
    upload_version(client, probe.pk, v1["document_id"], v1["id"])
    media_ids = list(FileObject.objects.values_list("media_file_id", flat=True))

    with django_capture_on_commit_callbacks(execute=True):
        resp = delete(client, probe.pk, v1["document_id"])

    assert resp.status_code == 204
    assert not FileObject.objects.filter(owner_id=probe.pk).exists()
    assert all(FileMetadata.objects.get(pk=m).deleted_at for m in media_ids)
    [(_actor, payload)] = _events(probe, "file_deleted")
    assert payload["physical"] is True and payload["versions"] == 2


def test_delete_after_sending_only_marks_the_document(django_capture_on_commit_callbacks):
    probe = _folder()
    client = Client()
    v1 = upload(client, probe.pk).json()
    _send(probe)
    _return(probe)

    with django_capture_on_commit_callbacks(execute=True):
        resp = delete(client, probe.pk, v1["document_id"])

    assert resp.status_code == 204
    row = FileObject.objects.get(pk=v1["id"])
    assert row.deleted_at is not None and row.deleted_by_id == AUTHOR
    assert FileMetadata.objects.get(pk=row.media_file_id).deleted_at is None
    data = folder(client, probe.pk)
    assert data["delete_is_physical"] is False and data["quotas"][0]["used"] == 0
    assert data["documents"][0]["deleted_at"] is not None
    # Повтор ничего не меняет; новых версий удалённый документ не принимает.
    assert delete(client, probe.pk, v1["document_id"]).status_code == 204
    assert_tz_error(upload_version(client, probe.pk, v1["document_id"], v1["id"]),
                    404, "E-FIL-05")


def test_deleted_documents_are_listed_after_active_ones():
    probe = _folder()
    client = Client()
    gone = upload(client, probe.pk, name="gone.pdf").json()
    _send(probe)
    _return(probe)
    delete(client, probe.pk, gone["document_id"])
    upload(client, probe.pk, name="kept.pdf")

    documents_ = folder(client, probe.pk)["documents"]
    assert [d["current"]["name"] for d in documents_] == ["kept.pdf", "gone.pdf"]


def test_delete_unknown_document_is_E_FIL_05():
    probe = _folder()
    assert_tz_error(delete(Client(), probe.pk, str(uuid.uuid4())), 404, "E-FIL-05")


# ── кто видит и кто меняет ──────────────────────────────────────────────

def test_strangers_see_nothing():
    probe = _folder()
    client = Client()
    document_id = upload(client, probe.pk).json()["document_id"]
    stranger = token(user_id=STRANGER)

    for resp in (client.get(files_url(probe.pk), **auth(stranger)),
                 upload(client, probe.pk, tok=stranger),
                 delete(client, probe.pk, document_id, tok=stranger)):
        assert_tz_error(resp, 404, "E-FIL-05")


def test_after_sending_files_are_read_only_but_visible_to_approvers():
    probe = _folder(viewer_ids=[APPROVER])
    client = Client()
    approver = token(user_id=APPROVER)
    v1 = upload(client, probe.pk).json()
    _send(probe)

    locked = assert_tz_error(upload(client, probe.pk, name="late.pdf"), 409, "E-FIL-06")
    assert locked["detail"]
    assert_tz_error(upload_version(client, probe.pk, v1["document_id"], v1["id"]),
                    409, "E-FIL-06")
    assert_tz_error(delete(client, probe.pk, v1["document_id"]), 409, "E-FIL-06")

    # Автору причина видна: документ на согласовании.
    own = folder(client, probe.pk)
    assert own["can_modify"] is False
    assert own["modify_reason"] == locked["detail"]
    # Согласующий видит и скачивает, но менять не может; причину отказа по
    # правам ему не показывают — он ничего не пытался.
    data = folder(client, probe.pk, tok=approver)
    assert data["can_modify"] is False and data["modify_reason"] is None
    assert all(t["can_add"] is False for t in data["types"])
    document = data["documents"][0]
    link = client.get(f"{files_url(probe.pk)}{document['document_id']}/versions/"
                      f"{document['current']['id']}/link", **auth(approver))
    assert link.status_code == 200 and "sig=" in link.json()["url"]
    denied = assert_tz_error(upload(client, probe.pk, tok=approver), 403, "E-ACC-01")
    assert "только автор" in denied["detail"]


def test_returned_owner_accepts_new_versions_again():
    probe = _folder()
    client = Client()
    v1 = upload(client, probe.pk).json()
    _send(probe)
    _return(probe)

    resp = upload_version(client, probe.pk, v1["document_id"], v1["id"])

    assert resp.status_code == 201, resp.content
    assert resp.json()["version_no"] == 2


def test_version_is_fixed_when_the_owner_is_sent():
    """Версия появляется при вложении — отправка её не пересчитывает."""
    probe = _folder()
    v1 = upload(Client(), probe.pk).json()

    _send(probe)

    row = FileObject.objects.get(pk=v1["id"])
    assert (row.version_no, row.is_replaced) == (1, False)


# ── ссылка и журнал ─────────────────────────────────────────────────────

def test_link_is_a_temporary_signed_url_and_the_download_is_logged():
    """ТЗ §25.2: скачивание файла журналируется — кто, когда, IP, user-agent.
    Ссылка выдаётся на конкретное скачивание, других путей к байтам нет."""
    probe = _folder()
    client = Client()
    v1 = upload(client, probe.pk).json()

    resp = client.get(f"{files_url(probe.pk)}{v1['document_id']}/versions/{v1['id']}/link",
                      HTTP_USER_AGENT="pytest-browser", REMOTE_ADDR="10.1.2.3", **auth())

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert "sig=" in body["url"] and body["expires_at"]
    download = Client().get(body["url"])
    assert download.status_code == 200 and download.content == PDF
    [(actor, payload)] = _events(probe, "file_downloaded")
    assert actor == AUTHOR
    assert payload["file_id"] == v1["id"] and payload["version_no"] == 1
    assert payload["ip"] == "10.1.2.3"
    assert payload["user_agent"] == "pytest-browser"


def test_upload_and_delete_are_logged_with_ip_and_user_agent():
    probe = _folder()
    client = Client()
    v1 = upload(client, probe.pk, HTTP_USER_AGENT="ua-upload",
                REMOTE_ADDR="10.9.9.9").json()

    [(_actor, attached)] = _events(probe, "file_attached")
    assert attached["ip"] == "10.9.9.9"
    assert attached["user_agent"] == "ua-upload"
    delete(client, probe.pk, v1["document_id"])
    [(_actor, deleted)] = _events(probe, "file_deleted")
    assert "ip" in deleted and "user_agent" in deleted


def test_every_file_operation_lands_in_the_file_journal():
    """ТЗ §25.2: журнал файлов — у каждого владельца, не только в его
    собственной ленте; строка журнала переживает физическое удаление."""
    probe = _folder()
    client = Client()
    v1 = upload(client, probe.pk, HTTP_USER_AGENT="ua-1", REMOTE_ADDR="10.2.2.2").json()
    v2 = upload_version(client, probe.pk, v1["document_id"], v1["id"]).json()
    client.get(f"{files_url(probe.pk)}{v1['document_id']}/versions/{v2['id']}/link",
               **auth())
    delete(client, probe.pk, v1["document_id"])

    events = list(FileEvent.objects.filter(owner_type=OWNER,
                                           owner_id=str(probe.pk)).order_by("id"))
    assert [e.event for e in events] == ["file_attached", "file_version_attached",
                                         "file_downloaded", "file_deleted"]
    attached = events[0]
    assert (attached.actor_id, attached.file_id, attached.ip, attached.user_agent) == (
        AUTHOR, v1["id"], "10.2.2.2", "ua-1")
    assert str(attached.document_id) == v1["document_id"]
    # Общий владелец без компании запроса: компания в журнале пуста (у
    # тенантного владельца она — часть ключа, см. test_registry_and_tenancy).
    assert attached.company_slug == "" and "ip" not in attached.payload
    assert events[3].payload["physical"] is True
    assert not FileObject.objects.filter(owner_id=probe.pk).exists()


# ── антивирус (ТЗ §21 [Л]; по умолчанию выключен, D-31) ─────────────────

@pytest.fixture
def scanner(settings, monkeypatch):
    from htqweb import antivirus

    settings.ANTIVIRUS_CLAMD_HOST = "clamav"
    state = {"verdict": antivirus.Verdict(clean=True), "error": None}

    def fake_scan(data):
        if state["error"]:
            raise state["error"]
        return state["verdict"]

    monkeypatch.setattr(antivirus, "scan", fake_scan)
    return state


def test_infected_upload_is_refused_and_journaled(scanner, storage):
    from htqweb import antivirus

    scanner["verdict"] = antivirus.Verdict(clean=False, signature="Win.Test.EICAR_HDB-1")
    probe = _folder()

    resp = upload(Client(), probe.pk, name="schet.pdf",
                  HTTP_USER_AGENT="ua-av", REMOTE_ADDR="10.3.3.3")

    body = assert_tz_error(resp, 422, "E-FIL-08")
    assert body["detail"].startswith("Файл schet.pdf не загружен: антивирус обнаружил "
                                     "угрозу «Win.Test.EICAR_HDB-1»")
    assert body["details"] == {"signature": "Win.Test.EICAR_HDB-1"}
    assert not FileObject.objects.filter(owner_id=probe.pk).exists()
    assert storage.objects == {}
    rejected = FileEvent.objects.get(owner_id=str(probe.pk), event="file_rejected")
    assert (rejected.actor_id, rejected.ip, rejected.user_agent) == (AUTHOR, "10.3.3.3", "ua-av")
    assert rejected.payload["signature"] == "Win.Test.EICAR_HDB-1"
    # Владельцу отказ не сообщается: документа не появилось.
    assert not _events(probe, "file_rejected")


def test_silent_scanner_refuses_the_upload_with_E_SYS_01(scanner):
    from htqweb import antivirus

    scanner["error"] = antivirus.ScanUnavailable("clamd clamav:3310 недоступен")
    probe = _folder()

    body = assert_tz_error(upload(Client(), probe.pk), 503, "E-SYS-01")

    assert "проверка на вирусы сейчас недоступна" in body["detail"]
    assert not FileObject.objects.filter(owner_id=probe.pk).exists()


def test_clean_upload_passes_the_scanner(scanner):
    assert upload(Client(), _folder().pk).status_code == 201


def test_without_a_configured_scanner_files_are_accepted_unchecked(monkeypatch):
    """D-31: проверка по умолчанию выключена — пустой хост clamd не
    закрывает приём и сканер вовсе не зовётся."""
    from htqweb import antivirus

    def must_not_scan(data):
        raise AssertionError("сканер не настроен — его не зовут")

    monkeypatch.setattr(antivirus, "scan", must_not_scan)

    assert upload(Client(), _folder().pk).status_code == 201


# ── запросы и маршруты ──────────────────────────────────────────────────

def test_unsupported_method_is_a_405_in_the_envelope():
    resp = Client().put(files_url(_folder().pk), **auth())
    body = assert_tz_error(resp, 405, "E-FIL-07")
    assert "PUT" in body["detail"]


def test_malformed_multipart_is_E_FIL_07_not_500():
    resp = Client().generic("POST", files_url(_folder().pk), b"garbage",
                            content_type="multipart/form-data", **auth())
    assert_tz_error(resp, 422, "E-FIL-07")


def test_a_key_reused_for_another_file_is_refused():
    probe = _folder()
    client = Client()
    upload(client, probe.pk, key="k-shared", file_type="probe.kp")

    other = upload(client, probe.pk, key="k-shared", file_type="probe.tz")

    assert "другого файла" in assert_tz_error(other, 422, "E-FIL-07")["detail"]


def test_both_url_spellings_are_registered():
    probe = _folder()
    client = Client()
    bare = files_url(probe.pk).rstrip("/")
    assert client.get(bare, **auth()).status_code == 200
    assert client.get(files_url(probe.pk), **auth()).status_code == 200


def test_unknown_owner_type_is_E_FIL_05():
    resp = Client().get(files_url(1, owner_type="nothing.here"), **auth())
    assert_tz_error(resp, 404, "E-FIL-05")


def test_a_key_the_owner_cannot_have_is_E_FIL_05_not_500():
    """Ключ в URL строкой: ``abc`` у владельца с целым ключом — «не найдено»."""
    assert_tz_error(Client().get(files_url("abc"), **auth()), 404, "E-FIL-05")


# ── владелец с UUID-ключом (документы модуля БЗО, D-05) ─────────────────

def test_uuid_owner_keeps_its_files_under_the_canonical_key(storage):
    probe = UuidProbeFolder.objects.create()
    client = Client()

    # Ключ в любом регистре адресует ту же папку.
    resp = upload(client, str(probe.pk).upper(), name="doc.pdf", file_type="probe.doc",
                  owner_type=UUID_OWNER)

    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["storage_key"].startswith(f"file_object/public/uuidfolder/{probe.pk}/")
    row = FileObject.objects.get(pk=body["id"])
    assert row.owner_id == str(probe.pk)
    data = folder(client, probe.pk, owner_type=UUID_OWNER)
    assert data["owner_id"] == str(probe.pk)
    assert [d["current"]["id"] for d in data["documents"]] == [body["id"]]


def test_uuid_owner_rejects_a_key_that_is_not_a_uuid():
    resp = Client().get(files_url("12", owner_type=UUID_OWNER), **auth())
    assert_tz_error(resp, 404, "E-FIL-05")


def test_uuid_owner_callbacks_receive_a_uuid(monkeypatch):
    from .testapp import hooks as probe_hooks

    probe = UuidProbeFolder.objects.create()
    seen = []
    real = probe_hooks._uuid_can_view

    def spy(owner_id, tok):
        seen.append(owner_id)
        return real(owner_id, tok)

    from apps.files.services import registry

    monkeypatch.setitem(registry._OWNERS, UUID_OWNER,
                        dataclasses.replace(registry.get_owner(UUID_OWNER), can_view=spy))

    folder(Client(), str(probe.pk), owner_type=UUID_OWNER)

    assert seen == [probe.pk] and isinstance(seen[0], uuid.UUID)


# ── справочник «Типы файлов» ────────────────────────────────────────────

def test_types_are_listed_with_owner_rules():
    resp = Client().get(f"/api/files/v1/types/?owner_type={OWNER}", **auth())

    assert resp.status_code == 200
    rows = {row["code"]: row for row in resp.json()}
    assert set(rows) == {"probe.kp", "probe.tz", "probe.spec", "probe.other"}
    assert rows["probe.kp"]["quota_group"] == "folder"
    assert rows["probe.kp"]["cardinality"] == "multi"


def test_type_size_is_changed_under_the_files_admin_gate_and_within_the_ceiling():
    """Правка справочника — под гейтом модуля ``files`` уровня ``admin``
    (права только через apps.access); вне контекста компании уровень есть
    лишь у суперпользователя."""
    client = Client()
    url = "/api/files/v1/types/probe.kp/"

    denied = client.patch(url, data='{"max_mb": 5}', content_type="application/json",
                          **auth())
    assert denied.status_code == 403
    too_big = client.patch(url, data='{"max_mb": 50}', content_type="application/json",
                           **auth(superuser_token()))
    assert assert_tz_error(too_big, 422, "E-FIL-07")["fields"][0]["field"] == "max_mb"
    ok = client.patch(url, data='{"max_mb": 5}', content_type="application/json",
                      **auth(superuser_token()))
    assert ok.status_code == 200 and ok.json()["max_mb"] == 5
    assert FileType.objects.get(pk="probe.kp").max_mb == 5

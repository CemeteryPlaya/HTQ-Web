"""Раскладка «папка на владельца» (``ScopePolicy.folder_layout``) и соседние
её правки: хранение оригинала без перекодирования, сигнатура DOCX/XLSX,
пакетная выдача ссылок ``get_file_links``, заголовок скачивания для кириллицы.

Потребитель — файловая подсистема ``apps.files`` (scope ``file_object``):
ключ ``file_object/<компания>/<владелец>/<id>/<uuid>/original<ext>``. Здесь
же — ``owner_gated``: такие файлы media отдаёт только по подписанной ссылке.
"""

from __future__ import annotations

import hashlib
import io
import uuid

import jwt as pyjwt
import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from PIL import Image

from apps.core.models import ServiceStatus
from apps.core.services import ServiceDisabled
from apps.media_files import interface
from apps.media_files.models import FileMetadata
from apps.media_files.services import upload_service
from apps.media_files.services.content_signature import SignatureCheck, verify_signature
from apps.media_files.tests.test_interface import _RecordingStorage

PDF = b"%PDF-1.4\n"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


COMPANY = "t-media-folders"


def auth(**over) -> dict:
    """Рядовой сотрудник под гейтом ``media:write`` (блок L): отказ в тестах
    ниже обязана давать проверка папки, а не гейт модуля."""
    from apps.access.tests.helpers import gate_company

    gate_company(COMPANY, {7: {"media": "write"}})
    claims = {"user_id": 7, "sub": "7", "username": "u", "email": "u@htq.test",
              "is_staff": False, "is_superuser": False, "is_admin": False,
              "token_type": "access", "iat": 1, "exp": 9_999_999_999,
              "iss": "htqweb-auth", "company": COMPANY, **over}
    return {"HTTP_AUTHORIZATION":
            f"Bearer {pyjwt.encode(claims, settings.JWT_SECRET, algorithm='HS256')}",
            "HTTP_X_HTQ_COMPANY": COMPANY}


@pytest.fixture
def storage(monkeypatch):
    fake = _RecordingStorage()
    monkeypatch.setattr(upload_service, "get_storage", lambda bucket=None: fake)
    return fake


def _store(**over):
    kwargs = {"data": PDF, "filename": "kp.pdf", "mime": "application/pdf",
              "scope": "file_object", "owner_id": 7, "folder": "42", **over}
    return interface.store_file(**kwargs)


@pytest.mark.django_db
def test_folder_scope_puts_the_file_under_its_folder(storage):
    result = _store()

    assert result["path"] == f"file_object/42/{result['id']}/original.pdf"
    assert result["path"] in storage.objects


@pytest.mark.django_db
@pytest.mark.parametrize("over", [
    {"folder": None},                       # папка обязательна
    {"folder": "../etc"},                   # выход из префикса
    {"folder": "/42"},                      # абсолютный путь
    {"folder": "42/"},                      # пустой сегмент
    {"folder": "Заявка"},                   # не ASCII
    {"scope": "generic", "folder": "42"},   # у обычного scope папок нет
])
def test_folder_is_required_where_declared_and_refused_elsewhere(storage, over):
    with pytest.raises(ValueError) as exc_info:
        _store(**over)

    assert getattr(exc_info.value, "status_code", None) == 422
    assert not storage.objects and not FileMetadata.objects.exists()


@pytest.mark.django_db
def test_direct_http_upload_into_a_folder_scope_is_refused(storage):
    """Прямая загрузка через media-эндпоинт папку не передаёт — и в
    ``file_object`` без владельца файл не ляжет."""
    resp = Client().post(
        "/api/media/v1/files/",
        {"file": SimpleUploadedFile("kp.pdf", PDF, "application/pdf"),
         "scope": "file_object"},
        **auth())

    assert resp.status_code == 422, resp.content
    assert not storage.objects


@pytest.mark.django_db
def test_date_layout_is_unchanged_for_other_scopes(storage):
    result = interface.store_file(data=b"x", filename="a.txt", mime="text/plain",
                                  scope="generic", owner_id=1)

    scope, year, month, file_id, name = result["path"].split("/")
    assert (scope, file_id, name) == ("generic", result["id"], "original.txt")
    assert len(year) == 4 and len(month) == 2


@pytest.mark.django_db
def test_keep_original_stores_images_byte_for_byte(storage):
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(buf, format="JPEG")
    jpeg = buf.getvalue()

    result = _store(data=jpeg, filename="scan.jpg", mime="image/jpeg")

    assert storage.objects[result["path"]][0] == jpeg
    assert result["sha256"] == hashlib.sha256(jpeg).hexdigest()
    assert result["size"] == len(jpeg)


def test_ooxml_signature_is_checked():
    zip_bytes = b"PK\x03\x04rest"
    assert verify_signature(zip_bytes, DOCX_MIME) is SignatureCheck.MATCH
    assert verify_signature(zip_bytes, XLSX_MIME) is SignatureCheck.MATCH
    assert verify_signature(b"MZ\x90\x00", DOCX_MIME) is SignatureCheck.MISMATCH


@pytest.mark.django_db
def test_renamed_binary_is_not_accepted_as_docx(storage):
    with pytest.raises(ValueError) as exc_info:
        _store(data=b"MZ\x90\x00", filename="spec.docx", mime=DOCX_MIME)

    assert getattr(exc_info.value, "status_code", None) == 415


@pytest.mark.django_db
def test_get_file_links_returns_live_files_only(storage):
    live = _store()
    gone = _store(filename="old.pdf")
    interface.delete_file(gone["id"])

    links = interface.get_file_links([live["id"], gone["id"], str(uuid.uuid4()), "junk"])

    assert set(links) == {live["id"]}
    assert "sig=" in links[live["id"]]["url"]
    assert links[live["id"]]["exp"] > 0


@pytest.mark.django_db
def test_private_download_is_not_cacheable_by_shared_caches(storage, monkeypatch):
    """Подписанная ссылка — приватный файл. Без ``Cache-Control: private``
    edge-кэш nginx (``/api/media/``, 7 дней) отдавал бы его по той же ссылке
    и после истечения ``exp``, мимо проверки подписи."""
    from apps.media_files import views

    monkeypatch.setattr(views, "get_storage", lambda bucket=None: storage)
    private = _store()
    public = interface.store_file(data=b"x", filename="a.txt", mime="text/plain",
                                  scope="generic", owner_id=7)
    FileMetadata.objects.filter(pk=public["id"]).update(is_public=True)

    signed = Client().get(interface.get_file_url(private["id"]))
    assert signed.status_code == 200
    assert signed["Cache-Control"] == "private, max-age=300"

    open_file = Client().get(f"/api/media/v1/files/{public['id']}")
    assert open_file.status_code == 200
    assert "Cache-Control" not in open_file  # публичное, как и раньше, кэшируется


@pytest.mark.django_db
def test_get_file_links_of_nothing_is_empty():
    assert interface.get_file_links([]) == {}


@pytest.mark.django_db
def test_get_file_links_raises_when_media_is_disabled():
    # Выключить ДО первого вызова: статус сервиса кэшируется на 5 секунд.
    ServiceStatus.objects.update_or_create(app_label="media", defaults={"enabled": False})
    with pytest.raises(ServiceDisabled):
        interface.get_file_links([str(uuid.uuid4())])


# ── owner_gated: доступ решает владелец, а не media ─────────────────────

@pytest.fixture
def served(storage, monkeypatch):
    from apps.media_files import views

    monkeypatch.setattr(views, "get_storage", lambda bucket=None: storage)
    return _store()


@pytest.mark.django_db
def test_owner_gated_file_is_served_by_signed_link(served):
    resp = Client().get(interface.get_file_url(served["id"]))

    assert resp.status_code == 200
    assert resp.content == PDF


@pytest.mark.django_db
@pytest.mark.parametrize("who", [
    {},                                    # загрузивший (owner_id=7)
    {"user_id": 9, "sub": "9", "is_admin": True},   # администратор
])
def test_owner_gated_file_is_not_served_by_jwt(served, who):
    """Обычный приватный файл загрузивший и администратор получают по JWT.
    Документ ТЗ §21 — нет: это обход проверки прав объекта-владельца."""
    resp = Client().get(f"/api/media/v1/files/{served['id']}", **auth(**who))

    assert resp.status_code == 403


@pytest.mark.django_db
def test_owner_gated_link_cannot_be_signed_through_media(served):
    resp = Client().post(f"/api/media/v1/files/{served['id']}/sign",
                         **auth(user_id=9, sub="9", is_admin=True))

    assert resp.status_code == 403


@pytest.mark.django_db
def test_cyrillic_file_name_survives_the_download_header(served, storage):
    """Имя вне latin-1 — в ``filename*=utf-8''…`` (RFC 6266). Прежний
    ``filename="КП.pdf"`` Django кодировал целиком по RFC 2047, браузер его
    не понимал: документ скачивался под UUID, а inline/attachment терялся."""
    stored = _store(filename="КП поставщика.pdf")

    resp = Client().get(interface.get_file_url(stored["id"]))

    assert resp.status_code == 200
    assert resp["Content-Disposition"] == (
        "inline; filename*=utf-8''%D0%9A%D0%9F%20%D0%BF%D0%BE%D1%81%D1%82%D0%B0"
        "%D0%B2%D1%89%D0%B8%D0%BA%D0%B0.pdf")


@pytest.mark.django_db
def test_html_with_a_cyrillic_name_is_still_an_attachment(storage, monkeypatch):
    """Защита R4 (HTML не рендерится на нашем происхождении) держится и
    для не-ASCII имени: тип ``attachment`` больше не теряется в кодировке."""
    from apps.media_files import views

    monkeypatch.setattr(views, "get_storage", lambda bucket=None: storage)
    page = interface.store_file(data=b"<script>alert(1)</script>", filename="отчёт.html",
                                mime="text/html", scope="generic", owner_id=7)
    FileMetadata.objects.filter(pk=page["id"]).update(is_public=True)

    resp = Client().get(f"/api/media/v1/files/{page['id']}")

    assert resp.status_code == 200
    assert resp["Content-Disposition"].startswith("attachment; filename*=utf-8''")


# ── антивирус (ScopePolicy.antivirus, ТЗ §21) ───────────────────────────

@pytest.fixture
def scanner(settings, monkeypatch):
    """Антивирус «включён», а clamd подменён: протокол проверяется в
    apps/core/tests/test_antivirus.py, здесь — что пайплайн с ним делает."""
    from htqweb import antivirus

    settings.ANTIVIRUS_CLAMD_HOST = "clamav"
    calls = []
    state = {"verdict": antivirus.Verdict(clean=True), "error": None}

    def fake_scan(data):
        calls.append(data)
        if state["error"]:
            raise state["error"]
        return state["verdict"]

    monkeypatch.setattr(antivirus, "scan", fake_scan)
    return calls, state


def test_document_scopes_require_antivirus():
    """Документы проверяются всегда: файлы ТЗ §21, сканы договорного контура
    (generic — туда же любой неизвестный scope) и PDF шагов согласования,
    включая «Счёт на оплату». Аватарки и чат — нет."""
    from apps.media_files.services.scope_policy import get_policy

    for scope in ("file_object", "generic", "signoff_doc", "no-such-scope"):
        assert get_policy(scope).antivirus is True, scope
    for scope in ("avatar", "chat", "news"):
        assert get_policy(scope).antivirus is False, scope


@pytest.mark.django_db
def test_clean_file_is_scanned_before_it_is_stored(storage, scanner):
    calls, _state = scanner

    result = _store()

    assert calls == [PDF]
    assert FileMetadata.objects.filter(pk=result["id"]).exists()


@pytest.mark.django_db
def test_infected_file_is_not_stored(storage, scanner):
    from htqweb import antivirus

    _calls, state = scanner
    state["verdict"] = antivirus.Verdict(clean=False, signature="Win.Test.EICAR_HDB-1")

    with pytest.raises(interface.FileInfected) as caught:
        _store()

    assert caught.value.status_code == 422
    assert caught.value.signature == "Win.Test.EICAR_HDB-1"
    assert not FileMetadata.objects.exists()
    assert storage.objects == {}  # байты угрозы в хранилище не попали


@pytest.mark.django_db
def test_silent_scanner_closes_the_door(storage, scanner):
    """Настроенный, но недоступный сканер — 503, а не непроверенный файл."""
    from htqweb import antivirus

    _calls, state = scanner
    state["error"] = antivirus.ScanUnavailable("clamd clamav:3310 недоступен")

    with pytest.raises(interface.ScanUnavailable) as caught:
        _store()

    assert caught.value.status_code == 503
    assert not FileMetadata.objects.exists()


@pytest.mark.django_db
def test_scopes_without_the_flag_are_not_scanned(storage, scanner):
    calls, _state = scanner

    interface.store_file(data=PDF, filename="scan.pdf", mime="application/pdf",
                         scope="chat", owner_id=7)

    assert calls == []


@pytest.mark.django_db
def test_disabled_antivirus_skips_the_scan(storage, scanner, settings):
    calls, _state = scanner
    settings.ANTIVIRUS_CLAMD_HOST = ""

    _store()

    assert calls == []

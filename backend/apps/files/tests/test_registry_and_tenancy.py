"""Реестр владельцев, тенантный владелец и правила, которых нет у пробной папки.

Тестовый владелец ``testapp.thing`` регистрируется на время теста: он
тенантный (как будущие документы модуля БЗО), разрешает всё и держит тип
``single`` («1 действующий + версии») и обязательный тип. На нём видно:

* файлы тенантного владельца разведены по компаниям — id строк в разных
  схемах повторяются, и без компании в ключе договор №5 одной компании
  показывал бы файлы договора №5 другой;
* папка в хранилище включает компанию;
* ``single`` не принимает второй документ, но принимает новую версию;
* ``missing_required`` / ``required_files_error`` — то, чем владелец
  откажет в отправке без обязательного файла (E-FIL-04);
* его ``lock`` ничего не блокирует — поэтому на нём видны последние рубежи
  против гонок: уникальные индексы, чей отказ становится повтором или
  E-CON-01, а не 500.
"""

from __future__ import annotations

import uuid

import pytest
from django.test import Client

from apps.files import interface as files
from apps.files.models import FileEvent, FileObject, FileType
from apps.files.services import documents, registry
from apps.media_files.models import FileMetadata
from htqweb.tenancy import NoCompanyContext

from .helpers import (
    OWNER, assert_tz_error, auth, delete, files_url, folder, upload, upload_version,
)

pytestmark = pytest.mark.django_db

THING = "testapp.thing"


@pytest.fixture
def thing(monkeypatch):
    FileType.objects.create(code="thing.main", owner_type=THING, name="Основной",
                            formats=[".pdf"], max_mb=20, sort_order=1)
    FileType.objects.create(code="thing.extra", owner_type=THING, name="Приложение",
                            formats=[".pdf", ".png"], max_mb=20, sort_order=2)
    events = []
    entry = files.register_owner(
        THING, label="Вещь", service="files", tenant=True, folder="thing",
        file_types=(files.FileTypeSpec("thing.main", cardinality=files.SINGLE,
                                       required=True),
                    files.FileTypeSpec("thing.extra", max_documents=2)),
        can_view=lambda owner_id, token: True,
        can_modify=lambda owner_id, token: None,
        was_sent=lambda owner_id: False,
        lock=lambda owner_id: None,
        on_event=lambda *args: events.append(args),
    )
    company = {"slug": "kz"}
    # interface берёт компанию через documents.owner_company — одна точка.
    monkeypatch.setattr(documents, "current_company_or_none", lambda: company["slug"])
    yield entry, company, events
    registry._OWNERS.pop(THING, None)


def test_tenant_owner_files_are_isolated_by_company(thing, storage):
    _entry, company, _events = thing
    client = Client()

    body = upload(client, 5, owner_type=THING, file_type="thing.main").json()
    assert body["storage_key"].startswith("file_object/kz/thing/5/")
    assert body["storage_key"] in storage.objects

    company["slug"] = "ru"
    assert folder(client, 5, owner_type=THING)["documents"] == []
    other = upload(client, 5, owner_type=THING, file_type="thing.main")
    assert other.status_code == 201  # у договора №5 в «ru» своего файла ещё нет
    assert other.json()["storage_key"].startswith("file_object/ru/thing/5/")

    company["slug"] = "kz"
    documents_kz = folder(client, 5, owner_type=THING)["documents"]
    assert [d["current"]["id"] for d in documents_kz] == [body["id"]]


def test_single_type_takes_one_document_and_new_versions(thing):
    client = Client()
    v1 = upload(client, 7, owner_type=THING, file_type="thing.main").json()

    second = upload(client, 7, owner_type=THING, file_type="thing.main", name="b.pdf")
    body = assert_tz_error(second, 409, "E-FIL-03")
    assert "уже приложен" in body["detail"] and "новую версию" in body["detail"]
    main = next(t for t in folder(client, 7, owner_type=THING)["types"]
                if t["code"] == "thing.main")
    assert main["can_add"] is False and main["cardinality"] == "single"

    version = upload_version(client, 7, v1["document_id"], v1["id"], owner_type=THING)
    assert version.status_code == 201 and version.json()["version_no"] == 2


def test_per_type_limit_without_a_group(thing):
    client = Client()
    for name in ("a.pdf", "b.pdf"):
        assert upload(client, 8, owner_type=THING, file_type="thing.extra",
                      name=name).status_code == 201

    over = upload(client, 8, owner_type=THING, file_type="thing.extra", name="c.pdf")

    assert_tz_error(over, 409, "E-FIL-03")


def test_owner_events_are_written(thing):
    _entry, _company, events = thing

    upload(Client(), 9, owner_type=THING, file_type="thing.main")

    assert events and events[0][0] == 9 and events[0][1] == "file_attached"


def test_missing_required_and_its_error(thing):
    assert files.missing_required(THING, 10) == [{"code": "thing.main", "name": "Основной"}]
    body = files.required_files_error(files.missing_required(THING, 10),
                                      action="отправить вещь")
    assert body["code"] == "E-FIL-04"
    assert body["detail"] == ("Не удалось отправить вещь: не приложен файл «Основной». "
                               "Приложите его и повторите отправку.")
    assert body["fields"] == [{"field": "thing.main",
                               "message": "Не приложен обязательный файл"}]

    upload(Client(), 10, owner_type=THING, file_type="thing.main")
    assert files.missing_required(THING, 10) == []
    assert files.live_document_count(THING, 10) == 1


def test_locked_and_forbidden_owner_answers_map_to_tz_codes(thing):
    entry, _company, _events = thing

    def locked(owner_id, token):
        raise files.FilesLocked("Файлы вещи меняются только в черновике.")

    # Запись реестра заморожена (frozen dataclass); тестовый владелец
    # снимается с регистрации в конце фикстуры.
    object.__setattr__(entry, "can_modify", locked)
    resp = upload(Client(), 11, owner_type=THING, file_type="thing.main")
    assert assert_tz_error(resp, 409, "E-FIL-06")["detail"] == \
        "Файлы вещи меняются только в черновике."

    def forbidden(owner_id, token):
        raise files.FilesForbidden("Нет прав на файлы вещи.")

    object.__setattr__(entry, "can_modify", forbidden)
    resp = upload(Client(), 11, owner_type=THING, file_type="thing.main")
    assert_tz_error(resp, 403, "E-ACC-01")


def test_tenant_owner_without_company_context_fails_loudly(thing, monkeypatch):
    """Компании заведены, а контекста нет (запрос мимо поддомена, задача без
    company_slug): молча взять «ничью» компанию значило бы читать и писать
    чужую кучу файлов — поэтому NoCompanyContext, наружу 500."""
    entry, company, _events = thing
    company["slug"] = None
    monkeypatch.setattr(documents.companies, "active_company_slugs", lambda: ["kz"])

    with pytest.raises(NoCompanyContext):
        documents.owner_company(entry)
    with pytest.raises(NoCompanyContext):
        files.live_document_count(THING, 5)
    assert Client().get(files_url(5, owner_type=THING), **auth()).status_code == 500
    assert not FileObject.objects.exists()


def test_before_the_first_company_tenant_files_live_in_public(thing, monkeypatch):
    """До tenancy_bootstrap компаний нет вовсе — честная компания ``""``."""
    _entry, company, _events = thing
    company["slug"] = None
    monkeypatch.setattr(documents.companies, "active_company_slugs", lambda: [])

    body = upload(Client(), 6, owner_type=THING, file_type="thing.main").json()

    assert body["storage_key"].startswith("file_object/public/thing/6/")
    assert FileObject.objects.get(pk=body["id"]).company_slug == ""


# ── гонки мимо блокировки владельца ─────────────────────────────────────

def _rival(owner_id: int, **fields) -> FileObject:
    """Запись «соседнего запроса», успевшего между проверкой и вставкой."""
    defaults = dict(company_slug="kz", owner_type=THING, owner_id=owner_id,
                    file_type_id="thing.main", document_id=uuid.uuid4(), version_no=1,
                    name="rival.pdf", mime="application/pdf", size=1, sha256="0" * 64,
                    storage_key=f"rival/{uuid.uuid4()}",
                    media_file_id=f"rival-{uuid.uuid4()}",
                    uploaded_by_id=99, uploaded_by_name="Соперник")
    defaults.update(fields)
    return FileObject.objects.create(**defaults)


def test_version_race_past_the_lock_is_a_conflict_not_500(thing, monkeypatch):
    """Две версии поверх одной базы сходятся на индексе (документ, номер):
    второй — E-CON-01 с именем успевшего, его файл возвращается в media."""
    client = Client()
    v1 = upload(client, 12, owner_type=THING, file_type="thing.main").json()
    real = documents._assert_base_is_current
    calls = []

    def _rival_commits_in_between(current, base_id):
        real(current, base_id)
        calls.append(1)
        if len(calls) == 2:  # проверка в _link пройдена — вставляет соперник
            _rival(12, document_id=v1["document_id"], version_no=2)

    monkeypatch.setattr(documents, "_assert_base_is_current", _rival_commits_in_between)
    resp = upload_version(client, 12, v1["document_id"], v1["id"], owner_type=THING,
                          name="loser.pdf")

    body = assert_tz_error(resp, 409, "E-CON-01")
    assert "Соперник" in body["detail"]
    assert FileMetadata.objects.get(original_filename="loser.pdf").deleted_at is not None


def test_repeat_race_past_the_lock_returns_the_first_record(
        thing, monkeypatch, django_capture_on_commit_callbacks):
    """Два повтора с одним ключом сходятся на индексе ключа повтора: второй
    отдаёт запись первого, а свой лишний файл возвращает в media."""
    real = documents._quota_error
    calls = []
    rival = {}

    def _rival_commits_in_between(ref, spec, live, types):
        blocked = real(ref, spec, live, types)
        calls.append(1)
        if len(calls) == 2:  # под «блокировкой» _link, после проверки повтора
            rival["row"] = _rival(13, file_type_id="thing.extra", idempotency_key="k-race")
        return blocked

    monkeypatch.setattr(documents, "_quota_error", _rival_commits_in_between)
    with django_capture_on_commit_callbacks(execute=True):
        resp = upload(Client(), 13, owner_type=THING, file_type="thing.extra",
                      key="k-race", name="second.pdf")

    assert resp.status_code == 201, resp.content
    assert resp.json()["id"] == rival["row"].pk
    assert FileMetadata.objects.get(original_filename="second.pdf").deleted_at is not None


def test_one_failed_discard_does_not_stop_the_others(
        thing, monkeypatch, django_capture_on_commit_callbacks):
    """Возврат файлов в media после коммита — robust: сбой на одном файле не
    роняет уже закоммиченное удаление и не мешает вернуть остальные."""
    client = Client()
    v1 = upload(client, 14, owner_type=THING, file_type="thing.main").json()
    upload_version(client, 14, v1["document_id"], v1["id"], owner_type=THING)
    media_ids = sorted(FileObject.objects.filter(owner_id=14)
                       .values_list("media_file_id", flat=True))
    attempted = []

    def _flaky_delete(media_file_id):
        attempted.append(media_file_id)
        if len(attempted) == 1:
            raise OSError("S3 недоступен")

    monkeypatch.setattr(documents.media, "delete_file", _flaky_delete)
    with django_capture_on_commit_callbacks(execute=True):
        resp = delete(client, 14, v1["document_id"], owner_type=THING)

    assert resp.status_code == 204
    assert sorted(attempted) == media_ids
    assert not FileObject.objects.filter(owner_id=14).exists()


# ── для владельцев и выкатки ────────────────────────────────────────────

def _row(owner_type: str, owner_id: int, file_type: str, company: str = "") -> FileObject:
    return FileObject.objects.create(
        company_slug=company, owner_type=owner_type, owner_id=owner_id,
        file_type_id=file_type, document_id=uuid.uuid4(), version_no=1, name="f.pdf",
        mime="application/pdf", size=1, sha256="0" * 64,
        storage_key=f"seed/{uuid.uuid4()}", media_file_id=f"seed-{uuid.uuid4()}",
        uploaded_by_id=7)


def test_owners_with_documents_is_one_query_per_list(thing, django_assert_num_queries):
    _entry, company, _events = thing
    _row(THING, 1, "thing.main", company="kz")
    _row(THING, 2, "thing.extra", company="kz")
    _row(THING, 3, "thing.main", company="ru")  # чужая компания не в счёт

    files.owners_with_documents(THING, [1])  # прогрев кэша рубильника сервиса
    with django_assert_num_queries(1):
        assert files.owners_with_documents(THING, [1, 2, 3, 4]) == {1, 2}
    assert files.owners_with_documents(THING, [1, 2, 3], "thing.main") == {1}
    company["slug"] = "ru"
    assert files.owners_with_documents(THING, [1, 2, 3]) == {3}


def test_assign_company_stamps_only_tenant_owners(thing):
    """tenancy_bootstrap: файлы тенантного владельца, заведённые до первой
    компании, переезжают вместе с его таблицами; общие владельцы — нет."""
    tenant = _row(THING, 5, "thing.main")
    shared = _row(OWNER, 5, "probe.kp")
    FileEvent.objects.create(owner_type=THING, owner_id=5, event="file_attached")
    FileEvent.objects.create(owner_type=OWNER, owner_id=5, event="file_attached")

    assert files.assign_company("kz", dry_run=True) == {"files": 1, "events": 1}
    tenant.refresh_from_db()
    assert tenant.company_slug == ""

    assert files.assign_company("kz") == {"files": 1, "events": 1}
    tenant.refresh_from_db()
    shared.refresh_from_db()
    assert (tenant.company_slug, shared.company_slug) == ("kz", "")
    assert set(FileEvent.objects.values_list("owner_type", "company_slug")) == {
        (THING, "kz"), (OWNER, "")}


# ── регистрация ─────────────────────────────────────────────────────────

def _register(owner_type="testapp.x", **over):
    kwargs = dict(label="X", service="files", tenant=False, folder="x",
                  file_types=(files.FileTypeSpec("x.a"),),
                  can_view=lambda *a: True, can_modify=lambda *a: None,
                  was_sent=lambda *a: False, lock=lambda *a: None)
    kwargs.update(over)
    try:
        return files.register_owner(owner_type, **kwargs)
    finally:
        registry._OWNERS.pop(owner_type, None)


@pytest.mark.parametrize("over", [
    {"owner_type": "NoDot"},
    {"folder": "Bad Folder"},
    {"file_types": ()},
    {"file_types": (files.FileTypeSpec("x.a"), files.FileTypeSpec("x.a"))},
    {"file_types": (files.FileTypeSpec("x.a", cardinality="many"),)},
    {"file_types": (files.FileTypeSpec("x.a", quota_group="nope"),)},
    {"file_types": (files.FileTypeSpec("x.a", quota_group="g"),), "quotas": {"g": 0}},
])
def test_invalid_registrations_are_refused(over):
    with pytest.raises(ValueError):
        _register(**over)


def test_every_registered_type_is_seeded_in_the_reference():
    """Строка справочника на каждый тип, объявленный настоящим владельцем:
    иначе папка владельца падает ImproperlyConfigured на выкатке. Пробные
    владельцы (тесты) сеют справочник фикстурой, а настоящих пока нет —
    владельцы модуля БЗО придут со своими миграциями справочника."""
    declared = {spec.code for entry in registry.registered_owners().values()
                if entry.owner_type != THING and not entry.owner_type.startswith("filestest.")
                for spec in entry.file_types}
    seeded = set(FileType.objects.exclude(owner_type__startswith="filestest.")
                 .values_list("code", flat=True))
    assert declared <= seeded

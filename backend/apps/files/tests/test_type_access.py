"""Права по типу файла — необязательные колбэки владельца ``can_view_type``/
``can_modify_type`` (ТЗ §21: счёт на оплату видят автор, ФД, БУХ, ТД, ОД, ГД,
а АВР и накладную — только автор, ФД и БУХ; закрывающие документы
прикладываются, когда файл счёта уже закрыт).

Пробный владелец ``filestest.typed`` — та же ``ProbeFolder``, что у папки
``filestest.folder``, но менять файлы может и согласующий из ``viewer_ids``
(колбэк объекта разрешающий), а тип уточняет:

* ``typed.open`` — видят и меняют все, кто видит папку;
* ``typed.secret`` — видит только автор: согласующему документа нет вовсе
  (папка, ссылка, новая версия, удаление — 404 как у несуществующего);
* ``typed.closed`` — видят все, менять нельзя: ``FilesLocked`` → 409;
* ``typed.denied`` — видят все, колбэк отвечает ``False`` → 403.

Загрузка из кода (``attach_bytes``) уточнений не спрашивает — права там
проверил сам владелец. Владелец без уточнений ведёт себя как прежде.
"""

from __future__ import annotations

import uuid

import pytest
from django.test import Client

from apps.files import interface as files
from apps.files.models import FileType
from apps.files.services import registry

from .helpers import (
    APPROVER, AUTHOR, OWNER, PDF, UUID_OWNER, assert_tz_error, auth, delete, files_url,
    folder, token, upload, upload_version,
)
from .testapp.models import ProbeFolder

pytestmark = pytest.mark.django_db

TYPED = "filestest.typed"
OPEN, SECRET, CLOSED, DENIED = "typed.open", "typed.secret", "typed.closed", "typed.denied"
LOCKED_TEXT = "Закрывающие документы этой папки уже приняты — менять их нельзя."


def _folder_of(owner_id) -> ProbeFolder | None:
    return ProbeFolder.objects.filter(pk=owner_id).first()


def _can_view(owner_id, tok) -> bool:
    probe = _folder_of(owner_id)
    return probe is not None and (tok.user_id == probe.author_id
                                  or tok.user_id in probe.viewer_ids)


def _can_modify(owner_id, tok) -> None:
    if not _can_view(owner_id, tok):
        raise files.FilesForbidden("Менять файлы может только участник документа.")


def _can_view_type(owner_id, tok, file_type) -> bool:
    return file_type != SECRET or tok.user_id == _folder_of(owner_id).author_id


def _can_modify_type(owner_id, tok, file_type) -> bool:
    if file_type == CLOSED:
        raise files.FilesLocked(LOCKED_TEXT)
    return file_type != DENIED


@pytest.fixture(autouse=True)
def typed_owner():
    for order, code in enumerate((OPEN, SECRET, CLOSED, DENIED)):
        FileType.objects.update_or_create(code=code, defaults={
            "owner_type": TYPED, "name": f"Тип {code}", "formats": [".pdf"],
            "max_mb": 20, "sort_order": order})
    files.register_owner(
        TYPED, label="Папка с правами по типу", service="files", tenant=False,
        folder="typed",
        file_types=tuple(files.FileTypeSpec(code) for code in (OPEN, SECRET, CLOSED, DENIED)),
        can_view=_can_view, can_modify=_can_modify,
        was_sent=lambda owner_id: False,
        lock=lambda owner_id: ProbeFolder.objects.select_for_update().filter(pk=owner_id).first(),
        can_view_type=_can_view_type, can_modify_type=_can_modify_type,
    )
    yield
    registry._OWNERS.pop(TYPED, None)


def _probe() -> ProbeFolder:
    return ProbeFolder.objects.create(viewer_ids=[APPROVER])


def _attach(probe: ProbeFolder, file_type: str, name: str = "doc.pdf") -> dict:
    """Документ из кода владельца — уточнения по типу не спрашиваются."""
    return files.attach_bytes(TYPED, probe.pk, file_type=file_type, data=PDF,
                              filename=name, mime="application/pdf", actor_id=AUTHOR)


def _approver() -> str:
    return token(user_id=APPROVER, sub=str(APPROVER))


def _link(client: Client, probe: ProbeFolder, version: dict, tok: str | None = None):
    return client.get(f"{files_url(probe.pk, TYPED)}{version['document_id']}/versions/"
                      f"{version['id']}/link", **auth(tok))


def test_hidden_type_is_not_in_the_folder_of_who_cannot_see_it():
    probe = _probe()
    open_doc = _attach(probe, OPEN, "open.pdf")
    secret = _attach(probe, SECRET, "secret.pdf")

    seen_by_approver = folder(Client(), probe.pk, tok=_approver(), owner_type=TYPED)
    assert [d["document_id"] for d in seen_by_approver["documents"]] == [open_doc["document_id"]]
    assert SECRET not in {t["code"] for t in seen_by_approver["types"]}

    seen_by_author = folder(Client(), probe.pk, owner_type=TYPED)
    assert {d["document_id"] for d in seen_by_author["documents"]} == {
        open_doc["document_id"], secret["document_id"]}
    assert SECRET in {t["code"] for t in seen_by_author["types"]}


def test_hidden_type_link_version_and_delete_answer_like_a_missing_document():
    probe = _probe()
    secret = _attach(probe, SECRET)
    client = Client()

    hidden = _link(client, probe, secret, _approver())
    missing = _link(client, probe, {"document_id": str(uuid.uuid4()), "id": secret["id"]},
                    _approver())
    assert assert_tz_error(hidden, 404, "E-FIL-05")["detail"] == missing.json()["detail"]

    version = upload_version(client, probe.pk, secret["document_id"], secret["id"],
                             tok=_approver(), owner_type=TYPED)
    assert_tz_error(version, 404, "E-FIL-05")
    removed = delete(client, probe.pk, secret["document_id"], tok=_approver(),
                     owner_type=TYPED)
    assert_tz_error(removed, 404, "E-FIL-05")

    # Автор видит и скачивает.
    assert _link(client, probe, secret).status_code == 200


def test_modify_by_type_locked_is_409_with_the_owner_text():
    probe = _probe()
    closed = _attach(probe, CLOSED)
    client = Client()

    new = upload(client, probe.pk, file_type=CLOSED, owner_type=TYPED)
    assert assert_tz_error(new, 409, "E-FIL-06")["detail"] == LOCKED_TEXT
    version = upload_version(client, probe.pk, closed["document_id"], closed["id"],
                             owner_type=TYPED)
    assert_tz_error(version, 409, "E-FIL-06")
    removed = delete(client, probe.pk, closed["document_id"], owner_type=TYPED)
    assert_tz_error(removed, 409, "E-FIL-06")
    # Посмотреть и скачать — можно: тип закрыт для правки, а не для чтения.
    assert _link(client, probe, closed).status_code == 200


def test_modify_by_type_denied_is_403():
    probe = _probe()
    client = Client()

    resp = upload(client, probe.pk, file_type=DENIED, owner_type=TYPED)

    body = assert_tz_error(resp, 403, "E-ACC-01")
    assert f"Тип {DENIED}" in body["detail"]


def test_folder_explains_per_type_add_ability():
    """Папка говорит, какой тип можно добавить: закрытый — с объяснением
    владельца, запрещённый — без объяснения, открытый — можно."""
    probe = _probe()

    types = {t["code"]: t for t in folder(Client(), probe.pk, owner_type=TYPED)["types"]}

    assert types[OPEN]["can_add"] is True and types[OPEN]["reason"] is None
    assert types[CLOSED]["can_add"] is False and types[CLOSED]["reason"] == LOCKED_TEXT
    assert types[DENIED]["can_add"] is False and types[DENIED]["reason"] is None


def test_open_type_is_modified_as_before():
    probe = _probe()
    client = Client()

    first = upload(client, probe.pk, file_type=OPEN, owner_type=TYPED, tok=_approver())
    assert first.status_code == 201, first.content
    body = first.json()
    second = upload_version(client, probe.pk, body["document_id"], body["id"],
                            tok=_approver(), owner_type=TYPED)
    assert second.status_code == 201, second.content


def test_owners_without_type_callbacks_are_unchanged():
    """Уточнения необязательны: у владельцев, заведённых без них, тип файла на
    доступ не влияет (их поведение проверяют остальные тесты подсистемы)."""
    for owner_type in (OWNER, UUID_OWNER):
        entry = registry.get_owner(owner_type)
        assert entry.can_view_type is None and entry.can_modify_type is None
    assert registry.get_owner(TYPED).can_view_type is _can_view_type

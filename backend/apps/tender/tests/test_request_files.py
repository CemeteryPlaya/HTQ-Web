"""Файлы ТЗ и чертежей заявки — владелец ``tender.request`` в ``apps.files``
(T1.1; план этапов 0–2, §3.4). Своих ручек файлов у заявки нет: панель
``/api/files/v1/tender.request/<id>/files/``. Добавляет и удаляет автор в
«Черновике» и «На доработке»; видит тот, кто видит заявку."""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.bpp.tests.test_files import PDF, memory_storage  # noqa: F401  (фикстура)
from apps.files.models import FileType
from apps.tender import file_owners
from apps.tender.models import TenderRequest
from apps.tender.tests import helpers as h
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db
FILES = "/api/files/v1"


def test_spec_file_type_is_seeded():
    row = FileType.objects.get(code="tender_spec")
    assert row.owner_type == file_owners.REQUEST_OWNER == "tender.request"
    assert set(row.formats) >= {".pdf", ".docx", ".xlsx", ".jpg", ".jpeg", ".png"}
    assert row.max_mb == 20


def _add(slug, user_id, request_id, name="tz.pdf"):
    return Client().post(f"{FILES}/{file_owners.REQUEST_OWNER}/{request_id}/files/", data={
        "file_type": "tender_spec",
        "file": SimpleUploadedFile(name, PDF, content_type="application/pdf"),
    }, **h.auth(slug, user_id))


def test_author_attaches_in_draft_others_cannot(company_context, memory_storage):  # noqa: F811
    slug = company_context["slug"]
    h.staff(slug)
    proj = h.project()
    card = h.call("post", "requests", slug, h.SN, h.body(proj)).json()

    added = _add(slug, h.SN, card["id"])
    assert added.status_code == 201, added.content
    # Чужой закупщик заявку не видит — папка 404; ФД видит, но не меняет.
    assert _add(slug, h.SN2, card["id"]).status_code == 404
    assert _add(slug, h.FD, card["id"]).status_code == 403
    folder = Client().get(f"{FILES}/{file_owners.REQUEST_OWNER}/{card['id']}/files/",
                          **h.auth(slug, h.FD))
    assert folder.status_code == 200 and len(folder.json()["documents"]) == 1

    with use_company(slug):
        TenderRequest.objects.filter(pk=card["id"]).update(status="in_approval")
    locked = _add(slug, h.SN, card["id"], "drawing.pdf")
    assert locked.status_code == 409 and locked.json()["code"] == "E-FIL-06"


def test_deleting_the_draft_takes_its_files(company_context, memory_storage):  # noqa: F811
    from apps.files.models import FileObject

    slug = company_context["slug"]
    h.staff(slug)
    card = h.call("post", "requests", slug, h.SN, h.body(h.project())).json()
    assert _add(slug, h.SN, card["id"]).status_code == 201
    assert h.call("delete", f"requests/{card['id']}", slug, h.SN).status_code == 200
    assert not FileObject.objects.filter(owner_type=file_owners.REQUEST_OWNER,
                                         owner_id=card["id"]).exists()

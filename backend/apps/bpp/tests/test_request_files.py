"""Документы заявки (ТЗ §7.5, §21) — через панель файлов ``/api/files/v1``
(владелец ``bpp.purchase_request``, своих ручек файлов у заявки нет, B-2):
добавляет и удаляет автор в черновике и на доработке, после отправки —
только новая версия (``can_version``); скачивание — через журнал."""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.bpp.file_owners import REQUEST_OWNER
from apps.bpp.services.requests import requests as service
from apps.bpp.tests import stage2 as s
from apps.bpp.tests.test_files import PDF, memory_storage  # noqa: F401  (фикстура)
from apps.files.models import FileEvent
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db
FILES = "/api/files/v1"


def _pdf(name="kp.pdf"):
    return SimpleUploadedFile(name, PDF, content_type="application/pdf")


def _headers(slug, user_id):
    # Multipart — без content_type JSON из ``s.auth``.
    return {k: v for k, v in s.auth(slug, user_id).items() if k != "content_type"}


def _setup(slug):
    proj, art = s.project(), s.metal()
    s.approved_budget(slug, proj, {art: 10_000})
    s.request_route()
    sn = s.actor(slug, s.SN, "bpp-sn")
    req = service.create_draft(sn, {**s.header(proj, art), "items": s.items((1, 100))})
    return sn, req


def _add(client, slug, user_id, request_id, name="kp.pdf"):
    return client.post(f"{FILES}/{REQUEST_OWNER}/{request_id}/files/", data={
        "file_type": "request_attachment", "file": _pdf(name)}, **_headers(slug, user_id))


def test_author_attaches_in_draft_and_only_versions_after_submit(company_context):
    slug = company_context["slug"]
    sn, req = _setup(slug)
    request_id, client = req.id, Client()
    first = _add(client, slug, s.SN, request_id)
    assert first.status_code == 201, first.content
    document = first.json()

    with use_company(slug):       # клиент после ответа возвращает search_path на public
        service.submit(sn, request_id, expected_version=None)

    added = _add(client, slug, s.SN, request_id, "tz.pdf")
    assert added.status_code == 409 and added.json()["code"] == "E-FIL-06"
    newer = client.post(
        f"{FILES}/{REQUEST_OWNER}/{request_id}/files/{document['document_id']}/versions",
        data={"file": _pdf("kp-v2.pdf"), "base_file_id": document["id"]},
        **_headers(slug, s.SN))
    assert newer.status_code == 201, newer.content
    assert newer.json()["version_no"] == 2

    folder = client.get(f"{FILES}/{REQUEST_OWNER}/{request_id}/files/",
                        **s.auth(slug, s.SN)).json()
    assert folder["can_modify"] is False                     # добавлять и удалять — нельзя
    [doc] = folder["documents"]
    assert doc["current"]["name"] == "kp-v2.pdf"
    assert (doc["can_version"], doc["can_delete"]) == (True, False)


def test_only_the_author_attaches_and_every_download_is_logged(company_context):
    slug = company_context["slug"]
    sn, req = _setup(slug)
    s.grant(slug, s.SN2, "bpp-sn")
    s.grant(slug, s.TD, "bpp-td")
    request_id, client = req.id, Client()
    row = _add(client, slug, s.SN, request_id).json()
    # Чужую заявку другой СН и не видит — её папка тоже 404.
    assert _add(client, slug, s.SN2, request_id).status_code == 404

    with use_company(slug):
        service.submit(sn, request_id, expected_version=None)
    # Согласующий видит документы заявки и скачивает их через журнал (ТЗ §25.2).
    link = client.get(f"{FILES}/{REQUEST_OWNER}/{request_id}/files/{row['document_id']}"
                      f"/versions/{row['id']}/link", **s.auth(slug, s.TD))
    assert link.status_code == 200, link.content
    assert FileEvent.objects.filter(event="file_downloaded", file_id=row["id"],
                                    actor_id=s.TD).count() == 1

"""Документы заявки (ТЗ §7.5, §21): добавляет автор в черновике и на
доработке, дальше — только новая версия; скачивание — через журнал."""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.bpp.models import FileDownload
from apps.bpp.services.requests import files
from apps.bpp.services.requests import requests as service
from apps.bpp.tests import stage2 as s
from apps.bpp.tests.test_files import PDF, memory_storage  # noqa: F401  (фикстура)
from htqweb.errors import DomainError

pytestmark = pytest.mark.django_db


def _pdf(name="kp.pdf"):
    return SimpleUploadedFile(name, PDF, content_type="application/pdf")


def _setup(slug):
    proj, art = s.project(), s.metal()
    s.approved_budget(slug, proj, {art: 10_000})
    s.request_route()
    sn = s.actor(slug, s.SN, "bpp-sn")
    req = service.create_draft(sn, {**s.header(proj, art), "items": s.items((1, 100))})
    return sn, req


def test_author_attaches_in_draft_and_replaces_after_submit(company_context):
    slug = company_context["slug"]
    sn, req = _setup(slug)
    first = files.attach(sn, req.id, _pdf())
    assert [f["filename"] for f in files.list_files(sn, req.id)] == ["kp.pdf"]

    service.submit(sn, req.id, expected_version=None)
    with pytest.raises(DomainError) as exc:
        files.attach(sn, req.id, _pdf("tz.pdf"))
    assert exc.value.code == "E-STS-01"
    newer = files.replace(sn, req.id, first["id"], _pdf("kp-v2.pdf"))
    assert newer["version"] == 2
    assert [f["filename"] for f in files.list_files(sn, req.id)] == ["kp-v2.pdf"]


def test_only_the_author_attaches_and_every_download_is_logged(company_context):
    slug = company_context["slug"]
    sn, req = _setup(slug)
    row = files.attach(sn, req.id, _pdf())
    other = s.actor(slug, s.SN2, "bpp-sn")
    with pytest.raises(DomainError) as exc:
        files.attach(other, req.id, _pdf())
    assert exc.value.status == 404  # чужую заявку он и не видит

    td = s.actor(slug, s.TD, "bpp-td")
    files.link(td, req.id, row["id"])
    assert FileDownload.objects.filter(file_id=row["id"], user_id=s.TD).count() == 1

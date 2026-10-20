"""Файлы КП поставщика на портале (T3.4; план этапа 3, §1, §2 T3.4).

Владелец ``tender.offer``: файлы у строки предложения, автор — служебная
учётка ``tender-portal``. Загрузка — только при включённом антивирусе
(поддельный clamd из ``apps/core/tests/test_antivirus.py``).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.bpp.tests.test_files import PDF, memory_storage  # noqa: F401  (фикстура)
from apps.core.tests.test_antivirus import EICAR, clamd  # noqa: F401  (фикстура)
from apps.files.models import FileEvent, FileObject, FileType
from apps.tender import file_owners
from apps.tender.models import Offer
from apps.tender.services.portal import files as portal_files
from apps.tender.services.portal import offers
from apps.tender.tests.test_portal_offers import (  # noqa: F401  (фикстура world)
    Events,
    _filled,
    _request,
    _save,
    _submit,
    _tender,
    _invite,
    ctx,
    world,
)
from apps.users.models import User
from htqweb.errors import DomainError
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db


def _upload(world, name="kp.pdf", data=PDF, inv=None, events=None):
    with use_company(world.slug):
        return portal_files.upload(ctx(world, inv), data=data, filename=name,
                                   mime="application/pdf", ip="10.1.1.1",
                                   user_agent="phone/1",
                                   event=events if events is not None else Events())


def _list(world, inv=None):
    with use_company(world.slug):
        return portal_files.list_files(ctx(world, inv))


def _remove(world, document_id, inv=None, events=None):
    with use_company(world.slug):
        portal_files.remove(ctx(world, inv), document_id, ip="10.1.1.1",
                            user_agent="phone/1",
                            event=events if events is not None else Events())


def _error(call) -> DomainError:
    with pytest.raises(DomainError) as exc:
        call()
    return exc.value


def test_offer_file_type_is_seeded():
    row = FileType.objects.get(code="tender_offer")
    assert row.owner_type == file_owners.OFFER_OWNER == offers.OFFER_OWNER
    assert set(row.formats) == {".pdf", ".docx", ".xlsx", ".jpg", ".jpeg", ".png"}
    assert row.max_mb == 20


def test_no_scanner_no_upload(world, memory_storage, settings):  # noqa: F811
    settings.ANTIVIRUS_CLAMD_HOST = ""
    err = _error(lambda: _upload(world))
    assert (err.code, err.status) == ("E-SYS-01", 503)
    with use_company(world.slug):
        assert not FileObject.objects.filter(owner_type="tender.offer").exists()


def test_upload_list_and_remove(world, memory_storage, clamd):  # noqa: F811
    events = Events()
    out = _upload(world, events=events)
    assert set(out) == {"id", "name", "size", "mime", "uploaded_at"}
    assert [f["id"] for f in _list(world)] == [out["id"]]
    assert events[0][0] == "file_uploaded" and events[0][1]["document_id"] == out["id"]
    with use_company(world.slug):
        row = FileObject.objects.get(owner_type="tender.offer")
        author = User.objects.get(pk=row.uploaded_by_id)
        assert author.username == "tender-portal" and not author.is_active
        event = FileEvent.objects.get(owner_type="tender.offer", event="file_attached")
        assert (event.ip, event.user_agent) == ("10.1.1.1", "phone/1")
    assert clamd.received  # файл прошёл через сканер

    _remove(world, out["id"], events=events)
    assert _list(world) == []
    assert events[-1][0] == "file_removed"


def test_threat_is_e_fil_08_and_journaled(world, memory_storage, clamd):  # noqa: F811
    err = _error(lambda: _upload(world, data=PDF + EICAR))
    assert (err.code, err.status) == ("E-FIL-08", 422)
    with use_company(world.slug):
        assert not FileObject.objects.filter(owner_type="tender.offer").exists()
        assert FileEvent.objects.filter(owner_type="tender.offer",
                                        event="file_rejected").exists()


def test_eleventh_file_and_xml_are_refused(world, memory_storage, clamd):  # noqa: F811
    for n in range(10):
        _upload(world, name=f"kp{n}.pdf")
    err = _error(lambda: _upload(world, name="kp10.pdf"))
    # Предел документов подсистема файлов отдаёт 409 (как у всех владельцев).
    assert err.status == 409 and err.code.startswith("E-FIL-")
    err = _error(lambda: _upload(world, name="offer.xml", data=b"<offer/>"))
    # Формат — 415 подсистемы файлов с текстом ТЗ §13.2.
    assert err.status == 415 and "допустимы PDF, DOCX, XLSX, JPG, PNG" in err.message
    assert len(_list(world)) == 10


def test_foreign_document_is_404(world, memory_storage, clamd):  # noqa: F811
    theirs = _upload(world, inv=world.inv2)
    _upload(world)
    err = _error(lambda: _remove(world, theirs["id"]))
    assert err.status == 404
    assert [f["id"] for f in _list(world, world.inv2)] == [theirs["id"]]


def test_after_deadline_no_upload_or_remove(world, memory_storage, clamd,  # noqa: F811
                                            pinned_clock):
    out = _upload(world)
    pinned_clock(world.tender.deadline_at + timedelta(seconds=1), "UTC")
    for call in (lambda: _upload(world), lambda: _remove(world, out["id"])):
        err = _error(call)
        assert (err.code, err.status) == ("E-TND-05", 409)


def test_files_stay_with_the_submitted_version(world, memory_storage, clamd):  # noqa: F811
    _save(world, _filled(world))
    kept = _upload(world)
    sent = _submit(world, pd_consent=True)
    # Без черновика видна отправленная версия и её файлы.
    assert [f["id"] for f in _list(world)] == [kept["id"]]

    # Удаление заводит черновик-копию: у версии файл остаётся.
    _remove(world, kept["id"])
    assert _list(world) == []
    with use_company(world.slug):
        draft = Offer.objects.get(invitation=world.inv, status="draft")
        assert draft.pk != sent.pk
        version_files = FileObject.objects.filter(owner_type="tender.offer",
                                                  owner_id=str(sent.pk),
                                                  deleted_at__isnull=True)
        assert [str(f.document_id) for f in version_files] == [kept["id"]]


def test_decline_removes_the_draft_files(world, memory_storage, clamd):  # noqa: F811
    _upload(world)
    with use_company(world.slug):
        draft_id = Offer.objects.get(invitation=world.inv, status="draft").pk
        offers.decline(ctx(world), {"reason": "Нет такого металла на складе"},
                       event=Events())
        assert not FileObject.objects.filter(owner_type="tender.offer",
                                             owner_id=str(draft_id)).exists()


def test_staff_do_not_see_offer_files_on_the_panel(world, memory_storage, clamd):  # noqa: F811
    from django.test import Client

    from apps.tender.tests import helpers as h

    _upload(world)
    with use_company(world.slug):
        draft_id = Offer.objects.get(invitation=world.inv, status="draft").pk
    resp = Client().get(f"/api/files/v1/tender.offer/{draft_id}/files/",
                        **h.auth(world.slug, h.SN))
    assert resp.status_code == 404, resp.content


# ── ручки портала ``supplier/<token>/offer/files…`` (T3.4) ───────────────

def _upload_http(portal, client, world, name="kp.pdf", data=PDF):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return client.post(f"{portal.BASE}/{world.token}/offer/files",
                       data={"file": SimpleUploadedFile(name, data,
                                                        content_type="application/pdf")},
                       HTTP_X_HTQ_COMPANY=world.slug, HTTP_X_REAL_IP=portal.REAL_IP,
                       HTTP_ORIGIN=portal.origin(world.slug))


def test_http_files(company_context, memory_storage, clamd, settings):  # noqa: F811
    from django.core.cache import cache

    from apps.tender.models import PortalEvent
    from apps.tender.tests.test_portal_offers import _http_world

    settings.PUBLIC_BASE_URL = "https://htq.group"
    cache.clear()
    world, client, portal = _http_world(company_context["slug"])

    added = _upload_http(portal, client, world)
    assert added.status_code == 201, added.content
    doc = added.json()
    assert set(doc) == {"id", "name", "size", "mime", "uploaded_at"}
    listed = portal.get(client, world.slug, f"{world.token}/offer/files")
    assert [f["id"] for f in listed.json()] == [doc["id"]]
    assert portal.forbidden_keys(listed.json()) == []

    gone = client.delete(f"{portal.BASE}/{world.token}/offer/files/{doc['id']}",
                         HTTP_X_HTQ_COMPANY=world.slug, HTTP_X_REAL_IP=portal.REAL_IP,
                         HTTP_ORIGIN=portal.origin(world.slug))
    assert gone.status_code == 200, gone.content
    assert portal.get(client, world.slug, f"{world.token}/offer/files").json() == []

    with use_company(world.slug):
        kinds = list(PortalEvent.objects.filter(invitation=world.inv)
                     .order_by("created_at").values_list("kind", flat=True))
    assert kinds == ["bound", "file_uploaded", "file_removed"]

    settings.ANTIVIRUS_CLAMD_HOST = ""
    off = _upload_http(portal, client, world)
    assert (off.status_code, off.json()["code"]) == (503, "E-SYS-01")
    cache.clear()


def test_http_upload_rate_limit(company_context, memory_storage, clamd, settings):  # noqa: F811
    from django.core.cache import cache

    from apps.tender.tests.test_portal_offers import _http_world

    settings.PUBLIC_BASE_URL = "https://htq.group"
    cache.clear()
    settings.TENDER_PORTAL_UPLOAD_LIMIT = 1
    world, client, portal = _http_world(company_context["slug"])
    assert _upload_http(portal, client, world).status_code == 201
    second = _upload_http(portal, client, world, name="kp2.pdf")
    assert (second.status_code, second.json()["code"]) == (429, "E-RATE-01")
    assert int(second["Retry-After"]) > 0
    cache.clear()

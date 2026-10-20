"""Сторож белого списка портала поставщика (T3.6; план этапа 3, §1, §4.2).

Один сценарий проходит каждый маршрут ``urls_supplier.py`` — успешным
вызовом и вызовом с отказом (чужое устройство, чужой документ, битое тело,
лимит) — и у каждого JSON-ответа проверяет, что в нём нет ни плановых цен,
ни чужих участников, ни служебных ключей (``helpers.portal_forbidden_keys``).
Ручка, которую сценарий не прошёл, валит тест: новая ручка портала без
проверки ответа молча не появится.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import resolve
from django.utils import timezone

from apps.bpp.tests.test_files import PDF, memory_storage  # noqa: F401  (фикстура)
from apps.core.tests.test_antivirus import clamd  # noqa: F401  (фикстура)
from apps.files import interface as files
from apps.tender import urls_supplier
from apps.tender.tests import helpers as h
from apps.tender.tests import test_portal_access as portal
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db

PREFIX = "api/tender/v1/"


class Walk:
    """Вызовы портала с учётом пройденных маршрутов и проверкой ответов."""

    def __init__(self, slug: str, token: str):
        self.slug, self.token = slug, token
        self.routes: set[str] = set()

    def __call__(self, client: Client, method: str, path: str, *, body=None,
                 raw: bytes | None = None, upload=None, expect: int):
        url = f"{portal.BASE}/{self.token}{'/' + path if path else ''}"
        headers = {"HTTP_X_HTQ_COMPANY": self.slug, "HTTP_X_REAL_IP": portal.REAL_IP}
        if method != "get":
            headers["HTTP_ORIGIN"] = portal.origin(self.slug)
        if upload is not None:
            resp = client.post(url, data={"file": upload}, **headers)
        elif method == "get":
            resp = client.get(url, **headers)
        else:
            data = raw if raw is not None else (json.dumps(body) if body is not None else "")
            resp = getattr(client, method)(url, data=data, content_type="application/json",
                                           **headers)
        assert resp.status_code == expect, (method, path, resp.status_code, resp.content)
        self.routes.add(resolve(url).route)
        if resp.get("Content-Type", "").startswith("application/json") and resp.content:
            payload = resp.json()
            assert h.portal_forbidden_keys(payload) == [], (method, path, payload)
        return resp


def _expected_routes() -> set[str]:
    return {PREFIX + p.pattern._route for p in urls_supplier.urlpatterns
            if not p.pattern._route.endswith("/")}


def test_every_portal_route_answers_a_whitelist(company_context, memory_storage,  # noqa: F811
                                               clamd, settings):  # noqa: F811
    from django.core.files.uploadedfile import SimpleUploadedFile

    settings.PUBLIC_BASE_URL = "https://htq.group"
    cache.clear()
    slug = company_context["slug"]
    h.user(h.SN)
    world = portal.build(slug)
    other = portal.build(slug)
    with use_company(slug):
        spec = files.attach_bytes("tender.request", world.req.pk, file_type="tender_spec",
                                  data=PDF, filename="tz.pdf", mime="application/pdf",
                                  actor_id=h.SN)
        foreign = files.attach_bytes("tender.request", other.req.pk, file_type="tender_spec",
                                     data=PDF, filename="other.pdf", mime="application/pdf",
                                     actor_id=h.SN)
    walk = Walk(slug, world.token)
    phone, stranger = Client(), Client()

    # Вход: карточка, привязка, второе устройство.
    walk(phone, "get", "", expect=200)
    walk(phone, "post", "bind", body={}, expect=200)
    walk(stranger, "post", "bind", body={}, expect=409)

    # Тендер и файлы ТЗ.
    walk(phone, "get", "tender", expect=200)
    walk(stranger, "get", "tender", expect=403)
    walk(phone, "get", f"files/{spec['document_id']}", expect=302)
    walk(phone, "get", f"files/{foreign['document_id']}", expect=404)

    # Предложение: чтение, правка, битое тело.
    offer = walk(phone, "get", "offer", expect=200).json()
    saved = walk(phone, "put", "offer", body={
        "version": offer["version"],
        "valid_until": str(timezone.localdate() + timedelta(days=30)),
        "lines": [{"item_id": offer["lines"][0]["item_id"], "participates": True,
                   "price": "750", "qty": "10"}],
        "extras": {"works": {"amount": "450000", "note": "Монтаж"}}}, expect=200).json()
    walk(phone, "put", "offer", raw=b"{oops", expect=422)

    # Файлы КП: список, загрузка, недопустимый тип, удаление, чужой документ.
    walk(phone, "get", "offer/files", expect=200)
    added = walk(phone, "post", "offer/files", expect=201, upload=SimpleUploadedFile(
        "kp.pdf", PDF, content_type="application/pdf")).json()
    walk(phone, "post", "offer/files", expect=415, upload=SimpleUploadedFile(
        "kp.xml", b"<x/>", content_type="application/xml"))
    walk(phone, "delete", f"offer/files/{added['id']}", expect=200)
    walk(phone, "delete", f"offer/files/{added['id']}", expect=404)

    # Отправка, отзыв, отказ.
    walk(phone, "post", "offer/submit", body={"version": saved["version"]}, expect=422)
    sent = walk(phone, "post", "offer/submit",
                body={"version": saved["version"], "pd_consent": True}, expect=200).json()
    walk(phone, "post", "offer/withdraw", body={"version": sent["version"]}, expect=200)
    walk(phone, "post", "decline", body={"reason": "коротко"}, expect=422)
    walk(phone, "post", "decline", body={"reason": "Нет нужного проката на складе"},
         expect=200)
    walk(phone, "put", "offer", body={"version": sent["version"]}, expect=409)

    # Лимит запросов — тело 429 тоже ответ портала.
    settings.TENDER_PORTAL_TOKEN_LIMIT = 1
    cache.clear()
    walk(phone, "get", "tender", expect=200)
    walk(phone, "get", "tender", expect=429)
    cache.clear()

    assert walk.routes == _expected_routes()

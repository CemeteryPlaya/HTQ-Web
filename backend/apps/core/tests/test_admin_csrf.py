"""CSRF входа в /django-admin/ за прокси (settings/base.py, «CSRF за прокси»).

Django test Client по умолчанию CSRF не проверяет вовсе — поэтому 403 «Ошибка
проверки CSRF» на проде тестами не ловился. Здесь ``enforce_csrf_checks=True``
и заголовки ровно те, с которыми запрос доходит до backend-web из-за шлюза.
"""

import pytest
from django.test import Client, override_settings

from apps.users.models import User, UserStatus
from htqweb.settings import base

HOST = "portal.htq.test"
PASSWORD = "Adm1n!Pass"


@pytest.fixture
def superuser(db):
    u = User.objects.create(username="csrf-admin", email="csrf-admin@htq.test",
                            password="x", status=UserStatus.ACTIVE,
                            is_staff=True, is_superuser=True)
    u.set_password(PASSWORD)
    u.save()
    return u


def _login(user, **headers):
    c = Client(enforce_csrf_checks=True)
    assert c.get("/django-admin/login/", HTTP_HOST=HOST, **headers).status_code == 200
    return c.post("/django-admin/login/", {
        "username": user.username,
        "password": PASSWORD,
        "csrfmiddlewaretoken": c.cookies["csrftoken"].value,
        "next": "/django-admin/",
    }, HTTP_HOST=HOST, **headers)


def _is_csrf_reject(resp) -> bool:
    return resp.status_code == 403 and "CSRF" in resp.content.decode()


@override_settings(CSRF_TRUSTED_ORIGINS=[])
def test_tls_terminated_by_our_nginx(superuser):
    # nginx ставит X-Forwarded-Proto: https — Django узнаёт схему сам, и
    # дописывать домен в CSRF_TRUSTED_ORIGINS не нужно.
    resp = _login(superuser, HTTP_X_FORWARDED_PROTO="https", HTTP_ORIGIN=f"https://{HOST}")
    assert resp.status_code == 302, resp.content[:300]


@override_settings(CSRF_TRUSTED_ORIGINS=[])
def test_tls_before_nginx_without_trusted_origin_is_rejected(superuser):
    # Исходная поломка: TLS снят до nginx, тот честно пишет http, а браузер
    # шлёт Origin: https://… — без доверенного origin'а это 403.
    resp = _login(superuser, HTTP_X_FORWARDED_PROTO="http", HTTP_ORIGIN=f"https://{HOST}")
    assert _is_csrf_reject(resp)


@override_settings(CSRF_TRUSTED_ORIGINS=[f"https://{HOST}"])
def test_tls_before_nginx_with_trusted_origin(superuser):
    resp = _login(superuser, HTTP_X_FORWARDED_PROTO="http", HTTP_ORIGIN=f"https://{HOST}")
    assert resp.status_code == 302, resp.content[:300]


@override_settings(CSRF_TRUSTED_ORIGINS=[f"https://{HOST}"])
def test_foreign_origin_still_rejected(superuser):
    resp = _login(superuser, HTTP_X_FORWARDED_PROTO="https", HTTP_ORIGIN="https://evil.example")
    assert _is_csrf_reject(resp)


def test_trusted_origins_from_env(monkeypatch):
    monkeypatch.setenv("CSRF_TRUSTED_ORIGINS", " https://second.example/ , ,http://45.10.110.212")
    # Путь и хвост PUBLIC_BASE_URL отбрасываются — origin это схема+хост.
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://portal.example/join/")
    assert base._trusted_origins() == [
        "https://second.example", "http://45.10.110.212", "https://portal.example",
        "https://*.portal.example",
    ]


def test_trusted_origins_dedup_and_bad_public_url(monkeypatch):
    monkeypatch.setenv("CSRF_TRUSTED_ORIGINS", "https://portal.example")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://portal.example")
    assert base._trusted_origins() == ["https://portal.example", "https://*.portal.example"]

    # Без схемы PUBLIC_BASE_URL в origin не превращается — лучше не доверить,
    # чем доверить не то.
    monkeypatch.setenv("CSRF_TRUSTED_ORIGINS", "")
    monkeypatch.setenv("PUBLIC_BASE_URL", "portal.example")
    assert base._trusted_origins() == []


def test_trusted_origins_cover_company_subdomains(monkeypatch):
    # Компании живут на поддоменах (блок I.2): форма, открытая на
    # htq.htq.group, обязана пройти проверку CSRF так же, как голый домен.
    monkeypatch.setenv("CSRF_TRUSTED_ORIGINS", "")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://htq.group")
    origins = base._trusted_origins()
    assert "https://htq.group" in origins
    assert "https://*.htq.group" in origins

    # Пустой PUBLIC_BASE_URL не даёт подстановки — доверять «*.» нечему.
    monkeypatch.setenv("PUBLIC_BASE_URL", "")
    assert not any("*." in o for o in base._trusted_origins())


@override_settings(CSRF_TRUSTED_ORIGINS=["https://*.htq.test"])
def test_company_subdomain_origin_passes_csrf(superuser):
    # Сквозная проверка, что Django понимает подстановку: TLS снят до nginx,
    # до Django доходит http, а Origin — https-поддомен компании.
    host = "acme.htq.test"
    c = Client(enforce_csrf_checks=True)
    headers = {"HTTP_X_FORWARDED_PROTO": "http", "HTTP_ORIGIN": f"https://{host}"}
    assert c.get("/django-admin/login/", HTTP_HOST=host, **headers).status_code == 200
    resp = c.post("/django-admin/login/", {
        "username": superuser.username,
        "password": PASSWORD,
        "csrfmiddlewaretoken": c.cookies["csrftoken"].value,
        "next": "/django-admin/",
    }, HTTP_HOST=host, **headers)
    assert resp.status_code == 302, resp.content[:300]

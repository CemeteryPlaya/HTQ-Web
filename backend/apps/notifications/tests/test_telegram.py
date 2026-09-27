"""Привязка Telegram: код из профиля → /start <код> в боте → chat_id сохранён."""

import json

import pytest
from django.test import Client

from apps.access.tests.helpers import token
from apps.notifications.models import TelegramLink

BASE = "/api/notifications/v1"


@pytest.mark.django_db
def test_link_flow(settings):
    settings.NOTIFY_TELEGRAM_BOT_NAME = "htq_notify_bot"
    settings.NOTIFY_TELEGRAM_WEBHOOK_SECRET = "s3cret"
    auth = {"HTTP_AUTHORIZATION": f"Bearer {token(user_id=7, sub='7')}"}
    started = Client().post(f"{BASE}/telegram/link", **auth).json()
    assert started["url"].startswith("https://t.me/htq_notify_bot?start=")
    code = started["url"].rsplit("=", 1)[1]

    update = {"message": {"chat": {"id": 555}, "text": f"/start {code}"}}
    wrong = Client().post(f"{BASE}/telegram/webhook", data=json.dumps(update),
                          content_type="application/json",
                          HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="nope")
    assert wrong.status_code == 403
    ok = Client().post(f"{BASE}/telegram/webhook", data=json.dumps(update),
                       content_type="application/json",
                       HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="s3cret")
    assert ok.status_code == 200
    assert TelegramLink.objects.get(user_id=7).chat_id == "555"


@pytest.mark.django_db
def test_expired_or_unknown_code_does_not_link(settings):
    settings.NOTIFY_TELEGRAM_WEBHOOK_SECRET = "s3cret"
    update = {"message": {"chat": {"id": 555}, "text": "/start nosuchcode"}}
    Client().post(f"{BASE}/telegram/webhook", data=json.dumps(update),
                  content_type="application/json", HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="s3cret")
    assert not TelegramLink.objects.exclude(chat_id="").exists()


@pytest.mark.django_db
def test_webhook_with_broken_json_is_400(settings):
    settings.NOTIFY_TELEGRAM_WEBHOOK_SECRET = "s3cret"
    response = Client().post(f"{BASE}/telegram/webhook", data="{not json",
                             content_type="application/json",
                             HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="s3cret")
    assert response.status_code == 400

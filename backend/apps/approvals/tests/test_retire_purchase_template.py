"""Снятие шаблона «Заявка на закуп» (модуль БЗО, B6.3): форма скрыта,
заявки удалены, справочники форм и таблица данных целы."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

from apps.approvals.models import (
    RequestFormTemplate,
    RequestInstance,
    RequestReferenceSource,
    TemplateStatus,
)

pytestmark = pytest.mark.django_db
SLUG = "zayavka-na-zakup"


def _run(*args) -> str:
    out = StringIO()
    call_command("retire_purchase_request_template", *args, stdout=out)
    return out.getvalue()


def _template_with_request():
    call_command("seed_purchase_request_template", stdout=StringIO())
    template = RequestFormTemplate.objects.get(slug=SLUG)
    RequestInstance.objects.create(code="REQ-TEST-1", template=template,
                                   template_version_id=template.current_version_id or 1,
                                   initiator_id=1)
    return template


def test_dry_run_changes_nothing():
    template = _template_with_request()
    assert "заявок 1" in _run("--dry-run")
    template.refresh_from_db()
    assert template.status == TemplateStatus.ACTIVE
    assert RequestInstance.objects.count() == 1


def test_retire_hides_the_form_drops_requests_and_keeps_reference_data():
    template = _template_with_request()
    sources = RequestReferenceSource.objects.filter(template_id=template.pk).count()
    assert sources >= 1

    assert "удалено заявок 1" in _run()
    template.refresh_from_db()
    assert (template.status, template.is_active) == (TemplateStatus.DELETED, False)
    assert not RequestInstance.objects.exists()
    assert RequestReferenceSource.objects.filter(template_id=template.pk).count() == sources

    assert "уже снят" in _run()


def test_missing_template_is_reported():
    assert "снимать нечего" in _run("--slug", "net-takogo")

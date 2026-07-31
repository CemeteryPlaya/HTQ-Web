"""Выключенный signoff деградирует по общему контракту платформы.

Тот же набор проверок, что у остальных доменов (ср.
``apps/contracts/tests/test_contracts_disableable.py``): межаппный вызов
через ``interface`` превращается в ``ServiceDisabled``, который ``api_view``
у вызывающей стороны отдаёт 503-конвертом.

Отдельно проверяется, что РЕГИСТРАЦИЯ типов гейтом не закрыта: она
происходит в ``AppConfig.ready()``, до появления соединения с БД, и гейт на
ней ронял бы запуск всей платформы из-за выключенного сервиса.
"""

from __future__ import annotations

import pytest

from apps.core.models import ServiceStatus
from apps.core.services import ServiceDisabled
from apps.signoff import interface
from apps.signoff.services import registry
from apps.signoff.tests.helpers import make_doc, make_user, simple_route
from apps.signoff.tests.testapp.models import ProbeDoc

pytestmark = pytest.mark.django_db


def _disable() -> None:
    ServiceStatus.objects.update_or_create(
        app_label="signoff",
        defaults={"enabled": False, "message": "Согласование отключено"},
    )


def test_interface_raises_service_disabled():
    a = make_user("a")
    doc = make_doc()
    simple_route(a.pk)
    _disable()

    with pytest.raises(ServiceDisabled) as exc:
        interface.start_process(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE,
                                subject_id=doc.pk)
    assert exc.value.service == "signoff"


def test_every_runtime_interface_function_is_gated():
    doc = make_doc()
    _disable()

    for call in (
        lambda: interface.get_process(1),
        lambda: interface.get_process_for(ProbeDoc.SIGNOFF_SUBJECT_TYPE, doc.pk),
        lambda: interface.approval_state_of(ProbeDoc.SIGNOFF_SUBJECT_TYPE, doc.pk),
        lambda: interface.count_awaiting(1),
        lambda: interface.cancel_process(process_id=1),
    ):
        with pytest.raises(ServiceDisabled):
            call()


def test_subject_registration_is_not_gated():
    """Регистрация типа переживает выключенный сервис.

    Она идёт из ``AppConfig.ready()``: гейт здесь означал бы, что платформа
    не поднимается, пока кто-то не включит signoff обратно — при том что
    выключенный signoff должен запрещать согласование, а не запуск.
    """
    _disable()

    subject = interface.register_subject(
        ProbeDoc.SIGNOFF_SUBJECT_TYPE, label="Пробный документ", model=ProbeDoc)
    assert subject.subject_type == ProbeDoc.SIGNOFF_SUBJECT_TYPE
    assert registry.is_registered(ProbeDoc.SIGNOFF_SUBJECT_TYPE)

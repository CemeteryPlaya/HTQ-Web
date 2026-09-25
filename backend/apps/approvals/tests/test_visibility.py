"""Кому видна карточка заявки.

Список всегда отвечает по «ящику» спрашивающего и чужого не покажет; дыра
была в карточке — `GET /instances/{id}` не проверял ничего, и заявку с
суммами, поставщиками и обоснованием мог прочитать любой, кто подставил id.

Правило: причастные и только они — инициатор, наблюдатель в копии,
согласующий (в любом круге, включая закрытый) и администратор платформы.
Чужая заявка отвечает **404**, а не 403: 403 подтвердил бы, что заявка с
таким id существует.
"""

import pytest
from django.core.cache import cache
from django.test import Client

from apps.approvals.models import RequestStatus, RequestWatcher
from apps.core.models import ServiceStatus

from .helpers import APPROVER, BASE, admin_token, auth, decide, make_instance, make_template, token

pytestmark = pytest.mark.django_db

USER = 7
OTHER = 42


def _get(instance_id: int, tok: str | None = None):
    return Client().get(f"{BASE}/instances/{instance_id}/", **auth(tok))


def test_the_initiator_sees_their_own_request():
    instance = make_instance(make_template(), initiator_id=USER)
    assert _get(instance.id).status_code == 200


def test_a_stranger_gets_404_not_403():
    """404, а не 403: существование чужой заявки — тоже сведения."""
    instance = make_instance(make_template(), initiator_id=USER)
    resp = _get(instance.id, token(user_id=OTHER, sub=str(OTHER)))
    assert resp.status_code == 404
    assert "form_values_json" not in resp.content.decode()


def test_a_watcher_in_cc_sees_it():
    instance = make_instance(make_template(), initiator_id=USER)
    RequestWatcher.objects.create(request=instance, user_id=OTHER)
    assert _get(instance.id, token(user_id=OTHER, sub=str(OTHER))).status_code == 200


def test_an_approver_sees_it_while_deciding_and_after():
    template = make_template()          # маршрут на APPROVER
    instance = make_instance(template, initiator_id=USER)
    approver = token(user_id=APPROVER, sub=str(APPROVER))
    assert _get(instance.id, approver).status_code == 404   # до отправки — нет

    client = Client()
    client.post(f"{BASE}/instances/{instance.id}/submit/", **auth())
    assert _get(instance.id, approver).status_code == 200   # пока решает

    decide(client, instance, APPROVER)
    instance.refresh_from_db()
    assert instance.status == RequestStatus.APPROVED
    # И после закрытия круга: он вправе видеть, что подписывал.
    assert _get(instance.id, approver).status_code == 200


def test_a_platform_admin_sees_everything():
    instance = make_instance(make_template(), initiator_id=USER)
    assert _get(instance.id, admin_token()).status_code == 200


def test_a_disabled_signoff_does_not_widen_visibility():
    """Выключенный движок не должен открывать чужие заявки на время
    обслуживания: согласующего спросить негде — значит «не видно»."""
    template = make_template()
    instance = make_instance(template, initiator_id=USER)
    client = Client()
    client.post(f"{BASE}/instances/{instance.id}/submit/", **auth())
    approver = token(user_id=APPROVER, sub=str(APPROVER))
    assert _get(instance.id, approver).status_code == 200

    ServiceStatus.objects.update_or_create(app_label="signoff",
                                           defaults={"enabled": False})
    cache.clear()
    assert _get(instance.id, approver).status_code == 404
    # Инициатор и админ видят её по-прежнему — их право не зависит от движка.
    assert _get(instance.id).status_code == 200
    assert _get(instance.id, admin_token()).status_code == 200


def test_the_sent_box_lists_only_my_requests():
    template = make_template()
    mine = make_instance(template, initiator_id=USER)
    make_instance(template, initiator_id=OTHER)
    listed = Client().get(f"{BASE}/instances/?box=sent", **auth()).json()
    assert [row["id"] for row in listed] == [mine.id]

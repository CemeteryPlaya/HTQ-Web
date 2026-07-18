import pytest
from django_q.tasks import async_task, result

from apps.core.models import ServiceStatus
from apps.core.services import ServiceDisabled


@pytest.mark.django_db
def test_async_task_roundtrip():
    tid = async_task("apps.core.tasks.ping", "x")
    assert result(tid) == "pong:x"


@pytest.mark.django_db
def test_guarded_task_refuses_when_disabled():
    # guard проверяем прямым вызовом — так тест не зависит от того,
    # пробрасывает ли sync-режим Q исключение или сохраняет его в result
    from apps.core.tasks import guarded_ping

    ServiceStatus.objects.update_or_create(app_label="cms", defaults={"enabled": False})
    with pytest.raises(ServiceDisabled):
        guarded_ping("cms", "x")

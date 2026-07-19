import pytest

from apps.core.models import ServiceStatus
from apps.core.services import ServiceDisabled


@pytest.mark.django_db
def test_task_delay_roundtrip_in_eager_mode():
    # CELERY_TASK_ALWAYS_EAGER=True (htqweb/settings/test.py) makes
    # .delay(...) run inline, no broker required.
    from apps.core.tasks import ping

    async_result = ping.delay("x")
    assert async_result.get() == "pong:x"


@pytest.mark.django_db
def test_guarded_task_refuses_when_disabled():
    # guard проверяем прямым вызовом — так тест не зависит от того,
    # пробрасывает ли eager-режим Celery исключение или сохраняет его в result
    from apps.core.tasks import guarded_ping

    ServiceStatus.objects.update_or_create(app_label="cms", defaults={"enabled": False})
    with pytest.raises(ServiceDisabled):
        guarded_ping("cms", "x")

import pytest
from django.core.management import CommandError, call_command

from apps.core.models import ServiceStatus


@pytest.mark.django_db
def test_service_command_toggles_known_service():
    call_command("service", "cms", "--off")
    row = ServiceStatus.objects.get(app_label="cms")
    assert row.enabled is False

    call_command("service", "cms", "--on")
    row.refresh_from_db()
    assert row.enabled is True


@pytest.mark.django_db
def test_service_command_rejects_unknown_name():
    """Finding 7: a typo'd app_label must not silently create an inert row —
    the operator would believe the app is off when nothing was ever wired up."""
    with pytest.raises(CommandError):
        call_command("service", "not-a-real-service", "--off")
    assert not ServiceStatus.objects.filter(app_label="not-a-real-service").exists()

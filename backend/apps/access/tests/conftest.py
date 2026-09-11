"""Фикстуры аппки доступа.

Кадровые модели импортируются ЗДЕСЬ, а не в рабочем коде: тесты исключены из
``apps/core/tests/test_app_isolation.py`` намеренно — проверять поведение шва
без соседской модели нельзя, а сам ``apps.access`` её по-прежнему не знает.
"""

import datetime

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache

from apps.core.models import ServiceStatus


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(
        username="ivanov", email="i@htq.test", password="x")


@pytest.fixture
def superuser(db):
    return get_user_model().objects.create_superuser(
        username="root", email="root@htq.test", password="x")


@pytest.fixture
def employee_with_position(db, user):
    """Кадровая карточка пользователя со штатной должностью."""
    from apps.hr.models import Department, Employee, Position

    dep = Department.objects.create(name="ИТ", path="it")
    pos = Position.objects.create(title="Инженер", department=dep, weight=100)
    Employee.objects.create(
        first_name="Иван", last_name="Иванов", email="i@htq.test",
        department=dep, position=pos,
        hire_date=datetime.date(2024, 1, 9), user_id=user.id,
    )
    return pos


@pytest.fixture
def service_off():
    """Выключить домен на время блока, как это делает `manage.py service`."""
    import contextlib

    @contextlib.contextmanager
    def _off(name: str):
        ServiceStatus.objects.update_or_create(
            app_label=name, defaults={"enabled": False})
        cache.delete(f"svc-status:{name}")
        try:
            yield
        finally:
            ServiceStatus.objects.update_or_create(
                app_label=name, defaults={"enabled": True})
            cache.delete(f"svc-status:{name}")

    return _off

"""Поиск людей для окна карточки (этап S2): только действующие участники
текущей компании — исполнителем задачи не назначить человека без входа в неё.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.companies import interface as companies
from apps.users.models import User, UserStatus

from .helpers import BASE, COMPANY
from .org_fixtures import EMP_IT, as_user, make_org

pytestmark = pytest.mark.django_db


def _user(username, last_name, status=UserStatus.ACTIVE):
    return User.objects.create(username=username, email=f"{username}@htq.test", password="x",
                               first_name="Ерлан", last_name=last_name, status=status)


def test_only_active_company_members_are_found():
    make_org()
    headers = as_user(EMP_IT)                    # заводит компанию запроса
    member = _user("kb-member", "Сапаров")
    outsider = _user("kb-outsider", "Чужой")
    suspended = _user("kb-suspended", "Отключённый", status=UserStatus.SUSPENDED)
    for user in (member, suspended):
        companies.grant_membership(COMPANY, user.pk)
    body = Client().get(f"{BASE}/people", {"query": "Ерлан"}, **headers).json()
    ids = {row["id"] for row in body}
    assert member.pk in ids
    assert outsider.pk not in ids and suspended.pk not in ids


def test_short_query_returns_nothing():
    make_org()
    assert Client().get(f"{BASE}/people", {"query": "Е"}, **as_user(EMP_IT)).json() == []

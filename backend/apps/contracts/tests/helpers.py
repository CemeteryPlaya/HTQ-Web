"""Общие помощники тестов домена contracts.

Токены собираются настоящим ``jwt.encode`` против ``settings.JWT_SECRET`` —
тот же стиль, что в ``apps/cms/tests``.
"""

from __future__ import annotations

import json
from decimal import Decimal

import jwt as pyjwt
from django.conf import settings
from django.test import Client

from apps.contracts.models import (
    Administrator,
    Agreement,
    Budget,
    Counterparty,
    Country,
    Program,
)

BASE = "/api/contracts/v1"


def token(**over) -> str:
    claims = {
        "user_id": 7, "username": "u", "email": "u@htq.test",
        "is_staff": False, "is_superuser": False, "is_admin": False,
        "token_type": "access", "iat": 1, "exp": 9_999_999_999,
        "iss": "htqweb-auth", "sub": "7",
        **over,
    }
    return pyjwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")


def admin_token(**over) -> str:
    return token(user_id=9, sub="9", is_admin=True, **over)


def auth(tok: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {tok}"}


def post_json(client: Client, path: str, body: dict, **extra):
    return client.post(path, data=json.dumps(body, default=str),
                       content_type="application/json", **extra)


def patch_json(client: Client, path: str, body: dict, **extra):
    return client.patch(path, data=json.dumps(body, default=str),
                        content_type="application/json", **extra)


# ── Фабрики доменных объектов ───────────────────────────────────────────

def make_country(name: str = "Казахстан", iso_code: str = "KZ") -> Country:
    # get_or_create, а не create: страна уникальна по имени, и несколько
    # фабрик в одном тесте (два администратора, контрагент) иначе роняли бы
    # тест на IntegrityError вместо проверки того, ради чего он написан.
    return Country.objects.get_or_create(name=name, defaults={"iso_code": iso_code})[0]


def make_program(name: str = "Образование", expense_item: str = "Оборудование",
                 code: str = "") -> Program:
    return Program.objects.create(name=name, expense_item=expense_item, code=code)


def make_administrator(country: Country | None = None,
                       project_name: str = "Проект А") -> Administrator:
    return Administrator.objects.create(
        country=country or make_country(), project_name=project_name,
    )


def make_budget(*, administrator: Administrator | None = None,
                program: Program | None = None, amount="5000000.00",
                period_year: int = 2026, currency: str = "KZT") -> Budget:
    administrator = administrator or make_administrator()
    return Budget.objects.create(
        administrator=administrator,
        program=program or make_program(),
        amount=Decimal(amount), period_year=period_year, currency=currency,
    )


def make_counterparty(*, country: Country | None = None, bin_iin: str = "123456789012",
                      name: str = "ТОО «Альфа»", **over) -> Counterparty:
    return Counterparty.objects.create(
        bin_iin=bin_iin, name=name,
        country=country or Country.objects.first() or make_country(),
        **over,
    )


def make_agreement(*, budget: Budget, counterparty: Counterparty | None = None,
                   number: str = "Д-001", amount="400000.00",
                   status: str = "signed", **over) -> Agreement:
    return Agreement.objects.create(
        number=number, name="Поставка ноутбуков", budget=budget,
        counterparty=counterparty or make_counterparty(country=budget.administrator.country),
        amount=Decimal(amount), payment_type="postpayment",
        currency=budget.currency, status=status, **over,
    )

"""Реестр контрагентов («Реестр контрактов» в терминах заказчика).

Самостоятельный справочник: карточка организации/ИП заводится один раз и
живёт независимо от того, как устроены бюджеты. Договор просто на неё
ссылается.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q
from django.http import Http404

from apps.contracts.models import Counterparty
from apps.contracts.services.reference_service import (
    conflict_as,
    delete_protected,
    get_country_or_404,
    resolve_country_input,
)


def list_counterparties(*, search: str | None = None, status: str | None = None,
                        country_id: int | None = None):
    query = Counterparty.objects.select_related("country")
    if search:
        # Один поисковый параметр на наименование и на БИН/ИИН: в реальном
        # использовании человек вбивает в одно поле либо название, либо
        # номер, и разделять их на два параметра означало бы заставлять
        # фронтенд угадывать, что именно ввели.
        query = query.filter(Q(name__icontains=search) | Q(bin_iin__startswith=search))
    if status is not None:
        query = query.filter(status=status)
    if country_id is not None:
        query = query.filter(country_id=country_id)
    return list(query)


def get_counterparty_or_404(counterparty_id: int) -> Counterparty:
    row = Counterparty.objects.select_related("country").filter(pk=counterparty_id).first()
    if row is None:
        raise Http404("Контрагент не найден")
    return row


def create_counterparty(*, bin_iin: str, name: str, country_id: int, vat: str = "",
                        contacts: str = "", address: str = "",
                        status: str | None = None) -> Counterparty:
    get_country_or_404(country_id)
    fields = dict(bin_iin=bin_iin, name=name, country_id=country_id, vat=vat,
                  contacts=contacts, address=address)
    if status is not None:
        fields["status"] = status
    with conflict_as(f"Контрагент с БИН/ИИН {bin_iin} уже есть в реестре"):
        return Counterparty.objects.create(**fields)


@transaction.atomic
def create_counterparty_full(*, bin_iin: str, name: str, country, vat: str = "",
                             contacts: str = "", address: str = "",
                             status: str | None = None) -> Counterparty:
    """Завести контрагента вместе со страной — одной транзакцией.

    ``country`` — это ``schemas.CountryInput``: либо ``id`` существующей
    записи, либо название новой. Так работает форма карточки контрагента.

    Транзакция здесь не формальность: самая частая ошибка при заведении —
    дубль БИН/ИИН, и без отката только что созданная страна осталась бы
    висеть после каждой такой неудачной попытки.
    """
    country_obj = resolve_country_input(country)

    fields = dict(bin_iin=bin_iin.strip(), name=name.strip(), country=country_obj,
                  vat=vat, contacts=contacts, address=address)
    if status is not None:
        fields["status"] = status

    with conflict_as(f"Контрагент с БИН/ИИН {bin_iin} уже есть в реестре"):
        return Counterparty.objects.create(**fields)


def update_counterparty(counterparty_id: int, **fields) -> Counterparty:
    row = get_counterparty_or_404(counterparty_id)
    if fields.get("country_id") is not None:
        get_country_or_404(fields["country_id"])

    changed = [key for key, value in fields.items() if value is not None]
    for key in changed:
        setattr(row, key, fields[key])
    if changed:
        with conflict_as("Контрагент с таким БИН/ИИН уже есть в реестре"):
            row.save()
    return row


def delete_counterparty(counterparty_id: int) -> None:
    delete_protected(get_counterparty_or_404(counterparty_id),
                     "У контрагента есть договоры — переведите его в статус "
                     "inactive/blocked вместо удаления")

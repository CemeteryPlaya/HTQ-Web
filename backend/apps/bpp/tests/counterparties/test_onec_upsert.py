"""Заготовка 1С: идемпотентный upsert контрагентов (A7.3, D-38, D-S7-5).

Сопоставление — по ``ext_1c_ref``, затем по естественному ключу (страна +
рег. номер). Синхронизации нет: функция принимает уже прочитанную запись.
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from apps.bpp import interface
from apps.bpp.models import AuditLog
from apps.bpp.models.counterparties import Counterparty
from apps.bpp.services.counterparties import onec, service
from htqweb.errors import DomainError
from htqweb.tenancy.db import use_company

from . import common

GUID_A = "0f8fad5b-d9cb-469f-a165-70867728950e"
GUID_B = "7c9e6679-7425-40de-944b-e07fc1f90ae7"


@pytest.fixture
def ctx(two_company_schemas):
    common.countries()
    with use_company(two_company_schemas[0]):
        yield two_company_schemas


def _record(number: str, guid: str = GUID_A, **over) -> dict:
    row = {"Ref_Key": guid, "Description": "ТОО «Альфа»", "БИНИИН": number, "КодСтраны": "KZ",
           "ВидКонтрагента": "ЮридическоеЛицо", "АдресЮридический": "г. Астана", "Телефон": "+77010000000"}
    row.update(over)
    return row


def _broken(number: str) -> str:
    """Тот же номер с испорченным контрольным разрядом."""
    return number[:-1] + str((int(number[-1]) + 1) % 10)


def _journal(cp) -> int:
    return AuditLog.objects.filter(object_type="bpp.counterparty", object_id=str(cp.pk)).count()


def test_new_record_is_created_with_ref_and_audit_source(ctx):
    out = onec.upsert_counterparty(_record(common.bin_first_pass()))
    assert out.status == "created"
    cp = Counterparty.objects.get(pk=out.object_id)
    assert cp.ext_1c_ref == GUID_A and cp.created_by is None
    row = AuditLog.objects.get(object_type="bpp.counterparty", object_id=str(cp.pk))
    assert row.actor_id is None and "1С" in row.comment


def test_repeat_is_unchanged_and_version_and_journal_do_not_grow(ctx):
    record = _record(common.bin_first_pass())
    first = onec.upsert_counterparty(record)
    cp = Counterparty.objects.get(pk=first.object_id)
    version, journal = cp.version, _journal(cp)
    again = onec.upsert_counterparty(record)
    cp.refresh_from_db()
    assert again.status == "unchanged"
    assert (cp.version, _journal(cp)) == (version, journal)


def test_changed_name_updates_the_card_by_ref(ctx):
    number = common.bin_first_pass()
    cp = Counterparty.objects.get(pk=onec.upsert_counterparty(_record(number)).object_id)
    out = onec.upsert_counterparty(_record(number, Description="ТОО «Альфа Плюс»"))
    cp.refresh_from_db()
    assert out.status == "updated" and cp.name == "ТОО «Альфа Плюс»" and cp.version == 2


def test_existing_card_without_ref_is_linked_by_natural_key_keeping_its_data(ctx):
    number = common.bin_first_pass()
    mine = service.create(common.data(number, name="Наше название"), actor_id=7)
    out = onec.upsert_counterparty(_record(number, Description="Название из 1С"))
    mine.refresh_from_db()
    assert out.status == "updated" and out.object_id == str(mine.pk)
    assert mine.ext_1c_ref == GUID_A and mine.name == "Наше название"


def test_other_ref_on_natural_key_is_a_conflict_and_nothing_changes(ctx):
    number = common.bin_first_pass()
    mine = service.create(common.data(number, ext_1c_ref=GUID_B), actor_id=7)
    saved_name = mine.name
    out = onec.upsert_counterparty(_record(number, GUID_A, Description="Другое"))
    mine.refresh_from_db()
    assert out.status == "conflict" and out.reason
    assert (mine.ext_1c_ref, mine.name, mine.version) == (GUID_B, saved_name, 1)
    assert Counterparty.objects.count() == 1


def test_invalid_bin_is_rejected_and_nothing_is_written(ctx):
    out = onec.upsert_counterparty(_record(_broken(common.bin_first_pass())))
    assert out.status == "rejected" and "E-CTR-03" in out.reason
    assert Counterparty.objects.count() == 0


def test_bin_change_of_a_linked_card_is_rejected(ctx):
    first, second = common.valid_bins(2)
    cp = Counterparty.objects.get(pk=onec.upsert_counterparty(_record(first)).object_id)
    out = onec.upsert_counterparty(_record(second))
    cp.refresh_from_db()
    assert out.status == "rejected" and cp.reg_number == first and cp.version == 1


def test_bad_guid_is_rejected(ctx):
    out = onec.upsert_counterparty(_record(common.bin_first_pass(), "not-a-guid"))
    assert out.status == "rejected" and Counterparty.objects.count() == 0


def test_one_bad_record_does_not_spoil_the_neighbours(ctx):
    good = common.bin_first_pass()
    outcomes = [onec.upsert_counterparty(_record(_broken(common.bin_first_pass()), GUID_B)),
                onec.upsert_counterparty(_record(good, GUID_A))]
    assert [o.status for o in outcomes] == ["rejected", "created"]


def test_failure_after_the_write_rolls_back_only_that_record(ctx, monkeypatch):
    """Сбой ПОСЛЕ записи карточки (журнал) откатывает эту запись целиком, соседи целы."""
    from django.db import DataError

    from apps.bpp.services.core import audit

    real = audit.record
    first, second = common.valid_bins(2)

    def flaky(obj, action, **kwargs):
        if obj.reg_number == first:
            raise DataError("value too long")
        return real(obj, action, **kwargs)

    monkeypatch.setattr(audit, "record", flaky)
    bad = onec.upsert_counterparty(_record(first, GUID_B))
    good = onec.upsert_counterparty(_record(second, GUID_A))
    assert (bad.status, good.status) == ("rejected", "created")
    assert list(Counterparty.objects.values_list("reg_number", flat=True)) == [second]


def test_empty_country_of_a_linked_nonresident_keeps_its_country(ctx):
    cp = service.create(common.data("AB-123", kind="nonresident", country_code="RU",
                                    ext_1c_ref=GUID_A), actor_id=1)
    out = onec.upsert_counterparty(_record("AB-123", КодСтраны="", Description="Новое имя"))
    cp.refresh_from_db()
    assert out.status == "updated" and cp.country_code == "RU" and cp.name == "Новое имя"


def test_too_long_value_is_rejected_not_raised(ctx):
    out = onec.upsert_counterparty(_record(common.bin_first_pass(), Телефон="9" * 500))
    assert out.status == "rejected" and Counterparty.objects.count() == 0


def test_manual_ref_must_be_a_guid_and_is_lowercased(ctx):
    first, second = common.valid_bins(2)
    err = pytest.raises(DomainError, service.create,
                        common.data(first, ext_1c_ref="не-guid"), actor_id=1).value
    assert err.fields[0]["field"] == "ext_1c_ref"
    cp = service.create(common.data(second, ext_1c_ref=GUID_A.upper()), actor_id=1)
    assert cp.ext_1c_ref == GUID_A


def test_interface_exposes_the_upsert(ctx):
    out = interface.upsert_counterparty_from_1c(_record(common.bin_first_pass()))
    assert out.status == "created"


# ── ограничение уникальности ────────────────────────────────────────────

def test_duplicate_nonempty_ref_is_integrity_error(ctx):
    first, second = common.valid_bins(2)
    service.create(common.data(first, ext_1c_ref=GUID_A), actor_id=1)
    with pytest.raises(IntegrityError), transaction.atomic():
        Counterparty.objects.create(name="Дубль", kind="legal", country_code="KZ",
                                    reg_number=second, ext_1c_ref=GUID_A)


def test_several_empty_refs_are_allowed(ctx):
    first, second = common.valid_bins(2)
    service.create(common.data(first), actor_id=1)
    service.create(common.data(second), actor_id=1)
    assert Counterparty.objects.filter(ext_1c_ref="").count() == 2


def test_same_ref_in_two_companies_is_allowed(two_company_schemas):
    common.countries()
    number = common.bin_first_pass()
    for slug in two_company_schemas:
        with use_company(slug):
            assert onec.upsert_counterparty(_record(number)).status == "created"

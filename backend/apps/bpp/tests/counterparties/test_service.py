"""Справочник «Контрагенты» — сервис и функции для договоров и счетов
(ТЗ §18, §26.1, D-20, задача A2.3; Review Focus 2)."""

from __future__ import annotations

import threading
from datetime import datetime, timezone as dt_timezone

import pytest
from django.db import connection

from apps.bpp.models import AuditLog
from apps.bpp.models.counterparties import Counterparty, CounterpartyBankAccount
from apps.bpp.services.core.settings import get_setting, set_setting
from apps.bpp.services.counterparties import lookup, service
from htqweb.errors import DomainError

from . import common

FD = 911


def _create(number: str | None = None, **over) -> Counterparty:
    common.countries()
    return service.create(common.data(number or common.bin_first_pass(), **over), actor_id=FD)


def _code(fn, *args, **kwargs) -> DomainError:
    with pytest.raises(DomainError) as exc:
        fn(*args, **kwargs)
    return exc.value


# ── создание и дубль ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_create_normalizes_number_and_writes_audit(company_context):
    number = common.bin_first_pass()
    cp = _create(f"{number[:4]} {number[4:8]}-{number[8:]}")
    assert (cp.reg_number, cp.status, cp.version) == (number, "active", 1)
    row = AuditLog.objects.get(object_type="bpp.counterparty", object_id=str(cp.pk))
    assert row.action == "created" and row.changes["reg_number"] == number


@pytest.mark.django_db
def test_duplicate_is_e_ctr_02_with_link_to_existing(company_context):
    number = common.bin_first_pass()
    first = _create(number)
    err = _code(_create, f"{number[:6]} {number[6:]}", name="Другое имя")
    assert err.code == "E-CTR-02" and err.status == 422
    assert err.fields[0]["existing_id"] == str(first.pk)
    # Тот же номер в другой стране — другой контрагент.
    other = _create(number, kind="nonresident", country_code="RU")
    assert other.pk != first.pk


@pytest.mark.django_db
def test_integrity_error_on_insert_becomes_e_ctr_02(company_context, monkeypatch):
    """Предварительная проверка пропустила (как у проигравшего гонку) —
    уникальный ключ БД ловится и превращается в E-CTR-02, транзакция
    вызывающего остаётся живой."""
    number = common.bin_first_pass()
    first = _create(number)
    monkeypatch.setattr(service, "_raise_if_duplicate", lambda *a, **k: None)
    err = _code(_create, number)
    assert err.code == "E-CTR-02" and err.fields[0]["existing_id"] == str(first.pk)
    assert Counterparty.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_parallel_duplicate_is_422(monkeypatch):
    """Review Focus 2: два одновременных запроса с одной парой «страна +
    номер» — один создан, второй получает E-CTR-02 со ссылкой на первого, а
    не 500. Оба проходят предварительную проверку до того, как любой
    вставит строку (барьер), — значит, второго останавливает уникальный
    ключ БД. Каждый поток — в своём соединении (таблицы модуля в тестовой
    БД есть и в ``public``)."""
    common.countries()
    number = common.bin_first_pass()
    barrier = threading.Barrier(2)
    real_check = service._raise_if_duplicate

    def check_then_wait(*args, **kwargs):
        real_check(*args, **kwargs)
        barrier.wait(timeout=10)

    monkeypatch.setattr(service, "_raise_if_duplicate", check_then_wait)
    outcome: list[tuple] = []
    lock = threading.Lock()

    def worker():
        try:
            cp = service.create(common.data(number), actor_id=FD)
            result = ("ok", str(cp.pk))
        except DomainError as exc:
            result = (exc.code, (exc.fields or [{}])[0].get("existing_id"))
        except Exception as exc:  # noqa: BLE001 — любой другой исход — провал теста
            result = ("crash", repr(exc))
        finally:
            connection.close()
        with lock:
            outcome.append(result)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    codes = sorted(code for code, _ in outcome)
    assert codes == ["E-CTR-02", "ok"], outcome
    created = next(ref for code, ref in outcome if code == "ok")
    linked = next(ref for code, ref in outcome if code == "E-CTR-02")
    assert linked == created
    assert Counterparty.objects.filter(reg_number=number).count() == 1


@pytest.mark.django_db
def test_invalid_number_and_unknown_country(company_context):
    common.countries()
    body = common.bin_body_ten_twice()
    assert _code(_create, body + "0").code == "E-CTR-03"
    err = _code(_create, "A-1", kind="nonresident", country_code="ZZ")
    assert (err.code, err.fields[0]["field"]) == ("E-REF-04", "country_code")


# ── правка и версия ─────────────────────────────────────────────────────

@pytest.mark.django_db
def test_update_audits_changed_fields_and_bumps_version(company_context):
    cp = _create()
    cp = service.update(cp.pk, {"phone": "+7 701 000 00 00", "name": cp.name},
                        expected_version=1, actor_id=FD)
    assert cp.version == 2
    row = AuditLog.objects.filter(object_id=str(cp.pk), action="updated").get()
    assert row.changes == {"phone": ["", "+7 701 000 00 00"]}


@pytest.mark.django_db
def test_stale_version_is_e_con_01(company_context):
    cp = _create()
    service.update(cp.pk, {"phone": "1"}, expected_version=1, actor_id=FD)
    err = _code(service.update, cp.pk, {"phone": "2"}, expected_version=1, actor_id=FD)
    assert (err.code, err.status) == ("E-CON-01", 409)
    err = _code(service.block, cp.pk, reason="нет оригиналов документов",
                expected_version=1, actor_id=FD)
    assert err.code == "E-CON-01"


@pytest.mark.django_db
def test_update_to_taken_number_is_e_ctr_02(company_context):
    first_number, second_number = common.valid_bins(2)
    first = _create(first_number)
    second = _create(second_number)
    err = _code(service.update, second.pk, {"reg_number": first_number},
                expected_version=None, actor_id=FD)
    assert err.code == "E-CTR-02" and err.fields[0]["existing_id"] == str(first.pk)


@pytest.mark.django_db
def test_old_invalid_number_does_not_block_other_edits(company_context):
    """Карточка, перенесённая со старым неверным номером, принимает правку
    телефона: номер проверяется, только когда меняется он, тип или страна."""
    cp = _create()
    Counterparty.objects.filter(pk=cp.pk).update(reg_number="12345")
    cp = service.update(cp.pk, {"phone": "+7"}, expected_version=None, actor_id=FD)
    assert cp.phone == "+7"
    assert _code(service.update, cp.pk, {"reg_number": "123456"},
                 expected_version=None, actor_id=FD).code == "E-CTR-03"


# ── блокировка и архив ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_blocked_counterparty_is_e_ctr_01_with_date_and_reason(company_context):
    cp = _create()
    assert _code(service.block, cp.pk, reason="коротко", expected_version=None,
                 actor_id=FD).code == "BR-060"
    service.block(cp.pk, reason="нет оригиналов документов", expected_version=None,
                  actor_id=FD)
    # 09.09 20:00 UTC — это уже 10.09 в Алматы: дата — в поясе платформы.
    Counterparty.objects.filter(pk=cp.pk).update(
        blocked_at=datetime(2026, 9, 9, 20, 0, tzinfo=dt_timezone.utc))
    err = _code(lookup.assert_usable, cp.pk)
    assert err.code == "E-CTR-01"
    assert err.message == ("Контрагент ТОО „Альфа“ заблокирован 10.09.2026: „нет оригиналов "
                           "документов“. Выберите другого контрагента или обратитесь к "
                           "финансовому директору.")
    # Повторная блокировка — не из «Активен».
    assert _code(service.block, cp.pk, reason="ещё одна причина", expected_version=None,
                 actor_id=FD).code == "E-STATE-01"
    cp = service.unblock(cp.pk, expected_version=None, actor_id=FD)
    assert (cp.status, cp.block_reason, cp.blocked_at) == ("active", "", None)
    assert lookup.assert_usable(cp.pk).pk == cp.pk


@pytest.mark.django_db
def test_archived_counterparty_is_not_usable_nor_editable(company_context):
    cp = _create()
    service.archive(cp.pk, expected_version=None, actor_id=FD)
    err = _code(lookup.assert_usable, cp.pk)
    assert err.code == "E-CTR-01" and "в архив" in err.message
    assert _code(service.update, cp.pk, {"phone": "1"}, expected_version=None,
                 actor_id=FD).status == 409
    assert _code(lookup.assert_usable, "не-uuid").status == 404


# ── метка «Проверенный» ─────────────────────────────────────────────────

@pytest.mark.django_db
def test_verified_by_threshold_and_manual_override(company_context):
    cp = _create()
    assert get_setting("counterparty_verified_threshold") == 3
    assert lookup.needs_confirmation(cp.pk)
    for _ in range(3):
        lookup.record_success(cp.pk)
    assert not lookup.needs_confirmation(cp.pk)
    assert lookup.brief([str(cp.pk)])[str(cp.pk)]["is_verified"] is True

    # Ручное снятие ФД порогом не перебивается — даже после новых удачных.
    service.set_verified(cp.pk, False, expected_version=None, actor_id=FD)
    lookup.record_success(cp.pk)
    assert lookup.needs_confirmation(cp.pk)
    # null возвращает решение порогу.
    service.set_verified(cp.pk, None, expected_version=None, actor_id=FD)
    assert not lookup.needs_confirmation(cp.pk)

    # Порог — настройка модуля.
    set_setting("counterparty_verified_threshold", 10, actor_id=FD)
    assert lookup.needs_confirmation(cp.pk)
    service.set_verified(cp.pk, True, expected_version=None, actor_id=FD)
    assert not lookup.needs_confirmation(cp.pk)


@pytest.mark.django_db
def test_record_success_does_not_bump_version(company_context):
    cp = _create()
    lookup.record_success(cp.pk)
    cp.refresh_from_db()
    assert (cp.successful_documents, cp.version) == (1, 1)
    assert _code(lookup.record_success, "00000000-0000-0000-0000-000000000000").status == 404


@pytest.mark.django_db
def test_record_success_is_audited(company_context):
    """Метка «Проверенный» появляется сама — «История изменений» обязана
    показать, когда и почему (ТЗ §25.2): каждый удачный документ — запись."""
    from apps.bpp.models import AuditLog

    cp = _create()
    for _ in range(3):
        lookup.record_success(cp.pk)
    rows = list(AuditLog.objects.filter(object_type="bpp.counterparty", object_id=str(cp.pk),
                                        action="success_recorded").order_by("created_at"))
    assert [r.changes["successful_documents"] for r in rows] == [1, 2, 3]
    assert [r.changes["verified"] for r in rows] == [False, False, True]
    assert all(r.actor_id is None for r in rows)


@pytest.mark.django_db
def test_brief_shape(company_context):
    cp = _create(is_vat_payer=True)
    assert lookup.brief([str(cp.pk), "мусор"]) == {str(cp.pk): {
        "id": str(cp.pk), "name": cp.name, "short_name": "ТОО „Альфа“",
        "reg_number": cp.reg_number, "country_code": "KZ", "is_vat_payer": True,
        "status": "active", "is_verified": False}}


# ── банковские счета ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_bank_accounts(company_context):
    first_number, second_number = common.valid_bins(2)
    cp = _create(first_number)
    iban1, iban2 = common.kz_iban("125KZT5004100100"), common.kz_iban("125KZT5004100200")
    assert _code(service.add_account, cp.pk, {"iban": "KZ00125KZT5004100100",
                                              "bic": "HSBKKZKX"}, actor_id=FD).code == "E-CTR-04"
    assert _code(service.add_account, cp.pk, {"iban": iban1, "bic": "HSBK"},
                 actor_id=FD).code == "E-CTR-04"

    one = service.add_account(cp.pk, {"iban": iban1.lower(), "bic": "hsbkkzkx",
                                      "bank_name": "Банк"}, actor_id=FD)
    assert (one["iban"], one["bic"], one["is_primary"]) == (iban1, "HSBKKZKX", True)
    two = service.add_account(cp.pk, {"iban": iban2, "bic": "HSBKKZKX001",
                                      "is_primary": True}, actor_id=FD)
    primaries = list(CounterpartyBankAccount.objects.filter(is_primary=True)
                     .values_list("pk", flat=True))
    assert [str(pk) for pk in primaries] == [two["id"]]

    # Один IBAN — один счёт, даже у другого контрагента.
    other = _create(second_number)
    err = _code(service.add_account, other.pk, {"iban": iban1, "bic": "HSBKKZKX"},
                actor_id=FD)
    assert (err.code, err.fields[0]["field"]) == ("E-CTR-04", "iban")

    # Архивный счёт основным не бывает.
    archived = service.update_account(two["id"], {"is_active": False}, actor_id=FD)
    assert (archived["is_active"], archived["is_primary"]) == (False, False)
    assert len(service.list_accounts(cp.pk)) == 2
    assert AuditLog.objects.filter(object_id=str(cp.pk),
                                   action__startswith="account_").count() == 3

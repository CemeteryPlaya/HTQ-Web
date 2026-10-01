"""Модели альтернатив и KPI: ограничения БД (план этапа 5 A, задача 1).

BR-091 — один контрагент — одна ДЕЙСТВУЮЩАЯ АП к документу («Черновик»,
«Подано», «Выбрано»); BR-096 — одна запись KPI на АП. Лимит счёта —
``Invoice.alt_limit`` (3 по умолчанию).
"""

from __future__ import annotations

import itertools
import uuid
from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from apps.bpp.models import (
    AlternativeOffer,
    AlternativeOfferLine,
    Invoice,
    KpiRecord,
    KpiStatus,
    OfferStatus,
)
from apps.bpp.tests.bank.common import counterparty, orm_invoice

_SEQ = itertools.count(1)


def _offer(source_id, cp, *, status=OfferStatus.SUBMITTED, author_id=501) -> AlternativeOffer:
    return AlternativeOffer.objects.create(
        number=f"АП-2026-{next(_SEQ):06d}", source_type="invoice", source_id=source_id,
        author_id=author_id, author_role="sn", counterparty=cp, status=status)


def _kpi(offer: AlternativeOffer) -> KpiRecord:
    return KpiRecord.objects.create(
        offer=offer, buyer_id=offer.author_id, buyer_role=offer.author_role,
        project_id=uuid.uuid4(), article_id=uuid.uuid4(), source_type=offer.source_type,
        source_id=offer.source_id, source_number="СЧ-2026-000140",
        source_amount_kzt=Decimal("2800000.00"), result_type="invoice",
        result_id=uuid.uuid4(), result_number="СЧ-2026-000141",
        result_amount_kzt=Decimal("2450000.00"), saving_amount=Decimal("350000.00"),
        saving_pct=Decimal("12.50"), selected_at=timezone.now(), selected_by_id=900)


@pytest.mark.django_db
def test_offer_counterparty_unique_among_live():
    source = uuid.uuid4()
    cp = counterparty("100000000011")
    first = _offer(source, cp)
    with pytest.raises(IntegrityError), transaction.atomic():
        _offer(source, cp, status=OfferStatus.DRAFT, author_id=502)

    # Тот же контрагент к ДРУГОМУ документу — можно.
    _offer(uuid.uuid4(), cp)

    # «Отозвано» контрагента не держит.
    first.status = OfferStatus.WITHDRAWN
    first.save(update_fields=["status"])
    again = _offer(source, cp, status=OfferStatus.DRAFT, author_id=502)
    assert again.status == OfferStatus.DRAFT


@pytest.mark.django_db
@pytest.mark.parametrize("closed", [OfferStatus.NOT_SELECTED, OfferStatus.ANNULLED])
def test_closed_offers_do_not_hold_the_counterparty(closed):
    source = uuid.uuid4()
    cp = counterparty("100000000012")
    _offer(source, cp, status=closed)
    _offer(source, cp, status=OfferStatus.SELECTED, author_id=502)
    # «Выбрано» — действующая: третья с тем же контрагентом не проходит.
    with pytest.raises(IntegrityError), transaction.atomic():
        _offer(source, cp, author_id=503)


@pytest.mark.django_db
def test_drafts_without_counterparty_do_not_collide():
    """Черновик без контрагента — NULL, а NULL в уникальном индексе не
    совпадает с NULL: несколько свежих черновиков к документу допустимы."""
    source = uuid.uuid4()
    _offer(source, None, status=OfferStatus.DRAFT)
    _offer(source, None, status=OfferStatus.DRAFT, author_id=502)
    assert AlternativeOffer.objects.filter(source_id=source).count() == 2


@pytest.mark.django_db
def test_offer_defaults_are_a_draft_without_money():
    offer = AlternativeOffer.objects.create(
        number="АП-2026-900001", source_type="agreement", source_id=uuid.uuid4(),
        author_id=501, author_role="pm")
    offer.refresh_from_db()
    assert offer.status == OfferStatus.DRAFT
    assert offer.version == 1
    assert (offer.currency_code, offer.amount, offer.amount_kzt) == ("KZT", Decimal("0"), None)
    assert offer.counterparty_id is None
    assert (offer.result_type, offer.result_id) == ("", None)
    assert offer.own_document is False


@pytest.mark.django_db
def test_offer_number_is_unique():
    first = _offer(uuid.uuid4(), None, status=OfferStatus.DRAFT)
    with pytest.raises(IntegrityError), transaction.atomic():
        AlternativeOffer.objects.create(number=first.number, source_type="invoice",
                                        source_id=uuid.uuid4(), author_id=1, author_role="sn")


@pytest.mark.django_db
def test_kpi_record_one_per_offer():
    offer = _offer(uuid.uuid4(), counterparty("100000000013"), status=OfferStatus.SELECTED)
    record = _kpi(offer)
    record.refresh_from_db()
    assert record.status == KpiStatus.PRELIMINARY
    with pytest.raises(IntegrityError), transaction.atomic():
        _kpi(offer)


@pytest.mark.django_db
def test_offer_with_kpi_is_not_deleted():
    """``PROTECT``: запись KPI держит свою АП — выбранную АП не стереть."""
    offer = _offer(uuid.uuid4(), counterparty("100000000014"), status=OfferStatus.SELECTED)
    _kpi(offer)
    with pytest.raises(ProtectedError):
        offer.delete()


@pytest.mark.django_db
def test_offer_line_price_must_be_positive_or_empty():
    """Цена > 0 или пуста (у черновика цены ещё не введены). Проверка —
    сырой вставкой нулевой цены: CHECK срабатывает сразу, а внешние ключи
    Django в Postgres отложены до коммита, поэтому настоящая позиция заявки
    не нужна — строка откатывается вместе с точкой сохранения и проверку FK
    в конце теста не застаёт."""
    offer = _offer(uuid.uuid4(), None, status=OfferStatus.DRAFT)
    table = AlternativeOfferLine._meta.db_table
    sql = (f"INSERT INTO {table} (id, created_at, updated_at, version, offer_id, "
           f"source_line_id, request_item_id, qty, source_price, price, amount) "
           f"VALUES (%s, now(), now(), 1, %s, %s, %s, 1, 10, %s, NULL)")
    with pytest.raises(IntegrityError) as exc, transaction.atomic(), connection.cursor() as cur:
        cur.execute(sql, [uuid.uuid4(), offer.pk, uuid.uuid4(), uuid.uuid4(), 0])
    assert "ck_bpp_altline_price" in str(exc.value)
    field = AlternativeOfferLine._meta.get_field("price")
    assert field.null, "черновик АП хранит позиции без цены"


@pytest.mark.django_db
def test_invoice_alt_limit_defaults_to_three():
    inv = orm_invoice(counterparty("100000000015"), "1000.00", status="under_review")
    inv.refresh_from_db()
    assert inv.alt_limit == 3
    # db_default: строка, вставленная старым кодом во время выкатки (без
    # столбца), тоже получает 3.
    assert Invoice._meta.get_field("alt_limit").db_default == 3

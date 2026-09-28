"""Типы файлов договора, счёта и выписки (ТЗ §21; план этапа 3 БЗО A,
задача 1) и текстовые форматы выписки в подсистеме.

Справочник заводит миграция ``files/0004_bpp_stage3_file_types``, а её
владельцев регистрируют документы модуля (``services/<подмодуль>/
file_owner.py``) — поэтому здесь проверяется только справочник: формат,
размер и владелец каждой строки — по таблице ТЗ §21, выписанной в тесте
заново, а не взятой из миграции (иначе тест сверял бы миграцию с самой
собой). ``seed`` миграции зовётся перед проверкой: transaction=True-тесты
других модулей чистят ``public`` целиком вместе со справочником.

Выписка — TXT (1CClientBankExchange), XLSX, CSV: подсистема отдаёт такой
файл в scope ``file_object`` как ``text/plain``/``text/csv`` (тип — из
расширения, заявленный браузером не указ: Windows шлёт CSV как
``application/vnd.ms-excel``) и отдаёт только вложением.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as django_apps
from django.test import Client

from apps.files.models import FileObject, FileType

from .helpers import assert_tz_error, auth, files_url, upload
from .testapp.models import ProbeFolder

pytestmark = pytest.mark.django_db

_MIGRATION = importlib.import_module("apps.files.migrations.0004_bpp_stage3_file_types")

IMAGES = {".jpg", ".jpeg", ".png"}

#: ТЗ §21 и таблица задачи 1 плана этапа 3 A:
#: код → (владелец, форматы, МБ).
EXPECTED = {
    "agreement": ("bpp.agreement", {".pdf", ".docx", *IMAGES}, 20),
    "agreement_annex": ("bpp.agreement", {".pdf", ".docx", *IMAGES}, 20),
    "invoice": ("bpp.invoice", {".pdf", *IMAGES}, 10),
    "act": ("bpp.invoice", {".pdf", *IMAGES}, 10),
    "waybill": ("bpp.invoice", {".pdf", *IMAGES}, 10),
    "vat_invoice": ("bpp.invoice", {".pdf", *IMAGES, ".xml"}, 10),
    "bank_statement": ("bpp.bank_import", {".txt", ".xlsx", ".csv"}, 20),
}

#: Выписка 1С в том виде, в каком её отдаёт банк-клиент: CP1251 и CRLF.
ONEC = ("1CClientBankExchange\r\nВерсияФормата=1.03\r\nКодировка=Windows\r\n"
        "СекцияДокумент=Платежное поручение\r\nНомер=15\r\nКонецДокумента\r\n"
        "КонецФайла\r\n").encode("cp1251")
CSV = "Дата;Сумма;Назначение\r\n01.10.2026;1 250 000,00;Оплата по счёту\r\n".encode("utf-8")


@pytest.fixture
def reference():
    _MIGRATION.seed(django_apps, None)


@pytest.mark.parametrize("code", sorted(EXPECTED))
def test_stage3_type_is_in_the_reference_as_in_tz(reference, code):
    owner_type, formats, max_mb = EXPECTED[code]

    row = FileType.objects.get(pk=code)

    assert row.owner_type == owner_type
    assert set(row.formats) == formats
    assert row.max_mb == max_mb
    assert row.name


def test_reseed_keeps_the_size_set_by_the_administrator(reference):
    """Размер правит администратор (ТЗ стр. 61: «Нет / размеры / нет») —
    повторный прогон миграции его не сбрасывает, а остальное возвращает."""
    FileType.objects.filter(pk="invoice").update(max_mb=5, name="переименован",
                                                 formats=[".pdf"])

    _MIGRATION.seed(django_apps, None)

    row = FileType.objects.get(pk="invoice")
    assert row.max_mb == 5
    assert row.name == "Счёт на оплату"
    assert set(row.formats) == {".pdf", *IMAGES}
    assert FileType.objects.filter(pk__in=list(EXPECTED)).count() == len(EXPECTED)


def test_unseed_removes_the_stage3_types_and_seed_brings_them_back(reference):
    """Откат миграции проходит (типы без файлов удаляются), повторный прогон
    заводит их снова."""
    _MIGRATION.unseed(django_apps, None)

    assert not FileType.objects.filter(pk__in=list(EXPECTED)).exists()
    _MIGRATION.seed(django_apps, None)
    assert FileType.objects.filter(pk__in=list(EXPECTED)).count() == len(EXPECTED)


# ── текстовые форматы выписки ───────────────────────────────────────────

def _text_folder() -> ProbeFolder:
    FileType.objects.filter(pk="probe.other").update(formats=[".pdf", ".txt", ".csv"])
    return ProbeFolder.objects.create()


@pytest.mark.parametrize("name, content, declared, stored", [
    ("kl_to_1c.txt", ONEC, "text/plain", "text/plain"),
    ("vypiska.csv", CSV, "text/csv", "text/csv"),
    # Браузер на Windows шлёт CSV как Excel: тип берётся из расширения.
    ("vypiska.csv", CSV, "application/vnd.ms-excel", "text/csv"),
])
def test_text_statement_is_accepted_and_served_only_as_an_attachment(
        name, content, declared, stored):
    probe = _text_folder()
    client = Client()

    resp = upload(client, probe.pk, name=name, content=content, mime=declared,
                  file_type="probe.other")

    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["mime"] == stored
    link = client.get(f"{files_url(probe.pk)}{body['document_id']}/versions/{body['id']}/link",
                      **auth()).json()
    download = Client().get(link["url"])
    assert download.status_code == 200 and download.content == content
    # Текст не рисуется в браузере на origin приложения — только скачивание.
    assert download["Content-Disposition"].startswith("attachment")


def test_text_formats_still_follow_the_type_reference():
    """Потолок scope расширен, но узкое правило — у типа: где справочник
    TXT не разрешает, выписку не примут."""
    probe = ProbeFolder.objects.create()

    resp = upload(Client(), probe.pk, name="kl_to_1c.txt", content=ONEC, mime="text/plain")

    assert_tz_error(resp, 415, "E-FIL-01")
    assert not FileObject.objects.exists()

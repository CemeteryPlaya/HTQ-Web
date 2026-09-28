"""Загрузка выписки (ТЗ §11.2, §11.3 п.1–3, §15.5, BR-075, L-07; план
этапа 3 A, задача 3 — A4.1, Review Focus 1, 2, 4).

Разбор идёт в Celery после фиксации транзакции: в тестах задача
выполняется сразу (``CELERY_TASK_ALWAYS_EAGER``), а момент фиксации даёт
``django_capture_on_commit_callbacks(execute=True)``. После запроса
``Client`` схема компании сброшена — чтения из базы идут под
``use_company(slug)``.
"""

from __future__ import annotations

import io
import json
import re
import threading
from datetime import date, timedelta
from decimal import Decimal

import openpyxl
import pytest
from django.db import connection
from django.test import Client
from django.utils import timezone

from apps.access.tests.helpers import token
from apps.bpp import tasks_bank
from apps.bpp.models import AuditLog
from apps.bpp.models.bank import (
    BankImport,
    BankImportStatus,
    BankStatementLine,
    OrgBankAccount,
)
from apps.bpp.services.bank import file_owner, imports
from apps.bpp.services.bank import settings as bank_settings
from apps.bpp.services.bank.parsers import MAX_ROWS
from apps.bpp.tests import stage2 as s
from apps.bpp.tests.test_files import memory_storage  # noqa: F401  (фикстура)
from apps.files import interface as files_interface
from apps.files.models import FileObject
from htqweb.authn.jwt import decode_token
from htqweb.errors import DomainError
from htqweb.tenancy.db import use_company

from . import common

ADM, FD, BUH, TD = 951, 952, 953, 954
BASE = "/api/bpp/v1/bank/imports"

#: Текст E-IMP-01 — ТЗ §26.1 дословно.
E_IMP_01 = ("Файл не распознан как выписка формата 1С: нет строки „1CClientBankExchange“. "
            "Выберите другой формат или файл.")


# ── даты: период выписки не может заканчиваться позже сегодня ──────────

def _ago(days: int) -> date:
    return timezone.localdate() - timedelta(days=days)


def _ru(day: date) -> str:
    return day.strftime("%d.%m.%Y")


PERIOD = (_ago(20), _ago(1))


def _onec_period() -> tuple[str, str]:
    return _ru(PERIOD[0]), _ru(PERIOD[1])


# ── справочник и файлы ─────────────────────────────────────────────────

@pytest.fixture
def slug(company_context):
    slug = company_context["slug"]
    s.grant(slug, ADM, "bpp-adm")
    s.grant(slug, FD, "bpp-fd")
    s.grant(slug, BUH, "bpp-buh")
    s.grant(slug, TD, "bpp-td")
    return slug


def _account(fmt: str = "onec", n: int = 1, **tpl_over) -> OrgBankAccount:
    data = {"name": f"Шаблон {fmt}", "format": fmt,
            "columns": {} if fmt == "onec" else
            {**common.HEADERS, "payer_account": "Счёт плательщика"}, **tpl_over}
    tpl = bank_settings.create_template(data, actor_id=ADM)
    return bank_settings.create_account(
        {"iban": common.iban(n), "bank_name": "Halyk Bank", "bic": "HSBKKZKX",
         "currency": "KZT", "template_id": str(tpl.pk)}, actor_id=ADM)


@pytest.fixture
def onec_account(slug) -> OrgBankAccount:
    return _account("onec")


@pytest.fixture
def xlsx_account(slug) -> OrgBankAccount:
    return _account("xlsx", 2)


def _docs(own: str, *, bad_date: bool = False) -> list[list[str]]:
    """Два списания своего счёта, поступление и (по желанию) документ с
    датой «31.02.2026»."""
    docs = [common.onec_doc("101", _ru(_ago(10)), "1250000.00", own),
            common.onec_doc("102", _ru(_ago(9)), "500.50", own, recipient_bin="990340000123"),
            common.onec_doc("103", _ru(_ago(9)), "7000.00", common.iban(9), recipient_iban=own)]
    if bad_date:
        docs.insert(1, common.onec_doc("104", "31.02.2026", "10.00", own))
    return docs


def _onec_upload(account, **kwargs):
    return common.onec_file(account.iban, _docs(account.iban, **kwargs),
                            period=_onec_period())


def _xlsx_upload(account, rows):
    head = [common.HEADERS["doc_number"], common.HEADERS["date"], common.HEADERS["amount"],
            common.HEADERS["purpose"], common.HEADERS["recipient_bin"], "Счёт плательщика"]
    return common.xlsx_file([["Выписка по счёту", account.iban], head, *rows])


def _start(capture, account, upload, **kwargs) -> tuple[BankImport, list[str]]:
    """Загрузка через сервис; разбор выполняется на фиксации транзакции."""
    with capture(execute=True):
        imp, warnings = imports.start_import(account_id=account.pk, upload=upload,
                                             actor_id=FD, **kwargs)
    imp.refresh_from_db()
    return imp, warnings


def _live(account) -> int:
    return BankStatementLine.objects.filter(account=account, cancelled_at__isnull=True).count()


def _headers(slug, user_id) -> dict:
    headers = s.auth(slug, user_id)
    headers.pop("content_type")  # multipart ставит клиент сам
    return headers


def _error(fn, *args, **kwargs) -> DomainError:
    with pytest.raises(DomainError) as exc:
        fn(*args, **kwargs)
    return exc.value


# ── загрузка 1С через ручку ─────────────────────────────────────────────

@pytest.mark.django_db
def test_upload_parses_in_background_and_card_shows_totals(
        slug, onec_account, django_capture_on_commit_callbacks):
    """Review Focus 1 целиком: грязный файл 1С (cp1251, CRLF, «31.02.2026»)
    — загрузка «Обрабатывается», после разбора «Загружена»: 4 документа,
    2 списания, ошибка строки с номером, строки выписки — «Не
    сопоставлена», файл — в apps.files."""
    client = Client()
    upload = _onec_upload(onec_account, bad_date=True)
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(BASE, {"account_id": str(onec_account.pk), "file": upload,
                                      "comment": "Сентябрь"}, **_headers(slug, FD))
        assert response.status_code == 201, response.json()
        created = response.json()
        assert created["status"] == "processing"
    assert re.fullmatch(r"ВП-\d{4}-0001", created["number"])
    assert created["warnings"] == []
    assert (created["period_from"], created["period_to"]) == tuple(
        day.isoformat() for day in PERIOD)  # период — из заголовка файла

    card = client.get(f"{BASE}/{created['id']}", **_headers(slug, FD)).json()
    assert card["status"] == "loaded" and card["progress"] == 100
    assert (card["rows_total"], card["debits"], card["duplicates"]) == (4, 2, 0)
    assert len(card["errors"]) == 1
    assert re.fullmatch(r"Строка \d+: не распознана дата „31\.02\.2026“", card["errors"][0])
    assert (card["lines"], card["matched"], card["unmatched"]) == (2, 0, 2)
    assert card["file"]["filename"] == "kl_to_1c.txt" and card["file"]["file_type"] == "bank_statement"
    assert card["comment"] == "Сентябрь" and card["author_id"] == FD

    lines = client.get(f"{BASE}/{created['id']}/lines", **_headers(slug, BUH)).json()
    assert lines["total"] == 2
    assert [row["amount"] for row in lines["items"]] == ["1250000.00", "500.50"]
    assert {row["match_status"] for row in lines["items"]} == {"unmatched"}

    with use_company(slug):  # запрос вернул search_path в public
        imp = BankImport.objects.get(pk=created["id"])
        assert bytes(imp.source) == b""  # копия байтов — только на время разбора
        assert imp.started_at is not None and imp.finished_at is not None
        assert set(AuditLog.objects.filter(object_type="bpp.bankimport", object_id=str(imp.pk))
                   .values_list("action", flat=True)) >= {"created", "loaded", "file_attached"}


@pytest.mark.django_db
def test_rights_upload_fd_read_fd_and_buh(slug, onec_account):
    """ТЗ §11.1: загружает ФД, смотрят ФД и БУХ; журнал — тем же."""
    client = Client()
    denied = client.post(BASE, {"account_id": str(onec_account.pk),
                                "file": _onec_upload(onec_account)}, **_headers(slug, BUH))
    assert denied.status_code == 403 and denied.json()["code"] == "E-ACC-01"
    assert client.get(BASE, **_headers(slug, BUH)).status_code == 200
    assert client.get(BASE, **_headers(slug, TD)).status_code == 403

    created = client.post(BASE, {"account_id": str(onec_account.pk),
                                 "file": _onec_upload(onec_account)}, **_headers(slug, FD))
    assert created.status_code == 201, created.json()
    history = f"/api/bpp/v1/history/bpp.bankimport/{created.json()['id']}"
    assert client.get(history, **_headers(slug, BUH)).status_code == 200
    assert client.get(history, **_headers(slug, TD)).status_code == 404
    assert client.get(f"{BASE}/not-a-uuid", **_headers(slug, FD)).status_code == 404


# ── дубли (BR-075) ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_reupload_skips_duplicates(slug, onec_account, django_capture_on_commit_callbacks):
    """Review Focus 2: та же выписка второй раз — «Пропущено дублей: 2»,
    новых строк нет; форма предупреждает о пересечении периода."""
    first, warnings = _start(django_capture_on_commit_callbacks, onec_account,
                             _onec_upload(onec_account))
    assert (first.status, first.debits, first.duplicates, warnings) == ("loaded", 2, 0, [])
    assert _live(onec_account) == 2

    second, warnings = _start(django_capture_on_commit_callbacks, onec_account,
                              _onec_upload(onec_account))
    assert (second.status, second.debits, second.duplicates) == ("loaded", 2, 2)
    assert second.lines.count() == 0 and _live(onec_account) == 2
    assert len(warnings) == 1 and first.number in warnings[0]


@pytest.mark.django_db(transaction=True)
def test_parallel_upload_no_duplicates(monkeypatch):
    """Review Focus 2: две загрузки одного файла разбираются одновременно
    (оба разбора закончены до первой вставки — барьер): строк в базе 2,
    вторая загрузка насчитала 2 дубля, ни одна не упала. Каждый поток — в
    своём соединении; таблицы модуля в тестовой базе есть и в ``public``."""
    account = _account("onec")
    content = common.onec_bytes(account.iban, _docs(account.iban), period=_onec_period())
    ids = [BankImport.objects.create(
        number=f"ВП-2026-{n:04d}", account=account, format="onec", period_from=PERIOD[0],
        period_to=PERIOD[1], filename="kl_to_1c.txt", author_id=FD, source=content).pk
        for n in (1, 2)]

    barrier = threading.Barrier(2)
    real_parse = imports._parse

    def parse_then_wait(imp):
        parsed = real_parse(imp)
        barrier.wait(timeout=10)
        return parsed

    monkeypatch.setattr(imports, "_parse", parse_then_wait)
    crashes: list[str] = []
    lock = threading.Lock()

    def worker(import_id):
        try:
            imports.run_import(import_id)
        except Exception as exc:  # noqa: BLE001 — любой исход, кроме штатного, — провал
            with lock:
                crashes.append(repr(exc))
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(pk,)) for pk in ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert crashes == []
    rows = list(BankImport.objects.filter(pk__in=ids).order_by("number"))
    assert [row.status for row in rows] == ["loaded", "loaded"], [row.failure for row in rows]
    assert sorted(row.duplicates for row in rows) == [0, 2]
    assert BankStatementLine.objects.filter(cancelled_at__isnull=True).count() == 2


@pytest.mark.django_db
def test_failed_import_cancels_its_lines_and_frees_the_keys(
        slug, onec_account, django_capture_on_commit_callbacks, monkeypatch):
    """Разбор упал после записи строк — «Ошибка загрузки» с причиной, строки
    отменены; та же выписка потом грузится без «дублей»."""
    real_insert = imports._insert

    def insert_then_crash(imp, lines):
        real_insert(imp, lines)
        raise RuntimeError("сбой после вставки")

    monkeypatch.setattr(imports, "_insert", insert_then_crash)
    failed, _ = _start(django_capture_on_commit_callbacks, onec_account,
                       _onec_upload(onec_account))
    assert failed.status == BankImportStatus.FAILED and "внутренней ошибки" in failed.failure
    assert failed.lines.count() == 2 and _live(onec_account) == 0
    assert bytes(failed.source) == b"" and "Повторите загрузку" in failed.failure
    # Строки загрузки — по умолчанию только действующие, как счётчики карточки.
    assert imports.lines(failed)["total"] == 0
    assert imports.lines(failed, include_cancelled=True)["total"] == 2

    monkeypatch.setattr(imports, "_insert", real_insert)
    retry, warnings = _start(django_capture_on_commit_callbacks, onec_account,
                             _onec_upload(onec_account))
    assert (retry.status, retry.duplicates, _live(onec_account)) == ("loaded", 0, 2)
    assert warnings == []  # неудавшаяся загрузка пересечением не считается


@pytest.mark.django_db
def test_redelivered_task_does_not_parse_twice(slug, onec_account,
                                               django_capture_on_commit_callbacks):
    imp, _ = _start(django_capture_on_commit_callbacks, onec_account,
                    _onec_upload(onec_account))
    before = (imp.status, imp.duplicates, imp.finished_at)
    imports.run_import(imp.pk)  # повторная доставка той же задачи
    imp.refresh_from_db()
    assert (imp.status, imp.duplicates, imp.finished_at) == before
    assert _live(onec_account) == 2


# ── только списания своего счёта; Excel ────────────────────────────────

@pytest.mark.django_db
def test_xlsx_only_own_debits_numeric_amount_exact(slug, xlsx_account,
                                                    django_capture_on_commit_callbacks):
    """Review Focus 4 и 3: поступление и чужой плательщик не загружаются
    («списаний 1 из 3»), число ячейки 1250000.1 — ``Decimal("1250000.10")``."""
    day = _ru(_ago(5))
    upload = _xlsx_upload(xlsx_account, [
        ["1", day, -1250000.1, "Оплата металла", "050140000656", xlsx_account.iban],
        ["2", day, 300000, "Поступление", "", xlsx_account.iban],
        ["3", day, -10, "Чужой счёт", "", common.iban(8)],
    ])
    imp, _ = _start(django_capture_on_commit_callbacks, xlsx_account, upload,
                    period_from=PERIOD[0].isoformat(), period_to=PERIOD[1].isoformat())
    assert (imp.status, imp.rows_total, imp.debits, imp.errors) == ("loaded", 3, 1, [])
    line = imp.lines.get()
    assert line.amount == Decimal("1250000.10") and line.recipient_bin == "050140000656"
    assert line.doc_date == _ago(5) and line.purpose == "Оплата металла"


# ── отказы при загрузке — до сохранения чего-либо ──────────────────────

def _nothing_saved() -> None:
    assert not BankImport.objects.exists()
    assert not FileObject.objects.filter(owner_type=file_owner.OWNER).exists()


@pytest.mark.django_db
def test_file_without_1c_header_is_422_e_imp_01_verbatim(slug, onec_account):
    upload = common.onec_file(onec_account.iban, _docs(onec_account.iban), header=False)
    response = Client().post(BASE, {"account_id": str(onec_account.pk), "file": upload},
                             **_headers(slug, FD))
    assert response.status_code == 422
    body = response.json()
    assert (body["code"], body["detail"]) == ("E-IMP-01", E_IMP_01)
    with use_company(slug):
        _nothing_saved()


@pytest.mark.django_db
def test_upload_rejections(slug, onec_account, xlsx_account):
    doc = common.onec_doc("1", _ru(_ago(3)), "1.00", onec_account.iban)
    too_many = common.onec_file(onec_account.iban, [doc] * (MAX_ROWS + 1),
                                period=_onec_period())
    assert _error(imports.start_import, account_id=onec_account.pk, upload=too_many,
                  actor_id=FD).code == "E-IMP-03"

    # Файл Excel на счёт с шаблоном 1С — не тот формат.
    xlsx = _xlsx_upload(onec_account, [["1", _ru(_ago(3)), -1, "x", "", ""]])
    assert _error(imports.start_import, account_id=onec_account.pk, upload=xlsx,
                  actor_id=FD).code == "E-IMP-01"

    # Нет обязательной колонки шаблона.
    no_purpose = common.xlsx_file([[common.HEADERS["date"], common.HEADERS["doc_number"],
                                    common.HEADERS["amount"]]])
    err = _error(imports.start_import, account_id=xlsx_account.pk, upload=no_purpose,
                 period_from=PERIOD[0], period_to=PERIOD[1], actor_id=FD)
    assert err.code == "E-IMP-02" and common.HEADERS["purpose"] in err.message

    # Архивный счёт и счёт, которого нет.
    bank_settings.update_account(onec_account.pk, {"is_active": False}, expected_version=None,
                                 actor_id=ADM)
    for account_id in (onec_account.pk, "не-uuid"):
        err = _error(imports.start_import, account_id=account_id,
                     upload=_onec_upload(onec_account), actor_id=FD)
        assert err.code == "E-VAL-01" and err.fields[0]["field"] == "account_id"

    assert _error(imports.start_import, account_id=xlsx_account.pk, upload=None,
                  actor_id=FD).fields[0]["field"] == "file"
    _nothing_saved()


@pytest.mark.django_db
def test_file_over_twenty_megabytes_is_413(slug, onec_account):
    upload = common.onec_file(onec_account.iban, _docs(onec_account.iban))
    upload.size = imports.MAX_MB * 1024 * 1024 + 1
    err = _error(imports.start_import, account_id=onec_account.pk, upload=upload, actor_id=FD)
    assert (err.code, err.status) == ("E-FIL-02", 413)
    assert "до 20 МБ" in err.message


@pytest.mark.django_db
def test_period_rules(slug, xlsx_account):
    """ТЗ §11.2: период — из файла, если есть, иначе из формы; «по» ≥ «с»,
    не позже сегодня. У Excel периода в файле нет."""
    def upload():
        return _xlsx_upload(xlsx_account, [["1", _ru(_ago(3)), -1, "x", "", ""]])

    err = _error(imports.start_import, account_id=xlsx_account.pk, upload=upload(), actor_id=FD)
    assert err.code == "E-VAL-01"
    assert {f["field"] for f in err.fields} == {"period_from", "period_to"}
    err = _error(imports.start_import, account_id=xlsx_account.pk, upload=upload(),
                 period_from=_ago(1).isoformat(), period_to=_ago(5).isoformat(), actor_id=FD)
    assert err.fields[0]["field"] == "period_to"
    err = _error(imports.start_import, account_id=xlsx_account.pk, upload=upload(),
                 period_from=_ago(1).isoformat(),
                 period_to=(timezone.localdate() + timedelta(days=1)).isoformat(), actor_id=FD)
    assert err.fields[0]["field"] == "period_to" and "сегодня" in err.message
    err = _error(imports.start_import, account_id=xlsx_account.pk, upload=upload(),
                 period_from="01.09.2026", period_to=_ago(1).isoformat(), actor_id=FD)
    assert err.fields[0]["field"] == "period_from"


# ── реестр L-07 ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_registry_filters_and_xlsx_export(slug, onec_account, xlsx_account,
                                           django_capture_on_commit_callbacks):
    loaded, _ = _start(django_capture_on_commit_callbacks, onec_account,
                       _onec_upload(onec_account))
    old = _xlsx_upload(xlsx_account, [["1", _ru(_ago(60)), -5, "x", "", ""]])
    earlier, _ = _start(django_capture_on_commit_callbacks, xlsx_account, old,
                        period_from=_ago(70).isoformat(), period_to=_ago(50).isoformat())
    client = Client()
    headers = _headers(slug, BUH)

    page = client.get(BASE, **headers).json()
    assert (page["total"], page["page"], page["page_size"]) == (2, 1, 50)
    assert [item["number"] for item in page["items"]] == [earlier.number, loaded.number]
    item = page["items"][1]
    assert item["bank_name"] == "Halyk Bank" and item["account"]["iban"] == onec_account.iban
    assert (item["rows_total"], item["debits"], item["unmatched"]) == (3, 2, 2)
    assert item["author_id"] == FD and item["status"] == "loaded"

    by_account = client.get(BASE, {"account_id": str(xlsx_account.pk)}, **headers).json()
    assert [i["number"] for i in by_account["items"]] == [earlier.number]
    by_period = client.get(BASE, {"period_from": _ago(30).isoformat()}, **headers).json()
    assert [i["number"] for i in by_period["items"]] == [loaded.number]
    assert client.get(BASE, {"status": "failed"}, **headers).json()["total"] == 0
    assert client.get(BASE, {"status": "bogus"}, **headers).status_code == 422
    assert client.get(BASE, {"period_from": "вчера"}, **headers).status_code == 422

    xlsx = client.get(BASE, {"format": "xlsx", "account_id": str(onec_account.pk)}, **headers)
    assert xlsx.status_code == 200
    assert xlsx["Content-Type"].startswith("application/vnd.openxmlformats")
    sheet = openpyxl.load_workbook(io.BytesIO(xlsx.content)).active
    rows = list(sheet.iter_rows(values_only=True))
    assert rows[0][0] == "Номер" and len(rows) == 2 and rows[1][0] == loaded.number


# ── счёт с загрузками и файл выписки ───────────────────────────────────

@pytest.mark.django_db
def test_iban_of_an_account_with_imports_does_not_change(slug, onec_account,
                                                         django_capture_on_commit_callbacks):
    """Ключ дубля строки — счёт организации; IBAN счёта с загрузками не
    меняется (409 E-STATE-01), без загрузок — меняется."""
    fresh = _account("xlsx", 3)
    changed = bank_settings.update_account(fresh.pk, {"iban": common.iban(4)},
                                           expected_version=None, actor_id=ADM)
    assert changed.iban == common.iban(4)

    _start(django_capture_on_commit_callbacks, onec_account, _onec_upload(onec_account))
    err = _error(bank_settings.update_account, onec_account.pk, {"iban": common.iban(5)},
                 expected_version=None, actor_id=ADM)
    assert (err.code, err.status) == ("E-STATE-01", 409)
    # Остальные поля счёта править можно.
    renamed = bank_settings.update_account(onec_account.pk, {"bank_name": "Halyk"},
                                           expected_version=None, actor_id=ADM)
    assert renamed.bank_name == "Halyk"


@pytest.mark.django_db
def test_statement_file_is_visible_to_readers_and_never_modifiable(
        slug, onec_account, django_capture_on_commit_callbacks):
    imp, _ = _start(django_capture_on_commit_callbacks, onec_account,
                    _onec_upload(onec_account))

    def tok(user_id):
        return decode_token(token(user_id=user_id, sub=str(user_id), company=slug))

    assert file_owner._can_view(imp.pk, tok(BUH)) is True
    assert file_owner._can_view(imp.pk, tok(TD)) is False
    with pytest.raises(files_interface.FilesLocked):
        file_owner._can_modify(imp.pk, tok(FD))
    with pytest.raises(files_interface.FilesForbidden):
        file_owner._can_modify(imp.pk, tok(BUH))


@pytest.mark.django_db
def test_dedup_hash_is_by_account_not_by_iban():
    """BR-075: ключ — «счёт организации + дата + № + сумма + БИН»; номер —
    без регистра и лишних пробелов, сумма — с двумя знаками."""
    key = dict(doc_date=date(2026, 9, 5), doc_number=" 101 ", amount=Decimal("1250000"),
               recipient_bin="050140000656")
    first = imports.dedup_hash("a", **key)
    assert first == imports.dedup_hash("a", **{**key, "doc_number": "101",
                                               "amount": Decimal("1250000.00")})
    assert first != imports.dedup_hash("b", **key)
    assert first != imports.dedup_hash("a", **{**key, "recipient_bin": "990340000123"})
    assert len(first) == 64


# ── потерянные разборы, очередь, кодировка, период из файла ─────────────

def _processing(account, number: str, *, created_ago: int, started_ago: int | None = None,
                lines: int = 0) -> BankImport:
    """Загрузка «Обрабатывается», созданная (и начатая) столько-то минут
    назад, с ``lines`` уже записанными строками."""
    content = common.onec_bytes(account.iban, _docs(account.iban), period=_onec_period())
    imp = BankImport.objects.create(
        number=number, account=account, format="onec", period_from=PERIOD[0],
        period_to=PERIOD[1], filename="kl_to_1c.txt", author_id=FD, source=content)
    now = timezone.now()
    BankImport.objects.filter(pk=imp.pk).update(
        created_at=now - timedelta(minutes=created_ago),
        started_at=None if started_ago is None else now - timedelta(minutes=started_ago))
    for n in range(lines):
        doc_number = f"{number}/{n}"
        BankStatementLine.objects.create(
            bank_import=imp, account=account, row_no=n + 1, doc_date=_ago(3),
            doc_number=doc_number, amount=Decimal("1.00"),
            dedup_hash=imports.dedup_hash(account.pk, doc_date=_ago(3), doc_number=doc_number,
                                          amount=Decimal("1.00"), recipient_bin=""))
    imp.refresh_from_db()
    return imp


@pytest.mark.django_db
def test_reaper_fails_stale_imports_and_cancels_their_lines(slug, onec_account):
    """Разбор, убитый пределом времени или перезапуском воркера, до ``_fail``
    не доходит: уборка переводит в «Ошибка загрузки» загрузки, чей разбор
    начат (или, не начатый, создан) больше 15 минут назад, — строки
    отменены, копия файла стёрта. Свежие не трогаются."""
    started_long_ago = _processing(onec_account, "ВП-2026-0101", created_ago=21,
                                   started_ago=20, lines=2)
    never_started = _processing(onec_account, "ВП-2026-0102", created_ago=16)
    fresh = _processing(onec_account, "ВП-2026-0103", created_ago=3, started_ago=2, lines=1)
    queued = _processing(onec_account, "ВП-2026-0104", created_ago=5)

    assert tasks_bank.reap_stale_imports.delay(company_slug=slug).get() == {"failed": 2}

    for imp in (started_long_ago, never_started):
        imp.refresh_from_db()
        assert imp.status == BankImportStatus.FAILED and imp.failure == imports.STALE_REASON
        assert imp.failure.startswith("Загрузка прервана — повторите загрузку")
        assert bytes(imp.source) == b"" and imp.finished_at is not None
        assert not imp.lines.filter(cancelled_at__isnull=True).exists()
    assert started_long_ago.lines.count() == 2  # отменены, а не удалены
    for imp in (fresh, queued):
        imp.refresh_from_db()
        assert imp.status == BankImportStatus.PROCESSING and bytes(imp.source) != b""
    assert fresh.lines.filter(cancelled_at__isnull=True).count() == 1

    # Задача, дошедшая до воркера после уборки, ничего не делает.
    imports.run_import(never_started.pk)
    never_started.refresh_from_db()
    assert never_started.status == BankImportStatus.FAILED and never_started.lines.count() == 0
    # Повторная уборка — ничего нового.
    assert imports.reap_stale() == {"failed": 0}


@pytest.mark.django_db
def test_reaper_dispatcher_fans_out_to_companies(slug, onec_account):
    stale = _processing(onec_account, "ВП-2026-0201", created_ago=30, started_ago=30)
    result = tasks_bank.reap_stale_imports_dispatch.delay().get()
    assert slug in result["dispatched"]
    with use_company(slug):
        stale.refresh_from_db()
    assert stale.status == BankImportStatus.FAILED


@pytest.mark.django_db
def test_unreachable_queue_marks_the_import_failed(slug, onec_account,
                                                   django_capture_on_commit_callbacks,
                                                   monkeypatch):
    """Брокер недоступен — загрузка не висит «Обрабатывается»: «Ошибка
    загрузки» с причиной, копия файла стёрта."""
    def broken_delay(**kwargs):
        raise ConnectionError("брокер недоступен")

    monkeypatch.setattr(tasks_bank.run_bank_import, "delay", broken_delay)
    imp, _ = _start(django_capture_on_commit_callbacks, onec_account,
                    _onec_upload(onec_account))
    assert imp.status == BankImportStatus.FAILED
    assert "Очередь фоновых задач недоступна" in imp.failure
    assert "Повторите загрузку" in imp.failure
    assert bytes(imp.source) == b"" and imp.started_at is None


@pytest.mark.django_db
def test_csv_in_wrong_encoding_is_e_imp_01_at_upload(slug):
    """CSV в cp1251 при шаблоне utf-8 — 422 ``E-IMP-01`` ещё в запросе, до
    сохранения файла."""
    account = _account("csv", 6, encoding="utf-8")
    upload = common.csv_file([
        [common.HEADERS["date"], common.HEADERS["doc_number"], common.HEADERS["amount"],
         common.HEADERS["purpose"]],
        [_ru(_ago(3)), "1", "-1,00", "Оплата"],
    ], encoding="cp1251")
    err = _error(imports.start_import, account_id=account.pk, upload=upload,
                 period_from=PERIOD[0], period_to=PERIOD[1], actor_id=FD)
    assert err.code == "E-IMP-01" and "кодировке" in err.message
    _nothing_saved()


@pytest.mark.django_db
def test_iban_change_after_import_is_409_over_http(slug, onec_account,
                                                   django_capture_on_commit_callbacks):
    _start(django_capture_on_commit_callbacks, onec_account, _onec_upload(onec_account))
    onec_account.refresh_from_db()
    response = Client().patch(f"/api/bpp/v1/bank/accounts/{onec_account.pk}",
                              json.dumps({"iban": common.iban(7),
                                          "version": onec_account.version}),
                              **s.auth(slug, ADM))
    assert response.status_code == 409, response.json()
    assert response.json()["code"] == "E-STATE-01"
    with use_company(slug):  # запрос вернул search_path в public
        onec_account.refresh_from_db()
    assert onec_account.iban == common.iban(1)


@pytest.mark.django_db
def test_period_from_the_1c_file_wins_with_a_warning(slug, onec_account,
                                                     django_capture_on_commit_callbacks):
    """ТЗ §11.2: период — из файла, если он есть; другой период из формы не
    теряется молча — ответ предупреждает."""
    imp, warnings = _start(django_capture_on_commit_callbacks, onec_account,
                           _onec_upload(onec_account), period_from=_ago(40).isoformat(),
                           period_to=_ago(30).isoformat())
    assert (imp.period_from, imp.period_to) == PERIOD
    assert len(warnings) == 1 and warnings[0].startswith("Период взят из файла выписки")

    # Форма совпала с файлом — предупреждения о периоде нет (есть только о
    # пересечении с первой загрузкой).
    _, warnings = _start(django_capture_on_commit_callbacks, onec_account,
                         _onec_upload(onec_account), period_from=PERIOD[0].isoformat(),
                         period_to=PERIOD[1].isoformat())
    assert len(warnings) == 1 and imp.number in warnings[0]

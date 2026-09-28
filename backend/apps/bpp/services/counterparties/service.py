"""Справочник «Контрагенты» (ТЗ §18, L-08, D-20, задача A2.3): создание,
правка, блокировка, архив, метка «Проверенный», банковские счета.

Права проверяет вьюха (узлы ``bpp.counterparties`` и
``bpp.counterparties.block``), здесь — правила самих данных. Каждая
правка карточки — под блокировкой строки, со сверкой ``version``
(E-CON-01) и записью изменённых полей в журнал.

Дубль (страна, рег. номер) ловится дважды: заранее — чтобы ответить
ссылкой на существующего, и на вставке — уникальным ключом БД. Второе
нужно для гонки: два одновременных запроса оба проходят предварительную
проверку, и без перехвата ``IntegrityError`` второй получил бы 500 вместо
E-CTR-02 (Review Focus 2).
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.bpp.models.counterparties import (
    Counterparty,
    CounterpartyBankAccount,
    CounterpartyKind,
    CounterpartyStatus,
)
from apps.bpp.services.core import audit
from apps.bpp.services.core.errors import check_version
from apps.refdata import interface as refdata
from htqweb.errors import DomainError

from . import lookup, validation

REASON_MIN = 10
PAGE_SIZES = (25, 50, 100)
DEFAULT_PAGE_SIZE = 50
SORTS = ("name", "short_name", "reg_number", "country_code", "status", "created_at",
         "updated_at")

#: Поля карточки, которые правит форма (статус, блокировка и метка — своими
#: действиями).
EDITABLE_FIELDS = ("name", "short_name", "kind", "country_code", "reg_number",
                   "is_vat_payer", "vat_cert_series", "vat_cert_number", "legal_address",
                   "contact_person", "phone", "email", "ext_1c_ref")
ACCOUNT_FIELDS = ("iban", "bank_name", "bic", "currency", "is_primary", "is_active")


# ── общие куски ─────────────────────────────────────────────────────────

def _lock(counterparty_id) -> Counterparty:
    cp = lookup.get(counterparty_id)  # неверный ключ и чужой — 404
    return Counterparty.objects.select_for_update().get(pk=cp.pk)


def _state_error(cp: Counterparty, action: str) -> DomainError:
    return DomainError(
        "E-STATE-01",
        f"Контрагент {lookup.display_name(cp)} в статусе «{cp.get_status_display()}» — "
        f"{action} сейчас недоступно.",
        status=409)


def _touch(cp: Counterparty, actor_id: int | None, *fields: str) -> None:
    cp.version += 1
    cp.updated_by = actor_id
    cp.save(update_fields=[*fields, "version", "updated_by", "updated_at"])


def _plain(value):
    """Значение поля для журнала — JSON-безопасное."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    return str(value)


def _check_country(code: str) -> str:
    code = (code or "").strip().upper()
    country = refdata.country_brief([code]).get(code) if code else None
    if not country or not country["is_active"]:
        message = (f"Страна «{code}» не найдена в справочнике стран или переведена в архив. "
                   f"Выберите страну из списка или обратитесь к администратору справочников.")
        raise DomainError("E-REF-04", message,
                          fields=[{"field": "country_code", "message": message}])
    return code


def _check_kind(kind: str) -> str:
    if kind not in CounterpartyKind.values:
        message = "Выберите тип контрагента: ЮЛ, ИП, ФЛ или нерезидент."
        raise DomainError("E-VAL-01", message, fields=[{"field": "kind", "message": message}])
    return kind


def _check_email(value: str) -> str:
    value = (value or "").strip()
    if value:
        try:
            validate_email(value)
        except ValidationError:
            message = f"Адрес «{value}» не похож на e-mail. Проверьте написание."
            raise DomainError("E-VAL-01", message,
                              fields=[{"field": "email", "message": message}]) from None
    return value


def _duplicate_error(country_code: str, reg_number: str, existing: Counterparty | None
                     ) -> DomainError:
    who = f": {lookup.display_name(existing)}" if existing else ""
    message = (f"Контрагент с номером {reg_number} ({country_code}) уже есть в "
               f"справочнике{who}. Откройте существующую карточку.")
    return DomainError("E-CTR-02", message, fields=[{
        "field": "reg_number", "message": "Номер уже занят",
        "existing_id": str(existing.pk) if existing else None,
    }])


def _existing(country_code: str, reg_number: str, exclude_id=None) -> Counterparty | None:
    rows = Counterparty.objects.filter(country_code=country_code, reg_number=reg_number)
    if exclude_id is not None:
        rows = rows.exclude(pk=exclude_id)
    return rows.first()


def _raise_if_duplicate(country_code: str, reg_number: str, exclude_id=None) -> None:
    """Предварительная проверка дубля — чтобы ответить ссылкой на
    существующего до вставки."""
    existing = _existing(country_code, reg_number, exclude_id)
    if existing is not None:
        raise _duplicate_error(country_code, reg_number, existing)


def _save_unique(cp: Counterparty, save) -> None:
    """Сохранить под уникальным ключом (страна, номер): проигравший гонку
    получает E-CTR-02, а не 500. Точка сохранения (вложенный ``atomic``)
    откатывает только неудачную вставку — внешняя транзакция живёт дальше
    и может прочитать победителя."""
    try:
        with transaction.atomic():
            save()
    except IntegrityError as exc:
        existing = _existing(cp.country_code, cp.reg_number, exclude_id=cp.pk)
        if existing is None:  # нарушен другой ключ — не наш случай
            raise
        raise _duplicate_error(cp.country_code, cp.reg_number, existing) from exc


def _clean(data: dict, current: Counterparty | None = None) -> dict:
    """Проверенные и нормализованные поля формы. ``current`` — карточка при
    правке.

    Тип, страна и номер проверяются вместе и только когда меняется хоть
    одно из трёх: карточка, перенесённая из ``contracts`` со старым неверным
    номером, должна принимать правку телефона, а не требовать сначала
    исправить БИН."""
    clean = {key: data[key] for key in EDITABLE_FIELDS if key in data}
    for key in ("name", "short_name", "vat_cert_series", "vat_cert_number", "legal_address",
                "contact_person", "phone", "ext_1c_ref"):
        if key in clean:
            clean[key] = (clean[key] or "").strip()
    if "name" in clean and not clean["name"]:
        message = "Укажите наименование контрагента."
        raise DomainError("E-VAL-01", message, fields=[{"field": "name", "message": message}])
    if "email" in clean:
        clean["email"] = _check_email(clean["email"])
    if "is_vat_payer" in clean:
        clean["is_vat_payer"] = bool(clean["is_vat_payer"])
    if "country_code" in clean:
        clean["country_code"] = (clean["country_code"] or "").strip().upper()
    if current is None:
        kind = _check_kind(clean.get("kind"))
        country = _check_country(clean.get("country_code", ""))
        raw_number = clean.get("reg_number", "")
    else:
        kind = clean.get("kind", current.kind)
        country = clean.get("country_code", current.country_code)
        raw_number = clean.get("reg_number", current.reg_number)
        same = (kind == current.kind and country == current.country_code
                and validation.normalize_reg_number(raw_number) == current.reg_number)
        if same:
            for key in ("kind", "country_code", "reg_number"):
                clean.pop(key, None)
            return clean
        _check_kind(kind)
        if country != current.country_code:
            country = _check_country(country)
    clean["kind"], clean["country_code"] = kind, country
    clean["reg_number"] = validation.check_reg_number(kind, country, raw_number)
    return clean


# ── карточка ────────────────────────────────────────────────────────────

def serialize_account(account: CounterpartyBankAccount) -> dict:
    return {"id": str(account.pk), "counterparty_id": str(account.counterparty_id),
            "iban": account.iban, "bank_name": account.bank_name, "bic": account.bic,
            "currency": account.currency, "is_primary": account.is_primary,
            "is_active": account.is_active, "created_at": account.created_at,
            "updated_at": account.updated_at}


def serialize(cp: Counterparty, *, threshold: int | None = None,
              with_accounts: bool = True) -> dict:
    threshold = lookup.verified_threshold() if threshold is None else threshold
    data = {
        "id": str(cp.pk), "name": cp.name, "short_name": cp.short_name, "kind": cp.kind,
        "country_code": cp.country_code, "reg_number": cp.reg_number,
        "is_vat_payer": cp.is_vat_payer, "vat_cert_series": cp.vat_cert_series,
        "vat_cert_number": cp.vat_cert_number, "legal_address": cp.legal_address,
        "contact_person": cp.contact_person, "phone": cp.phone, "email": cp.email,
        "status": cp.status, "block_reason": cp.block_reason, "blocked_at": cp.blocked_at,
        "blocked_by": cp.blocked_by, "successful_documents": cp.successful_documents,
        "verified_override": cp.verified_override,
        "verified_threshold": threshold, "is_verified": lookup.is_verified(cp, threshold),
        "ext_1c_ref": cp.ext_1c_ref, "version": cp.version,
        "created_at": cp.created_at, "created_by": cp.created_by,
        "updated_at": cp.updated_at, "updated_by": cp.updated_by,
    }
    if with_accounts:
        data["bank_accounts"] = [serialize_account(a) for a in cp.bank_accounts.all()]
    return data


def _filtered(*, q: str | None = None, countries=(), statuses=()):
    """Фильтр реестра — общий код страницы экрана (``registry``) и выгрузки
    (``export_rows``/``export_count``), чтобы файл xlsx не мог разойтись со
    списком на экране: правило фильтра живёт ровно в одном месте."""
    rows = Counterparty.objects.all()
    if q:
        text = q.strip()
        number = validation.normalize_reg_number(text)
        cond = Q(name__icontains=text) | Q(short_name__icontains=text)
        if number:
            cond |= Q(reg_number__icontains=number)
        rows = rows.filter(cond)
    countries = [c.strip().upper() for c in countries if c and c.strip()]
    if countries:
        rows = rows.filter(country_code__in=countries)
    statuses = [s for s in statuses if s]
    if statuses:
        rows = rows.filter(status__in=statuses)
    return rows


def _ordered(rows, sort: str | None):
    sort = sort or "name"
    field = sort[1:] if sort.startswith("-") else sort
    order = sort if field in SORTS else "name"
    return rows.order_by(order, "pk")


def registry(*, q: str | None = None, countries=(), statuses=(), page: int = 1,
             page_size: int | None = None, sort: str | None = None) -> dict:
    """Реестр L-08: поиск по наименованию и номеру, фильтры «страна» и
    «статус», пагинация 25/50/100 (по умолчанию 50), серверная сортировка.
    Колонки «договоров» и «счетов» появятся с договором и счётом (этап 3)."""
    rows = _ordered(_filtered(q=q, countries=countries, statuses=statuses), sort)
    page_size = page_size if page_size in PAGE_SIZES else DEFAULT_PAGE_SIZE
    page = max(1, page or 1)
    total = rows.count()
    threshold = lookup.verified_threshold()
    chunk = rows[(page - 1) * page_size: page * page_size]
    return {"items": [serialize(cp, threshold=threshold, with_accounts=False) for cp in chunk],
            "total": total, "page": page, "page_size": page_size}


# ── экспорт в xlsx (ТЗ §19, D-32) ──────────────────────────────────────

def export_count(*, q: str | None = None, countries=(), statuses=(), sort: str | None = None
                 ) -> int:
    """``count`` для ``export.respond`` — ровно та же выборка, что уйдёт в
    файл (``sort`` в счёт не входит, оставлен для единой сигнатуры с
    ``export_rows``: обе зовутся одними и теми же ``**filters``)."""
    return _filtered(q=q, countries=countries, statuses=statuses).count()


def export_rows(*, q: str | None = None, countries=(), statuses=(), sort: str | None = None):
    """Строки выгрузки — полная (без пагинации) выборка реестра. Это и есть
    функция пересборки ``rebuild`` для фоновой ветки ``export.respond``:
    путь до неё передаёт ручка реестра, а параметры — ровно фильтры формы.

    Видимость контрагентов одна на всех держателей ``bpp.counterparties:view``
    — реестр никого не сужает по пользователю (в отличие, например, от
    «Моих заявок»), поэтому ``user_id`` заказчика в фильтрах не нужен."""
    rows = _ordered(_filtered(q=q, countries=countries, statuses=statuses), sort)
    threshold = lookup.verified_threshold()
    for cp in rows.iterator():
        yield {
            "name": cp.name,
            "reg_number": cp.reg_number,
            "country_code": cp.country_code,
            "status": cp.get_status_display(),
            "is_verified": "Да" if lookup.is_verified(cp, threshold) else "Нет",
            "successful_documents": cp.successful_documents,
            "created_at": cp.created_at,
        }


# ── создание и правка ──────────────────────────────────────────────────

@transaction.atomic
def create(data: dict, *, actor_id: int | None) -> Counterparty:
    clean = _clean(data)
    _raise_if_duplicate(clean["country_code"], clean["reg_number"])
    cp = Counterparty(**clean, created_by=actor_id, updated_by=actor_id)
    _save_unique(cp, lambda: cp.save(force_insert=True))
    audit.record(cp, "created", actor_id=actor_id,
                 changes={key: _plain(getattr(cp, key)) for key in EDITABLE_FIELDS})
    return cp


@transaction.atomic
def update(counterparty_id, data: dict, *, expected_version: int | None,
           actor_id: int | None) -> Counterparty:
    cp = _lock(counterparty_id)
    check_version(cp, expected_version)
    if cp.status == CounterpartyStatus.ARCHIVED:
        raise _state_error(cp, "правка")
    clean = _clean(data, current=cp)
    changed = {key: [_plain(getattr(cp, key)), _plain(value)] for key, value in clean.items()
               if getattr(cp, key) != value}
    if not changed:
        return cp
    if "country_code" in changed or "reg_number" in changed:
        _raise_if_duplicate(clean["country_code"], clean["reg_number"], exclude_id=cp.pk)
    for key in changed:
        setattr(cp, key, clean[key])
    _save_unique(cp, lambda: _touch(cp, actor_id, *changed))
    audit.record(cp, "updated", actor_id=actor_id, changes=changed)
    return cp


# ── статус и метка ──────────────────────────────────────────────────────

@transaction.atomic
def block(counterparty_id, *, reason: str, expected_version: int | None,
          actor_id: int | None) -> Counterparty:
    reason = (reason or "").strip()
    if len(reason) < REASON_MIN:
        message = f"Причина блокировки — не короче {REASON_MIN} символов."
        raise DomainError("BR-060", message, fields=[{"field": "reason", "message": message}])
    cp = _lock(counterparty_id)
    check_version(cp, expected_version)
    if cp.status != CounterpartyStatus.ACTIVE:
        raise _state_error(cp, "блокировка")
    cp.status = CounterpartyStatus.BLOCKED
    cp.block_reason, cp.blocked_at, cp.blocked_by = reason, timezone.now(), actor_id
    _touch(cp, actor_id, "status", "block_reason", "blocked_at", "blocked_by")
    audit.record(cp, "blocked", actor_id=actor_id, comment=reason,
                 changes={"status": [CounterpartyStatus.ACTIVE, cp.status]})
    return cp


@transaction.atomic
def unblock(counterparty_id, *, expected_version: int | None,
            actor_id: int | None) -> Counterparty:
    cp = _lock(counterparty_id)
    check_version(cp, expected_version)
    if cp.status != CounterpartyStatus.BLOCKED:
        raise _state_error(cp, "разблокировка")
    before = {"status": cp.status, "block_reason": cp.block_reason}
    # Причина уходит из карточки, но остаётся в журнале (запись «blocked»).
    cp.status = CounterpartyStatus.ACTIVE
    cp.block_reason, cp.blocked_at, cp.blocked_by = "", None, None
    _touch(cp, actor_id, "status", "block_reason", "blocked_at", "blocked_by")
    audit.record(cp, "unblocked", actor_id=actor_id, changes={
        "status": [before["status"], cp.status],
        "block_reason": [before["block_reason"], ""]})
    return cp


@transaction.atomic
def archive(counterparty_id, *, expected_version: int | None,
            actor_id: int | None) -> Counterparty:
    """В архив — soft delete (ТЗ §18): в новых документах не предлагается,
    в старых остаётся. Из архива карточка не возвращается этой функцией."""
    cp = _lock(counterparty_id)
    check_version(cp, expected_version)
    if cp.status == CounterpartyStatus.ARCHIVED:
        raise _state_error(cp, "перевод в архив")
    before = cp.status
    cp.status = CounterpartyStatus.ARCHIVED
    _touch(cp, actor_id, "status")
    audit.record(cp, "archived", actor_id=actor_id, changes={"status": [before, cp.status]})
    return cp


@transaction.atomic
def set_verified(counterparty_id, value: bool | None, *, expected_version: int | None,
                 actor_id: int | None) -> Counterparty:
    """Ручная метка ФД (D-20): ``True``/``False`` — поверх порога, ``None`` —
    вернуть решение порогу."""
    cp = _lock(counterparty_id)
    check_version(cp, expected_version)
    before = cp.verified_override
    if before is value:
        return cp
    cp.verified_override = value
    _touch(cp, actor_id, "verified_override")
    audit.record(cp, "verified_set", actor_id=actor_id,
                 changes={"verified_override": [before, value]})
    return cp


# ── банковские счета ────────────────────────────────────────────────────

def list_accounts(counterparty_id) -> list[dict]:
    cp = lookup.get(counterparty_id)
    return [serialize_account(a) for a in cp.bank_accounts.all()]


def _account_error(field: str, message: str) -> DomainError:
    return DomainError("E-CTR-04", message, fields=[{"field": field, "message": message}])


def _clean_account(data: dict) -> dict:
    clean = {key: data[key] for key in ACCOUNT_FIELDS if key in data and data[key] is not None}
    clean.update(validation.check_bank_details(iban=clean.get("iban"), bic=clean.get("bic")))
    if "bank_name" in clean:
        clean["bank_name"] = (clean["bank_name"] or "").strip()
    if "currency" in clean:
        currency = (clean["currency"] or "").strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise _account_error("currency", "Валюта счёта — трёхбуквенный код ISO 4217, "
                                             "например KZT.")
        clean["currency"] = currency
    return clean


def _iban_taken(account: CounterpartyBankAccount) -> DomainError:
    other = (CounterpartyBankAccount.objects.select_related("counterparty")
             .filter(iban=account.iban).exclude(pk=account.pk).first())
    owner = f" у контрагента {lookup.display_name(other.counterparty)}" if other else ""
    return _account_error("iban", f"Счёт {account.iban} уже заведён{owner}. "
                                  f"Один IBAN — один счёт в справочнике.")


def _save_account(account: CounterpartyBankAccount) -> None:
    if (CounterpartyBankAccount.objects.filter(iban=account.iban)
            .exclude(pk=account.pk).exists()):
        raise _iban_taken(account)
    if account.is_primary:
        # Основной — один: остальные счета контрагента теряют признак.
        (CounterpartyBankAccount.objects
         .filter(counterparty_id=account.counterparty_id, is_primary=True)
         .exclude(pk=account.pk).update(is_primary=False))
    try:
        with transaction.atomic():
            account.save()
    except IntegrityError as exc:  # гонка за тот же IBAN
        raise _iban_taken(account) from exc


@transaction.atomic
def add_account(counterparty_id, data: dict, *, actor_id: int | None) -> dict:
    cp = _lock(counterparty_id)  # счета одного контрагента меняются по очереди
    if cp.status == CounterpartyStatus.ARCHIVED:
        raise _state_error(cp, "добавление счёта")
    clean = _clean_account(data)
    for key in ("iban", "bic"):
        if key not in clean:
            raise _account_error(key, f"Укажите {'IBAN' if key == 'iban' else 'БИК'} счёта.")
    clean.pop("is_active", None)  # новый счёт всегда действующий
    account = CounterpartyBankAccount(counterparty=cp, created_by=actor_id,
                                      updated_by=actor_id, **clean)
    if not cp.bank_accounts.filter(is_primary=True).exists():
        account.is_primary = True  # первый счёт — основной
    _save_account(account)
    audit.record(cp, "account_added", actor_id=actor_id,
                 changes={key: _plain(getattr(account, key)) for key in ACCOUNT_FIELDS})
    return serialize_account(account)


@transaction.atomic
def update_account(account_id, data: dict, *, actor_id: int | None) -> dict:
    key = lookup.as_uuid(account_id)
    account = CounterpartyBankAccount.objects.filter(pk=key).first() if key else None
    if account is None:
        raise DomainError("E-NOT-FOUND", "Банковский счёт не найден.", status=404)
    cp = _lock(account.counterparty_id)
    account = CounterpartyBankAccount.objects.select_for_update().get(pk=account.pk)
    if cp.status == CounterpartyStatus.ARCHIVED:
        raise _state_error(cp, "правка счёта")
    clean = _clean_account(data)
    if clean.get("is_active") is False:
        clean["is_primary"] = False  # архивный счёт основным не бывает
    changed = {k: [_plain(getattr(account, k)), _plain(v)] for k, v in clean.items()
               if getattr(account, k) != v}
    if not changed:
        return serialize_account(account)
    for k in changed:
        setattr(account, k, clean[k])
    account.updated_by = actor_id
    _save_account(account)
    audit.record(cp, "account_updated", actor_id=actor_id,
                 changes={"account_id": str(account.pk), **changed})
    return serialize_account(account)

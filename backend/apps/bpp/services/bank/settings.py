"""Справочник АДМ «Банковские счета организации и шаблоны выписок» (ТЗ §18,
§11.1, задача A3.1).

Удаления нет — архив ``is_active=False`` (ТЗ §18: «Да / да / архив»); из
архива запись возвращается той же правкой. Каждая правка сверяет
``version`` (E-CON-01) и пишется в журнал модуля (ТЗ §25.2).

IBAN и БИК проверяет та же функция, что у счетов контрагентов
(``services/counterparties/validation.check_bank_details``: KZ + 18 знаков,
mod 97; БИК — 8 или 11 знаков; отказ — её код ``E-CTR-04``). IBAN уникален
вместе с архивными счетами: дубль — ``E-BNK-01`` со ссылкой на
существующий. Дубль ловится дважды — заранее (чтобы ответить ссылкой) и на
вставке уникальным ключом БД: два одновременных запроса оба проходят
предварительную проверку, и без перехвата ``IntegrityError`` второй получил
бы 500.

Шаблон, по которому разбирается выписка действующего счёта, в архив не
уходит (``E-STATE-01``): иначе загрузка этого счёта осталась бы без
правил разбора. Счёт привязывается только к действующему шаблону.
"""

from __future__ import annotations

import codecs
import uuid

from django.db import IntegrityError, transaction
from django.db.models import Count, Q

from apps.bpp.models.bank import AmountMode, OrgBankAccount, StatementFormat, StatementTemplate
from apps.bpp.services.core import audit
from apps.bpp.services.core.errors import check_version
from apps.bpp.services.counterparties import validation
from htqweb.errors import DomainError

from . import templates

__all__ = [
    "ACCOUNT_FIELDS",
    "TEMPLATE_FIELDS",
    "create_account",
    "create_template",
    "get_account",
    "get_template",
    "list_accounts",
    "list_templates",
    "serialize_account",
    "serialize_template",
    "update_account",
    "update_template",
]

TEMPLATE_FIELDS = ("name", "format", "encoding", "delimiter", "date_format", "columns",
                   "amount_mode", "is_active")
ACCOUNT_FIELDS = ("iban", "bank_name", "bic", "currency", "template_id", "is_active")

#: Кодировка по умолчанию: выгрузки банк-клиентов 1С и CSV — cp1251, xlsx
#: хранит текст в UTF-8 сам.
DEFAULT_ENCODING = {StatementFormat.ONEC: "cp1251", StatementFormat.CSV: "cp1251",
                    StatementFormat.XLSX: "utf-8"}
_DELIMITERS = (";", ",", "\t", "|")
_HEADER_MAX = 255


# ── общие куски ─────────────────────────────────────────────────────────

def _invalid(field: str, message: str) -> DomainError:
    return DomainError("E-VAL-01", message, fields=[{"field": field, "message": message}])


def _plain(value):
    """Значение поля для журнала — JSON-безопасное."""
    if value is None or isinstance(value, (bool, int, str, dict, list)):
        return value
    return str(value)


def _as_uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _not_found(what: str) -> DomainError:
    return DomainError("E-NOT-FOUND", f"{what} не найден.", status=404)


def _touch(obj, actor_id: int | None, fields) -> None:
    obj.version += 1
    obj.updated_by = actor_id
    obj.save(update_fields=[*fields, "version", "updated_by", "updated_at"])


def _audit_action(changed: dict) -> str:
    if "is_active" in changed:
        return "archived" if changed["is_active"][1] is False else "restored"
    return "updated"


# ── шаблоны ────────────────────────────────────────────────────────────

def serialize_template(tpl: StatementTemplate, *, active_accounts: int | None = None) -> dict:
    if active_accounts is None:
        active_accounts = tpl.accounts.filter(is_active=True).count()
    return {
        "id": str(tpl.pk), "name": tpl.name, "format": tpl.format,
        "encoding": tpl.encoding, "delimiter": tpl.delimiter,
        "date_format": tpl.date_format, "columns": tpl.columns,
        "amount_mode": tpl.amount_mode, "is_active": tpl.is_active,
        "active_accounts": active_accounts, "version": tpl.version,
        "created_at": tpl.created_at, "created_by": tpl.created_by,
        "updated_at": tpl.updated_at, "updated_by": tpl.updated_by,
    }


def list_templates(*, active: bool = False) -> list[dict]:
    rows = StatementTemplate.objects.annotate(
        n_active=Count("accounts", filter=Q(accounts__is_active=True)))
    if active:
        rows = rows.filter(is_active=True)
    return [serialize_template(t, active_accounts=t.n_active)
            for t in rows.order_by("name", "created_at")]


def get_template(template_id) -> StatementTemplate:
    key = _as_uuid(template_id)
    tpl = StatementTemplate.objects.filter(pk=key).first() if key else None
    if tpl is None:
        raise _not_found("Шаблон выписки")
    return tpl


def _check_columns(columns, fmt: str, amount_mode: str) -> dict:
    """Колонки шаблона: известные поля, непустые и неповторяющиеся
    заголовки, все обязательные поля (кроме 1С — её поля задаёт стандарт)."""
    if not isinstance(columns, dict):
        raise _invalid("columns", "Колонки шаблона — пары «поле выписки → заголовок колонки».")
    clean: dict[str, str] = {}
    seen: dict[str, str] = {}
    for field, header in columns.items():
        if field not in templates.FIELDS:
            known = ", ".join(templates.FIELDS)
            raise _invalid("columns", f"Поле «{field}» шаблону неизвестно. Допустимые поля: "
                                      f"{known}.")
        label = templates.FIELDS[field]
        text = str(header or "").strip()
        if not text or len(text) > _HEADER_MAX:
            raise _invalid("columns", f"Укажите заголовок колонки для поля «{label}» "
                                      f"(до {_HEADER_MAX} символов).")
        key = templates.normalize_header(text)
        if key in seen:
            raise _invalid("columns", f"Заголовок «{text}» указан и для поля «{label}», и для "
                                      f"поля «{templates.FIELDS[seen[key]]}». У каждого поля "
                                      f"— своя колонка.")
        seen[key] = field
        clean[field] = text
    if fmt != StatementFormat.ONEC:
        missing = [templates.FIELDS[f] for f in templates.required_fields(amount_mode)
                   if f not in clean]
        if missing:
            names = ", ".join(f"«{name}»" for name in missing)
            raise _invalid("columns", f"В шаблоне нет обязательных колонок: {names}. Дата, "
                                      f"номер документа, сумма (или дебет и кредит) и "
                                      f"назначение платежа нужны для разбора выписки.")
    return clean


def _clean_template(data: dict, current: StatementTemplate | None = None) -> dict:
    """Проверенные поля шаблона. Проверяется итоговое состояние (текущее +
    присланное): правка одного режима суммы не должна пропустить шаблон без
    нужных ему колонок."""
    sent = {key: data[key] for key in TEMPLATE_FIELDS if key in data and data[key] is not None}
    state = ({key: getattr(current, key) for key in TEMPLATE_FIELDS} if current else
             {"delimiter": ";", "date_format": "ДД.ММ.ГГГГ", "columns": {},
              "amount_mode": AmountMode.SIGNED, "is_active": True})
    state.update(sent)

    name = str(state.get("name") or "").strip()
    if not name or len(name) > 255:
        raise _invalid("name", "Укажите название шаблона (до 255 символов).")
    fmt = state.get("format")
    if fmt not in StatementFormat.values:
        raise _invalid("format", "Формат выписки — 1С, Excel или CSV.")
    if state.get("amount_mode") not in AmountMode.values:
        raise _invalid("amount_mode", "Сумма — одной колонкой со знаком или колонками "
                                      "«Дебет» и «Кредит».")
    encoding = str(state.get("encoding") or "").strip() or DEFAULT_ENCODING[fmt]
    # Кодек должен быть текстовым: rot13, base64, hex и им подобные Python
    # находит, но ``bytes.decode`` с ними падает — шаблон сохранился бы и
    # не прочитал ни одной выписки.
    try:
        is_text = codecs.lookup(encoding)._is_text_encoding
    except (LookupError, ValueError):  # ValueError — NUL в названии
        is_text = False
    if not is_text:
        raise _invalid("encoding", f"Кодировка «{encoding}» неизвестна. Обычно выписки "
                                   f"банк-клиентов — cp1251 или utf-8.")
    delimiter = str(state.get("delimiter") or "")
    if fmt == StatementFormat.CSV and delimiter not in _DELIMITERS:
        raise _invalid("delimiter", "Разделитель колонок CSV — «;», «,», табуляция или «|».")
    date_format = str(state.get("date_format") or "").strip()
    try:
        templates.date_pattern(date_format)
    except ValueError:
        raise _invalid("date_format", "Формат даты — маска с днём, месяцем и годом, например "
                                      "ДД.ММ.ГГГГ или ГГГГ-ММ-ДД.") from None
    clean = {"name": name, "format": fmt, "amount_mode": state["amount_mode"],
             "encoding": encoding, "delimiter": delimiter or ";", "date_format": date_format,
             "columns": _check_columns(state.get("columns") or {}, fmt, state["amount_mode"]),
             "is_active": bool(state.get("is_active", True))}
    if current is None:
        return clean
    return {key: value for key, value in clean.items() if getattr(current, key) != value}


@transaction.atomic
def create_template(data: dict, *, actor_id: int | None) -> StatementTemplate:
    clean = _clean_template(data)
    clean["is_active"] = True  # новый шаблон всегда действующий
    tpl = StatementTemplate.objects.create(**clean, created_by=actor_id, updated_by=actor_id)
    audit.record(tpl, "created", actor_id=actor_id,
                 changes={key: _plain(getattr(tpl, key)) for key in TEMPLATE_FIELDS})
    return tpl


@transaction.atomic
def update_template(template_id, data: dict, *, expected_version: int | None,
                    actor_id: int | None) -> StatementTemplate:
    get_template(template_id)  # неверный ключ — 404
    # Блокировка шаблона — против гонки с заведением счёта на нём (см.
    # ``_lock_template``): счета после неё только читаются, не блокируются.
    tpl = StatementTemplate.objects.select_for_update().get(pk=_as_uuid(template_id))
    check_version(tpl, expected_version)
    clean = _clean_template(data, current=tpl)
    if not clean:
        return tpl
    if clean.get("is_active") is False:
        in_use = list(tpl.accounts.filter(is_active=True).values_list("iban", flat=True))
        if in_use:
            raise DomainError(
                "E-STATE-01",
                f"Шаблон «{tpl.name}» разбирает выписки действующих счетов: "
                f"{', '.join(in_use)}. Переведите счета на другой шаблон или в архив, "
                f"затем архивируйте шаблон.",
                status=409)
    changed = {key: [_plain(getattr(tpl, key)), _plain(value)] for key, value in clean.items()}
    for key, value in clean.items():
        setattr(tpl, key, value)
    _touch(tpl, actor_id, clean)
    audit.record(tpl, _audit_action(changed), actor_id=actor_id, changes=changed)
    return tpl


# ── счета организации ───────────────────────────────────────────────────

def serialize_account(account: OrgBankAccount) -> dict:
    tpl = account.template
    return {
        "id": str(account.pk), "iban": account.iban, "bank_name": account.bank_name,
        "bic": account.bic, "currency": account.currency,
        "template": {"id": str(tpl.pk), "name": tpl.name, "format": tpl.format},
        "is_active": account.is_active, "version": account.version,
        "created_at": account.created_at, "created_by": account.created_by,
        "updated_at": account.updated_at, "updated_by": account.updated_by,
    }


def list_accounts(*, active: bool = False) -> list[dict]:
    """Справочник счетов; ``active=True`` — список для формы загрузки
    выписки (ТЗ §11.2: «Активный счёт»), архивных в нём нет."""
    rows = OrgBankAccount.objects.select_related("template")
    if active:
        rows = rows.filter(is_active=True)
    return [serialize_account(a) for a in rows]


def get_account(account_id) -> OrgBankAccount:
    key = _as_uuid(account_id)
    account = (OrgBankAccount.objects.select_related("template").filter(pk=key).first()
               if key else None)
    if account is None:
        raise _not_found("Банковский счёт организации")
    return account


# Блокировки: сначала шаблон, затем счёт — у всех операций в одном порядке.
# Шаблон блокируется и когда только проверяется, что он действующий: иначе
# заведение счёта и архивирование шаблона разошлись бы — ``update_template``
# не видит ещё не закоммиченный счёт и архивирует шаблон, а счёт вставляется
# на уже архивный. С блокировкой одна операция ждёт другую и видит её итог.

def _lock_template(template_id) -> StatementTemplate | None:
    key = _as_uuid(template_id)
    return StatementTemplate.objects.select_for_update().filter(pk=key).first() if key else None


def _require_active(tpl: StatementTemplate | None) -> StatementTemplate:
    if tpl is None or not tpl.is_active:
        raise _invalid("template_id", "Выберите действующий шаблон выписки: этот не найден "
                                      "или переведён в архив.")
    return tpl


def _active_template(template_id) -> StatementTemplate:
    """Действующий шаблон — под блокировкой строки до конца транзакции."""
    return _require_active(_lock_template(template_id))


def _clean_account(data: dict) -> dict:
    clean = {key: data[key] for key in ACCOUNT_FIELDS if key in data and data[key] is not None}
    clean.update(validation.check_bank_details(iban=clean.get("iban"), bic=clean.get("bic")))
    if "bank_name" in clean:
        clean["bank_name"] = str(clean["bank_name"] or "").strip()
    if "currency" in clean:
        currency = str(clean["currency"] or "").strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise _invalid("currency", "Валюта счёта — трёхбуквенный код ISO 4217, например KZT.")
        clean["currency"] = currency
    if "is_active" in clean:
        clean["is_active"] = bool(clean["is_active"])
    return clean


def _existing_account(iban: str, exclude_id=None) -> OrgBankAccount | None:
    """Предварительная проверка дубля IBAN — чтобы ответить ссылкой на
    существующий счёт до вставки."""
    rows = OrgBankAccount.objects.filter(iban=iban)
    if exclude_id is not None:
        rows = rows.exclude(pk=exclude_id)
    return rows.first()


def _duplicate_error(iban: str, existing: OrgBankAccount) -> DomainError:
    where = f" ({existing.bank_name})" if existing.bank_name else ""
    if existing.is_active:
        tail = "Один IBAN — один счёт в справочнике."
    else:
        tail = "Он в архиве — верните его из архива, а не заводите заново."
    message = f"Счёт организации {iban}{where} уже заведён. {tail}"
    return DomainError("E-BNK-01", message, fields=[{
        "field": "iban", "message": "IBAN уже заведён", "existing_id": str(existing.pk)}])


def _save_unique(account: OrgBankAccount, save) -> None:
    """Сохранить под уникальным IBAN: проигравший гонку получает E-BNK-01, а
    не 500. Точка сохранения откатывает только неудачную вставку — внешняя
    транзакция живёт дальше и читает победителя."""
    try:
        with transaction.atomic():
            save()
    except IntegrityError as exc:
        winner = (OrgBankAccount.objects.filter(iban=account.iban)
                  .exclude(pk=account.pk).first())
        if winner is None:  # нарушен другой ключ — не наш случай
            raise
        raise _duplicate_error(account.iban, winner) from exc


@transaction.atomic
def create_account(data: dict, *, actor_id: int | None) -> OrgBankAccount:
    clean = _clean_account(data)
    for key, label in (("iban", "IBAN"), ("bic", "БИК"), ("template_id", "шаблон выписки")):
        if key not in clean:
            raise _invalid(key, f"Укажите {label} счёта.")
    clean["template"] = _active_template(clean.pop("template_id"))
    clean["is_active"] = True  # новый счёт всегда действующий
    existing = _existing_account(clean["iban"])
    if existing is not None:
        raise _duplicate_error(clean["iban"], existing)
    account = OrgBankAccount(**clean, created_by=actor_id, updated_by=actor_id)
    _save_unique(account, lambda: account.save(force_insert=True))
    audit.record(account, "created", actor_id=actor_id, changes={
        "iban": account.iban, "bank_name": account.bank_name, "bic": account.bic,
        "currency": account.currency, "template_id": str(account.template_id)})
    return account


@transaction.atomic
def update_account(account_id, data: dict, *, expected_version: int | None,
                   actor_id: int | None) -> OrgBankAccount:
    get_account(account_id)  # неверный ключ — 404
    key = _as_uuid(account_id)
    # Шаблоны — до счёта (порядок блокировок выше): новый, если счёт на
    # него переводят, и текущий, если счёт возвращают из архива.
    wanted = (_lock_template(data["template_id"]) if data.get("template_id") is not None
              else None)
    restoring = bool(data.get("is_active"))
    current = (StatementTemplate.objects.select_for_update()
               .filter(pk__in=OrgBankAccount.objects.filter(pk=key).values("template_id"))
               .first() if restoring else None)
    account = (OrgBankAccount.objects.select_for_update(of=("self",)).select_related("template")
               .get(pk=key))
    check_version(account, expected_version)
    clean = _clean_account(data)
    if "template_id" in clean:
        template_id = _as_uuid(clean["template_id"])
        if template_id != account.template_id:
            clean["template"] = _require_active(wanted)
        clean.pop("template_id")
    # Возврат из архива — только на действующем шаблоне.
    if clean.get("is_active") is True and not account.is_active and "template" not in clean:
        if current is None or current.pk != account.template_id:
            # Шаблон счёта сменили между чтением и блокировкой счёта.
            current = _lock_template(account.template_id)
        if current is None or not current.is_active:
            raise _invalid("template_id", "Шаблон этого счёта в архиве — выберите действующий "
                                          "шаблон, чтобы вернуть счёт из архива.")
    changed = {}
    for key, value in clean.items():
        column = "template_id" if key == "template" else key
        before = getattr(account, column)
        after = value.pk if key == "template" else value
        if before != after:
            changed[column] = [_plain(before), _plain(after)]
    if not changed:
        return account
    if "iban" in changed:
        existing = _existing_account(clean["iban"], exclude_id=account.pk)
        if existing is not None:
            raise _duplicate_error(clean["iban"], existing)
    for key, value in clean.items():
        setattr(account, key, value)
    _save_unique(account, lambda: _touch(account, actor_id, [
        "template" if key == "template_id" else key for key in changed]))
    audit.record(account, _audit_action(changed), actor_id=actor_id, changes=changed)
    return account

"""Контрагенты из 1С: идемпотентный upsert одной записи (A7.3, D-38, D-S7-5).

Заготовка без запуска: синхронизации и расписания нет, функция принимает уже
прочитанную запись справочника 1С. Сопоставление:

1. по ``ext_1c_ref`` (GUID записи 1С) — карточка уже связана;
2. иначе по естественному ключу (страна + рег. номер) — найденная карточка
   без кода 1С связывается (её данные не перезаписываются), с ДРУГИМ
   непустым кодом — ``conflict``: решать, какая запись настоящая, человеку;
3. иначе создаётся новая.

Невалидный БИН/ИИН — ``rejected`` (проверка владельца, E-CTR-03); смена
рег. номера уже связанной карточки через 1С запрещена — ``rejected``. Каждая
запись — под своей точкой сохранения: сбой одной не откатывает соседей. Всё
пишется через сервис владельца (валидация, журнал ``bpp_auditlog`` с
пометкой «1С», актор — системный, ``None``).
"""

from __future__ import annotations

from django.db import DatabaseError, IntegrityError, transaction

from apps.bpp.models.counterparties import Counterparty, CounterpartyKind
from htqweb.errors import DomainError
from htqweb.integrations.onec import (
    CONFLICT,
    CREATED,
    REJECTED,
    UNCHANGED,
    UPDATED,
    Outcome,
    is_guid,
)

from . import service, validation

AUDIT_COMMENT = "Источник: 1С"

#: Отображение полей OData-справочника 1С → карточка контрагента.
#: ⚠️ ПРЕДПОЛОЖЕНИЕ: имена реквизитов — типовые, уточнить у администратора 1С
#: (Q-S7-2), когда он назовёт имя набора сущностей и реквизиты.
FIELD_MAP = {
    "ext_1c_ref": "Ref_Key",
    "name": "Description",
    "reg_number": "БИНИИН",
    "country_code": "КодСтраны",      # нет в записи — «KZ»
    "kind": "ВидКонтрагента",
    "legal_address": "АдресЮридический",
    "phone": "Телефон",
    "email": "Email",
}
#: Значения реквизита «ВидКонтрагента» → тип карточки (тоже предположение).
KIND_MAP = {
    "ЮридическоеЛицо": CounterpartyKind.LEGAL,
    "ИндивидуальныйПредприниматель": CounterpartyKind.IP,
    "ФизическоеЛицо": CounterpartyKind.INDIVIDUAL,
    "Нерезидент": CounterpartyKind.NONRESIDENT,
}
DEFAULT_COUNTRY = "KZ"
#: Поля, которые 1С обновляет у уже связанной карточки (пустое значение из
#: 1С нашу карточку не стирает).
UPDATABLE = ("name", "legal_address", "phone", "email")


def _get(record: dict, field: str) -> str:
    return str(record.get(FIELD_MAP[field]) or "").strip()


def _rejected(reason: str) -> Outcome:
    return Outcome(REJECTED, reason)


def _reason(exc: DomainError) -> str:
    return f"{exc.code}: {exc.message}"


def upsert_counterparty(record: dict) -> Outcome:
    """Один контрагент из 1С → ``Outcome``. Зовётся в контексте компании."""
    ref = _get(record, "ext_1c_ref").lower()
    if not is_guid(ref):
        return _rejected("Нет корректного GUID записи 1С (Ref_Key).")
    try:
        with transaction.atomic():
            return _upsert(record, ref)
    except DomainError as exc:
        return _rejected(_reason(exc))
    except IntegrityError:
        return Outcome(CONFLICT, "Запись 1С конкурирует с другой карточкой за уникальный ключ.")
    except DatabaseError:
        return _rejected("Запись 1С не помещается в поля карточки (слишком длинное значение).")


def _upsert(record: dict, ref: str) -> Outcome:
    name = _get(record, "name")
    if not name:
        return _rejected("У записи 1С нет наименования.")
    sent_country = _get(record, "country_code").upper()  # пусто — «не прислали»
    number = validation.normalize_reg_number(_get(record, "reg_number"))

    linked = Counterparty.objects.filter(ext_1c_ref=ref).first()
    if linked is not None:
        return _update_linked(linked, record, sent_country or linked.country_code, number)

    country = sent_country or DEFAULT_COUNTRY
    kind = KIND_MAP.get(_get(record, "kind"))
    if kind is None:
        return _rejected("Не распознан вид контрагента в записи 1С.")
    number = validation.check_reg_number(kind, country, number)  # E-CTR-03 → rejected

    same = Counterparty.objects.filter(country_code=country, reg_number=number).first()
    if same is not None:
        if same.ext_1c_ref and same.ext_1c_ref != ref:
            return Outcome(CONFLICT, "Карточка с этим номером уже связана с другой записью 1С "
                                     f"({same.ext_1c_ref}); данные не тронуты.", str(same.pk))
        service.update(same.pk, {"ext_1c_ref": ref}, expected_version=None, actor_id=None,
                       audit_comment=AUDIT_COMMENT)
        return Outcome(UPDATED, "Карточка связана с записью 1С по рег. номеру.", str(same.pk))

    data = {"name": name, "kind": kind, "country_code": country, "reg_number": number,
            "ext_1c_ref": ref}
    for field in UPDATABLE[1:]:
        if _get(record, field):
            data[field] = _get(record, field)
    created = service.create(data, actor_id=None, audit_comment=AUDIT_COMMENT)
    return Outcome(CREATED, object_id=str(created.pk))


def _update_linked(cp: Counterparty, record: dict, country: str, number: str) -> Outcome:
    if cp.reg_number != number or cp.country_code != country:
        return _rejected("Рег. номер или страна связанной карточки меняются только в самой "
                         "системе, не через 1С.")
    wanted = {field: _get(record, field) for field in UPDATABLE if _get(record, field)}
    diff = {field: value for field, value in wanted.items() if getattr(cp, field) != value}
    if not diff:
        return Outcome(UNCHANGED, object_id=str(cp.pk))
    service.update(cp.pk, diff, expected_version=None, actor_id=None, audit_comment=AUDIT_COMMENT)
    return Outcome(UPDATED, object_id=str(cp.pk))

"""Публичный API аппки approvals (домен «Запросы») для ДРУГИХ аппок.

Единственный способ, которым сосед имеет право обращаться к approvals.
Прямой импорт ``apps.approvals.models`` / ``apps.approvals.services`` из
другой аппки запрещён и ловится ``apps/core/tests/test_app_isolation.py``.

Долгое время модуль был пуст: approvals только потребляла соседей
(users/hr/messenger, затем contracts) и ничего не производила наружу. Первый
потребитель появился вместе со связью «заявка → договор»: ``apps.contracts``
заводит договор или счёт ПО одобренной заявке конструктора и должен
убедиться, что заявка одобрена и одобрена под ту же строку бюджета, а потом
оставить в ленте заявки след «заключён договор №…». Всё это — три функции
ниже. Контракт общий для всех ``interface.py`` в репозитории:

- ``require_service("approvals")`` первой строкой;
- наружу — только простые ``dict``/``list``/``bool``, никогда ORM-объекты.
"""

from __future__ import annotations

from typing import Iterable

from apps.approvals.models import (
    RequestActivity,
    RequestFormTemplateVersion,
    RequestInstance,
    RequestStatus,
)
from apps.approvals.services import budget_line_refs
from apps.approvals.services.form_schema import validate_form_schema
from apps.approvals.services.personal_stats import _item_groups, _number
from apps.core.services import require_service

# Событие ленты, которое оставляет сосед, заведя по заявке свой документ.
# Строковый литерал вынесен, чтобы карточка заявки и тесты не расходились с
# тем, что пишет ``log_linked_document``.
EVENT_DOCUMENT_LINKED = "document_linked"


def _budget_line_ids(instances: Iterable[RequestInstance]) -> dict[int, int | None]:
    """``{instance_id: budget_line_id}`` — первое заполненное значение виджета
    ``budget_line_ref`` в форме каждой заявки.

    Схему хранит версия шаблона, а не заявка, поэтому версии читаются одним
    запросом на весь список — иначе ``list_approved_requests`` делал бы
    запрос на каждую строку.
    """
    rows = list(instances)
    version_ids = {row.template_version_id for row in rows if row.template_version_id}
    schemas: dict[int, dict] = {}
    for version in RequestFormTemplateVersion.objects.filter(pk__in=version_ids):
        try:
            schemas[version.pk] = validate_form_schema(version.schema_json)
        except ValueError:
            # Схема, которую сегодняшний валидатор не принимает, — заявка
            # старого образца; строки бюджета в ней всё равно нет.
            continue

    out: dict[int, int | None] = {}
    for row in rows:
        schema = schemas.get(row.template_version_id)
        line_id = None
        if schema is not None:
            for _path, raw in budget_line_refs.iter_refs(schema, row.form_values_json or {}):
                if isinstance(raw, int) and not isinstance(raw, bool):
                    line_id = raw
                    break
        out[row.pk] = line_id
    return out


def _brief(instance: RequestInstance, budget_line_id: int | None) -> dict:
    return {
        "id": instance.pk,
        "code": instance.code,
        "title": instance.title,
        "status": instance.status,
        "initiator_id": instance.initiator_id,
        "template_id": instance.template_id,
        "template_name": instance.template.name,
        "budget_line_id": budget_line_id,
        "submitted_at": instance.submitted_at,
        "finalized_at": instance.finalized_at,
    }


def get_request_brief(instance_id: int) -> dict | None:
    """Карточка заявки для чужого UI и чужих проверок: код, заголовок,
    статус и строка бюджета, под которую заявка подана. ``None`` — заявки нет.
    """
    require_service("approvals")

    instance = (RequestInstance.objects.select_related("template")
                .filter(pk=instance_id).first())
    if instance is None:
        return None
    return _brief(instance, _budget_line_ids([instance])[instance.pk])


def list_approved_requests(*, with_budget_line: bool = True) -> list[dict]:
    """Одобренные заявки — список для выбора «по какой заявке заводится
    договор». ``with_budget_line=True`` оставляет только те, где указана
    строка бюджета: остальные к договорному контуру отношения не имеют.
    """
    require_service("approvals")

    rows = list(RequestInstance.objects
                .select_related("template")
                .filter(status=RequestStatus.APPROVED)
                .order_by("-finalized_at", "-id"))
    lines = _budget_line_ids(rows)
    briefs = [_brief(row, lines[row.pk]) for row in rows]
    if with_budget_line:
        briefs = [row for row in briefs if row["budget_line_id"] is not None]
    return briefs


def get_request_items(instance_id: int) -> list[dict] | None:
    """Позиции заявки — строки её ПОВТОРЯЕМЫХ групп: ``[{key, name, unit,
    quantity, amount}]``. ``None`` — заявки нет.

    Нужны договору, который заключают по заявке: его позиции — это позиции
    заявки (ТЗ «План закупок»), и количество по договору не может превысить
    заявленное. Колонки опознаются тем же правилом, что и в личной
    статистике (``personal_stats._item_groups``): ЧТО — первое текстовое
    поле строки, СКОЛЬКО — ``summarize_keys`` или первое число, В ЧЁМ —
    первый выпадающий список. Одно правило на оба места, иначе «позиция» в
    сводке и в договоре значила бы разное.

    ``key`` — ``"<ключ группы>:<номер строки>"``. Номер строки стабилен:
    одобренную заявку не правят. ``amount`` — первое денежное поле строки,
    если шаблон его объявил (у «Заявки на закуп» его нет — цена появляется
    только в договоре), иначе ``None``. Строки без наименования пропускаются:
    позицию без названия в договор не вписать.
    """
    require_service("approvals")

    instance = RequestInstance.objects.filter(pk=instance_id).first()
    if instance is None:
        return None
    version = (RequestFormTemplateVersion.objects
               .filter(pk=instance.template_version_id).first())
    if version is None:
        return []
    try:
        schema = validate_form_schema(version.schema_json)
    except ValueError:
        return []

    money_keys = {
        field.key: next((f.key for f in field.fields if f.type == "money"), None)
        for field in schema.fields
        if field.type == "group" and field.repeatable
    }
    values = instance.form_values_json or {}
    out = []
    for group_key, spec in _item_groups(schema):
        for index, row in enumerate(values.get(group_key) or [], start=1):
            if not isinstance(row, dict):
                continue
            name = str(row.get(spec["name"]) or "").strip()
            if not name:
                continue
            unit = str(row.get(spec["unit"]) or "").strip() if spec["unit"] else ""
            money_key = money_keys.get(group_key)
            amount = _number(row, [money_key]) if money_key else None
            out.append({
                "key": f"{group_key}:{index}",
                "name": name,
                "unit": unit,
                "quantity": _number(row, spec["quantity"]),
                "amount": amount if amount else None,
            })
    return out


def log_linked_document(instance_id: int, *, kind: str, document_id: int,
                        title: str, url: str, actor_id: int | None) -> bool:
    """Оставить в ленте заявки след о заведённом по ней документе соседа.

    ``kind`` — свободная строка соседа (``"agreement"``, ``"invoice"``):
    approvals её не интерпретирует, только показывает. ``False`` — заявки
    нет; исключение здесь не поднимается, потому что сосед зовёт это уже
    после того, как создал свой документ, и откатывать его из-за ленты
    незачем.
    """
    require_service("approvals")

    if not RequestInstance.objects.filter(pk=instance_id).exists():
        return False
    RequestActivity.objects.create(
        request_id=instance_id, event_type=EVENT_DOCUMENT_LINKED,
        actor_id=actor_id,
        payload={"kind": kind, "document_id": document_id,
                 "title": title, "url": url},
    )
    return True

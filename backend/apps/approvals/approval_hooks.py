"""Регистрация заявки конструктора («Запросы») в ``apps.signoff``.

Второй файл этого рода в репозитории после ``apps/contracts/approval_hooks.py``
— и устроен так же: зависимость направлена ОДНОСТОРОННЕ (approvals знает про
signoff, signoff про approvals — никогда), аппка сама приходит в реестр из
``ApprovalsConfig.ready()`` и отдаёт движку класс модели, колбэки итога,
``describe`` и факты.

Чем заявка отличается от документов contracts — и что из этого следует:

* **Маршрут у каждого шаблона свой.** Тип объекта один
  (``approvals.request``), а согласуют отпуск и закуп разные люди. Поэтому
  область маршрута (``ApprovalRoute.scope``) — шаблон: ``scope_of`` отдаёт
  ``template:<id>``, ``scopes`` — список активных шаблонов для редактора.
* **Факты — это поля формы.** Скаляры верхнего уровня ``form_values_json``
  плюс ``initiator_id``, ``project_id``, ``total_amount``. Для виджета
  ``budget_line_ref`` добавляются ``budget_administrator_id``,
  ``budget_program_id`` и ``budget_admin_country_id`` — через
  ``contracts.interface`` тем же батчем, что и проверка ссылки; так маршрут
  закупа ветвится «по администратору бюджета», не зная про contracts ничего.
  ``fact_fields`` берёт схему из ТЕКУЩЕЙ версии шаблона области.
* **Согласующих может назвать сама заявка** (``ApproverKind.SUBJECT``):
  ``project_admins`` — администраторы проекта заявок, ``field:<key>`` —
  значение поля ``user_ref``. Это то, что у старого движка звалось
  ``project_admins`` и ``field_ref``.
* **Колбэки двигают ``status``** — доменную ось заявки: ``pending`` →
  ``approved``/``rejected``/``returned``/``cancelled`` — и делают то, что
  старый рантайм делал при финализации: лента, роллап статистики, таблица
  данных. ``on_event`` шлёт SSE — уведомления в мессенджер теперь отправляет
  сам signoff, и дублировать их незачем.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from apps.contracts import interface as contracts_interface
from apps.signoff import interface as signoff

from .models import (
    ProjectMemberRole,
    RequestActivity,
    RequestFormTemplate,
    RequestFormTemplateVersion,
    RequestInstance,
    RequestProjectMember,
    RequestStatus,
    TemplateStatus,
)
from .services import budget_line_refs, quotes
from .services.form_schema import FormSchema, validate_form_schema
from .services.value_validation import (
    approver_fields, compute_total, is_blank, mismatch_in,
)

logger = logging.getLogger(__name__)

SUBJECT_TYPE = RequestInstance.SIGNOFF_SUBJECT_TYPE
SCOPE_PREFIX = "template:"
KEY_PROJECT_ADMINS = "project_admins"
KEY_FIELD_PREFIX = "field:"

# Типы полей формы, значение которых — число.
_NUMBER_TYPES = {"number", "money", "formula"}
# Типы, значение которых — строка (в том числе дата в ISO — signoff сравнивает
# ISO-даты как строки, и порядок совпадает с хронологическим).
_STRING_TYPES = {"text", "paragraph", "serial", "date"}


# ═══════════════════════════════════════════════════════════════════════
# Область = шаблон
# ═══════════════════════════════════════════════════════════════════════

def scope_for_template(template_id: int) -> str:
    return f"{SCOPE_PREFIX}{template_id}"


def template_id_from_scope(scope: str) -> int | None:
    if not scope or not scope.startswith(SCOPE_PREFIX):
        return None
    try:
        return int(scope[len(SCOPE_PREFIX):])
    except ValueError:
        return None


def _scope_of(subject_id: int) -> str:
    template_id = (RequestInstance.objects.filter(pk=subject_id)
                   .values_list("template_id", flat=True).first())
    return scope_for_template(template_id) if template_id else ""


def _scopes() -> list[dict]:
    """Все неудалённые шаблоны: у деактивированного маршрут тоже нужен —
    его включат обратно, а маршрут должен ждать готовым."""
    return [
        {"scope": scope_for_template(row.pk), "label": row.name}
        for row in (RequestFormTemplate.objects
                    .exclude(status=TemplateStatus.DELETED)
                    .order_by("name", "id"))
    ]


# ═══════════════════════════════════════════════════════════════════════
# Карточка, факты, согласующие
# ═══════════════════════════════════════════════════════════════════════

def _instance(subject_id: int) -> RequestInstance | None:
    return (RequestInstance.objects.select_related("template")
            .filter(pk=subject_id).first())


def _schema_of(instance: RequestInstance) -> FormSchema | None:
    version = (RequestFormTemplateVersion.objects
               .filter(pk=instance.template_version_id).first())
    return _parse(version.schema_json if version else None)


def _schema_for_scope(scope: str) -> FormSchema | None:
    template_id = template_id_from_scope(scope)
    if template_id is None:
        return None
    version_id = (RequestFormTemplate.objects.filter(pk=template_id)
                  .values_list("current_version_id", flat=True).first())
    version = (RequestFormTemplateVersion.objects.filter(pk=version_id).first()
               if version_id else None)
    return _parse(version.schema_json if version else None)


def _parse(schema_json: dict | None) -> FormSchema | None:
    if not schema_json:
        return None
    try:
        return validate_form_schema(schema_json)
    except ValueError:
        return None


def _describe(subject_id: int) -> dict | None:
    instance = _instance(subject_id)
    if instance is None:
        return None
    return {
        "title": f"{instance.code} — {instance.title or instance.template.name}",
        "url": f"/requests/{instance.pk}",
    }


def _scalar(value):
    """Значение поля → скаляр факта или ``None``, если оно не скаляр
    (списки многозначного выбора, файлы, строки групп)."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float, str)):
        return value
    return None


def _facts(subject_id: int) -> dict:
    instance = _instance(subject_id)
    if instance is None:
        return {}
    values = instance.form_values_json or {}
    schema = _schema_of(instance)
    facts: dict = {
        "initiator_id": instance.initiator_id,
        "project_id": instance.project_id,
    }
    if schema is None:
        return facts

    try:
        facts["total_amount"] = float(compute_total(schema.model_dump(), values))
    except ValueError:
        facts["total_amount"] = None

    budget_line_id: int | None = None
    for field in schema.fields:
        raw = values.get(field.key)
        if field.type == "amount":
            amount = raw.get("amount") if isinstance(raw, dict) else None
            facts[field.key] = float(amount) if isinstance(amount, (int, float)) else None
            currency = raw.get("currency") if isinstance(raw, dict) else None
            facts[f"{field.key}_currency"] = currency if isinstance(currency, str) else None
        elif field.type == budget_line_refs.WIDGET_TYPE:
            line_id = raw if isinstance(raw, int) and not isinstance(raw, bool) else None
            facts[field.key] = line_id
            if budget_line_id is None:
                budget_line_id = line_id
        elif field.type in ("group", "table", "file", "static_text", "signature",
                            "link_ref", "project_ref", "department_ref"):
            continue
        else:
            facts[field.key] = _scalar(raw)

    # Строка бюджета разворачивается в три факта, по которым и ветвят
    # маршрут закупа. Ошибка contracts здесь НЕ глушится (как и в
    # ``registry.facts_for``): факты решают, кто согласует.
    facts["budget_administrator_id"] = None
    facts["budget_program_id"] = None
    facts["budget_admin_country_id"] = None
    if budget_line_id is not None:
        for brief in contracts_interface.get_budget_lines_brief([budget_line_id]):
            facts["budget_administrator_id"] = brief["administrator_id"]
            facts["budget_program_id"] = brief["program_id"]
            facts["budget_admin_country_id"] = brief["administrator_country_id"]
    return facts


def _fact_fields(scope: str = "") -> list[dict]:
    schema = _schema_for_scope(scope)
    fields: list[dict] = [
        {"key": "total_amount", "label": "Итоговая сумма", "type": "number"},
    ]
    if schema is None:
        return fields

    has_budget_line = False
    for field in schema.fields:
        if field.type in _NUMBER_TYPES or field.type == "amount":
            fields.append({"key": field.key, "label": field.label, "type": "number"})
        elif field.type == "dropdown" and not getattr(field, "multiple", False):
            fields.append({"key": field.key, "label": field.label, "type": "choice",
                           "options": [{"value": option, "label": option}
                                       for option in field.options]})
        elif field.type == "checkbox":
            fields.append({"key": field.key, "label": field.label, "type": "bool"})
        elif field.type in _STRING_TYPES:
            fields.append({"key": field.key, "label": field.label, "type": "string"})
        elif field.type == budget_line_refs.WIDGET_TYPE:
            has_budget_line = True

    if has_budget_line:
        # Справочники — только когда в форме есть строка бюджета: форма
        # отпуска не должна ходить в contracts ради редактора маршрута.
        fields.extend([
            {"key": "budget_administrator_id", "label": "Администратор бюджета",
             "type": "choice",
             "options": [{"value": row["id"], "label": row["name"]}
                         for row in contracts_interface.list_administrators_brief()]},
            {"key": "budget_program_id", "label": "Программа бюджета",
             "type": "choice",
             "options": [{"value": row["id"], "label": row["name"]}
                         for row in contracts_interface.list_programs_brief()]},
            {"key": "budget_admin_country_id", "label": "Страна администратора бюджета",
             "type": "choice",
             "options": [{"value": row["id"], "label": row["name"]}
                         for row in contracts_interface.list_countries_brief()]},
        ])
    return fields


def _approvers(subject_id: int, key: str) -> list[int]:
    instance = _instance(subject_id)
    if instance is None:
        return []
    if key == KEY_PROJECT_ADMINS:
        if instance.project_id is None:
            return []
        return list(RequestProjectMember.objects
                    .filter(project_id=instance.project_id,
                            role=ProjectMemberRole.ADMIN)
                    .values_list("user_id", flat=True))
    if key.startswith(KEY_FIELD_PREFIX):
        raw = (instance.form_values_json or {}).get(key[len(KEY_FIELD_PREFIX):])
        candidates = raw if isinstance(raw, list) else [raw]
        out: list[int] = []
        for item in candidates:
            try:
                out.append(int(item))
            except (TypeError, ValueError):
                continue
        return out
    return []


def _approver_fields(scope: str = "") -> list[dict]:
    fields = [{"key": KEY_PROJECT_ADMINS, "label": "Администраторы проекта заявок"}]
    schema = _schema_for_scope(scope)
    if schema is not None:
        fields.extend(
            {"key": f"{KEY_FIELD_PREFIX}{field.key}", "label": f"Из поля «{field.label}»"}
            for field in schema.fields if field.type == "user_ref"
        )
    return fields


# ═══════════════════════════════════════════════════════════════════════
# Требования этапа к заявке: «поле согласующего заполнено»
# ═══════════════════════════════════════════════════════════════════════
#
# Этап маршрута может требовать, чтобы на заявке было заполнено поле с
# ``filled_by = approver`` — например «Поставщик» на шаге «Поиск
# поставщика». Ключ тот же формы, что у согласующих из поля: ``field:<key>``.
# Проверяет движок перед записью решения; текст отказа — отсюда.

def _requirement_fields(scope: str = "") -> list[dict]:
    schema = _schema_for_scope(scope)
    if schema is None:
        return []
    return [
        {"key": f"{KEY_FIELD_PREFIX}{field.key}", "label": f"Заполнено «{field.label}»"}
        for field in approver_fields(schema.model_dump())
    ]


def _check_requirement(subject_id: int, key: str) -> str | None:
    instance = _instance(subject_id)
    if instance is None or not key.startswith(KEY_FIELD_PREFIX):
        return None
    field_key = key[len(KEY_FIELD_PREFIX):]
    schema = _schema_of(instance)
    if schema is None:
        return None
    field = next((f for f in schema.fields if f.key == field_key), None)
    if field is None:
        return None
    values = instance.form_values_json or {}
    # Сравнительная таблица сама знает, чего ей не хватает: одного
    # предложения, цен по позициям или отметки выбранного. Её ответ точнее
    # общего «заполните поле», поэтому общая проверка пустоты сюда не идёт.
    if field.type == "supplier_quotes":
        return quotes.problem(schema, values, field_key)

    value = values.get(field_key)
    if is_blank(value):
        return f"заполнить «{field.label}» в заявке"
    # Блок (неповторяемая группа): «заполнен» значит заполнены его
    # обязательные поля — иначе пустой блок с одним пробелом считался бы
    # сделанным шагом.
    if field.type == "group" and not getattr(field, "repeatable", True):
        inner = value if isinstance(value, dict) else {}
        missing = [sub.label for sub in field.fields
                   if getattr(sub, "required", False) and is_blank(inner.get(sub.key))]
        if missing:
            return (f"заполнить в блоке «{field.label}»: "
                    + ", ".join(f"«{label}»" for label in missing))
    # Совпадение сумм — то же требование шага: пока «Сумма по счёту» не
    # равна согласованной, счёт не принят.
    problem = mismatch_in(schema, field_key, instance.form_values_json or {})
    if problem:
        return problem[0].lower() + problem[1:]
    return None


# ═══════════════════════════════════════════════════════════════════════
# Колбэки итога: ось ``status`` заявки
# ═══════════════════════════════════════════════════════════════════════

def _log(instance: RequestInstance, event_type: str, payload: dict | None = None) -> None:
    RequestActivity.objects.create(request=instance, event_type=event_type,
                                   actor_id=None, payload=payload)


def _after_change(instance: RequestInstance) -> None:
    # Локальные импорты: эти модули импортируют модели, а ``approval_hooks``
    # грузится из ``ready()`` — импорт верхнего уровня замкнул бы цикл.
    from .services.template_data_table import sync_row_for_instance

    sync_row_for_instance(instance)


def _finalize(instance: RequestInstance, status: str) -> None:
    from .services.stats_rollup import upsert_finalization

    instance.status = status
    instance.current_node_id = None
    instance.finalized_at = timezone.now()
    instance.save(update_fields=["status", "current_node_id", "finalized_at", "updated_at"])
    _log(instance, "finalized", {"result": status})
    upsert_finalization(instance)
    _after_change(instance)


def _on_started(subject_id: int) -> None:
    instance = _instance(subject_id)
    if instance is None:
        return
    instance.status = RequestStatus.PENDING
    instance.submitted_at = timezone.now()
    instance.finalized_at = None
    instance.current_node_id = None
    instance.requires_admin_attention = False
    instance.save(update_fields=["status", "submitted_at", "finalized_at",
                                 "current_node_id", "requires_admin_attention",
                                 "updated_at"])
    _log(instance, "submitted")
    _after_change(instance)


def _on_approved(subject_id: int) -> None:
    instance = _instance(subject_id)
    if instance is not None:
        _finalize(instance, RequestStatus.APPROVED)


def _on_rejected(subject_id: int) -> None:
    instance = _instance(subject_id)
    if instance is not None:
        _finalize(instance, RequestStatus.REJECTED)


def _on_rework(subject_id: int) -> None:
    """Возврат на доработку — ``returned``: заявка снова правится инициатором
    и отправляется заново (новый процесс signoff)."""
    instance = _instance(subject_id)
    if instance is None:
        return
    instance.status = RequestStatus.RETURNED
    instance.current_node_id = None
    instance.finalized_at = None
    instance.save(update_fields=["status", "current_node_id", "finalized_at", "updated_at"])
    _log(instance, "request_changes")
    _after_change(instance)


def _on_cancelled(subject_id: int) -> None:
    instance = _instance(subject_id)
    if instance is not None:
        _finalize(instance, RequestStatus.CANCELLED)


# ═══════════════════════════════════════════════════════════════════════
# События движка → SSE («Список дел» обновляется без перезагрузки)
# ═══════════════════════════════════════════════════════════════════════

_FINAL_EVENT = {
    "approved": "approved_final",
    "rejected": "rejected",
    "rework": "request_changes",
    "cancelled": "cancelled",
}


def _on_event(subject_id: int, kind: str, payload: dict) -> None:
    from .services.sse import publish_sse

    instance = _instance(subject_id)
    if instance is None:
        return
    meta = {"request_id": instance.pk, "request_code": instance.code,
            "deep_link": f"/requests/{instance.pk}"}
    if kind == "stage_activated":
        for user_id in payload.get("user_ids") or []:
            publish_sse(int(user_id), "request_assigned", meta)
    elif kind == "task_decided":
        publish_sse(instance.initiator_id, "approved_partial",
                    {**meta, "decision": payload.get("decision")})
    elif kind in _FINAL_EVENT:
        publish_sse(instance.initiator_id, _FINAL_EVENT[kind], meta)


def register() -> None:
    signoff.register_subject(
        SUBJECT_TYPE,
        label="Заявка",
        model=RequestInstance,
        on_started=_on_started,
        on_approved=_on_approved,
        on_rejected=_on_rejected,
        on_rework=_on_rework,
        on_cancelled=_on_cancelled,
        describe=_describe,
        facts=_facts,
        fact_fields=_fact_fields,
        scope_of=_scope_of,
        scopes=_scopes,
        approvers=_approvers,
        approver_fields=_approver_fields,
        requirement_fields=_requirement_fields,
        check_requirement=_check_requirement,
        on_event=_on_event,
    )

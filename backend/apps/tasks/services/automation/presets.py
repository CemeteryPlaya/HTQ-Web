"""Шаблон доски «Процесс задач HTQ» (решение K-40; разбор Trello §7;
спецификация логики docs/plans/2026-10-28-kanban-automation-logic.md, §14).

Процесс из Trello («Задачи HTQ») на каталоге автоматизации:

- колонки: «Постановка задачи» ``backlog``, «Ожидающие исполнения» ``todo``,
  «Исполнение» ``in_progress``, «В ожидании» ``blocked``, «Готово» ``done``;
  ``in_review`` и ``cancelled`` скрыты; «Протокольные поручения» — метка;
- поля «Причина ожидания» (текст) и «Взята в работу» (дата, на карточке);
- шаблон чек-листа «Чек-лист» — четыре пункта Trello;
- правила 1–5, 7–11, 18, 19 (6 не нужно: уход из «Готово» и есть снятие
  отметки; 4 и 7 — одно правило «чек-лист по шаблону»), запреты ручного
  переноса 12, 13, 16, 17 (K-38; 14 и 15 и так закрыты схемой статусов:
  «Ожидающие» → «Готово» и «Готово» → «Ожидающие» в ней не предусмотрены);
- команда «через 1 день после срока» — метка «Просрочено» и комментарий;
- кнопки «Взять в работу», «На доработку», «Сдать».

Защита, которой в Trello не было (решения L-02, L-03 от 28.10):

- кнопки — только в своих колонках: «Взять в работу» — в «Ожидающих
  исполнения» у назначенной задачи, «На доработку» — в «Готово», «Сдать» — в
  «Исполнении»;
- «Взята в работу» ставит правило при входе в «Исполнение» — встроенное
  «Взять в работу» (свободная задача отдела) запреты не держат;
- скрытой «На ревью» в процессе нет — вручную в неё нельзя; в «Готово» с
  невыполненным чек-листом нельзя из любой колонки;
- в «В ожидании» вручную — только с «Причиной ожидания», обратно — только
  очистив её;
- «Просрочено» снимается при выполнении, отмене, переносе и снятии срока.

Применение идемпотентно: поля, метки и шаблон ищутся по названию, у каждой
автоматизации — свой ``preset_key``, повтор правит её, а не дублирует, и
восстанавливает шаблон: правки администратора в автоматизациях шаблона и
колонках заменяются, сломанные чинятся. Поле с тем же названием, но другого
типа — отказ 422 (переименуйте поле или удалите его). Прочие настройки доски
(свои поля, шаблоны, автоматизации) шаблон не трогает.
"""

from __future__ import annotations

from django.db import transaction

from htqweb.errors import DomainError

from ... import schemas
from ...models import (AutomationKind, AutomationRule, BoardField, BoardFieldType, BoardKind,
                       BoardSettings, Label)
from .. import board_fields
from .. import board_service
from .. import ranked
from . import rules

PRESETS = ("htq_process",)

COLUMNS = {
    "backlog": {"title": "Постановка задачи", "color": "purple", "hidden": False},
    "todo": {"title": "Ожидающие исполнения", "color": "yellow", "hidden": False},
    "in_progress": {"title": "Исполнение", "color": "sky", "hidden": False},
    "in_review": {"title": None, "color": None, "hidden": True},
    "blocked": {"title": "В ожидании", "color": "red", "hidden": False},
    "done": {"title": "Готово", "color": "green", "hidden": False},
    "cancelled": {"title": None, "color": None, "hidden": True},
}
FIELD_REASON = "Причина ожидания"
FIELD_TAKEN = "Взята в работу"
CHECKLIST = "Чек-лист"
CHECKLIST_ITEMS = ["Ознакомиться с задачей", "Выполнить задачу", "Проверить результат",
                   "Отправить отчёт руководителю"]
LABEL_PROTOCOL = ("Протокольные поручения", "#7f5f01")
LABEL_OVERDUE = ("Просрочено", "#ae2e24")

BLOCK_12 = ("Сразу в «Исполнение» переносить нельзя. Назначьте исполнителя и срок — "
            "карточка сама перейдёт в «Ожидающие исполнения», а оттуда её берут в работу.")
BLOCK_13 = ("Обратно в «Ожидающие исполнения» переносить нельзя. Если задачу не получается "
            "сделать, напишите причину в поле «Причина ожидания» — карточка сама уйдёт "
            "в «В ожидании».")
BLOCK_16 = ("В «Готово» вручную переносить нельзя. Когда закончите, нажмите «Сдать» или "
            "отметьте все пункты чек-листа — карточка сама уйдёт в «Готово».")
BLOCK_17 = ("Вручную в «Исполнение» переносить нельзя. Чтобы взять задачу в работу, нажмите "
            "«Взять в работу» или отметьте пункт «Выполнить задачу» в чек-листе.")
BLOCK_REVIEW = ("Колонки «На ревью» в процессе доски нет. Когда закончите, нажмите «Сдать» "
                "или отметьте все пункты чек-листа — карточка сама уйдёт в «Готово».")
BLOCK_WAIT_IN = ("В «В ожидании» карточка уходит сама: напишите причину в поле «Причина "
                 "ожидания».")
BLOCK_WAIT_OUT = ("Пока указана «Причина ожидания», карточка остаётся в «В ожидании». Очистите "
                  "поле — карточка сама вернётся в «Исполнение».")
COMMENT_REWORK = ("@card Задачу вернули на доработку. Что исправить — смотрите комментарии к "
                  "карточке. Чек-лист сброшен: когда исправите, снова отметьте пункты или "
                  "нажмите «Сдать» — карточка сама уйдёт в «Готово».")
COMMENT_OVERDUE = ("@card Срок выполнения прошёл, а задача не завершена. Обновите статус или "
                   "перенесите срок.")


def _move(status: str, position: str) -> dict:
    return {"type": "move", "status": status, "position": position}


def _block(message: str) -> list[dict]:
    return [{"type": "block", "message": message}]


def _automations(reason: int, taken: int, overdue: int, template_id: str) -> list[tuple]:
    """``(ключ, вид, название, значок, триггер, условия, действия)``."""
    rule, due, button = AutomationKind.RULE, AutomationKind.DUE, AutomationKind.CARD_BUTTON
    in_column = lambda status: {"type": "in_column", "status": status}  # noqa: E731
    reason_set = {"type": "field", "field_id": reason, "op": "set"}
    reason_empty = {"type": "field", "field_id": reason, "op": "empty"}
    unmark_overdue = [{"type": "remove_label", "label_id": overdue}]
    return [
        ("htq.r01", rule, "Исполнитель назначен — в «Ожидающие исполнения»", "",
         {"type": "assignee_added"},
         [in_column("backlog"), {"type": "has_due"}], [_move("todo", "bottom")]),
        ("htq.r02", rule, "Срок поставлен — в «Ожидающие исполнения»", "",
         {"type": "due_set"},
         [in_column("backlog"), {"type": "assigned", "who": "anyone"}], [_move("todo", "bottom")]),
        ("htq.r03", rule, "Сдана — отметить все пункты", "",
         {"type": "moved", "from_status": "in_progress", "to_status": "done"},
         [], [{"type": "check_all"}, {"type": "reposition", "position": "top"}]),
        ("htq.r04", rule, "Новая задача — чек-лист по шаблону", "",
         {"type": "card_created"},
         [{"type": "has_checklist", "title": CHECKLIST, "negate": True}],
         [{"type": "add_checklist", "title": CHECKLIST, "template_id": template_id}]),
        ("htq.r05", rule, "Все пункты отмечены — в «Готово»", "",
         {"type": "item_checked"},
         [in_column("in_progress"), {"type": "checklists_complete"}], [_move("done", "top")]),
        ("htq.r08", rule, "Выполнена — снять «Просрочено»", "",
         {"type": "completed"}, [], unmark_overdue),
        ("htq.r09", rule, "Причина ожидания задана — в «В ожидании»", "",
         {"type": "field_changed", "field_id": reason, "op": "set"},
         [in_column("in_progress")], [_move("blocked", "top")]),
        ("htq.r10", rule, "Причина ожидания очищена — в «Исполнение»", "",
         {"type": "field_changed", "field_id": reason, "op": "cleared"},
         [in_column("blocked")], [_move("in_progress", "top")]),
        ("htq.r11", rule, "«Выполнить задачу» отмечен — в «Исполнение»", "",
         {"type": "item_checked", "text": "Выполнить задачу"},
         [in_column("todo")],
         [{"type": "set_field", "field_id": taken, "mode": "today"}, _move("in_progress", "top")]),
        ("htq.r12", rule, "Запрет: «Постановка задачи» → «Исполнение»", "",
         {"type": "moved", "from_status": "backlog", "to_status": "in_progress"}, [],
         _block(BLOCK_12)),
        ("htq.r13", rule, "Запрет: «Исполнение» → «Ожидающие исполнения»", "",
         {"type": "moved", "from_status": "in_progress", "to_status": "todo"},
         [{"type": "field", "field_id": taken, "op": "set"}], _block(BLOCK_13)),
        ("htq.r16", rule, "Запрет: в «Готово» с невыполненным чек-листом", "",
         {"type": "moved", "to_status": "done"},
         [{"type": "checklists_incomplete"}], _block(BLOCK_16)),
        ("htq.r17", rule, "Запрет: в «Исполнение», пока не взята в работу", "",
         {"type": "moved", "from_status": "todo", "to_status": "in_progress"},
         [{"type": "field", "field_id": taken, "op": "empty"}], _block(BLOCK_17)),
        ("htq.r18", rule, "Вернули на доработку — сбросить чек-лист", "",
         {"type": "moved", "from_status": "done", "to_status": "in_progress"},
         [{"type": "checklists_complete"}],
         [{"type": "reset_all"}, {"type": "comment", "text": COMMENT_REWORK}]),
        ("htq.r19", rule, "Комментарий «На доработку» — в «Исполнение»", "",
         {"type": "comment_added", "match": "starts_with", "text": "На доработку"},
         [in_column("done")], [_move("in_progress", "top")]),
        ("htq.r20", rule, "Вошла в «Исполнение» — «Взята в работу» сегодня", "",
         {"type": "moved", "to_status": "in_progress"},
         [{"type": "field", "field_id": taken, "op": "empty"}],
         [{"type": "set_field", "field_id": taken, "mode": "today"}]),
        ("htq.r21", rule, "Запрет: в «На ревью»", "",
         {"type": "moved", "to_status": "in_review"}, [], _block(BLOCK_REVIEW)),
        ("htq.r22", rule, "Запрет: в «В ожидании» без причины", "",
         {"type": "moved", "to_status": "blocked"}, [reason_empty], _block(BLOCK_WAIT_IN)),
        ("htq.r23", rule, "Запрет: из «В ожидании» в «Исполнение» с причиной", "",
         {"type": "moved", "from_status": "blocked", "to_status": "in_progress"}, [reason_set],
         _block(BLOCK_WAIT_OUT)),
        ("htq.r24", rule, "Запрет: из «В ожидании» в «Ожидающие исполнения» с причиной", "",
         {"type": "moved", "from_status": "blocked", "to_status": "todo"}, [reason_set],
         _block(BLOCK_WAIT_OUT)),
        ("htq.r25", rule, "Отменена — снять «Просрочено»", "",
         {"type": "cancelled"}, [], unmark_overdue),
        ("htq.r26", rule, "Срок перенесён — снять «Просрочено»", "",
         {"type": "due_changed"},
         [{"type": "due_window", "window": "overdue", "negate": True}], unmark_overdue),
        ("htq.r27", rule, "Срок снят — снять «Просрочено»", "",
         {"type": "due_removed"}, [], unmark_overdue),
        ("htq.due", due, "Просрочено", "",
         {"type": "due", "offset_days": 1},
         [{"type": "due_window", "window": "overdue"}],
         [{"type": "add_label", "label_id": overdue},
          {"type": "comment", "text": COMMENT_OVERDUE}]),
        ("htq.take", button, "Взять в работу", "arrow-right",
         {"type": "card_button"}, [in_column("todo"), {"type": "assigned", "who": "anyone"}],
         [{"type": "set_field", "field_id": taken, "mode": "today"},
          _move("in_progress", "bottom"), {"type": "join_actor"}]),
        ("htq.rework", button, "На доработку", "hammer",
         {"type": "card_button"}, [in_column("done")], [_move("in_progress", "top")]),
        ("htq.submit", button, "Сдать", "circle-check",
         {"type": "card_button"}, [in_column("in_progress")], [{"type": "complete"}]),
    ]


def _field(board, name: str, field_type: str, show_on_card: bool, actor_id, report) -> int:
    found = BoardField.objects.filter(board_kind=board.kind, board_id=board.id,
                                      name__iexact=name).first()
    if found is not None:
        if found.field_type != field_type:
            raise DomainError("preset_field_conflict",
                              f"На доске уже есть поле «{found.name}» другого типа — "
                              "переименуйте или удалите его", status=422)
        report["fields"]["kept"].append(name)
        return found.pk
    existing = list(BoardField.objects.filter(board_kind=board.kind, board_id=board.id))
    if len(existing) >= board_fields.FIELD_LIMIT:
        raise DomainError("board_field_limit",
                          f"На доске не больше {board_fields.FIELD_LIMIT} полей", status=422)
    created = BoardField.objects.create(
        board_kind=board.kind, board_id=board.id, name=name, field_type=field_type,
        show_on_card=show_on_card, created_by=actor_id,
        position=ranked.position_between(existing, None, None, None,
                                         code="board_field_order_stale", what="поля доски"))
    report["fields"]["created"].append(name)
    return created.pk


def _label(name: str, color: str, report) -> int:
    label, created = Label.objects.get_or_create(name=name, defaults={"color": color})
    report["labels"]["created" if created else "kept"].append(name)
    return label.pk


def _settings(board, actor_id, report) -> str:
    """Колонки процесса и шаблон «Чек-лист»; прочие шаблоны доски остаются."""
    row, _created = BoardSettings.objects.select_for_update().get_or_create(
        board_kind=board.kind, board_id=board.id)
    templates = list(row.checklist_templates or [])
    template = next((item for item in templates if item.get("title", "").casefold()
                     == CHECKLIST.casefold()), None)
    if template is None:
        template_id = board_fields.normalize_templates(
            [schemas.ChecklistTemplateIn(title=CHECKLIST, items=CHECKLIST_ITEMS)], templates)[0]["id"]
        templates.append({"id": template_id, "title": CHECKLIST, "items": CHECKLIST_ITEMS})
        report["templates"]["created"].append(CHECKLIST)
    else:
        template_id = template["id"]
        template["items"] = list(CHECKLIST_ITEMS)
        report["templates"]["kept"].append(CHECKLIST)
    row.columns = dict(COLUMNS)
    row.checklist_templates = templates
    row.updated_by = actor_id
    row.save()
    return template_id


def apply(board, preset: str, actor_id: int | None, *, dry_run: bool = False) -> dict:
    """Применить шаблон к доске отдела или проекта (права проверил вызывающий).
    ``dry_run`` — тот же отчёт, всё откатывается: что изменится."""
    if preset not in PRESETS:
        raise DomainError("preset_unknown", "Неизвестный шаблон доски", status=422)
    if board.kind == BoardKind.PERSONAL:
        raise DomainError("board_automation_personal", "У личной доски нет автоматизации",
                          status=422)
    report = {"board": {"kind": board.kind, "id": board.id}, "preset": preset,
              "dry_run": dry_run,
              "fields": {"created": [], "kept": []}, "labels": {"created": [], "kept": []},
              "templates": {"created": [], "kept": []},
              "automations": {"created": [], "updated": [], "unchanged": []}}
    with transaction.atomic():
        template_id = _settings(board, actor_id, report)
        reason = _field(board, FIELD_REASON, BoardFieldType.TEXT, False, actor_id, report)
        taken = _field(board, FIELD_TAKEN, BoardFieldType.DATE, True, actor_id, report)
        _label(*LABEL_PROTOCOL, report)
        overdue = _label(*LABEL_OVERDUE, report)
        for key, kind, name, icon, trigger, conditions, actions in _automations(
                reason, taken, overdue, template_id):
            data = schemas.AutomationIn(kind=kind, name=name, icon=icon, trigger=trigger,
                                        conditions=conditions, actions=actions)
            existing = AutomationRule.objects.filter(board_kind=board.kind, board_id=board.id,
                                                     preset_key=key).first()
            if existing is None:
                rules.save_new(board, data, actor_id, preset_key=key)
                report["automations"]["created"].append(name)
                continue
            before = rules.snapshot(existing), existing.broken_reason
            rules.apply_patch(board, existing, schemas.AutomationPatch(
                name=name, icon=icon, trigger=trigger, conditions=conditions,
                actions=actions, enabled=True), actor_id)
            changed = (rules.snapshot(existing), existing.broken_reason) != before
            report["automations"]["updated" if changed else "unchanged"].append(name)
        if dry_run:
            transaction.set_rollback(True)
    return report


@transaction.atomic
def apply_from_request(request, board, preset: str, *, dry_run: bool = False) -> dict:
    board_service.require_admin(request, board)
    return apply(board, preset, request.token.user_id, dry_run=dry_run)

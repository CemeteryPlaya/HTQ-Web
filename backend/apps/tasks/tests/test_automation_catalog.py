"""Каталог автоматизации: проверка при сохранении (этап S4).

Вид и триггер согласованы, действия допустимы для вида, «Запретить перенос»
— только у правила на перенос и единственным действием, ссылки на метки,
свои поля и шаблоны — этой доски, операция подходит типу поля. Каталог для
конструктора отдаёт все триггеры, условия и действия.
"""

from __future__ import annotations

import pytest

from apps.tasks.models import BoardField, BoardSettings
from apps.tasks.services.automation import catalog
from htqweb.errors import DomainError

from .automation_helpers import dept_board, label
from .org_fixtures import make_org

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    return make_org()


def _check(board, kind, trigger, actions, conditions=None):
    return catalog.validate(board, kind, trigger, conditions or [], actions)


def _rejected(board, kind, trigger, actions, conditions=None) -> str:
    with pytest.raises(DomainError) as caught:
        _check(board, kind, trigger, actions, conditions)
    assert caught.value.code == "automation_invalid"
    return caught.value.message


def test_valid_rule_is_normalized(org):
    trigger, conditions, actions = _check(
        dept_board(org.it), "rule", {"type": "moved", "to_status": "done"},
        [{"type": "move", "status": "in_progress"}], [{"type": "has_due"}])
    assert trigger == {"type": "moved", "from_status": None, "to_status": "done"}
    assert conditions == [{"type": "has_due", "negate": False}]
    assert actions == [{"type": "move", "status": "in_progress", "position": "bottom"}]


@pytest.mark.parametrize(("kind", "trigger", "actions", "message"), [
    ("rule", {"type": "nope"}, [{"type": "complete"}], "trigger"),
    ("rule", {"type": "moved"}, [], "хотя бы одно действие"),
    ("rule", {"type": "due_set"}, [{"type": "block", "message": "Нет"}], "на перенос"),
    ("rule", {"type": "moved"}, [{"type": "block", "message": "Нет"}, {"type": "complete"}],
     "единственное"),
    ("rule", {"type": "moved"}, [{"type": "sort_column", "status": "todo"}], "Сортировка"),
    ("board_button", {"type": "board_button"}, [{"type": "complete"}], "над карточкой"),
    ("schedule", {"type": "schedule", "freq": "weekly"}, [{"type": "create_task",
                                                           "summary": "x"}], "дни недели"),
    ("schedule", {"type": "schedule", "freq": "daily", "time": "25:00"},
     [{"type": "create_task", "summary": "x"}], "ЧЧ:ММ"),
    ("card_button", {"type": "moved"}, [{"type": "complete"}], "trigger"),
])
def test_bad_shapes_are_rejected(org, kind, trigger, actions, message):
    assert message in _rejected(dept_board(org.it), kind, trigger, actions)


def test_board_level_automation_takes_no_conditions(org):
    message = _rejected(dept_board(org.it), "board_button", {"type": "board_button"},
                        [{"type": "create_task", "summary": "x"}], [{"type": "has_due"}])
    assert "колонку карточек" in message


def test_references_must_be_alive_and_of_this_board(org):
    board = dept_board(org.it)
    assert "Метки нет" in _rejected(board, "rule", {"type": "moved"},
                                    [{"type": "add_label", "label_id": 999999}])
    foreign = BoardField.objects.create(board_kind="department", board_id=org.ops.id,
                                        name="Чужое", field_type="text", position="V")
    assert "Поля нет на этой доске" in _rejected(
        board, "rule", {"type": "moved"}, [{"type": "clear_field", "field_id": foreign.pk}])
    assert "Шаблона" in _rejected(board, "rule", {"type": "moved"},
                                  [{"type": "add_checklist", "title": "x", "template_id": "zz"}])
    BoardSettings.objects.create(board_kind="department", board_id=org.it.id,
                                 checklist_templates=[{"id": "zz", "title": "x", "items": []}])
    _check(board, "rule", {"type": "moved"},
           [{"type": "add_checklist", "title": "x", "template_id": "zz"},
            {"type": "add_label", "label_id": label("Живая").pk}])


@pytest.mark.parametrize(("field_type", "spec", "message"), [
    ("text", {"type": "field", "op": "checked"}, "не флажок"),
    ("text", {"type": "field", "op": "gt", "value": 3}, "не число"),
    ("number", {"type": "field", "op": "equals", "value": "много"}, "число"),
    ("list", {"type": "field", "op": "equals", "value": "nope"}, "варианта"),
    ("checkbox", {"type": "field", "op": "equals", "value": True}, "флажок сравнивается"),
])
def test_field_conditions_follow_field_type(org, field_type, spec, message):
    field = BoardField.objects.create(board_kind="department", board_id=org.it.id, name="Поле",
                                      field_type=field_type, position="V",
                                      options=[{"id": "a1", "name": "Да", "color": None}]
                                      if field_type == "list" else [])
    condition = {**spec, "field_id": field.pk}
    assert message in _rejected(dept_board(org.it), "rule", {"type": "moved"},
                                [{"type": "complete"}], [condition])


def test_field_actions_follow_field_type(org):
    board = dept_board(org.it)
    text = BoardField.objects.create(board_kind="department", board_id=org.it.id, name="Текст",
                                     field_type="text", position="V")
    flag = BoardField.objects.create(board_kind="department", board_id=org.it.id, name="Флаг",
                                     field_type="checkbox", position="W")
    assert "не дата" in _rejected(board, "rule", {"type": "moved"},
                                  [{"type": "set_field", "field_id": text.pk, "mode": "today"}])
    assert "не число" in _rejected(board, "rule", {"type": "moved"},
                                   [{"type": "increment_field", "field_id": text.pk, "by": 1}])
    assert "да или нет" in _rejected(board, "rule", {"type": "moved"},
                                     [{"type": "set_field", "field_id": flag.pk, "value": "x"}])
    _check(board, "rule", {"type": "moved"},
           [{"type": "set_field", "field_id": flag.pk, "value": False},
            {"type": "set_field", "field_id": text.pk, "value": "Готово"}])


def test_describe_lists_everything():
    described = catalog.describe()
    triggers = {item["type"] for item in described["triggers"]}
    assert {"card_created", "moved", "item_checked", "field_changed", "fields_filled",
            "comment_added", "column_count"} <= triggers
    assert "attachment_removed" not in triggers
    actions = {item["type"] for item in described["actions"]}
    assert {"move", "block", "check_all", "notify", "sort_column", "round_robin_assignee"} <= actions
    assert len(actions) == 39
    assert set(described["kinds"]) == {"card_button", "board_button", "due", "schedule"}
    assert described["board_actions"] == ["create_task", "notify", "sort_column"]

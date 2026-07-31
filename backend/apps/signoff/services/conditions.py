"""Условные ветки маршрута: разбор, проверка и выбор этапов по фактам объекта.

Задача модуля — дать заказчику «после проверки согласует тот, кто отвечает за
страну этого бюджета», не втащив в signoff ни строчки про страны и бюджеты.

**Откуда берутся факты.** Движок не имеет права дотянуться до
``budget.administrator.country`` — это чужая аппка (правило границ,
``apps/core/tests/test_app_isolation.py``). Поэтому предметная аппка сама
отдаёт при регистрации две функции (см. ``services/registry.py``):

* ``facts(subject_id) -> dict`` — плоский словарь скаляров, снимаемый с
  объекта на запуске (``{"admin_country_id": 3, "amount": 12000000.0}``);
* ``fact_fields() -> list[dict]`` — что из этого разрешено спрашивать в
  условии и как показать это в редакторе маршрута
  (``{"key", "label", "type", "options"}``).

signoff сравнивает скаляры, которые ему дали, и не знает, что значит
``admin_country_id``. Ровно поэтому механизм работает для любой модели: чтобы
сделать новый тип ветвимым, в самом signoff не меняется ничего.

**Формат условия** — список предикатов, соединённых И. Пустой список значит
«этап нужен всегда»::

    []                                                    # всегда
    [{"field": "admin_country_id", "op": "in", "value": [1, 4]}]

Вложенности, ИЛИ между полями и выражений здесь нет намеренно. ИЛИ по одному
полю — это ``in``; ИЛИ по разным полям — два этапа в одной группе. Всё, что
сложнее, — это уже дерево условий ``apps.approvals``, и стоит оно на порядок
дороже (см. докстринг ``apps/signoff/models.py``).

**Ветка = группа по ``order``.** Отдельной модели ветвления нет: из группы
этапов с одинаковым ``order`` в процесс попадают только те, чьё условие
сошлось. Дальше движок видит обычный линейный список групп и про ветвление не
знает вовсе — поэтому ``engine.act``/``_advance``/кворум/блокировки этой
правкой не затронуты.

**Почему пустая группа — ошибка.** Самый опасный исход здесь — не отказ, а
молчание: завели страну, забыли дописать ветку, и бюджет тихо проходит мимо
финконтроля прямо к финальному утверждению. Никто этого не заметит. Поэтому
группа, из которой не прошёл ни один этап, роняет ЗАПУСК с внятным текстом,
а «для прочих стран согласует вот этот» выражается явным этапом
``is_fallback``.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal
from itertools import groupby
from typing import Any, Iterable

# Операторы. Список короткий и закрытый: каждый новый оператор — это ещё и
# виджет в редакторе маршрута, поэтому добавляются они по необходимости, а не
# «на всякий случай».
OP_EQ = "eq"
OP_IN = "in"
OP_NOT_IN = "not_in"
OP_GT = "gt"
OP_GTE = "gte"
OP_LT = "lt"
OP_LTE = "lte"

SET_OPS = (OP_IN, OP_NOT_IN)
ORDER_OPS = (OP_GT, OP_GTE, OP_LT, OP_LTE)
OPS = (OP_EQ, *SET_OPS, *ORDER_OPS)

OP_LABELS = {
    OP_EQ: "равно",
    OP_IN: "одно из",
    OP_NOT_IN: "не из",
    OP_GT: "больше",
    OP_GTE: "больше или равно",
    OP_LT: "меньше",
    OP_LTE: "меньше или равно",
}

# Типы полей, которые предметная аппка может объявить в ``fact_fields``.
TYPE_CHOICE = "choice"
TYPE_NUMBER = "number"
TYPE_STRING = "string"
TYPE_BOOL = "bool"
FIELD_TYPES = (TYPE_CHOICE, TYPE_NUMBER, TYPE_STRING, TYPE_BOOL)

# Как этап попал в процесс — снимается вместе с условием
# (``ApprovalProcessStage.matched_by``).
MATCH_ALWAYS = "always"
MATCH_CONDITION = "condition"
MATCH_FALLBACK = "fallback"


class ConditionError(Exception):
    """Условие нельзя проверить: неизвестное поле, оператор или тип значения.

    Поднимается и при настройке маршрута (``route_service`` переводит в 409),
    и на запуске процесса, если маршрут успел разойтись с тем, что предметная
    аппка отдаёт в ``facts`` — например, ключ факта переименовали.

    Отдельно от «условие не сошлось»: несошедшееся условие — это нормальная
    работа ветвления, а вот условие про несуществующее поле — сломанная
    настройка, и молча считать её ложью значило бы бесшумно выкинуть этап.
    """


class NoBranchMatched(Exception):
    """В группе этапов не осталось ни одного этапа.

    Несёт ``order`` и факты, потому что читать это будет не администратор
    маршрута, а пользователь, нажавший «отправить на согласование»: ему нужно
    знать, ЧТО именно не сошлось.
    """

    def __init__(self, order: int, facts: dict):
        self.order = order
        self.facts = facts
        super().__init__(f"В группе этапов №{order} не сошлось ни одно условие")


@dataclass(frozen=True)
class Selected:
    """Этап маршрута, прошедший отбор, и причина, по которой он прошёл."""

    stage: Any
    matched_by: str


# ═══════════════════════════════════════════════════════════════════════
# Факты
# ═══════════════════════════════════════════════════════════════════════

def normalize_facts(facts: dict | None) -> dict:
    """Привести факты к JSON-совместимым скалярам.

    Нужно потому, что факты не только сравниваются, но и СОХРАНЯЮТСЯ
    (``ApprovalProcess.subject_facts``), а ``JSONField`` не умеет ни
    ``Decimal``, ни ``date``. Приведение сделано здесь, централизованно, а не
    вменено каждой предметной аппке: забытый ``float()`` в одной из них
    уронил бы запуск согласования, причём не на настройке, а в руках
    пользователя.

    ``Decimal`` → ``float``: сравнение порога маршрутизации («сумма больше
    5 млн») к точности денег не предъявляет требований — это выбор
    согласующего, а не проводка. Даты → ISO-строка: у ISO-8601
    лексикографический порядок совпадает с хронологическим, поэтому
    ``gt``/``lt`` на них продолжают работать.
    """
    out: dict = {}
    for key, value in (facts or {}).items():
        if isinstance(value, Decimal):
            value = float(value)
        elif isinstance(value, (_dt.datetime, _dt.date)):
            value = value.isoformat()
        elif not isinstance(value, (str, int, float, bool, type(None))):
            raise ConditionError(
                f"Факт «{key}» имеет неподдерживаемый тип {type(value).__name__}: "
                f"условия сравнивают только скаляры"
            )
        out[str(key)] = value
    return out


# ═══════════════════════════════════════════════════════════════════════
# Проверка условия
# ═══════════════════════════════════════════════════════════════════════

def evaluate(condition, facts: dict) -> bool:
    """Сошлось ли условие на этих фактах. Пустое условие — всегда да."""
    for predicate in condition or []:
        if not _evaluate_one(predicate, facts):
            return False
    return True


def _evaluate_one(predicate, facts: dict) -> bool:
    field, op, value = _unpack(predicate)

    if field not in facts:
        # Не «условие не сошлось», а сломанная настройка: маршрут спрашивает
        # поле, которого предметная аппка не отдаёт. Считать это ложью значило
        # бы тихо выкинуть этап из согласования — ровно тот бесшумный отказ,
        # против которого написан весь модуль.
        raise ConditionError(
            f"Объект не сообщает поле «{field}» — маршрут ссылается на факт, "
            f"которого нет. Известные факты: {', '.join(sorted(facts)) or '(ни одного)'}"
        )

    actual = facts[field]
    if actual is None:
        # У объекта поля действительно нет значения — это уже данные, а не
        # настройка, и ветка просто не подходит. Такой объект подхватит
        # этап «иначе», а если его нет — запуск упадёт на пустой группе.
        return False

    if op == OP_EQ:
        return actual == value
    if op == OP_IN:
        return actual in value
    if op == OP_NOT_IN:
        return actual not in value

    # Порядковые операторы: сравниваются либо два числа, либо две строки.
    # Смешение запрещено, потому что в Python оно не ошибка настройки, а
    # TypeError посреди запуска согласования. bool исключён из чисел явно —
    # иначе ``urgent > 0`` прошло бы как осмысленное сравнение.
    numeric = (_is_number(actual) and _is_number(value))
    textual = isinstance(actual, str) and isinstance(value, str)
    if not (numeric or textual):
        raise ConditionError(
            f"«{field}»: оператор «{OP_LABELS[op]}» сравнивает числа с числами "
            f"или строки со строками, а получено {actual!r} и {value!r}"
        )
    if op == OP_GT:
        return actual > value
    if op == OP_GTE:
        return actual >= value
    if op == OP_LT:
        return actual < value
    return actual <= value


def _is_number(value) -> bool:
    """``bool`` — не число: ``True`` иначе прошло бы любое сравнение с нулём."""
    return not isinstance(value, bool) and isinstance(value, (int, float))


def _unpack(predicate) -> tuple[str, str, Any]:
    """Разобрать один предикат, проверив форму (без сверки со схемой полей)."""
    if not isinstance(predicate, dict):
        raise ConditionError(f"Предикат должен быть объектом, получено: {predicate!r}")

    unknown = set(predicate) - {"field", "op", "value"}
    if unknown:
        raise ConditionError(
            f"Лишние ключи в предикате: {', '.join(sorted(unknown))}")

    field = predicate.get("field")
    op = predicate.get("op")
    if not isinstance(field, str) or not field:
        raise ConditionError("В предикате не указано поле")
    if op not in OPS:
        raise ConditionError(
            f"Неизвестный оператор «{op}». Допустимы: {', '.join(OPS)}")

    value = predicate.get("value")
    if op in SET_OPS:
        if not isinstance(value, list) or not value:
            raise ConditionError(
                f"«{field}»: оператор «{OP_LABELS[op]}» ждёт непустой список значений")
    elif isinstance(value, (list, dict)):
        raise ConditionError(
            f"«{field}»: оператор «{OP_LABELS[op]}» ждёт одно значение, не список")

    return field, op, value


# ═══════════════════════════════════════════════════════════════════════
# Проверка условия против схемы полей (настройка маршрута)
# ═══════════════════════════════════════════════════════════════════════

def validate(condition, fields: list[dict]) -> list:
    """Проверить условие против ``fact_fields`` типа. Возвращает его же.

    Вызывается при СОХРАНЕНИИ этапа. Смысл ровно тот же, что у
    ``route_service._check_approvers_exist``: опечатка в настройке должна
    ловиться на настройке, у того, кто её делает, а не всплывать через месяц
    у пользователя в виде «не сошлось ни одно условие».
    """
    if condition in (None, "", []):
        return []
    if not isinstance(condition, list):
        raise ConditionError("Условие должно быть списком предикатов")

    if not fields:
        raise ConditionError(
            "Для этого типа объектов не объявлено ни одного поля — "
            "условные этапы ему настроить нельзя"
        )
    by_key = {field["key"]: field for field in fields}

    for predicate in condition:
        field, op, value = _unpack(predicate)
        spec = by_key.get(field)
        if spec is None:
            raise ConditionError(
                f"Неизвестное поле «{field}». Доступны: {', '.join(sorted(by_key))}")
        _validate_value(spec, op, value)
    return condition


def _validate_value(spec: dict, op: str, value) -> None:
    key = spec["key"]
    field_type = spec.get("type", TYPE_STRING)
    values = value if op in SET_OPS else [value]

    if field_type == TYPE_CHOICE:
        if op in ORDER_OPS:
            raise ConditionError(
                f"«{spec.get('label', key)}»: значение из справочника нельзя "
                f"сравнивать оператором «{OP_LABELS[op]}»")
        allowed = {option["value"] for option in spec.get("options", [])}
        unknown = [item for item in values if item not in allowed]
        if unknown:
            raise ConditionError(
                f"«{spec.get('label', key)}»: неизвестные значения "
                f"{', '.join(repr(item) for item in unknown)}")
    elif field_type == TYPE_NUMBER:
        bad = [item for item in values
               if isinstance(item, bool) or not isinstance(item, (int, float))]
        if bad:
            raise ConditionError(
                f"«{spec.get('label', key)}»: ожидается число, получено "
                f"{', '.join(repr(item) for item in bad)}")
    elif field_type == TYPE_BOOL:
        if op in ORDER_OPS or any(not isinstance(item, bool) for item in values):
            raise ConditionError(
                f"«{spec.get('label', key)}»: ожидается да/нет")
    else:  # TYPE_STRING
        if any(not isinstance(item, str) for item in values):
            raise ConditionError(
                f"«{spec.get('label', key)}»: ожидается строка")


def validate_fields(fields) -> list[dict]:
    """Проверить сам ответ ``fact_fields()`` предметной аппки.

    Ошибка в нём иначе доедет до фронтенда полусломанным справочником, а
    выглядеть будет как баг редактора маршрутов.
    """
    if not isinstance(fields, list):
        raise ConditionError("fact_fields() должен вернуть список")
    for field in fields:
        if not isinstance(field, dict) or not field.get("key"):
            raise ConditionError(f"Поле без ключа: {field!r}")
        field_type = field.get("type", TYPE_STRING)
        if field_type not in FIELD_TYPES:
            raise ConditionError(
                f"Поле «{field['key']}»: неизвестный тип «{field_type}». "
                f"Допустимы: {', '.join(FIELD_TYPES)}")
        if field_type == TYPE_CHOICE:
            options = field.get("options")
            if not isinstance(options, list) or not options:
                raise ConditionError(
                    f"Поле «{field['key']}» типа choice должно перечислить options")
            if any("value" not in option for option in options):
                raise ConditionError(
                    f"Поле «{field['key']}»: у варианта нет value")
    return list(fields)


# ═══════════════════════════════════════════════════════════════════════
# Отбор этапов
# ═══════════════════════════════════════════════════════════════════════

def select_stages(stages: Iterable, facts: dict) -> list[Selected]:
    """Какие этапы маршрута участвуют в процессе для объекта с такими фактами.

    Группа (этапы с одинаковым ``order``) разбирается так:

    1. безусловные этапы участвуют всегда;
    2. из условных участвуют те, чьё условие сошлось;
    3. если не сошлось НИ ОДНО условное — вместо них берутся этапы «иначе»;
    4. если после этого группа пуста — ``NoBranchMatched`` (см. докстринг
       модуля о том, почему это ошибка, а не пропуск группы).

    Этап с непустым условием считается условным, даже если у него взведён
    ``is_fallback``: сочетание бессмысленно, ``route_service`` его не
    пропускает, и молча предпочесть флаг значило бы исполнить не то, что
    написано в условии.
    """
    selected: list[Selected] = []

    by_order = sorted(stages, key=lambda stage: (stage.order, stage.pk))
    for order, group_iter in groupby(by_order, key=lambda stage: stage.order):
        group = list(group_iter)
        conditional = [stage for stage in group if stage.condition]
        fallback = [stage for stage in group
                    if stage.is_fallback and not stage.condition]
        always = [stage for stage in group
                  if not stage.condition and not stage.is_fallback]

        matched = [stage for stage in conditional
                   if evaluate(stage.condition, facts)]
        matched_by = MATCH_CONDITION
        if conditional and not matched:
            matched, matched_by = fallback, MATCH_FALLBACK

        if not always and not matched:
            raise NoBranchMatched(order, facts)

        selected.extend(Selected(stage, MATCH_ALWAYS) for stage in always)
        selected.extend(Selected(stage, matched_by) for stage in matched)

    selected.sort(key=lambda item: (item.stage.order, item.stage.pk))
    return selected


# ═══════════════════════════════════════════════════════════════════════
# Подсказка редактору маршрута
# ═══════════════════════════════════════════════════════════════════════

def coverage_gaps(stages: Iterable, fields: list[dict]) -> list[dict]:
    """Значения справочника, для которых в группе не заведено ни одной ветки.

    Это ровно тот случай, ради которого ``NoBranchMatched`` кричит на запуске:
    завели новую страну, а ветку под неё дописать забыли. Но узнать об этом
    должен администратор маршрута в редакторе, а не пользователь через месяц
    в момент отправки, — поэтому та же дыра ищется заранее и статически.

    Считается только там, где дыра действительно приведёт к отказу: если в
    группе есть безусловный этап или этап «иначе», непокрытое значение —
    это нормальная настройка, а не пробел.

    Работает для любого поля типа ``choice`` и ничего не знает про страны:
    берётся объединение значений всех ``eq``/``in`` группы и вычитается из
    ``options``.
    """
    choice_fields = {field["key"]: field for field in fields
                     if field.get("type") == TYPE_CHOICE}
    if not choice_fields:
        return []

    gaps: list[dict] = []
    by_order = sorted(stages, key=lambda stage: (stage.order, stage.pk))
    for order, group_iter in groupby(by_order, key=lambda stage: stage.order):
        group = list(group_iter)
        if any(stage.is_fallback or not stage.condition for stage in group):
            continue

        covered: dict[str, set] = {}
        for stage in group:
            for predicate in stage.condition or []:
                try:
                    field, op, value = _unpack(predicate)
                except ConditionError:
                    continue  # сломанный предикат — забота validate(), не эта
                if field not in choice_fields or op not in (OP_EQ, OP_IN):
                    continue
                covered.setdefault(field, set()).update(
                    value if op == OP_IN else [value])

        for key, seen in covered.items():
            missing = [option for option in choice_fields[key].get("options", [])
                       if option["value"] not in seen]
            if missing:
                gaps.append({
                    "order": order,
                    "field": key,
                    "label": choice_fields[key].get("label", key),
                    "missing": missing,
                })
    return gaps

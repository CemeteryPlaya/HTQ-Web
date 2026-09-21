"""Перевод графа старого движка (``workflow_json``) в этапы маршрута signoff.

Чистая функция над графом: ни БД, ни HTTP. Результат — список описаний
этапов (``StageSpec``) в терминах signoff либо список причин, почему граф
не переносится. Создаёт маршрут и решает, что делать с непереносимым,
команда ``migrate_workflows_to_signoff``.

Что переносится — ровно то, что выражается «группами этапов по order»:

* цепочка узлов ``approval`` → этапы 1..n; ``mode`` ``any`` → кворум
  «достаточно одного», ``all``/``sequential`` → «нужны все»;
* узел ``condition`` с двумя ветками, каждая из которых ведёт не более чем
  к одному ``approval`` и обе сходятся в одном узле → группа из этапа с
  условием (ветка ``true``) и этапа «иначе» (ветка ``false``);
* JsonLogic ``==``, ``!=``, ``>``, ``>=``, ``<``, ``<=``, ``in`` по полю
  формы и ``and`` из них → плоские предикаты signoff;
* согласующие ``user``/``users`` → «поимённо», ``initiator`` → инициатор,
  ``project_admins`` и ``field_ref`` → «назначает объект».

Что НЕ переносится и почему — в тексте проблемы, по одной на причину:
ветка без этапа (у signoff группа без сработавшего этапа роняет запуск —
нужен явный этап «иначе»), отказ, ведущий не в ``end_rejected``, ``or``/
арифметика/``if`` в условии, ``department_head``/``initiator_supervisor``/
``role`` (не работали и в старом движке), узлы ``parallel``/``acknowledge``
(рантайм их не исполнял). Такой шаблон администратор настраивает руками.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .workflow_schema import WorkflowGraph, WorkflowNode, validate_workflow

PASSIVE = {"start", "notify"}
_OPS = {">": "gt", ">=": "gte", "<": "lt", "<=": "lte"}


@dataclass
class StageSpec:
    order: int
    name: str
    quorum: str                      # "any" | "all"
    approver_kind: str               # "position" | "initiator" | "users" | "subject"
    position_ids: list[int] = field(default_factory=list)
    user_ids: list[int] = field(default_factory=list)
    approver_key: str = ""
    condition: list[dict] = field(default_factory=list)
    is_fallback: bool = False


@dataclass
class Conversion:
    stages: list[StageSpec] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems and bool(self.stages)


class _Unconvertible(Exception):
    pass


def convert_graph(workflow_json: dict) -> Conversion:
    """Граф → этапы signoff или список причин отказа."""
    try:
        graph = validate_workflow(workflow_json)
    except Exception as exc:  # noqa: BLE001 — pydantic/ValueError
        return Conversion(problems=[f"граф не проходит валидацию: {exc}"])

    # Название узла конструктор кладёт в ``name``, которого в pydantic-схеме
    # нет (лишние поля отбрасываются) — берём из сырого JSON.
    names = {str(n.get("id")): str(n.get("name") or "")
             for n in (workflow_json or {}).get("nodes", []) if isinstance(n, dict)}
    converter = _Converter(graph, names)
    try:
        converter.run()
    except _Unconvertible as exc:
        return Conversion(problems=[str(exc)])
    if not converter.stages:
        return Conversion(problems=[
            "в графе нет ни одного этапа согласования — у signoff маршрут без "
            "этапов невозможен"])
    return Conversion(stages=converter.stages)


class _Converter:
    def __init__(self, graph: WorkflowGraph, names: dict[str, str] | None = None):
        self.graph = graph
        self.names = names or {}
        self.nodes: dict[str, WorkflowNode] = {n.id: n for n in graph.nodes}
        self.stages: list[StageSpec] = []
        self.order = 0

    # ── обход ────────────────────────────────────────────────────────────

    def run(self) -> None:
        start = next(n for n in self.graph.nodes if n.type == "start")
        current = self._skip_passive(self._single_target(start.id))
        guard = 0
        while True:
            guard += 1
            if guard > 64:
                raise _Unconvertible("обход графа превысил 64 шага")
            node = self.nodes[current]
            if node.type == "end_approved":
                return
            if node.type == "end_rejected":
                raise _Unconvertible(
                    "основной путь ведёт в отказ (end_rejected) — так маршрут "
                    "не выражается")
            if node.type == "approval":
                self.order += 1
                self.stages.append(self._stage(node, self.order))
                current = self._after_approval(node)
                continue
            if node.type == "condition":
                current = self._condition_group(node)
                continue
            raise _Unconvertible(
                f"узел «{node.id}» типа {node.type} рантайм не исполнял — "
                f"уберите его из маршрута")

    def _skip_passive(self, node_id: str) -> str:
        seen = 0
        while self.nodes[node_id].type in PASSIVE:
            seen += 1
            if seen > 64:
                raise _Unconvertible("цикл из пассивных узлов")
            node_id = self._single_target(node_id)
        return node_id

    def _single_target(self, node_id: str) -> str:
        edges = [e for e in self.graph.edges
                 if e.from_ == node_id and e.on is None and e.when is None]
        if len(edges) != 1:
            raise _Unconvertible(
                f"у узла «{node_id}» должно быть ровно одно исходящее ребро, "
                f"найдено {len(edges)}")
        return edges[0].to

    def _labelled_target(self, node_id: str, *, on: str | None = None,
                         when: str | None = None) -> str:
        edges = [e for e in self.graph.edges
                 if e.from_ == node_id and e.on == on and e.when == when]
        if len(edges) != 1:
            label = f"on={on}" if on else f"when={when}"
            raise _Unconvertible(
                f"у узла «{node_id}» должно быть ровно одно ребро {label}, "
                f"найдено {len(edges)}")
        return edges[0].to

    def _after_approval(self, node: WorkflowNode) -> str:
        """Ребро ``reject`` обязано вести в отказ: у signoff отказ закрывает
        круг, и «отказ → другой этап» выразить нечем."""
        reject_to = self._skip_passive(self._labelled_target(node.id, on="reject"))
        if self.nodes[reject_to].type != "end_rejected":
            raise _Unconvertible(
                f"отказ на этапе «{node.id}» ведёт в «{reject_to}», а не в "
                f"end_rejected — у signoff отказ всегда закрывает согласование")
        return self._skip_passive(self._labelled_target(node.id, on="approve"))

    def _condition_group(self, node: WorkflowNode) -> str:
        """``condition`` → группа: этап с условием + этап «иначе»."""
        if not node.expr:
            raise _Unconvertible(f"у условия «{node.id}» нет выражения")
        predicates = _predicates(node.expr, node.id)

        branches: dict[str, tuple[WorkflowNode | None, str]] = {}
        for when in ("true", "false"):
            target = self._skip_passive(self._labelled_target(node.id, when=when))
            target_node = self.nodes[target]
            if target_node.type == "approval":
                branches[when] = (target_node, self._after_approval(target_node))
            elif target_node.type in ("end_approved", "condition"):
                branches[when] = (None, target)
            else:
                raise _Unconvertible(
                    f"ветка «{when}» условия «{node.id}» ведёт в узел типа "
                    f"{target_node.type} — переносятся только этапы и конец")

        yes_node, yes_next = branches["true"]
        no_node, no_next = branches["false"]
        if yes_node is None or no_node is None:
            raise _Unconvertible(
                f"у условия «{node.id}» есть ветка без этапа — у signoff "
                f"группа без сработавшего этапа роняет запуск; добавьте на "
                f"эту ветку этап «иначе» руками")
        if yes_next != no_next:
            raise _Unconvertible(
                f"ветки условия «{node.id}» не сходятся в одном узле "
                f"(«{yes_next}» и «{no_next}») — такой граф не выражается "
                f"группами этапов")

        self.order += 1
        yes = self._stage(yes_node, self.order)
        yes.condition = predicates
        no = self._stage(no_node, self.order)
        no.is_fallback = True
        self.stages.extend([yes, no])
        return yes_next

    # ── этап ─────────────────────────────────────────────────────────────

    def _stage(self, node: WorkflowNode, order: int) -> StageSpec:
        name = self.names.get(node.id) or f"Этап {order}"
        # Старый движок считал узел без ``mode`` как ``any``
        # (``request_runtime._advance``).
        quorum = "any" if (node.mode or "any") == "any" else "all"
        spec = StageSpec(order=order, name=name, quorum=quorum,
                         approver_kind="position")
        assignee = node.assignee or {}
        kind = assignee.get("kind")
        if kind == "user":
            spec.approver_kind = "users"
            spec.user_ids = [int(assignee["id"])] if assignee.get("id") is not None else []
        elif kind == "users":
            spec.approver_kind = "users"
            spec.user_ids = [int(x) for x in assignee.get("ids") or []]
        elif kind == "initiator":
            spec.approver_kind = "initiator"
        elif kind == "project_admins":
            spec.approver_kind = "subject"
            spec.approver_key = "project_admins"
        elif kind == "field_ref":
            spec.approver_kind = "subject"
            spec.approver_key = f"field:{assignee.get('field', '')}"
        else:
            raise _Unconvertible(
                f"согласующий «{kind}» на этапе «{node.id}» не переносится "
                f"(в старом движке он не работал) — назначьте согласующих руками")
        if spec.approver_kind == "users" and not spec.user_ids:
            raise _Unconvertible(f"на этапе «{node.id}» не назван ни один согласующий")
        return spec


# ── JsonLogic → предикаты signoff ───────────────────────────────────────

def _var(arg, node_id: str) -> str:
    if isinstance(arg, dict) and isinstance(arg.get("var"), str):
        name = arg["var"]
        if "." in name:
            raise _Unconvertible(
                f"условие «{node_id}» ссылается на вложенное поле «{name}» — "
                f"факты signoff только верхнего уровня")
        return name
    raise _Unconvertible(
        f"условие «{node_id}»: слева от оператора должно быть поле формы")


def _literal(arg, node_id: str):
    if isinstance(arg, (dict, list)) and not (isinstance(arg, list) and
                                              all(not isinstance(x, (dict, list)) for x in arg)):
        raise _Unconvertible(
            f"условие «{node_id}»: справа от оператора должен быть литерал")
    return arg


def _predicates(expr, node_id: str) -> list[dict]:
    if not isinstance(expr, dict) or len(expr) != 1:
        raise _Unconvertible(f"условие «{node_id}» имеет неподдерживаемую форму")
    op, args = next(iter(expr.items()))
    if op == "and":
        out: list[dict] = []
        for item in args if isinstance(args, list) else [args]:
            out.extend(_predicates(item, node_id))
        return out
    if not isinstance(args, list) or len(args) != 2:
        raise _Unconvertible(
            f"условие «{node_id}»: оператор {op} ожидает два аргумента")
    if op in ("==", "==="):
        return [{"field": _var(args[0], node_id), "op": "eq",
                 "value": _literal(args[1], node_id)}]
    if op in ("!=", "!=="):
        return [{"field": _var(args[0], node_id), "op": "not_in",
                 "value": [_literal(args[1], node_id)]}]
    if op in _OPS:
        return [{"field": _var(args[0], node_id), "op": _OPS[op],
                 "value": _literal(args[1], node_id)}]
    if op == "in":
        values = _literal(args[1], node_id)
        if not isinstance(values, list):
            raise _Unconvertible(f"условие «{node_id}»: «in» ожидает список справа")
        return [{"field": _var(args[0], node_id), "op": "in", "value": values}]
    raise _Unconvertible(
        f"условие «{node_id}»: оператор «{op}» не переносится (signoff "
        f"поддерживает только =, ≠, <, ≤, >, ≥, «одно из» и И)")

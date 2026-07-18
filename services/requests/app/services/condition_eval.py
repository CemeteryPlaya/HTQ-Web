"""Minimal JsonLogic evaluator for workflow condition nodes.

We hand-roll a small subset rather than depend on the unmaintained PyPI
``json-logic`` (broken under Python 3.14). Operators covered:

  Comparison:    >  <  >=  <=  ==  !=
  Logic:         and  or  !  if
  Arithmetic:    +  -  *  /
  Membership:    in
  Variable:      var  (supports dot-path, e.g. {"var": "items.0.price"})
  Literals:      any non-dict / dict without a known op key passes through.

Structural validation of the expression (e.g. that `var` refs point at known
field keys) lives in template_validation; runtime eval here is permissive
about unknowns — missing variables resolve to ``None`` and most comparisons
with ``None`` yield ``False``."""

from __future__ import annotations

from typing import Any


def _get_var(path: Any, values: dict) -> Any:
    if isinstance(path, list) and path and isinstance(path[0], str):
        path = path[0]
    if not isinstance(path, str):
        return None
    cur: Any = values
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if cur is None:
            return None
    return cur


def _coerce_pair(a: Any, b: Any) -> tuple[Any, Any]:
    """Best-effort numeric coercion so ``{"=": ["1", 1]}`` matches JsonLogic."""
    if isinstance(a, (int, float)) and isinstance(b, str):
        try:
            return a, type(a)(b)
        except (TypeError, ValueError):
            return a, b
    if isinstance(b, (int, float)) and isinstance(a, str):
        try:
            return type(b)(a), b
        except (TypeError, ValueError):
            return a, b
    return a, b


def _cmp(op: str, args: list[Any]) -> bool:
    if len(args) < 2:
        return False
    a, b = _coerce_pair(args[0], args[1])
    try:
        if op == ">":
            return a > b
        if op == "<":
            return a < b
        if op == ">=":
            return a >= b
        if op == "<=":
            return a <= b
        if op in ("==", "==="):
            return a == b
        if op in ("!=", "!=="):
            return a != b
    except TypeError:
        return False
    return False


def _arith(op: str, args: list[Any]) -> Any:
    nums = []
    for a in args:
        try:
            nums.append(float(a))
        except (TypeError, ValueError):
            return None
    if op == "+":
        return sum(nums)
    if op == "-":
        if len(nums) == 1:
            return -nums[0]
        return nums[0] - sum(nums[1:])
    if op == "*":
        out = 1.0
        for n in nums:
            out *= n
        return out
    if op == "/":
        if len(nums) < 2 or nums[1] == 0:
            return None
        return nums[0] / nums[1]
    return None


def evaluate_raw(expr: Any, values: dict) -> Any:
    """Evaluate ``expr`` against ``values`` and return the raw result."""
    if not isinstance(expr, dict) or not expr:
        return expr
    if len(expr) != 1:
        # JsonLogic spec: an op-dict has exactly one key. Multiple keys = invalid.
        return None

    op, raw_args = next(iter(expr.items()))
    args = raw_args if isinstance(raw_args, list) else [raw_args]

    if op == "var":
        return _get_var(raw_args, values)

    # Recursively evaluate child operations.
    evaluated = [evaluate_raw(a, values) for a in args]

    if op in (">", "<", ">=", "<=", "==", "===", "!=", "!=="):
        return _cmp(op, evaluated)
    if op == "and":
        for v in evaluated:
            if not v:
                return v
        return evaluated[-1] if evaluated else True
    if op == "or":
        for v in evaluated:
            if v:
                return v
        return evaluated[-1] if evaluated else False
    if op == "!":
        return not bool(evaluated[0]) if evaluated else True
    if op == "if":
        # if(cond, then, [elif_cond, elif_then, ...], else)
        i = 0
        while i + 1 < len(evaluated):
            if evaluated[i]:
                return evaluated[i + 1]
            i += 2
        return evaluated[i] if i < len(evaluated) else None
    if op in ("+", "-", "*", "/"):
        return _arith(op, evaluated)
    if op == "in":
        if len(evaluated) < 2:
            return False
        needle, haystack = evaluated[0], evaluated[1]
        try:
            return needle in haystack
        except TypeError:
            return False
    # Unknown op → falsy
    return None


def evaluate(expr: Any, values: dict) -> bool:
    """Return the boolean value of ``expr`` evaluated against ``values``."""
    return bool(evaluate_raw(expr, values or {}))

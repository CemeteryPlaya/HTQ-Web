"""Перевести выбранные правила Grafana-провижининга в rule-файл Prometheus.

Зачем: правила алертинга живут в ``infra/logging/grafana-provisioning/
alerting/rules.yml`` (Grafana unified alerting), и ``promtool test rules``
их не читает. Провижининг проверяет, что правило ПРИНЯТО, но не что оно
СРАБОТАЕТ. Этот генератор строит из правила Grafana эквивалентное правило
Prometheus — ``alert: <uid>``, ``expr: (<PromQL запроса>) <op> <порог>``,
``for`` и метки правила, — и ``promtool test rules`` гоняет его на
подложенных рядах (``scripts/check-monitoring-config.sh``, шаг 1б).

Переводится ТОЛЬКО то, что переводится честно, — форма, в которой
написаны все правила Prometheus-группы файла:

* условие правила (``condition``) — выражение ``type: threshold`` с одним
  условием (оценщик ``gt``/``lt``, редуктор ``last``) и без порога
  восстановления (``unloadEvaluator``);
* оно смотрит на запрос к Prometheus с ``instant: true`` — у мгновенного
  вектора одна точка на серию, редуктор ``last`` её и берёт, поэтому
  «значение серии <op> порог» в Grafana и фильтр сравнения в PromQL
  выбирают одни и те же серии с теми же метками;
* ``noDataState: OK`` — «нет серий — нет алерта», как и у Prometheus;
  ``execErrState: OK`` — ошибка запроса не алертит, как и у Prometheus;
* запрос смотрит на момент оценки (``relativeTimeRange.to`` = 0), правило
  не на паузе (``isPaused``).

Всё остальное (``math``/``reduce``, диапазонный запрос, несколько условий,
``within_range``, ``noDataState: Alerting``, сдвиг ``to``, пауза …) отвергается с причиной и
кодом 2, а не переводится «приблизительно»: тест на подделанном выражении
доказывал бы срабатывание не того правила, которое стоит на проде.

Аннотации не переносятся — это шаблоны Grafana (``$values.A``), promtool
их не раскроет.

С ``--tests`` генератор ещё сверяет набор с файлом тестов promtool: у
каждого переведённого правила должна быть проверка «срабатывает»
(непустой ``exp_alerts``) и «молчит» (``exp_alerts: []``) — новое правило
под ``--match`` без тестов роняет шаг, а не проходит молча.

Usage:
    grafana_rules_to_promtool.py RULES_YML OUT_YML [--match SUBSTR]...
        [--uid UID]... [--tests TEST_YML]

Печатает число переведённых правил в stdout; ошибки — в stderr, код 2.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

OPERATORS = {"gt": ">", "lt": "<"}
PROMETHEUS_TYPE = "prometheus"
EXPR_DATASOURCE = "__expr__"


class Untranslatable(Exception):
    """Правило нельзя честно перевести в правило Prometheus."""


def _format_threshold(value) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Untranslatable(f"порог {value!r} — не число")
    return repr(value) if isinstance(value, float) else str(value)


def _node(rule: dict, ref_id: str) -> dict:
    for item in rule.get("data") or []:
        if item.get("refId") == ref_id:
            return item
    raise Untranslatable(f"нет выражения refId={ref_id!r}")


def _is_prometheus_query(item: dict) -> bool:
    model = item.get("model") or {}
    ds = model.get("datasource") or {}
    return item.get("datasourceUid") != EXPR_DATASOURCE and ds.get("type") == PROMETHEUS_TYPE


def _promql(rule: dict) -> str | None:
    """PromQL запроса правила (для ``--match``), если правило — к Prometheus."""
    for item in rule.get("data") or []:
        if _is_prometheus_query(item):
            return (item.get("model") or {}).get("expr")
    return None


def translate(rule: dict) -> dict:
    """Правило Grafana → правило Prometheus (словарь для rule-файла)."""
    uid = rule.get("uid")
    condition = rule.get("condition")
    if not condition:
        raise Untranslatable("нет condition")
    cond = _node(rule, condition)
    if cond.get("datasourceUid") != EXPR_DATASOURCE:
        raise Untranslatable(f"условие {condition} — не выражение сервера (__expr__)")
    model = cond.get("model") or {}
    if model.get("type") != "threshold":
        raise Untranslatable(
            f"условие {condition} — type: {model.get('type')!r}, переводится только threshold")
    if model.get("unloadEvaluator"):
        raise Untranslatable("у threshold есть порог восстановления (unloadEvaluator)")
    conditions = model.get("conditions") or []
    if len(conditions) != 1:
        raise Untranslatable(f"у threshold {len(conditions)} условий, переводится ровно одно")
    evaluator = conditions[0].get("evaluator") or {}
    op = OPERATORS.get(evaluator.get("type"))
    if op is None:
        raise Untranslatable(f"оценщик {evaluator.get('type')!r} — переводятся только gt/lt")
    params = evaluator.get("params") or []
    if len(params) != 1:
        raise Untranslatable(f"у оценщика {len(params)} параметров, ждали один порог")
    threshold = _format_threshold(params[0])
    reducer = (conditions[0].get("reducer") or {}).get("type")
    if reducer not in (None, "last"):
        raise Untranslatable(f"редуктор {reducer!r} — переводится только last")

    query = _node(rule, model.get("expression"))
    if not _is_prometheus_query(query):
        raise Untranslatable(f"threshold смотрит на {model.get('expression')!r} — не запрос к Prometheus")
    qmodel = query.get("model") or {}
    if qmodel.get("instant") is not True or qmodel.get("range"):
        raise Untranslatable("запрос не мгновенный (instant: true) — редуктор свёл бы диапазон")
    expr = (qmodel.get("expr") or "").strip()
    if not expr:
        raise Untranslatable("пустой PromQL")
    time_range = query.get("relativeTimeRange") or {}
    if time_range.get("to", 0) != 0:
        raise Untranslatable(
            f"relativeTimeRange.to = {time_range.get('to')} — запрос смотрит в прошлое, "
            "а правило Prometheus — на момент оценки")
    no_data = rule.get("noDataState", "NoData")
    if no_data != "OK":
        raise Untranslatable(f"noDataState: {no_data} — у Prometheus «нет данных» не алертит")
    exec_err = rule.get("execErrState", "Error")
    if exec_err != "OK":
        raise Untranslatable(
            f"execErrState: {exec_err} — у Prometheus ошибка запроса не алертит")
    if rule.get("isPaused"):
        raise Untranslatable("правило на паузе (isPaused: true) — в Grafana оно не оценивается")

    out = {"alert": uid, "expr": f"({expr}) {op} {threshold}"}
    if rule.get("for"):
        out["for"] = str(rule["for"])
    if rule.get("labels"):
        out["labels"] = {str(k): str(v) for k, v in rule["labels"].items()}
    return out


def _select(groups: list, matches: list[str], uids: list[str]):
    """(группа, правило) по --match (подстрока PromQL) и --uid, в порядке файла."""
    wanted = set(uids)
    found: set[str] = set()
    for group in groups:
        for rule in group.get("rules") or []:
            uid = rule.get("uid")
            expr = _promql(rule) or ""
            if uid in wanted or any(m in expr for m in matches):
                found.add(uid)
                yield group, rule
    missing = wanted - found
    if missing:
        raise SystemExit(_err(f"правила не найдены: {', '.join(sorted(missing))}"))


def _err(message: str) -> int:
    print(f"grafana_rules_to_promtool: {message}", file=sys.stderr)
    return 2


def _check_tests(tests_path: Path, uids: list[str]) -> list[str]:
    """Причины, по которым тесты не покрывают переведённые правила."""
    doc = yaml.safe_load(tests_path.read_text(encoding="utf-8")) or {}
    fires: set[str] = set()
    silent: set[str] = set()
    for test in doc.get("tests") or []:
        for case in test.get("alert_rule_test") or []:
            name = case.get("alertname")
            (fires if case.get("exp_alerts") else silent).add(name)
    problems = []
    for uid in uids:
        if uid not in fires:
            problems.append(f"{uid}: нет проверки «срабатывает» (непустой exp_alerts)")
        if uid not in silent:
            problems.append(f"{uid}: нет проверки «молчит» (exp_alerts: [])")
    unknown = (fires | silent) - set(uids)
    for name in sorted(unknown):
        problems.append(f"{name}: в тестах есть, среди переведённых правил нет")
    return problems


def main(argv: list[str] | None = None) -> int:
    # На Windows консоль Git Bash — не cp1251, и русские причины отказа
    # выходили бы кракозябрами (PYTHONIOENCODING там обычно не задан).
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("rules", type=Path, help="rules.yml Grafana-провижининга")
    parser.add_argument("out", type=Path, help="куда записать rule-файл Prometheus")
    parser.add_argument("--match", action="append", default=[],
                        help="взять правила, чей PromQL содержит подстроку (можно повторять)")
    parser.add_argument("--uid", action="append", default=[],
                        help="взять правило по uid (можно повторять)")
    parser.add_argument("--tests", type=Path,
                        help="файл promtool test rules: сверить покрытие правил")
    args = parser.parse_args(argv)
    if not args.match and not args.uid:
        return _err("не задано ни --match, ни --uid — переводить нечего")

    doc = yaml.safe_load(args.rules.read_text(encoding="utf-8")) or {}
    out_groups: dict[str, dict] = {}
    problems: list[str] = []
    uids: list[str] = []
    for group, rule in _select(doc.get("groups") or [], args.match, args.uid):
        try:
            translated = translate(rule)
        except Untranslatable as exc:
            problems.append(f"{rule.get('uid')}: {exc}")
            continue
        name = group.get("name", "grafana")
        target = out_groups.setdefault(name, {
            "name": name, "interval": str(group.get("interval", "1m")), "rules": []})
        target["rules"].append(translated)
        uids.append(translated["alert"])
    if problems:
        return _err("не переводятся честно, тест не строим:\n  " + "\n  ".join(problems))
    if not uids:
        return _err("под --match/--uid не попало ни одного правила")
    if args.tests:
        gaps = _check_tests(args.tests, uids)
        if gaps:
            return _err("тесты не покрывают правила:\n  " + "\n  ".join(gaps))

    args.out.write_text(
        yaml.safe_dump({"groups": list(out_groups.values())},
                       allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    print(len(uids))
    return 0


if __name__ == "__main__":
    sys.exit(main())

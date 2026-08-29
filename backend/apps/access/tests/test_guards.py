"""Задача 10 плана A: сторож изоляции компаний.

Таблицы ``PositionRole`` и ``RoleAssignment`` лежат в ``public`` — роль одна на
все компании, и связать её с тенантной таблицей внешним ключом нельзя (спека
§1.3). Значит ``search_path`` эти строки НЕ разделяет, и единственное, что
отделяет права одной компании от другой, — фильтр ``company_slug`` в каждой
выборке.

Забытый фильтр отдаёт права соседней компании и **не выглядит ошибкой**:
запрос отрабатывает, данные возвращаются, тест домена проходит. Поэтому
проверка механическая, а не «на внимательность» (риск 3 спеки).

Разбор через ``ast``, а не регулярку по строкам: цепочки вызовов в этом коде
разбиты переносами, и построчный поиск пропускал бы ровно те места, ради
которых сторож написан.
"""

from __future__ import annotations

import ast
import pathlib

SERVICES = pathlib.Path(__file__).resolve().parents[1] / "services"

# Модели, у которых компания — часть ключа, а не уточнение.
TENANT_MODELS = {"PositionRole", "RoleAssignment"}

QUERY_METHODS = {"filter", "get", "exclude", "get_or_create", "update_or_create"}


def _chain(node: ast.Call) -> tuple[str | None, set[str]]:
    """Корень цепочки ``Model.objects…`` и все именованные аргументы в ней."""
    keywords: set[str] = set()
    current: ast.AST = node
    while isinstance(current, ast.Call) and isinstance(current.func, ast.Attribute):
        keywords.update(kw.arg for kw in current.keywords if kw.arg)
        current = current.func.value
    if (isinstance(current, ast.Attribute) and current.attr == "objects"
            and isinstance(current.value, ast.Name)):
        return current.value.id, keywords
    return None, keywords


def _queries_without_company() -> list[str]:
    offenders: list[str] = []
    for path in sorted(SERVICES.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            # 1. Выборки: Model.objects.filter(...) и соседи по цепочке.
            if isinstance(node.func, ast.Attribute) and node.func.attr in QUERY_METHODS:
                model, keywords = _chain(node)
                if model in TENANT_MODELS and "company_slug" not in keywords:
                    offenders.append(f"{path.name}:{node.lineno} выборка {model}")

            # 2. Конструкторы: company_slug — CharField без null, и забытый
            #    аргумент запишет ПУСТУЮ строку, а не упадёт.
            if isinstance(node.func, ast.Name) and node.func.id in TENANT_MODELS:
                if "company_slug" not in {kw.arg for kw in node.keywords if kw.arg}:
                    offenders.append(
                        f"{path.name}:{node.lineno} создание {node.func.id}")
    return offenders


def test_every_tenant_query_carries_company():
    offenders = _queries_without_company()
    assert offenders == [], (
        "выборка или запись без company_slug — права утекут в соседнюю "
        f"компанию: {offenders}"
    )


def test_the_guard_actually_catches_a_violation(tmp_path, monkeypatch):
    """Сторож без самопроверки — украшение: он обязан уметь падать.

    Проверяется на подставном модуле, а не на порче настоящего: сторож,
    который молча перестал что-либо находить (сменилось имя модели, съехал
    разбор), выглядит зелёным ровно так же, как работающий.
    """
    module = tmp_path / "leaky.py"
    module.write_text(
        "from apps.access.models import RoleAssignment\n"
        "def leak(user_id):\n"
        "    return RoleAssignment.objects.filter(user_id=user_id)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        __import__("apps.access.tests.test_guards", fromlist=["x"]),
        "SERVICES", tmp_path)
    assert _queries_without_company() != []

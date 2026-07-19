"""Границы аппок: сосед — только через interface.py.

Это исполняемая версия правила из Global Constraints мастер-плана (риск Р4).
Без него договорённость разъедется на третьей фазе.

interface.py тоже сканируется (раньше был целиком исключён — единственный
файл, который обязана писать каждая аппка, был слепой зоной для этой же
проверки). Свой собственный импорт (apps.<x>.interface импортирует
apps.<x>.models) и так разрешён веткой own_app ниже, так что отдельное
исключение было ещё и избыточным.

Известные, принятые пробелы (относительные импорты вида `from ..users import
models` и `importlib`) не детектируются. Сейчас в apps/ таких импортов нет —
это просто документация, чтобы пробел не переоткрывали заново."""
import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parents[3]
APPS_DIR = BACKEND / "apps"

# from apps.<other>.<module> import ...  /  import apps.<other>.<module>
_CROSS_IMPORT_MODULE = re.compile(r"^\s*(?:from|import)\s+apps\.(\w+)\.(\w+)")

# from apps.<other> import <name>  (однослойная форма — без под-модуля перед import)
_CROSS_IMPORT_FROM_SINGLE = re.compile(r"^\s*from\s+apps\.(\w+)\s+import\s+(\w+)")

# import apps.<other>  (голый импорт пакета аппки целиком, без под-модуля)
_CROSS_IMPORT_BARE = re.compile(r"^\s*import\s+apps\.(\w+)\s*(?:as\s+\w+)?\s*$")

# apps.core — общий фундамент (services/models реестра), его импортировать можно.
_SHARED = {"core"}


def _violations() -> list[str]:
    found = []
    for path in APPS_DIR.rglob("*.py"):
        if "tests" in path.parts:
            continue
        own_app = path.relative_to(APPS_DIR).parts[0]
        rel = path.relative_to(BACKEND)
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            m = _CROSS_IMPORT_MODULE.match(line)
            if m:
                other_app, module = m.group(1), m.group(2)
                if other_app not in (own_app, *_SHARED) and module != "interface":
                    found.append(f"{rel}:{lineno}: {own_app} -> apps.{other_app}.{module}")
                continue

            m = _CROSS_IMPORT_FROM_SINGLE.match(line)
            if m:
                other_app, name = m.group(1), m.group(2)
                if other_app not in (own_app, *_SHARED) and name != "interface":
                    found.append(f"{rel}:{lineno}: {own_app} -> apps.{other_app}.{name}")
                continue

            m = _CROSS_IMPORT_BARE.match(line)
            if m:
                other_app = m.group(1)
                if other_app not in (own_app, *_SHARED):
                    found.append(f"{rel}:{lineno}: {own_app} -> apps.{other_app}")
                continue
    return found


def test_apps_only_reach_each_other_through_interface():
    violations = _violations()
    assert violations == [], (
        "Аппки общаются только через apps.<x>.interface:\n  " + "\n  ".join(violations))

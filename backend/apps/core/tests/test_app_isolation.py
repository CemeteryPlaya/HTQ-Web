"""Границы аппок: сосед — только через interface.py.

Это исполняемая версия правила из Global Constraints мастер-плана (риск Р4).
Без него договорённость разъедется на третьей фазе."""
import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parents[3]
APPS_DIR = BACKEND / "apps"

# from apps.<other>.<module> import ...  /  import apps.<other>.<module>
_CROSS_IMPORT = re.compile(r"^\s*(?:from|import)\s+apps\.(\w+)\.(\w+)")

# apps.core — общий фундамент (services/models реестра), его импортировать можно.
_SHARED = {"core"}


def _violations() -> list[str]:
    found = []
    for path in APPS_DIR.rglob("*.py"):
        if "tests" in path.parts or path.name == "interface.py":
            continue
        own_app = path.relative_to(APPS_DIR).parts[0]
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            m = _CROSS_IMPORT.match(line)
            if not m:
                continue
            other_app, module = m.group(1), m.group(2)
            if other_app in (own_app, *_SHARED):
                continue
            if module != "interface":
                rel = path.relative_to(BACKEND)
                found.append(f"{rel}:{lineno}: {own_app} -> apps.{other_app}.{module}")
    return found


def test_apps_only_reach_each_other_through_interface():
    violations = _violations()
    assert violations == [], (
        "Аппки общаются только через apps.<x>.interface:\n  " + "\n  ".join(violations))

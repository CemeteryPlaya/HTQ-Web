"""«Сегодня» на платформе одно — ``timezone.localdate()``.

``date.today()`` — дата ХОСТА, ``timezone.now().date()`` — дата UTC, а
записи (сводка согласований, отчёты, доски) датируются днём в поясе
платформы (``TIME_ZONE``). Пока все три совпадают, смесь не видна; стоит
поясу платформы отличаться — несколько часов в сутки запись и чтение смотрят
в разные дни. Разбор — ``ast``: строки и комментарии не считаются.

Зона второго разработчика (``contracts``, ``signoff``) не сканируется —
правило к ней не применялось и навязывать его не нам. Миграции — история.
"""
import ast
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[3]
_OTHER_DEVELOPER = {"contracts", "signoff"}


def _foreign_dates(text: str):
    """(lineno, форма) для ``date.today()`` и ``<…>.now().date()``."""
    for node in ast.walk(ast.parse(text)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and not node.args):
            continue
        func = node.func
        owner = func.value
        if func.attr == "today" and (
            (isinstance(owner, ast.Name) and owner.id == "date")
            or (isinstance(owner, ast.Attribute) and owner.attr == "date")
        ):
            yield node.lineno, "date.today()"
        elif (func.attr == "date" and isinstance(owner, ast.Call)
              and isinstance(owner.func, ast.Attribute) and owner.func.attr == "now"):
            yield node.lineno, "now().date()"


def _scanned_files():
    for root in (BACKEND / "apps", BACKEND / "htqweb"):
        for path in sorted(root.rglob("*.py")):
            parts = path.relative_to(BACKEND).parts
            if "migrations" in parts:
                continue
            if parts[0] == "apps" and len(parts) > 1 and parts[1] in _OTHER_DEVELOPER:
                continue
            yield path


def test_today_is_taken_in_the_platform_time_zone():
    offenders = [
        f"{path.relative_to(BACKEND).as_posix()}:{lineno} {form}"
        for path in _scanned_files()
        for lineno, form in _foreign_dates(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], (
        "«сегодня» берётся не в поясе платформы — замените на "
        "django.utils.timezone.localdate(): %s" % offenders
    )


_SAMPLE = '''
import datetime
import datetime as dt
from datetime import date
from django.utils import timezone

a = date.today()
b = dt.date.today()
c = datetime.date.today()
d = timezone.now().date()
e = timezone.localdate()
f = timezone.now().astimezone(dt.timezone.utc).date()
g = "date.today()"
'''


def test_guard_sees_every_foreign_form():
    assert [form for _lineno, form in _foreign_dates(_SAMPLE)] == [
        "date.today()", "date.today()", "date.today()", "now().date()",
    ]

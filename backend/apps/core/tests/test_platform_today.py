"""«Сегодня» в ``hr``/``tasks``/``approvals`` одно — ``timezone.localdate()``.

``date.today()``/``datetime.today()`` — дата ХОСТА, ``timezone.now().date()`` —
дата UTC, а записи (сводка согласований, отчёты, доски) датируются днём в
поясе хранения (``TIME_ZONE``, в проде UTC). Пока все три совпадают, смесь не
видна; стоит ``TIME_ZONE`` отличаться — несколько часов в сутки запись и
чтение смотрят в разные дни. Разбор — ``ast``: строки и комментарии не
считаются.

Зона второго разработчика (``contracts``, ``signoff``) не сканируется —
правило к ней не применялось и навязывать его не нам. Миграции — история.

Не путать с ``PLATFORM_TIME_ZONE`` (``apps/conference/services/platform_time.py``)
— пояс людей для границ суток конференций; ``platform_time.today()`` сторож
не трогает намеренно. С 00:00 до 05:00 по Алматы эти два «сегодня» расходятся
на день (roadmap §9.2).
"""
import ast
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[3]
_OTHER_DEVELOPER = {"contracts", "signoff"}


def _foreign_dates(text: str):
    """(lineno, форма) для ``date.today()``/``datetime.today()`` и
    ``<…>.now().date()`` — в том числе при ``from django.utils.timezone
    import now`` (``now().date()``, владелец — голое имя)."""
    for node in ast.walk(ast.parse(text)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and not node.args):
            continue
        func = node.func
        owner = func.value
        if func.attr == "today" and (
            (isinstance(owner, ast.Name) and owner.id in {"date", "datetime"})
            or (isinstance(owner, ast.Attribute) and owner.attr in {"date", "datetime"})
        ):
            yield node.lineno, f"{_owner_name(owner)}.today()"
        elif func.attr == "date" and isinstance(owner, ast.Call) and (
            (isinstance(owner.func, ast.Attribute) and owner.func.attr == "now")
            or (isinstance(owner.func, ast.Name) and owner.func.id == "now")
        ):
            yield node.lineno, "now().date()"


def _owner_name(owner) -> str:
    return owner.id if isinstance(owner, ast.Name) else owner.attr


def _scanned_files():
    for root in (BACKEND / "apps", BACKEND / "htqweb"):
        for path in sorted(root.rglob("*.py")):
            parts = path.relative_to(BACKEND).parts
            if "migrations" in parts:
                continue
            if parts[0] == "apps" and len(parts) > 1 and parts[1] in _OTHER_DEVELOPER:
                continue
            yield path


def test_today_is_taken_in_settings_time_zone():
    offenders = [
        f"{path.relative_to(BACKEND).as_posix()}:{lineno} {form}"
        for path in _scanned_files()
        for lineno, form in _foreign_dates(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], (
        "«сегодня» берётся не в поясе TIME_ZONE — замените на "
        "django.utils.timezone.localdate(): %s" % offenders
    )


_SAMPLE = '''
import datetime
import datetime as dt
from datetime import date
from datetime import datetime as moment
from django.utils import timezone
from django.utils.timezone import now

a = date.today()
b = dt.date.today()
c = datetime.date.today()
d = timezone.now().date()
e = timezone.localdate()
f = timezone.now().astimezone(dt.timezone.utc).date()
g = "date.today()"
h = now().date()
i = datetime.datetime.today().date()
j = dt.datetime.today()
k = moment.today()  # псевдоним класса сторож не разрешает — известная граница
'''


def test_guard_sees_every_foreign_form():
    assert [form for _lineno, form in sorted(_foreign_dates(_SAMPLE))] == [
        "date.today()", "date.today()", "date.today()", "now().date()",
        "now().date()", "datetime.today()", "datetime.today()",
    ]

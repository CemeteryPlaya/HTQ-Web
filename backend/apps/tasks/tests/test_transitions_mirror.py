"""Копия схемы переходов на фронте совпадает с ``TRANSITIONS`` модели.

Доска (``frontend/src/lib/tasks/transitions.ts``) по этой копии гасит
колонки, куда карточку не бросить, и решает, показывать ли кружок
«выполнено». Решает всё равно сервер, поэтому устаревшая копия обхода не даёт,
но даёт лишние отказы или закрытые колонки, куда переход уже разрешён, — и
заметить это можно только руками. Сторож сверяет копию с моделью; в образе
бэкенда без каталога ``frontend`` (тесты внутри контейнера) — пропуск, в CI
репозиторий целиком.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.conf import settings

from apps.tasks.models import TRANSITIONS

MIRROR = Path(settings.BASE_DIR).parent / "frontend" / "src" / "lib" / "tasks" / "transitions.ts"


def _mirror() -> dict[str, frozenset[str]]:
    text = MIRROR.read_text(encoding="utf-8")
    body = text.split("TASK_TRANSITIONS", 1)[1].split("};", 1)[0]
    rows = re.findall(r"^\s*(\w+): \[([^\]]*)\],?\s*$", body, re.MULTILINE)
    return {status: frozenset(re.findall(r"'(\w+)'", targets)) for status, targets in rows}


@pytest.mark.skipif(not MIRROR.exists(), reason="нет каталога frontend рядом с backend")
def test_frontend_transitions_mirror_matches_the_model():
    expected = {str(status): frozenset(map(str, targets)) for status, targets in TRANSITIONS.items()}
    assert _mirror() == expected

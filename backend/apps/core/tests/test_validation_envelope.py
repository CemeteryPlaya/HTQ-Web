"""Конверт ошибки валидации не должен уметь падать.

Найдено сквозным проходом по HR: любое тело запроса, которое не проходит
валидацию И содержит хоть один не-ASCII символ, отвечало голым **500**
вместо 422 — на трёх разных ручках трёх разных аппов, потому что причина
одна и лежит в ``htqweb/http.py``.

Механика: pydantic кладёт в запись об ошибке поле ``input`` — исходное
значение так, как он его увидел. Для тела, разобранного из ``bytes``, это
срез исходных байтов, и на кириллице срез рвётся посередине UTF-8
последовательности. ``exc.json()`` на таком бросает ``ValueError`` ПРЯМО В
обработчике ошибки, внешний ``except Exception`` его не ловит, и наружу
уходит необработанное исключение.

Для пользователя это выглядело так: заполнил форму по-русски, ошибся в
одном поле — получил 500 без единого слова о том, что не так. В проде с
``DEBUG=False`` — просто пустая пятисотка.

Тесты ниже держат инвариант из CLAUDE.md: «конверт ошибок всегда
``{"detail": ...}``».
"""

from __future__ import annotations

import json

import pytest
from django.test import Client
from pydantic import BaseModel, Field, ValidationError

from htqweb.http import validation_detail


class _Sample(BaseModel):
    number: int
    text: str = Field(..., max_length=5)


# ── сама функция ────────────────────────────────────────────────────────

def test_validation_detail_survives_cyrillic():
    """Тот самый случай, который ронял ответ."""
    try:
        _Sample.model_validate_json(
            '{"number": "строка", "text": "Иван"}'.encode("utf-8")
        )
    except ValidationError as exc:
        detail = validation_detail(exc)
    else:                                     # pragma: no cover
        pytest.fail("ожидалась ошибка валидации")

    # Главное: результат сериализуется в JSON без исключения.
    json.dumps(detail)
    assert detail and all({"type", "loc", "msg"} <= set(row) for row in detail)


def test_validation_detail_drops_the_input_echo():
    """``input`` выброшен намеренно — клиент и так знает, что отправил."""
    try:
        _Sample.model_validate_json(b'{"number": "x", "text": "y"}')
    except ValidationError as exc:
        detail = validation_detail(exc)
    else:                                     # pragma: no cover
        pytest.fail("ожидалась ошибка валидации")

    assert all("input" not in row for row in detail)
    assert all("url" not in row for row in detail)


def test_validation_detail_names_the_offending_field():
    """``loc`` обязан называть место — без него 422 бесполезна."""
    try:
        _Sample.model_validate_json(b'{"number": "x", "text": "ok"}')
    except ValidationError as exc:
        detail = validation_detail(exc)
    else:                                     # pragma: no cover
        pytest.fail("ожидалась ошибка валидации")

    assert any("number" in row["loc"] for row in detail)


def test_validation_detail_reports_every_bad_field_at_once():
    """Не первая ошибка, а все — иначе форму чинят по одному полю за круг."""
    try:
        _Sample.model_validate_json(
            '{"number": "строка", "text": "слишком длинно"}'.encode("utf-8")
        )
    except ValidationError as exc:
        detail = validation_detail(exc)
    else:                                     # pragma: no cover
        pytest.fail("ожидалась ошибка валидации")

    assert len(detail) == 2


# ── сквозь настоящую ручку ──────────────────────────────────────────────

BASE = "/api/tasks/v1"


def _auth() -> dict:
    from apps.tasks.tests.helpers import admin_token
    return {"HTTP_AUTHORIZATION": f"Bearer {admin_token()}"}


@pytest.mark.django_db
def test_cyrillic_body_gets_422_not_500():
    """Регрессия. Раньше здесь была голая 500 с трейсбеком."""
    resp = Client().post(
        f"{BASE}/tasks/",
        data='{"summary": "Задача", "project_id": "строка"}'.encode("utf-8"),
        content_type="application/json",
        **_auth(),
    )
    assert resp.status_code == 422, (
        "тело с кириллицей и ошибкой валидации обязано давать 422"
    )
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_latin_body_still_gets_422():
    """Контроль: латиница вела себя правильно и до починки — не сломали."""
    resp = Client().post(
        f"{BASE}/tasks/",
        data=b'{"summary": "Task", "project_id": "notanint"}',
        content_type="application/json",
        **_auth(),
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_multipart_sent_to_a_json_endpoint_gets_422():
    """Форма, отправленная не тем способом, — ошибка клиента, а не сервера."""
    resp = Client().post(
        f"{BASE}/tasks/",
        data={"summary": "Задача"},          # Django закодирует как multipart
        **_auth(),
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_error_envelope_shape_is_unchanged():
    """Форма ответа та же, что вьюхи собирают руками для своих 422."""
    resp = Client().post(
        f"{BASE}/tasks/",
        data='{"summary": "Задача", "priority": "срочно"}'.encode("utf-8"),
        content_type="application/json",
        **_auth(),
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert isinstance(detail, list)
    for row in detail:
        assert {"type", "loc", "msg"} <= set(row)

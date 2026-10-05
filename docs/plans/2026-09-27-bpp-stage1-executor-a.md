# БЗО, этап 1 — исполнитель A (Санжар, ветка `new-module-BPP-sanzhar`)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Построить фундамент, на котором исполнитель B со второго этапа пишет документы модуля:
- коды ошибок ТЗ, идемпотентность и оптимистическая блокировка;
- ядро `bpp`: базовые модели, годовая нумерация, неизменяемый аудит, файлы документов;
- общие справочники `refdata`;
- «Проект»;
- восемь ролей модуля;
- центр уведомлений с ежедневной сводкой, куда переезжает лента задач.

**Architecture:**
- **Платформа.** Общие механизмы (ошибка предметной области, идемпотентность) живут в `htqweb/` и доступны любой аппке. Всё про БЗО — в `apps/bpp`.
- **Схемы.** `refdata` и `notifications` — схема `public`. `bpp` и `project` — схема компании, в `TENANT_APPS` попадают вместе с первой миграцией.
- **Ежедневная сводка** собирается из реестра источников: любая аппка регистрирует функцию «что ждёт этого пользователя». Поэтому центр уведомлений не зависит от signoff, а signoff (задача B1.3) регистрируется сам.

**Tech Stack:** Django 5.2.7, PostgreSQL (схема на компанию), Celery + django-celery-beat, Redis-кэш, httpx, pytest-django (Postgres на `:55432`), React + vitest.

**Spec:** [мастер-план](2026-09-26-bpp-master-plan.md): §1 (решения D-03, D-24, D-28…D-31), §2.4 (узлы прав), §2.5 (нумерация, деньги), §2.6 (контракты), §5 «Этап 1»; ТЗ [§17](../tz/TZ-budget-procurement-payments-v1.0.md) (права), §18 (справочники), §21 (файлы), §22 (уведомления), §26.1 (тексты ошибок).

**Как задачи этого плана соотносятся с мастер-планом:**

| Мастер-план | Этот план |
|---|---|
| A1.1 | задачи 1, 2, 3 |
| A1.2 | задача 4 |
| A1.3 | задача 5 (экран проектов — в A2.4, вместе с экранами справочников) |
| A1.4 | задача 6 |
| A1.5 | задачи 7, 8, 9 |

**Ветки и синхронизация.** Работа идёт в `new-module-BPP-sanzhar`. Ветки мерджит пользователь, до этого A и B друг к другу не мерджат. Поэтому зависимости между ветками этого этапа сделаны через контракты мастер-плана §2.6 и через регистрацию, а не через вызов чужого кода:
- сводка — реестр источников (задача 8);
- signoff регистрируется в нём сам в задаче B1.3.

B на этапе 2 нужен код задач 1–6 этого плана. Когда синхронизировать ветки перед этапом 2, решает пользователь.

---

## Global Constraints

- Интерпретатор — корневой `.venv`. Backend-команды — из `backend/`: `../.venv/Scripts/python.exe -m pytest …`. Postgres для тестов: `docker compose -f docker-compose.test-local.yml up -d db`. Одновременно — один прогон pytest на машине.
- Ветки не создавать. Коммитить только файлы своей задачи. Строка соавторства — если коммит делает агент.
- Межаппный доступ — только `apps.<x>.interface`. Первая строка каждой функции `interface.py` и каждой Celery-задачи — `require_service("<сервис>")`. Задачи тенантных аппок — `@company_task`.
- Каждая ручка новых аппок — `api_view(module="<модуль>", level="read"|"write"|"admin")` с явным уровнем. Исключения — только записью в `apps/access/self_service.py` с причиной `self`/`open`/`scoped`.
- Ошибка предметной области — `{"detail": "<готовый текст>", "code": "<E-код>", "fields": [...]}`. Тексты — дословно из ТЗ §26.1.
- Модели новых аппок: `id = UUIDField(primary_key=True, default=uuid.uuid4, editable=False)`. Денежные суммы — `Decimal`, округление `ROUND_HALF_UP`.
- Модели тенантных аппок не содержат поля компании.
- Метрика — только вместе с панелью или правилом алерта (`apps/core/tests/test_metrics_are_observed.py`). В этом этапе новых метрик нет.
- Подмены значений — только через `htqweb/fallback.py`.
- Новые строки фронта — `t('<ключ>', 'Русский текст')`, переводы не добавлять.
- `STRUCTURE.md`, `CLAUDE.md`, `API.md` обновляются в той же задаче, что меняет структуру или добавляет ручки.

## Review Focus

1. **Двойной клик на записи.** Два одинаковых POST с одним `Idempotency-Key` подряд или одновременно. Ожидается один эффект; второй получает тот же ответ либо 409 «уже выполняется», но не второй документ. Тест — задача 1 (`test_same_key_replays_first_response`, `test_concurrent_same_key_is_rejected`).
2. **Номер под нагрузкой.** Параллельная выдача номеров не даёт дублей, новый год начинает счёт с 1. Тест — задача 2 (`test_parallel_numbers_are_unique`, `test_year_starts_a_new_counter`).
3. **Правка журнала аудита.** `UPDATE`/`DELETE` строки журнала из кода, из админки и сырым SQL падает на уровне БД. Тест — задача 2 (`test_audit_rows_cannot_be_updated_or_deleted`).
4. **Справочник из дочерней компании.** Пользователь с правом правки справочников, но на поддомене дочерней компании, получает 403, а не правит общий для группы справочник. Тест — задача 4 (`test_edit_from_subsidiary_is_forbidden`).
5. **Последний канал уведомлений.** Нельзя выключить все каналы: 422, настройки не меняются. Колокольчик без e-mail и Telegram — допустим. Тест — задача 7 (`test_cannot_disable_every_channel`).

---

## Task 1: Коды ошибок ТЗ и идемпотентность записи (платформа)

**Files:**
- Create: `backend/htqweb/errors.py`, `backend/htqweb/idempotency.py`
- Modify: `backend/htqweb/http.py` (`api_view`: параметр `idempotent`, перехват `DomainError`)
- Test: `backend/apps/core/tests/test_domain_errors.py`, `backend/apps/core/tests/test_idempotency.py`

**Interfaces:**
- Produces:
  - `htqweb.errors.DomainError(code: str, message: str, *, fields: list[dict] | None = None, status: int = 422)` — ручка превращает его в `{"detail", "code", "fields"}`;
  - `api_view(..., idempotent: bool = False)` — повтор с тем же `Idempotency-Key` в течение 24 ч отдаёт первый ответ и заголовок `Idempotent-Replay: true`; одновременный повтор — 409.

- [ ] **Step 1: Падающие тесты ошибки предметной области**

Create `backend/apps/core/tests/test_domain_errors.py`:

```python
"""Ошибка предметной области: текст для человека, код для машины (D-28)."""

import pytest
from django.test import RequestFactory

from htqweb.errors import DomainError
from htqweb.http import api_view


@api_view(methods=("POST",), auth=None)
def _raises(request):
    raise DomainError("E-BUD-02", "По проекту П-015 нет утверждённого бюджета.",
                      fields=[{"field": "project", "message": "нет бюджета"}])


@api_view(methods=("POST",), auth=None)
def _conflict(request):
    raise DomainError("E-CON-01", "Документ изменён.", status=409)


@pytest.mark.django_db
def test_domain_error_becomes_the_tz_envelope():
    response = _raises(RequestFactory().post("/x"))
    assert response.status_code == 422
    assert response.json() == {
        "detail": "По проекту П-015 нет утверждённого бюджета.",
        "code": "E-BUD-02",
        "fields": [{"field": "project", "message": "нет бюджета"}],
    }


@pytest.mark.django_db
def test_domain_error_carries_its_own_status():
    response = _conflict(RequestFactory().post("/x"))
    assert (response.status_code, response.json()["code"]) == (409, "E-CON-01")
    assert response.json()["fields"] == []
```

Run: `../.venv/Scripts/python.exe -m pytest apps/core/tests/test_domain_errors.py -q`
Expected: ошибка сбора — `ModuleNotFoundError: No module named 'htqweb.errors'`.

- [ ] **Step 2: `DomainError` и перехват в `api_view`**

Create `backend/htqweb/errors.py`:

```python
"""Ошибка предметной области — отказ, который пользователь должен прочитать.

``detail`` — готовый текст для человека (у модуля БЗО — дословно из ТЗ §26.1),
``code`` — для машины (фронт по нему выбирает поведение), ``fields`` — какие
поля формы подсветить. Конверт аддитивен к платформенному ``{"detail": ...}``:
фронт, который читает только ``detail``, продолжает работать (решение Q-C21).
"""

from __future__ import annotations


class DomainError(Exception):
    def __init__(self, code: str, message: str, *, fields: list[dict] | None = None,
                 status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.fields = list(fields or [])
        self.status = status

    def payload(self) -> dict:
        return {"detail": self.message, "code": self.code, "fields": self.fields}
```

In `backend/htqweb/http.py`:
1. Добавить импорт `from htqweb.errors import DomainError`.
2. В `api_view` перед `except ServiceDisabled as exc:` вставить:

```python
            except DomainError as exc:
                return JsonResponse(exc.payload(), status=exc.status)
```

Run: `../.venv/Scripts/python.exe -m pytest apps/core/tests/test_domain_errors.py -q`
Expected: 2 passed.

- [ ] **Step 3: Падающие тесты идемпотентности**

Create `backend/apps/core/tests/test_idempotency.py`:

```python
"""Idempotency-Key: повтор записи не создаёт второй документ (AC-013, D-29)."""

import threading

import pytest
from django.core.cache import cache
from django.test import RequestFactory

from htqweb.http import api_view
from htqweb.idempotency import lock_key

CALLS: list[int] = []


@api_view(methods=("POST",), auth=None, status=201, idempotent=True)
def _create(request):
    CALLS.append(1)
    return {"id": len(CALLS)}


def _post(key: str | None = None, path: str = "/api/x"):
    headers = {"HTTP_IDEMPOTENCY_KEY": key} if key else {}
    return _create(RequestFactory().post(path, **headers))


@pytest.fixture(autouse=True)
def _reset():
    CALLS.clear()
    cache.clear()
    yield
    CALLS.clear()


@pytest.mark.django_db
def test_same_key_replays_first_response():
    first = _post("k-1")
    second = _post("k-1")
    assert (first.status_code, first.json()) == (201, {"id": 1})
    assert (second.status_code, second.json()) == (201, {"id": 1})
    assert second["Idempotent-Replay"] == "true"
    assert len(CALLS) == 1


@pytest.mark.django_db
def test_other_key_or_other_path_is_a_new_request():
    _post("k-1")
    _post("k-2")
    _post("k-1", path="/api/y")
    assert len(CALLS) == 3


@pytest.mark.django_db
def test_without_key_every_request_runs():
    _post()
    _post()
    assert len(CALLS) == 2


@pytest.mark.django_db
def test_concurrent_same_key_is_rejected():
    """Второй запрос пришёл, пока первый ещё выполняется: 409, без эффекта."""
    request = RequestFactory().post("/api/x", HTTP_IDEMPOTENCY_KEY="k-busy")
    request.token = None
    cache.add(lock_key(request, "k-busy"), 1, 30)
    response = _create(RequestFactory().post("/api/x", HTTP_IDEMPOTENCY_KEY="k-busy"))
    assert response.status_code == 409
    assert response.json()["code"] == "E-IDEM-01"
    assert CALLS == []


@pytest.mark.django_db
def test_failed_request_is_not_remembered():
    @api_view(methods=("POST",), auth=None, idempotent=True)
    def _boom(request):
        CALLS.append(1)
        raise RuntimeError("упало")

    assert _boom(RequestFactory().post("/api/z", HTTP_IDEMPOTENCY_KEY="k-z")).status_code == 500
    assert _boom(RequestFactory().post("/api/z", HTTP_IDEMPOTENCY_KEY="k-z")).status_code == 500
    assert len(CALLS) == 2
```

Run: `../.venv/Scripts/python.exe -m pytest apps/core/tests/test_idempotency.py -q`
Expected: ошибка сбора — `No module named 'htqweb.idempotency'`.

- [ ] **Step 4: Модуль идемпотентности**

Create `backend/htqweb/idempotency.py`:

```python
"""Idempotency-Key для записывающих ручек (ТЗ §13.4, AC-013, D-29).

Клиент кладёт в заголовок ``Idempotency-Key`` случайный ключ на одно
действие пользователя («Отправить», «Оплатить»). Повтор с тем же ключом —
двойной клик, повтор после таймаута — получает ПЕРВЫЙ ответ, а не второй
эффект. Ключ живёт 24 часа в кэше (Redis на стенде и в проде).

Ключ кэша включает компанию, пользователя, метод и путь: один и тот же
ключ, пришедший на другую ручку или от другого человека, — другой запрос.

Одновременный повтор (первый ещё выполняется) получает 409 «уже
выполняется»: ждать первого внутри запроса значило бы держать воркер
gunicorn, а отдать 200 без тела — соврать.

Запоминается только успешный ответ (< 500): упавший запрос можно повторить
тем же ключом.
"""

from __future__ import annotations

import json

from django.core.cache import cache
from django.http import JsonResponse

from htqweb.errors import DomainError

TTL = 24 * 60 * 60
LOCK_TTL = 60
HEADER = "Idempotency-Key"


def _base(request, key: str) -> str:
    company = getattr(request, "company", None) or {}
    token = getattr(request, "token", None)
    user_id = getattr(token, "user_id", None)
    return f"idem:{company.get('slug', '-')}:{user_id}:{request.method}:{request.path}:{key}"


def lock_key(request, key: str) -> str:
    return _base(request, key) + ":lock"


def key_of(request) -> str | None:
    value = (request.headers.get(HEADER) or "").strip()
    return value[:200] or None


def replay(request, key: str) -> JsonResponse | None:
    """Сохранённый ответ на этот ключ или ``None``."""
    stored = cache.get(_base(request, key))
    if stored is None:
        return None
    response = JsonResponse(stored["body"], status=stored["status"], safe=False)
    response["Idempotent-Replay"] = "true"
    return response


def acquire(request, key: str) -> None:
    """Занять ключ на время выполнения; занят — ``DomainError`` 409."""
    if not cache.add(lock_key(request, key), 1, LOCK_TTL):
        raise DomainError(
            "E-IDEM-01",
            "Этот запрос уже выполняется. Дождитесь результата и обновите страницу.",
            status=409,
        )


def remember(request, key: str, response) -> None:
    if response.status_code >= 500 or not isinstance(response, JsonResponse):
        return
    body = json.loads(response.content or b"null")
    cache.set(_base(request, key), {"status": response.status_code, "body": body}, TTL)


def release(request, key: str) -> None:
    cache.delete(lock_key(request, key))
```

- [ ] **Step 5: Параметр `idempotent` в `api_view`**

In `backend/htqweb/http.py`:

1. Импорт: `from htqweb import idempotency`.
2. Сигнатура:

```python
def api_view(methods=("GET",), auth="jwt", body: type[BaseModel] | None = None,
            status: int = 200, admin: bool = False,
            module: str | None = None, level: str = "read",
            idempotent: bool = False):
```

3. Вынести превращение результата в ответ в функцию модуля (над `api_view`):

```python
def _to_response(result, status: int):
    if isinstance(result, BaseModel):
        return JsonResponse(result.model_dump(mode="json"), status=status)
    if isinstance(result, list) and result and all(isinstance(item, BaseModel) for item in result):
        return JsonResponse(
            [item.model_dump(mode="json") for item in result], safe=False, status=status,
        )
    if isinstance(result, (dict, list)):
        return JsonResponse(result, safe=False, status=status)
    return result  # готовый HttpResponse (файлы, 302, кастомные статусы) — status игнорируется
```

4. Заменить в `view` блок от `if body is not None:` до `return result  # готовый HttpResponse…` на:

```python
                idem_key = idempotency.key_of(request) if idempotent else None
                if idem_key is not None:
                    replayed = idempotency.replay(request, idem_key)
                    if replayed is not None:
                        return replayed
                    idempotency.acquire(request, idem_key)
                try:
                    if body is not None:
                        try:
                            kwargs["data"] = body.model_validate_json(request.body or b"{}")
                        except ValidationError as exc:
                            return JsonResponse({"detail": validation_detail(exc)},
                                                status=422)
                    response = _to_response(fn(request, *args, **kwargs), status)
                    if idem_key is not None:
                        idempotency.remember(request, idem_key, response)
                    return response
                finally:
                    if idem_key is not None:
                        idempotency.release(request, idem_key)
```

Run: `../.venv/Scripts/python.exe -m pytest apps/core/tests/test_idempotency.py apps/core/tests/test_domain_errors.py apps/core/tests/test_api_view.py apps/core/tests/test_validation_envelope.py -q`
Expected: всё PASS.

- [ ] **Step 6: Регрессия HTTP-слоя**

Run: `../.venv/Scripts/python.exe -m pytest apps/core apps/access/tests/test_gate.py apps/tasks/tests -q`
Expected: всё PASS.

- [ ] **Step 7: Документация и коммит**

В `backend/README.md`, раздел про `api_view`, добавить абзац:

```markdown
**Ошибки предметной области и повторы.** `raise htqweb.errors.DomainError(code, message, fields=..., status=422)` в сервисе превращается в `{"detail", "code", "fields"}` — `detail` готов для человека, `code` для фронта. `api_view(..., idempotent=True)` на записывающей ручке: повтор с тем же заголовком `Idempotency-Key` в течение 24 часов отдаёт первый ответ (`Idempotent-Replay: true`), одновременный повтор — 409 `E-IDEM-01`, упавший запрос не запоминается.
```

```bash
git add backend/htqweb/errors.py backend/htqweb/idempotency.py backend/htqweb/http.py backend/apps/core/tests/test_domain_errors.py backend/apps/core/tests/test_idempotency.py backend/README.md
git commit -m "feat(htqweb): ошибка предметной области с кодом и Idempotency-Key у записывающих ручек"
```

---

## Task 2: Ядро `bpp` — базовые модели, нумерация, неизменяемый аудит

**Files:**
- Create: `backend/apps/bpp/models/__init__.py`, `backend/apps/bpp/models/core.py`
- Create: `backend/apps/bpp/migrations/__init__.py`, `backend/apps/bpp/migrations/0001_core.py`
- Create: `backend/apps/bpp/services/__init__.py`, `backend/apps/bpp/services/core/__init__.py`, `numbering.py`, `audit.py`, `errors.py`
- Create: `backend/apps/bpp/admin.py`, `backend/apps/bpp/schemas.py`
- Modify: `backend/apps/bpp/views.py`, `backend/apps/bpp/urls.py`, `backend/htqweb/settings/base.py` (`TENANT_APPS`)
- Test: `backend/apps/bpp/tests/__init__.py`, `backend/apps/bpp/tests/helpers.py`, `backend/apps/bpp/tests/test_numbering.py`, `backend/apps/bpp/tests/test_audit.py`, `backend/apps/bpp/tests/test_conflict.py`

**Interfaces:**
- Consumes: `htqweb.errors.DomainError` (задача 1).
- Produces:
  - `apps.bpp.models.core.BppModel` (абстрактная: `id` UUID, `created_at`, `created_by`, `updated_at`, `updated_by`) и `VersionedModel` (+ `version`);
  - `numbering.next_number(prefix: str, *, width: int = 6, year: int | None = None) -> str` — `"СЧ-2026-000001"`;
  - `audit.record(obj, action: str, *, actor_id: int | None, changes: dict | None = None, comment: str = "") -> None`;
  - `audit.history(object_type: str, object_id: str) -> list[dict]`;
  - `errors.check_version(obj, expected: int | None) -> None` — 409 `E-CON-01` с текстом ТЗ;
  - ручка `GET /api/bpp/v1/history/<object_type>/<object_id>`.

- [ ] **Step 1: Тестовые помощники модуля**

Create `backend/apps/bpp/tests/__init__.py` (пустой) и `backend/apps/bpp/tests/helpers.py`:

```python
"""Помощники тестов модуля БЗО.

Запрос к ручке модуля — это токен с claim ``company`` + заголовок компании +
роль с нужным узлом (без роли гейт модуля отдаёт 403 всем, кроме
суперпользователя; CLAUDE.md, «Модель прав — одна»).
"""

from __future__ import annotations

from apps.access.tests.helpers import assign, token

__all__ = ["assign", "auth"]


def auth(slug: str, *, user_id: int = 7, **claims) -> dict:
    tok = token(user_id=user_id, sub=str(user_id), company=slug, **claims)
    return {"HTTP_AUTHORIZATION": f"Bearer {tok}", "HTTP_X_HTQ_COMPANY": slug}
```

- [ ] **Step 2: Падающие тесты нумерации**

Create `backend/apps/bpp/tests/test_numbering.py`:

```python
"""Годовые номера документов без дублей (§13.3, D-11)."""

import threading

import pytest
from django.db import connection

from apps.bpp.services.core.numbering import next_number


@pytest.mark.django_db
def test_numbers_grow_inside_a_year(company_context):
    assert next_number("СЧ", year=2026) == "СЧ-2026-000001"
    assert next_number("СЧ", year=2026) == "СЧ-2026-000002"
    assert next_number("ДГ", year=2026) == "ДГ-2026-000001"


@pytest.mark.django_db
def test_year_starts_a_new_counter(company_context):
    next_number("СЧ", year=2026)
    assert next_number("СЧ", year=2027) == "СЧ-2027-000001"


@pytest.mark.django_db
def test_width_is_configurable(company_context):
    assert next_number("ВП", year=2026, width=4) == "ВП-2026-0001"


@pytest.mark.django_db(transaction=True)
def test_parallel_numbers_are_unique():
    """20 потоков, по своему соединению каждый: номера не повторяются."""
    got: list[str] = []
    lock = threading.Lock()

    def worker():
        try:
            number = next_number("ЗЗ", year=2026)
            with lock:
                got.append(number)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(got) == 20 and len(set(got)) == 20
```

Run: `../.venv/Scripts/python.exe -m pytest apps/bpp/tests/test_numbering.py -q`
Expected: ошибка сбора — `No module named 'apps.bpp.services'`.

- [ ] **Step 3: Модели ядра**

Create `backend/apps/bpp/models/core.py`:

```python
"""Базовые модели модуля БЗО.

``BppModel`` — общая основа документов: UUID-ключ (ТЗ §24, решение Q-C23),
кто и когда создал и изменил. ``VersionedModel`` добавляет ``version`` —
счётчик правок для оптимистической блокировки (E-CON-01, D-29).
"""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models.functions import Now


class BppModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    created_by = models.IntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())
    updated_by = models.IntegerField(null=True, blank=True)

    class Meta:
        abstract = True


class VersionedModel(BppModel):
    version = models.PositiveIntegerField(default=1, db_default=1)

    class Meta:
        abstract = True


class NumberSequence(models.Model):
    """Годовой счётчик номеров одного вида документа в схеме компании.

    Строка на (префикс, год). Номер выдаёт одна атомарная команда
    ``INSERT … ON CONFLICT DO UPDATE … RETURNING`` (``services/core/
    numbering.py``) — гонка двух выдач невозможна без явной блокировки.
    """

    prefix = models.CharField(max_length=8)
    year = models.PositiveSmallIntegerField()
    last = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["prefix", "year"],
                                               name="uq_bpp_number_prefix_year")]
        verbose_name = "Счётчик номеров"
        verbose_name_plural = "Счётчики номеров"


class AuditLog(models.Model):
    """Журнал изменений документов — только для записи (ТЗ §25.2, D-30).

    Правку и удаление запрещает триггер БД (миграция ``0001_core``): запрет
    только в коде обходится django-admin'ом и сырым SQL. Хранение — 5 лет
    (Q-B32); чистка — отдельной задачей через отключение триггера под
    ролью миграций, не из приложения.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    object_type = models.CharField(max_length=64)
    object_id = models.CharField(max_length=64)
    action = models.CharField(max_length=32)
    actor_id = models.IntegerField(null=True, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    comment = models.TextField(default="", blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        indexes = [models.Index(fields=["object_type", "object_id", "created_at"],
                                name="ix_bpp_audit_object")]
        ordering = ("created_at",)
        verbose_name = "Запись журнала"
        verbose_name_plural = "Журнал изменений"
```

Create `backend/apps/bpp/models/__init__.py`:

```python
"""Модели модуля БЗО. Подмодули импортируются здесь — файл правит только
исполнитель A (мастер-план §0, правило 5); B присылает строку импорта."""

from .core import AuditLog, BppModel, NumberSequence, VersionedModel  # noqa: F401
```

- [ ] **Step 4: Первая миграция с триггером и включение в `TENANT_APPS`**

Сгенерировать миграцию:

```bash
DJANGO_SETTINGS_MODULE=htqweb.settings.dev DB_HOST=localhost DB_PORT=55432 DB_NAME=htqweb DB_USER=htqweb DB_PASSWORD=change-me JWT_SECRET=dev PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe manage.py makemigrations bpp --name core
```

Expected: `apps/bpp/migrations/0001_core.py` с `CreateModel` для `NumberSequence` и `AuditLog`. В конец её `operations` добавить:

```python
        migrations.RunSQL(
            sql=[
                """
                CREATE OR REPLACE FUNCTION bpp_auditlog_immutable() RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'bpp_auditlog: журнал изменений только для записи';
                END;
                $$ LANGUAGE plpgsql;
                """,
                """
                CREATE TRIGGER bpp_auditlog_no_change
                BEFORE UPDATE OR DELETE ON bpp_auditlog
                FOR EACH ROW EXECUTE FUNCTION bpp_auditlog_immutable();
                """,
            ],
            reverse_sql=[
                "DROP TRIGGER IF EXISTS bpp_auditlog_no_change ON bpp_auditlog;",
                "DROP FUNCTION IF EXISTS bpp_auditlog_immutable();",
            ],
        ),
```

и докстринг миграции:

```python
"""Ядро модуля БЗО: счётчики номеров и журнал изменений.

Триггер создаётся в той схеме, где идёт миграция (``migrate_companies``
ставит ``search_path`` на ``co_<slug>``), поэтому у каждой компании свой.
``TRUNCATE`` (фикстуры тестов) строковые триггеры не вызывает.
"""
```

В `backend/htqweb/settings/base.py`:

```python
TENANT_APPS = ("hr", "tasks", "contracts", "signoff", "bpp")
```

и в комментарий над `INSTALLED_APPS` у `apps.bpp` дописать «в TENANT_APPS — с миграции 0001_core».

- [ ] **Step 5: Нумерация**

Create `backend/apps/bpp/services/__init__.py`, `backend/apps/bpp/services/core/__init__.py` (пустые) и `backend/apps/bpp/services/core/numbering.py`:

```python
"""Годовые номера документов: ``ЗЗ-2026-000045``, ``СЧ-2026-000123`` (§13.3).

Одна атомарная команда БД: строка счётчика создаётся с 1 или увеличивается,
новое значение возвращается тем же запросом. Параллельные выдачи
сериализует сама вставка по уникальному ключу (префикс, год).
"""

from __future__ import annotations

from django.db import connection
from django.utils import timezone

from apps.bpp.models import NumberSequence

_SQL = f"""
INSERT INTO {NumberSequence._meta.db_table} (prefix, year, last)
VALUES (%s, %s, 1)
ON CONFLICT (prefix, year)
DO UPDATE SET last = {NumberSequence._meta.db_table}.last + 1
RETURNING last
"""


def next_number(prefix: str, *, width: int = 6, year: int | None = None) -> str:
    year = year or timezone.localdate().year
    with connection.cursor() as cursor:
        cursor.execute(_SQL, [prefix, year])
        (value,) = cursor.fetchone()
    return f"{prefix}-{year}-{value:0{width}d}"
```

Run: `../.venv/Scripts/python.exe -m pytest apps/bpp/tests/test_numbering.py -q`
Expected: 4 passed.

- [ ] **Step 6: Падающие тесты аудита и конфликта версий**

Create `backend/apps/bpp/tests/test_audit.py`:

```python
"""Журнал изменений: пишется, читается, не правится (ТЗ §25.2)."""

import uuid

import pytest
from django.db import DatabaseError, connection, transaction
from django.test import Client

from apps.bpp.models import AuditLog
from apps.bpp.services.core import audit
from apps.bpp.tests.helpers import assign, auth


class _Doc:
    """Документ-заглушка: у аудита спрашивают только тип и ключ."""

    class _meta:  # noqa: N801 — повторяет интерфейс модели
        label_lower = "bpp.probe"

    def __init__(self):
        self.pk = uuid.uuid4()


@pytest.mark.django_db
def test_record_and_history(company_context):
    doc = _Doc()
    audit.record(doc, "created", actor_id=7, changes={"amount": [None, "10.00"]})
    audit.record(doc, "submitted", actor_id=7, comment="на согласование")
    rows = audit.history("bpp.probe", str(doc.pk))
    assert [row["action"] for row in rows] == ["created", "submitted"]
    assert rows[0]["changes"] == {"amount": [None, "10.00"]}
    assert rows[1]["comment"] == "на согласование"


@pytest.mark.django_db
def test_audit_rows_cannot_be_updated_or_deleted(company_context):
    audit.record(_Doc(), "created", actor_id=7)
    row = AuditLog.objects.get()
    with pytest.raises(DatabaseError), transaction.atomic():
        AuditLog.objects.filter(pk=row.pk).update(action="forged")
    with pytest.raises(DatabaseError), transaction.atomic():
        row.delete()
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(f"DELETE FROM {AuditLog._meta.db_table}")
    assert AuditLog.objects.get().action == "created"


@pytest.mark.django_db
def test_history_endpoint_needs_bpp_read(company_context):
    slug = company_context["slug"]
    doc = _Doc()
    audit.record(doc, "created", actor_id=7)
    url = f"/api/bpp/v1/history/bpp.probe/{doc.pk}"
    assert Client().get(url, **auth(slug)).status_code == 403
    assign(slug, 7, "bpp", "view")
    response = Client().get(url, **auth(slug))
    assert response.status_code == 200
    assert [row["action"] for row in response.json()] == ["created"]
```

Create `backend/apps/bpp/tests/test_conflict.py`:

```python
"""Оптимистическая блокировка: E-CON-01 с именем и временем правки (§26.1)."""

from datetime import datetime, timezone as dt_timezone
from types import SimpleNamespace

import pytest

from apps.bpp.services.core.errors import check_version
from apps.users.models import User
from htqweb.errors import DomainError


@pytest.mark.django_db
def test_matching_version_passes():
    check_version(SimpleNamespace(version=3, updated_by=None, updated_at=None), 3)


@pytest.mark.django_db
def test_missing_expected_version_is_not_checked():
    check_version(SimpleNamespace(version=3, updated_by=None, updated_at=None), None)


@pytest.mark.django_db
def test_stale_version_names_who_and_when():
    user = User.objects.create(username="ivanov", email="i@htq.test", password="x",
                               last_name="Иванов", first_name="Алексей")
    obj = SimpleNamespace(version=4, updated_by=user.pk,
                          updated_at=datetime(2026, 9, 27, 9, 32, tzinfo=dt_timezone.utc))
    with pytest.raises(DomainError) as exc:
        check_version(obj, 3)
    assert (exc.value.code, exc.value.status) == ("E-CON-01", 409)
    assert "Иванов" in exc.value.message
    assert "14:32" in exc.value.message  # PLATFORM_TIME_ZONE Asia/Almaty = UTC+5
    assert exc.value.message.endswith("Обновите страницу и внесите их повторно.")
```

Run: `../.venv/Scripts/python.exe -m pytest apps/bpp/tests/test_audit.py apps/bpp/tests/test_conflict.py -q`
Expected: ошибка сбора — нет `apps.bpp.services.core.audit` / `errors`.

- [ ] **Step 7: Аудит, ошибки модуля, ручка истории**

Create `backend/apps/bpp/services/core/audit.py`:

```python
"""Журнал изменений документов модуля (ТЗ §25.2).

``record`` пишет строку в той же транзакции, что и изменение: откатилось
изменение — откатилась и запись. Тип объекта — ``app_label.model`` модели
(``bpp.invoice``), ключ — строка UUID.
"""

from __future__ import annotations

from apps.bpp.models import AuditLog


def record(obj, action: str, *, actor_id: int | None, changes: dict | None = None,
           comment: str = "") -> None:
    AuditLog.objects.create(
        object_type=obj._meta.label_lower, object_id=str(obj.pk), action=action,
        actor_id=actor_id, changes=changes or {}, comment=comment or "",
    )


def history(object_type: str, object_id: str) -> list[dict]:
    rows = AuditLog.objects.filter(object_type=object_type, object_id=object_id)
    return [
        {"id": str(row.id), "action": row.action, "actor_id": row.actor_id,
         "changes": row.changes, "comment": row.comment,
         "created_at": row.created_at.isoformat()}
        for row in rows.order_by("created_at")
    ]
```

Create `backend/apps/bpp/services/core/errors.py`:

```python
"""Ошибки модуля с текстами ТЗ §26.1.

Тексты с подстановками собираются здесь, а не по месту: так один раз и
дословно. Класс исключения — платформенный ``htqweb.errors.DomainError``.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from django.conf import settings

from apps.users import interface as users
from htqweb.errors import DomainError

__all__ = ["DomainError", "check_version"]


def check_version(obj, expected: int | None) -> None:
    """Сверить версию документа из формы с текущей; устарела — E-CON-01.

    ``expected=None`` — клиент версию не прислал (старый клиент, служебный
    вызов): проверка не выполняется.
    """
    if expected is None or int(expected) == int(obj.version):
        return
    name = "другим пользователем"
    if obj.updated_by:
        briefs = users.get_users_brief([obj.updated_by])
        if briefs:
            name = f"пользователем {briefs[0]['full_name']}"
    # Время читает человек — в поясе платформы (PLATFORM_TIME_ZONE, Алматы),
    # а не в поясе хранения TIME_ZONE (UTC).
    zone = ZoneInfo(settings.PLATFORM_TIME_ZONE)
    when = obj.updated_at.astimezone(zone).strftime("%H:%M") if obj.updated_at else "—"
    raise DomainError(
        "E-CON-01",
        f"Документ изменён {name} в {when}. Ваши изменения не сохранены. "
        f"Обновите страницу и внесите их повторно.",
        status=409,
    )
```

`TIME_ZONE` платформы — UTC (пояс хранения), людям время показывается в `PLATFORM_TIME_ZONE` (Asia/Almaty) — поэтому 09:32 UTC в тесте становится 14:32. Год номера (`numbering`) — `timezone.localdate()`, по правилу сторожа `apps/core/tests/test_platform_today.py`.

Replace `backend/apps/bpp/views.py`:

```python
"""Общие ручки модуля: история изменений документа.

Каждая — под гейтом модуля ``bpp`` с явным уровнем.
"""

from htqweb.http import api_view

from .services.core import audit


@api_view(methods=("GET",), module="bpp", level="read")
def object_history(request, object_type: str, object_id: str):
    return audit.history(object_type, object_id)
```

Replace `backend/apps/bpp/urls.py` (сохранить докстринг):

```python
from django.urls import path

from . import views

urlpatterns = [
    path("history/<str:object_type>/<str:object_id>", views.object_history),
    path("history/<str:object_type>/<str:object_id>/", views.object_history),
]
```

Create `backend/apps/bpp/admin.py`:

```python
from django.contrib import admin

from htqweb.admin_gate import ServiceGatedAdminMixin

from .models import AuditLog, NumberSequence


@admin.register(NumberSequence)
class NumberSequenceAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("prefix", "year", "last")
    readonly_fields = ("prefix", "year", "last")


@admin.register(AuditLog)
class AuditLogAdmin(ServiceGatedAdminMixin, admin.ModelAdmin):
    list_display = ("created_at", "object_type", "object_id", "action", "actor_id")
    list_filter = ("object_type", "action")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
```

Run: `../.venv/Scripts/python.exe -m pytest apps/bpp/tests -q`
Expected: всё PASS.

- [ ] **Step 8: Сторожа платформы**

Run: `../.venv/Scripts/python.exe -m pytest apps/core/tests/test_invariants.py apps/core/tests/test_app_isolation.py apps/access/tests/test_gate.py apps/companies/tests/test_holding_views.py apps/companies/tests/test_migration_service.py apps/core/tests/test_bpp_scaffold.py -q`
Expected: всё PASS. `test_bpp_scaffold` проверяет 404 при включённом модуле — у `bpp` теперь есть маршруты, но путь `__probe__` по-прежнему не найден.

- [ ] **Step 9: Документация и коммит**

`STRUCTURE.md` §3.1, строка **bpp**: заменить «Тенантная (в `TENANT_APPS` — с первой миграцией)» на «Тенантная (в `TENANT_APPS` с `0001_core`). Ядро: `models/core.py` (`BppModel`, `VersionedModel`, `NumberSequence`, `AuditLog` с триггером «только запись»), `services/core/` (`numbering.next_number`, `audit.record/history`, `errors.check_version`)». В `CLAUDE.md` строку `TENANT_APPS = ("hr", "tasks", "contracts", "signoff")` в разделе «Мультикомпанейность» дополнить `"bpp"`. В `API.md` строку `/api/bpp/v1/*` дополнить «`history/<тип>/<id>` — журнал изменений документа».

```bash
git add backend/apps/bpp backend/htqweb/settings/base.py STRUCTURE.md CLAUDE.md API.md
git commit -m "feat(bpp): ядро модуля — базовые модели, годовая нумерация, журнал изменений только для записи"
```

---

## Task 3: Файлы документов

**Files:**
- Create: `backend/apps/bpp/models/files.py`, `backend/apps/bpp/services/core/files.py`, `backend/apps/bpp/services/core/scanner.py`
- Modify: `backend/apps/bpp/models/__init__.py`, `backend/apps/media_files/services/scope_policy.py` (`bpp_doc`, `RESTRICTED_SCOPES`), `backend/apps/bpp/views.py`, `backend/apps/bpp/urls.py`
- Create migration: `backend/apps/bpp/migrations/0002_files.py` (makemigrations)
- Test: `backend/apps/bpp/tests/test_files.py`

**Interfaces:**
- Consumes: `audit.record`, `DomainError`, `BppModel`, `media_files.interface.store_file / get_file_url`.
- Produces:
  - `files.FILE_RULES: dict[str, FileRule]` — типы файлов ТЗ §21;
  - `files.attach(owner, file_type: str, *, data: bytes, filename: str, mime: str, actor_id: int) -> dict`;
  - `files.replace(file_id: str, *, data: bytes, filename: str, mime: str, actor_id: int) -> dict`;
  - `files.list_files(owner) -> list[dict]` (только действующие версии);
  - `files.download_url(file_id: str, *, user_id: int) -> str` (пишет журнал скачиваний);
  - `scanner.scan(data: bytes, filename: str) -> None` (по умолчанию ничего не делает).
- Словарь файла: `{id, file_type, filename, mime, size, sha256, version, replaced, uploaded_by, uploaded_at}`.

- [ ] **Step 1: Падающие тесты**

Create `backend/apps/bpp/tests/test_files.py`:

```python
"""Файлы документов: типы и лимиты ТЗ §21, версии, журнал скачиваний."""

import uuid

import pytest

from apps.bpp.models import DocumentFile, FileDownload
from apps.bpp.services.core import files
from htqweb.errors import DomainError

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


class _Owner:
    class _meta:  # noqa: N801
        label_lower = "bpp.probe"

    def __init__(self):
        self.pk = uuid.uuid4()


@pytest.fixture
def owner():
    return _Owner()


@pytest.mark.django_db
def test_attach_and_list(company_context, owner):
    row = files.attach(owner, "invoice", data=PDF, filename="счёт.pdf",
                       mime="application/pdf", actor_id=7)
    assert (row["file_type"], row["version"], row["replaced"]) == ("invoice", 1, False)
    assert row["sha256"] and row["size"] == len(PDF)
    assert [f["id"] for f in files.list_files(owner)] == [row["id"]]


@pytest.mark.django_db
def test_wrong_format_is_415(company_context, owner):
    with pytest.raises(DomainError) as exc:
        files.attach(owner, "invoice", data=b"PK\x03\x04docx", filename="a.docx",
                     mime="application/vnd.openxmlformats-officedocument."
                          "wordprocessingml.document", actor_id=7)
    assert (exc.value.code, exc.value.status) == ("E-FILE-01", 415)


@pytest.mark.django_db
def test_too_big_is_413(company_context, owner):
    big = PDF + b"0" * (10 * 1024 * 1024)
    with pytest.raises(DomainError) as exc:
        files.attach(owner, "invoice", data=big, filename="a.pdf",
                     mime="application/pdf", actor_id=7)
    assert (exc.value.code, exc.value.status) == ("E-FILE-02", 413)


@pytest.mark.django_db
def test_count_limit(company_context, owner):
    for n in range(5):
        files.attach(owner, "invoice", data=PDF, filename=f"{n}.pdf",
                     mime="application/pdf", actor_id=7)
    with pytest.raises(DomainError) as exc:
        files.attach(owner, "invoice", data=PDF, filename="6.pdf",
                     mime="application/pdf", actor_id=7)
    assert exc.value.code == "E-FILE-03"


@pytest.mark.django_db
def test_replace_makes_a_new_version(company_context, owner):
    first = files.attach(owner, "agreement", data=PDF, filename="v1.pdf",
                         mime="application/pdf", actor_id=7)
    second = files.replace(first["id"], data=PDF, filename="v2.pdf",
                           mime="application/pdf", actor_id=8)
    assert second["version"] == 2
    assert [f["filename"] for f in files.list_files(owner)] == ["v2.pdf"]
    assert DocumentFile.objects.get(pk=first["id"]).replaced is True


@pytest.mark.django_db
def test_download_is_logged(company_context, owner):
    row = files.attach(owner, "invoice", data=PDF, filename="a.pdf",
                       mime="application/pdf", actor_id=7)
    assert files.download_url(row["id"], user_id=9)
    assert FileDownload.objects.filter(file_id=row["id"], user_id=9).count() == 1


@pytest.mark.django_db
def test_scanner_can_reject(company_context, owner, settings):
    settings.BPP_FILE_SCANNER = "apps.bpp.tests.test_files._reject_all"
    with pytest.raises(DomainError) as exc:
        files.attach(owner, "invoice", data=PDF, filename="a.pdf",
                     mime="application/pdf", actor_id=7)
    assert exc.value.code == "E-FILE-04"
    assert not DocumentFile.objects.exists()


def _reject_all(data: bytes, filename: str) -> str | None:
    return "найден вирус EICAR"
```

Run: `../.venv/Scripts/python.exe -m pytest apps/bpp/tests/test_files.py -q`
Expected: ошибка сбора — `cannot import name 'DocumentFile'`.

- [ ] **Step 2: Модели файлов и миграция**

Create `backend/apps/bpp/models/files.py`:

```python
"""Файлы документов модуля (ТЗ §21, D-31).

Сами байты — в ``apps.media_files`` (scope ``bpp_doc``); здесь паспорт:
какому документу принадлежит, какого типа, какая версия, кто загрузил.
Новая версия не стирает старую — старая получает ``replaced`` и остаётся
в истории (ТЗ: «файлы не удаляются физически после отправки документа»).
"""

from __future__ import annotations

from django.db import models
from django.db.models.functions import Now

from .core import BppModel


class DocumentFile(BppModel):
    owner_type = models.CharField(max_length=64)
    owner_id = models.CharField(max_length=64)
    file_type = models.CharField(max_length=32)
    media_file_id = models.CharField(max_length=64)
    filename = models.CharField(max_length=255)
    mime = models.CharField(max_length=128)
    size = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    version = models.PositiveIntegerField(default=1)
    replaced = models.BooleanField(default=False, db_default=False)
    previous = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="next_versions")

    class Meta:
        indexes = [models.Index(fields=["owner_type", "owner_id", "file_type"],
                                name="ix_bpp_file_owner")]
        verbose_name = "Файл документа"
        verbose_name_plural = "Файлы документов"


class FileDownload(models.Model):
    """Журнал скачиваний (ТЗ §25.2): кто и когда получил ссылку на файл."""

    file = models.ForeignKey(DocumentFile, on_delete=models.PROTECT, related_name="downloads")
    user_id = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        verbose_name = "Скачивание файла"
        verbose_name_plural = "Журнал скачиваний"
```

В `backend/apps/bpp/models/__init__.py` добавить строку:

```python
from .files import DocumentFile, FileDownload  # noqa: F401
```

Сгенерировать миграцию:

```bash
DJANGO_SETTINGS_MODULE=htqweb.settings.dev DB_HOST=localhost DB_PORT=55432 DB_NAME=htqweb DB_USER=htqweb DB_PASSWORD=change-me JWT_SECRET=dev PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe manage.py makemigrations bpp --name files
```

Expected: `apps/bpp/migrations/0002_files.py`.

- [ ] **Step 3: Scope хранилища**

В `backend/apps/media_files/services/scope_policy.py` в `_POLICIES` перед `"generic"` добавить:

```python
    # Файлы документов модуля БЗО (ТЗ §21). Типы, размеры и число файлов
    # по типу документа проверяет сам модуль (apps/bpp/services/core/files.py);
    # здесь — общий верхний предел и список форматов. XML — для счетов-фактур
    # (отдаётся вложением, в браузере не открывается). В RESTRICTED_SCOPES:
    # пишет только сервер модуля, проверив права на документ.
    "bpp_doc": ScopePolicy(
        name="bpp_doc",
        public=False,
        max_mb=20,
        mimes=(
            "application/pdf", "image/jpeg", "image/png",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/xml", "text/xml", "text/plain", "text/csv",
        ),
        variants=(),
    ),
```

и заменить `RESTRICTED_SCOPES`:

```python
RESTRICTED_SCOPES = frozenset({"hr_doc", "hr_department", "task_attachment", "bpp_doc"})
```

- [ ] **Step 4: Сканер и сервис файлов**

Create `backend/apps/bpp/services/core/scanner.py`:

```python
"""Антивирусная проверка файлов — задел (Q-B25, D-31).

``settings.BPP_FILE_SCANNER`` — путь к функции ``(data, filename) -> str |
None`` (строка — причина отказа). Не задан — проверки нет. ClamAV
подключается задачей A7.4 реализацией этой функции, без правки модуля.
"""

from __future__ import annotations

from django.conf import settings
from django.utils.module_loading import import_string

from htqweb.errors import DomainError


def scan(data: bytes, filename: str) -> None:
    path = getattr(settings, "BPP_FILE_SCANNER", "")
    if not path:
        return
    reason = import_string(path)(data, filename)
    if reason:
        raise DomainError("E-FILE-04", f"Файл «{filename}» не принят: {reason}.", status=422)
```

Create `backend/apps/bpp/services/core/files.py`:

```python
"""Файлы документов: типы и лимиты ТЗ §21, версии, журнал скачиваний."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from apps.bpp.models import DocumentFile, FileDownload
from apps.media_files import interface as media
from htqweb.errors import DomainError

from . import audit, scanner

PDF = "application/pdf"
JPG = "image/jpeg"
PNG = "image/png"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XML = ("application/xml", "text/xml")
TXT = "text/plain"
CSV = "text/csv"


@dataclass(frozen=True)
class FileRule:
    title: str
    mimes: tuple[str, ...]
    max_mb: int
    max_count: int


FILE_RULES: dict[str, FileRule] = {
    "request_attachment": FileRule("КП, ТЗ, спецификация", (PDF, DOCX, XLSX, JPG, PNG), 20, 20),
    "agreement": FileRule("Договор", (PDF, DOCX, JPG, PNG), 20, 1),
    "agreement_annex": FileRule("Приложение к договору", (PDF, DOCX, JPG, PNG), 20, 30),
    "invoice": FileRule("Счёт на оплату", (PDF, JPG, PNG), 10, 5),
    "act": FileRule("АВР", (PDF, JPG, PNG), 10, 10),
    "waybill": FileRule("Накладная", (PDF, JPG, PNG), 10, 10),
    "vat_invoice": FileRule("Счёт-фактура", (PDF, JPG, PNG, *XML), 10, 10),
    "bank_statement": FileRule("Выписка банка", (TXT, XLSX, CSV), 20, 1),
    "alternative_offer": FileRule("Коммерческое предложение", (PDF, DOCX, XLSX, JPG, PNG), 20, 5),
}


def _serialize(row: DocumentFile) -> dict:
    return {
        "id": str(row.id), "file_type": row.file_type, "filename": row.filename,
        "mime": row.mime, "size": row.size, "sha256": row.sha256,
        "version": row.version, "replaced": row.replaced,
        "uploaded_by": row.created_by, "uploaded_at": row.created_at.isoformat(),
    }


def _check(rule: FileRule, *, data: bytes, filename: str, mime: str) -> None:
    if mime not in rule.mimes:
        raise DomainError(
            "E-FILE-01",
            f"Формат файла «{filename}» не подходит для «{rule.title}». "
            f"Допустимы: {', '.join(sorted({m.split('/')[-1] for m in rule.mimes}))}.",
            status=415)
    if len(data) > rule.max_mb * 1024 * 1024:
        raise DomainError(
            "E-FILE-02",
            f"Файл «{filename}» больше {rule.max_mb} МБ. Уменьшите файл и загрузите снова.",
            status=413)
    scanner.scan(data, filename)


def _store(data: bytes, filename: str, mime: str, actor_id: int) -> dict:
    return media.store_file(data=data, filename=filename, mime=mime, scope="bpp_doc",
                            owner_id=actor_id, internal_authorized=True)


def _current(owner_type: str, owner_id: str, file_type: str | None = None):
    rows = DocumentFile.objects.filter(owner_type=owner_type, owner_id=owner_id,
                                       replaced=False)
    return rows.filter(file_type=file_type) if file_type else rows


@transaction.atomic
def attach(owner, file_type: str, *, data: bytes, filename: str, mime: str,
           actor_id: int) -> dict:
    rule = FILE_RULES[file_type]
    owner_type, owner_id = owner._meta.label_lower, str(owner.pk)
    if _current(owner_type, owner_id, file_type).count() >= rule.max_count:
        raise DomainError(
            "E-FILE-03",
            f"К документу уже приложено {rule.max_count} файл(ов) типа «{rule.title}» — "
            f"это предел. Замените один из них новой версией.",
            status=422)
    _check(rule, data=data, filename=filename, mime=mime)
    stored = _store(data, filename, mime, actor_id)
    row = DocumentFile.objects.create(
        owner_type=owner_type, owner_id=owner_id, file_type=file_type,
        media_file_id=str(stored["id"]), filename=filename, mime=mime,
        size=stored["size"], sha256=stored.get("sha256") or "",
        created_by=actor_id, updated_by=actor_id,
    )
    audit.record(owner, "file_attached", actor_id=actor_id,
                 changes={"file": str(row.id), "file_type": file_type, "filename": filename})
    return _serialize(row)


@transaction.atomic
def replace(file_id: str, *, data: bytes, filename: str, mime: str, actor_id: int) -> dict:
    old = DocumentFile.objects.select_for_update().get(pk=file_id, replaced=False)
    _check(FILE_RULES[old.file_type], data=data, filename=filename, mime=mime)
    stored = _store(data, filename, mime, actor_id)
    old.replaced = True
    old.save(update_fields=["replaced", "updated_at"])
    row = DocumentFile.objects.create(
        owner_type=old.owner_type, owner_id=old.owner_id, file_type=old.file_type,
        media_file_id=str(stored["id"]), filename=filename, mime=mime,
        size=stored["size"], sha256=stored.get("sha256") or "",
        version=old.version + 1, previous=old, created_by=actor_id, updated_by=actor_id,
    )
    return _serialize(row)


def list_files(owner) -> list[dict]:
    rows = _current(owner._meta.label_lower, str(owner.pk)).order_by("created_at")
    return [_serialize(row) for row in rows]


def download_url(file_id: str, *, user_id: int) -> str:
    row = DocumentFile.objects.get(pk=file_id)
    FileDownload.objects.create(file=row, user_id=user_id)
    return media.get_file_url(row.media_file_id) or ""
```

Run: `../.venv/Scripts/python.exe -m pytest apps/bpp/tests/test_files.py apps/media_files/tests -q`
Expected: всё PASS. Если `test_attach_and_list` падает на подписи PDF (`File content does not match`), значит заглушка `PDF` не проходит `verify_signature`: взять байты минимального PDF из `apps/media_files/tests` (там есть образец для `hr_doc`) и записать решение в отчёт.

- [ ] **Step 5: Коммит**

```bash
git add backend/apps/bpp backend/apps/media_files/services/scope_policy.py
git commit -m "feat(bpp): файлы документов — типы и лимиты ТЗ §21, версии, журнал скачиваний, задел под антивирус"
```

---

## Task 4: Справочники `refdata`

**Files:**
- Create: `backend/apps/refdata/models.py`, `backend/apps/refdata/migrations/__init__.py`, `0001_initial.py` (makemigrations), `0002_seed.py`, `0003_nbrk_periodic_task.py`
- Create: `backend/apps/refdata/services/__init__.py`, `services/lookup.py`, `services/editing.py`, `services/nbrk.py`, `backend/apps/refdata/tasks.py`, `backend/apps/refdata/schemas.py`, `backend/apps/refdata/admin.py`
- Modify: `backend/apps/refdata/interface.py`, `backend/apps/refdata/views.py`, `backend/apps/refdata/urls.py`
- Test: `backend/apps/refdata/tests/__init__.py`, `test_lookup.py`, `test_api.py`, `test_nbrk.py`

**Interfaces:**
- Consumes: `companies.interface.is_holding`, `access.interface.flags_for`, `htqweb.fallback.fallback`.
- Produces (`apps.refdata.interface`, мастер-план §2.6):
  - `vat_rate(country_code: str, on_date: date) -> Decimal | None`;
  - `mrp(on_date: date) -> Decimal` (`RefdataMissing`, если значения нет);
  - `contract_threshold(on_date: date) -> Decimal` (= 1000 × МРП);
  - `exchange_rate(currency: str, on_date: date) -> Decimal | None` (KZT → `Decimal("1")`);
  - `article_brief(ids: list[str]) -> dict[str, dict]`;
  - `article_groups() -> list[dict]`;
  - `uom_brief(ids: list[str]) -> dict[str, dict]`;
  - `country_brief(codes: list[str]) -> dict[str, dict]`;
  - `can_edit(user, company_slug: str | None, node: str = "refdata") -> bool`;
  - `class RefdataMissing(Exception)`.
- Ручки `/api/refdata/v1/{countries,currencies,rates,vat,mrp,uoms,article-groups,articles}`.

- [ ] **Step 1: Модели**

Create `backend/apps/refdata/models.py`:

```python
"""Общие справочники модуля БЗО — одна копия на группу, схема public (D-03).

Удаления нет: запись уходит в архив (``is_active=False``) и остаётся в
старых документах (ТЗ §18). Периодические значения (НДС, МРП, курсы) —
по датам: документ берёт значение на свою дату.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models.functions import Now


class _Base(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        abstract = True


class Country(_Base):
    code = models.CharField(max_length=2, unique=True)  # ISO 3166-1 alpha-2
    name = models.CharField(max_length=128)
    is_active = models.BooleanField(default=True, db_default=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Страна"
        verbose_name_plural = "Страны"


class Currency(_Base):
    code = models.CharField(max_length=3, unique=True)  # ISO 4217
    name = models.CharField(max_length=64)
    symbol = models.CharField(max_length=8, default="", blank=True)
    is_active = models.BooleanField(default=True, db_default=True)

    class Meta:
        ordering = ("code",)
        verbose_name = "Валюта"
        verbose_name_plural = "Валюты"


class RateSource(models.TextChoices):
    NBRK = "nbrk", "НБРК"
    MANUAL = "manual", "Вручную"


class ExchangeRate(_Base):
    """Курс валюты к KZT на дату. Ручной курс не перезаписывается загрузкой."""

    currency_code = models.CharField(max_length=3)
    on_date = models.DateField()
    rate = models.DecimalField(max_digits=18, decimal_places=6)
    source = models.CharField(max_length=8, choices=RateSource.choices)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["currency_code", "on_date"],
                                               name="uq_refdata_rate_day")]
        verbose_name = "Курс валюты"
        verbose_name_plural = "Курсы валют"


class VatRate(_Base):
    """Ставка НДС страны на период ``[date_from, date_to]`` (``date_to`` пусто — бессрочно)."""

    country_code = models.CharField(max_length=2)
    rate = models.DecimalField(max_digits=5, decimal_places=2)
    date_from = models.DateField()
    date_to = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ("country_code", "date_from")
        verbose_name = "Ставка НДС"
        verbose_name_plural = "Ставки НДС"


class MrpValue(_Base):
    """МРП, действующий с ``date_from`` (ТЗ §18: 2026 — 4 325 тг)."""

    date_from = models.DateField(unique=True)
    value = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ("date_from",)
        verbose_name = "МРП"
        verbose_name_plural = "МРП"


class Uom(_Base):
    code = models.CharField(max_length=16, unique=True)
    short_name = models.CharField(max_length=16)
    name = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True, db_default=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Единица измерения"
        verbose_name_plural = "Единицы измерения"


class ArticleGroup(_Base):
    """Группа статей. ``node_key`` — узел реестра прав, открывающий статьи группы (BR-010)."""

    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=128)
    node_key = models.CharField(max_length=128)
    is_active = models.BooleanField(default=True, db_default=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Группа статей"
        verbose_name_plural = "Группы статей"


class Article(_Base):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    group = models.ForeignKey(ArticleGroup, on_delete=models.PROTECT, related_name="articles")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                               related_name="children")
    is_active = models.BooleanField(default=True, db_default=True)
    ext_1c_ref = models.CharField(max_length=64, default="", blank=True)

    class Meta:
        ordering = ("code",)
        verbose_name = "Статья бюджета"
        verbose_name_plural = "Статьи бюджета"
```

Сгенерировать `0001_initial.py`:

```bash
DJANGO_SETTINGS_MODULE=htqweb.settings.dev DB_HOST=localhost DB_PORT=55432 DB_NAME=htqweb DB_USER=htqweb DB_PASSWORD=change-me JWT_SECRET=dev PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe manage.py makemigrations refdata --name initial
```

- [ ] **Step 2: Начальные данные**

Create `backend/apps/refdata/migrations/0002_seed.py`:

```python
"""Предзаполнение справочников (ТЗ §18, мастер-план A1.2).

Ставки НДС и МРП — «сверить с законодательством» перед выкаткой [У]:
значения взяты из ТЗ (РК 16% с 01.01.2026, МРП 2026 — 4 325 тг). Литералы, а
не константы кода: миграция обязана давать один результат всегда.
"""

from datetime import date
from decimal import Decimal

from django.db import migrations

COUNTRIES = [("KZ", "Казахстан"), ("RU", "Россия"), ("KG", "Кыргызстан"), ("UZ", "Узбекистан")]
CURRENCIES = [("KZT", "Казахстанский тенге", "₸"), ("USD", "Доллар США", "$"),
              ("EUR", "Евро", "€"), ("RUB", "Российский рубль", "₽"),
              ("CNY", "Китайский юань", "¥"), ("KGS", "Киргизский сом", "с"),
              ("UZS", "Узбекский сум", "сўм")]
VAT = [("KZ", "12.00", date(2020, 1, 1), date(2025, 12, 31)),
       ("KZ", "16.00", date(2026, 1, 1), None),
       ("RU", "20.00", date(2020, 1, 1), date(2025, 12, 31)),
       ("RU", "22.00", date(2026, 1, 1), None),
       ("KG", "12.00", date(2020, 1, 1), None),
       ("UZ", "12.00", date(2020, 1, 1), None)]
MRP = [(date(2025, 1, 1), "3932.00"), (date(2026, 1, 1), "4325.00")]
UOMS = [("pcs", "шт", "Штука"), ("kg", "кг", "Килограмм"), ("t", "т", "Тонна"),
        ("m", "м", "Метр"), ("m2", "м²", "Квадратный метр"),
        ("m3", "м³", "Кубический метр"), ("l", "л", "Литр"),
        ("set", "компл", "Комплект"), ("service", "усл.", "Услуга"), ("h", "ч", "Час")]
GROUPS = [("supply", "Снабжение", "bpp.articles.supply"),
          ("pm", "Проектное управление", "bpp.articles.pm")]


def seed(apps, schema_editor):
    Country = apps.get_model("refdata", "Country")
    Currency = apps.get_model("refdata", "Currency")
    VatRate = apps.get_model("refdata", "VatRate")
    MrpValue = apps.get_model("refdata", "MrpValue")
    Uom = apps.get_model("refdata", "Uom")
    ArticleGroup = apps.get_model("refdata", "ArticleGroup")
    for code, name in COUNTRIES:
        Country.objects.get_or_create(code=code, defaults={"name": name})
    for code, name, symbol in CURRENCIES:
        Currency.objects.get_or_create(code=code, defaults={"name": name, "symbol": symbol})
    for country, rate, date_from, date_to in VAT:
        VatRate.objects.get_or_create(country_code=country, date_from=date_from,
                                      defaults={"rate": Decimal(rate), "date_to": date_to})
    for date_from, value in MRP:
        MrpValue.objects.get_or_create(date_from=date_from, defaults={"value": Decimal(value)})
    for code, short, name in UOMS:
        Uom.objects.get_or_create(code=code, defaults={"short_name": short, "name": name})
    for code, name, node in GROUPS:
        ArticleGroup.objects.get_or_create(code=code, defaults={"name": name, "node_key": node})


class Migration(migrations.Migration):

    dependencies = [("refdata", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
```

- [ ] **Step 3: Падающие тесты поиска значений**

Create `backend/apps/refdata/tests/__init__.py` (пустой) и `backend/apps/refdata/tests/test_lookup.py`:

```python
"""Значения справочников на дату (BR-031, BR-040, CALC-011, CALC-012)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.refdata import interface
from apps.refdata.models import Article, ArticleGroup, ExchangeRate


@pytest.mark.django_db
def test_vat_on_a_date_uses_the_period_boundaries():
    assert interface.vat_rate("KZ", date(2025, 12, 31)) == Decimal("12.00")
    assert interface.vat_rate("KZ", date(2026, 1, 1)) == Decimal("16.00")
    assert interface.vat_rate("XX", date(2026, 1, 1)) is None


@pytest.mark.django_db
def test_mrp_and_threshold():
    assert interface.mrp(date(2026, 9, 1)) == Decimal("4325.00")
    assert interface.contract_threshold(date(2026, 9, 1)) == Decimal("4325000.00")
    assert interface.mrp(date(2025, 6, 1)) == Decimal("3932.00")
    with pytest.raises(interface.RefdataMissing):
        interface.mrp(date(2019, 1, 1))


@pytest.mark.django_db
def test_exchange_rate():
    assert interface.exchange_rate("KZT", date(2026, 9, 1)) == Decimal("1")
    ExchangeRate.objects.create(currency_code="USD", on_date=date(2026, 9, 1),
                                rate=Decimal("470.120000"), source="nbrk")
    assert interface.exchange_rate("USD", date(2026, 9, 1)) == Decimal("470.120000")
    assert interface.exchange_rate("USD", date(2026, 9, 2)) is None


@pytest.mark.django_db
def test_archived_article_is_still_described():
    group = ArticleGroup.objects.get(code="supply")
    article = Article.objects.create(code="111", name="Металлопрокат", group=group,
                                     is_active=False)
    brief = interface.article_brief([str(article.id)])[str(article.id)]
    assert brief == {"id": str(article.id), "code": "111", "name": "Металлопрокат",
                     "group_id": str(group.id), "node_key": "bpp.articles.supply",
                     "is_active": False}
    assert {g["code"] for g in interface.article_groups()} == {"supply", "pm"}
```

Run: `../.venv/Scripts/python.exe -m pytest apps/refdata/tests/test_lookup.py -q`
Expected: FAIL — `module 'apps.refdata.interface' has no attribute 'vat_rate'`.

- [ ] **Step 4: Поиск значений и интерфейс**

Create `backend/apps/refdata/services/__init__.py` (пустой) и `backend/apps/refdata/services/lookup.py`:

```python
"""Значения справочников на дату — для соседей через ``refdata.interface``."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db.models import Q

from apps.refdata.models import Article, ArticleGroup, Country, ExchangeRate, MrpValue, Uom, VatRate

THRESHOLD_MRP = Decimal("1000")


class RefdataMissing(Exception):
    """В справочнике нет значения на нужную дату."""


def vat_rate(country_code: str, on_date: date) -> Decimal | None:
    row = (VatRate.objects.filter(country_code=country_code, date_from__lte=on_date)
           .filter(Q(date_to__isnull=True) | Q(date_to__gte=on_date))
           .order_by("-date_from").first())
    return row.rate if row else None


def mrp(on_date: date) -> Decimal:
    row = MrpValue.objects.filter(date_from__lte=on_date).order_by("-date_from").first()
    if row is None:
        raise RefdataMissing(f"Нет МРП на {on_date:%d.%m.%Y}")
    return row.value


def contract_threshold(on_date: date) -> Decimal:
    return (THRESHOLD_MRP * mrp(on_date)).quantize(Decimal("0.01"))


def exchange_rate(currency: str, on_date: date) -> Decimal | None:
    if currency == "KZT":
        return Decimal("1")
    row = ExchangeRate.objects.filter(currency_code=currency, on_date=on_date).first()
    return row.rate if row else None


def article_brief(ids: list[str]) -> dict[str, dict]:
    rows = Article.objects.filter(id__in=ids).select_related("group")
    return {str(a.id): {"id": str(a.id), "code": a.code, "name": a.name,
                        "group_id": str(a.group_id), "node_key": a.group.node_key,
                        "is_active": a.is_active} for a in rows}


def article_groups() -> list[dict]:
    return [{"id": str(g.id), "code": g.code, "name": g.name, "node_key": g.node_key,
             "is_active": g.is_active} for g in ArticleGroup.objects.all()]


def uom_brief(ids: list[str]) -> dict[str, dict]:
    return {str(u.id): {"id": str(u.id), "code": u.code, "short_name": u.short_name,
                        "is_active": u.is_active} for u in Uom.objects.filter(id__in=ids)}


def country_brief(codes: list[str]) -> dict[str, dict]:
    return {c.code: {"code": c.code, "name": c.name, "is_active": c.is_active}
            for c in Country.objects.filter(code__in=codes)}
```

Replace `backend/apps/refdata/interface.py`:

```python
"""Межаппный интерфейс справочников (мастер-план §2.6).

Каждая функция первой строкой зовёт ``require_service("refdata")``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.core.services import require_service

from .services import editing, lookup
from .services.lookup import RefdataMissing  # noqa: F401 — часть контракта

__all__ = ["RefdataMissing", "article_brief", "article_groups", "can_edit",
           "contract_threshold", "country_brief", "exchange_rate", "mrp", "uom_brief",
           "vat_rate"]


def vat_rate(country_code: str, on_date: date) -> Decimal | None:
    require_service("refdata")
    return lookup.vat_rate(country_code, on_date)


def mrp(on_date: date) -> Decimal:
    require_service("refdata")
    return lookup.mrp(on_date)


def contract_threshold(on_date: date) -> Decimal:
    require_service("refdata")
    return lookup.contract_threshold(on_date)


def exchange_rate(currency: str, on_date: date) -> Decimal | None:
    require_service("refdata")
    return lookup.exchange_rate(currency, on_date)


def article_brief(ids: list[str]) -> dict[str, dict]:
    require_service("refdata")
    return lookup.article_brief(ids)


def article_groups() -> list[dict]:
    require_service("refdata")
    return lookup.article_groups()


def uom_brief(ids: list[str]) -> dict[str, dict]:
    require_service("refdata")
    return lookup.uom_brief(ids)


def country_brief(codes: list[str]) -> dict[str, dict]:
    require_service("refdata")
    return lookup.country_brief(codes)


def can_edit(user, company_slug: str | None, node: str = "refdata") -> bool:
    require_service("refdata")
    return editing.can_edit(user, company_slug, node)
```

Create `backend/apps/refdata/services/editing.py`:

```python
"""Кто правит справочники: роль с правом правки И поддомен управляющей компании.

Справочники общие для группы (D-03), поэтому правка из дочерней компании
запрещена даже держателю роли: иначе бухгалтер дочерней компании поменял
бы ставку НДС всем. Управляющая компания — компания вида «холдинг» (Q-E03).
"""

from __future__ import annotations

from apps.access import interface as access
from apps.companies import interface as companies


def can_edit(user, company_slug: str | None, node: str = "refdata") -> bool:
    if getattr(user, "is_superuser", False):
        return True
    if not company_slug or not companies.is_holding(company_slug):
        return False
    return "edit" in access.flags_for(user, node, company_slug) or \
        "create" in access.flags_for(user, node, company_slug)
```

Run: `../.venv/Scripts/python.exe -m pytest apps/refdata/tests/test_lookup.py -q`
Expected: 4 passed.

- [ ] **Step 5: Падающие тесты API**

Create `backend/apps/refdata/tests/test_api.py`:

```python
"""Ручки справочников: читать — всем с ролью, править — только в управляющей компании."""

import json

import pytest
from django.test import Client

from apps.access.tests.helpers import assign, token
from apps.companies.models import Company, CompanyKind

BASE = "/api/refdata/v1"


def _auth(slug, user_id=7):
    tok = token(user_id=user_id, sub=str(user_id), company=slug)
    return {"HTTP_AUTHORIZATION": f"Bearer {tok}", "HTTP_X_HTQ_COMPANY": slug}


def _post(path, body, slug):
    return Client().post(f"{BASE}/{path}", data=json.dumps(body),
                         content_type="application/json", **_auth(slug))


@pytest.fixture
def holding(db):
    return Company.objects.create(slug="group-hq", name="Холдинг", kind=CompanyKind.HOLDING)


@pytest.fixture
def subsidiary(db):
    return Company.objects.create(slug="htq-kz", name="ДО", kind=CompanyKind.CONSTRUCTION)


@pytest.mark.django_db
def test_read_needs_refdata_read(holding):
    assert Client().get(f"{BASE}/currencies", **_auth(holding.slug)).status_code == 403
    assign(holding.slug, 7, "refdata", "view")
    response = Client().get(f"{BASE}/currencies", **_auth(holding.slug))
    assert response.status_code == 200
    assert "KZT" in {row["code"] for row in response.json()}


@pytest.mark.django_db
def test_edit_in_holding(holding):
    assign(holding.slug, 7, "refdata", "full")
    response = _post("uoms", {"code": "pack", "short_name": "уп", "name": "Упаковка"},
                     holding.slug)
    assert response.status_code == 201, response.content
    assert response.json()["code"] == "pack"


@pytest.mark.django_db
def test_edit_from_subsidiary_is_forbidden(subsidiary):
    assign(subsidiary.slug, 7, "refdata", "full")
    response = _post("uoms", {"code": "pack", "short_name": "уп", "name": "Упаковка"},
                     subsidiary.slug)
    assert response.status_code == 403
    assert response.json()["code"] == "E-REF-01"


@pytest.mark.django_db
def test_archive_instead_of_delete(holding):
    assign(holding.slug, 7, "refdata", "full")
    uom_id = next(row["id"] for row in
                  Client().get(f"{BASE}/uoms", **_auth(holding.slug)).json()
                  if row["code"] == "h")
    response = Client().patch(f"{BASE}/uoms/{uom_id}", data=json.dumps({"is_active": False}),
                              content_type="application/json", **_auth(holding.slug))
    assert response.status_code == 200 and response.json()["is_active"] is False
    active = Client().get(f"{BASE}/uoms?active=1", **_auth(holding.slug)).json()
    assert "h" not in {row["code"] for row in active}
    assert Client().delete(f"{BASE}/uoms/{uom_id}", **_auth(holding.slug)).status_code == 405


@pytest.mark.django_db
def test_article_code_is_unique(holding):
    assign(holding.slug, 7, "refdata", "full")
    groups = Client().get(f"{BASE}/article-groups", **_auth(holding.slug)).json()
    supply = next(g["id"] for g in groups if g["code"] == "supply")
    body = {"code": "111", "name": "Металлопрокат", "group_id": supply}
    assert _post("articles", body, holding.slug).status_code == 201
    second = _post("articles", body, holding.slug)
    assert second.status_code == 422 and second.json()["code"] == "E-REF-02"
```

Run: `../.venv/Scripts/python.exe -m pytest apps/refdata/tests/test_api.py -q`
Expected: FAIL — 404 на `/api/refdata/v1/currencies`.

- [ ] **Step 6: Схемы, вьюхи, маршруты**

Create `backend/apps/refdata/schemas.py`:

```python
"""Схемы ручек справочников. PATCH-схемы: поле ``None`` — «не пришло»."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class CountryIn(BaseModel):
    code: str = Field(..., min_length=2, max_length=2)
    name: str = Field(..., min_length=1, max_length=128)


class CountryPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    is_active: Optional[bool] = None


class CurrencyIn(BaseModel):
    code: str = Field(..., min_length=3, max_length=3)
    name: str = Field(..., min_length=1, max_length=64)
    symbol: str = Field("", max_length=8)


class CurrencyPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=64)
    symbol: Optional[str] = Field(None, max_length=8)
    is_active: Optional[bool] = None


class RateIn(BaseModel):
    currency_code: str = Field(..., min_length=3, max_length=3)
    on_date: date
    rate: Decimal = Field(..., gt=0, max_digits=18, decimal_places=6)


class VatIn(BaseModel):
    country_code: str = Field(..., min_length=2, max_length=2)
    rate: Decimal = Field(..., ge=0, le=100, max_digits=5, decimal_places=2)
    date_from: date
    date_to: Optional[date] = None


class MrpIn(BaseModel):
    date_from: date
    value: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2)


class UomIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=16)
    short_name: str = Field(..., min_length=1, max_length=16)
    name: str = Field(..., min_length=1, max_length=64)


class UomPatch(BaseModel):
    short_name: Optional[str] = Field(None, min_length=1, max_length=16)
    name: Optional[str] = Field(None, min_length=1, max_length=64)
    is_active: Optional[bool] = None


class ArticleGroupIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=128)
    node_key: str = Field(..., min_length=1, max_length=128)


class ArticleGroupPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    is_active: Optional[bool] = None


class ArticleIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=255)
    group_id: str
    parent_id: Optional[str] = None
    ext_1c_ref: str = Field("", max_length=64)


class ArticlePatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    is_active: Optional[bool] = None
    ext_1c_ref: Optional[str] = Field(None, max_length=64)
```

Replace `backend/apps/refdata/views.py`:

```python
"""Ручки справочников — каждая под гейтом модуля refdata с явным уровнем.

Чтение — ``read``. Запись — ``write`` плюс проверка «управляющая компания»
(``services/editing.can_edit``): гейт модуля отвечает «может ли роль»,
проверка компании — «здесь ли» (D-03). Удаления нет — только архив.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.forms.models import model_to_dict
from django.http import Http404

from htqweb.errors import DomainError
from htqweb.http import api_view, json_error

from . import models, schemas
from .services import editing

READ_ONLY_FIELDS = {"id", "created_at", "updated_at"}


def _row(obj) -> dict:
    data = model_to_dict(obj)
    data["id"] = str(obj.id)
    for key, value in list(data.items()):
        if hasattr(value, "quantize"):
            data[key] = str(value)
        elif hasattr(value, "isoformat"):
            data[key] = value.isoformat()
    if "group" in data:
        data["group_id"] = str(data.pop("group"))
    if "parent" in data:
        parent = data.pop("parent")
        data["parent_id"] = str(parent) if parent else None
    return data


def _deny_unless_editor(request) -> None:
    company = getattr(request, "company", None) or {}
    if not editing.can_edit(request.token, company.get("slug")):
        raise DomainError(
            "E-REF-01",
            "Справочники ведёт управляющая компания. Откройте раздел на её "
            "поддомене или обратитесь к финансовому директору.",
            status=403)


def _save(obj) -> dict:
    try:
        with transaction.atomic():
            obj.save()
    except IntegrityError as exc:
        raise DomainError("E-REF-02", "Запись с таким кодом уже есть в справочнике.",
                          status=422) from exc
    return _row(obj)


def _collection(model, schema_in, order: str):
    @api_view(methods=("GET",), module="refdata", level="read")
    def listing(request):
        rows = model.objects.all().order_by(order)
        if request.GET.get("active") == "1" and hasattr(model, "is_active"):
            rows = rows.filter(is_active=True)
        return [_row(obj) for obj in rows]

    @api_view(methods=("POST",), module="refdata", level="write", body=schema_in, status=201)
    def create(request, data):
        _deny_unless_editor(request)
        return _save(model(**data.model_dump()))

    def dispatch(request):
        if request.method == "GET":
            return listing(request)
        if request.method == "POST":
            return create(request)
        return json_error("Method Not Allowed", 405)

    return dispatch


def _item(model, schema_patch):
    @api_view(methods=("PATCH",), module="refdata", level="write", body=schema_patch)
    def patch(request, obj_id: str, data):
        _deny_unless_editor(request)
        obj = model.objects.filter(pk=obj_id).first()
        if obj is None:
            raise Http404("Запись справочника не найдена")
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(obj, key, value)
        return _save(obj)

    def dispatch(request, obj_id: str):
        if request.method == "PATCH":
            return patch(request, obj_id=obj_id)
        return json_error("Method Not Allowed", 405)

    return dispatch


countries = _collection(models.Country, schemas.CountryIn, "name")
country_item = _item(models.Country, schemas.CountryPatch)
currencies = _collection(models.Currency, schemas.CurrencyIn, "code")
currency_item = _item(models.Currency, schemas.CurrencyPatch)
rates = _collection(models.ExchangeRate, schemas.RateIn, "-on_date")
vat = _collection(models.VatRate, schemas.VatIn, "country_code")
mrp = _collection(models.MrpValue, schemas.MrpIn, "date_from")
uoms = _collection(models.Uom, schemas.UomIn, "name")
uom_item = _item(models.Uom, schemas.UomPatch)
article_groups = _collection(models.ArticleGroup, schemas.ArticleGroupIn, "name")
article_group_item = _item(models.ArticleGroup, schemas.ArticleGroupPatch)
articles = _collection(models.Article, schemas.ArticleIn, "code")
article_item = _item(models.Article, schemas.ArticlePatch)
```

⚠️ Ручной курс: `rates` создаёт запись с `source` по умолчанию. Задать `source="manual"` в модели ручной записи — в `schemas.RateIn` поля `source` нет, поэтому в `_collection` для `ExchangeRate` добавить: если `model is models.ExchangeRate`, выставить `obj.source = "manual"` перед сохранением. Сделать это строкой в `create`:

```python
        obj = model(**data.model_dump())
        if model is models.ExchangeRate:
            obj.source = models.RateSource.MANUAL
        return _save(obj)
```

(заменив `return _save(model(**data.model_dump()))`).

Replace `backend/apps/refdata/urls.py`:

```python
"""Маршруты /api/refdata/v1/."""

from django.urls import path

from . import views

_ROUTES = [
    ("countries", views.countries, "countries/<str:obj_id>", views.country_item),
    ("currencies", views.currencies, "currencies/<str:obj_id>", views.currency_item),
    ("uoms", views.uoms, "uoms/<str:obj_id>", views.uom_item),
    ("article-groups", views.article_groups, "article-groups/<str:obj_id>",
     views.article_group_item),
    ("articles", views.articles, "articles/<str:obj_id>", views.article_item),
]

urlpatterns = []
for collection, collection_view, item, item_view in _ROUTES:
    urlpatterns += [path(collection, collection_view), path(f"{collection}/", collection_view),
                    path(item, item_view), path(f"{item}/", item_view)]
for collection, collection_view in (("rates", views.rates), ("vat", views.vat),
                                    ("mrp", views.mrp)):
    urlpatterns += [path(collection, collection_view), path(f"{collection}/", collection_view)]
```

⚠️ Сторож `apps/access/tests/test_gate.py::test_every_url_view_of_translated_apps_carries_api_view` читает маршруты как `views.<имя>` и ищет функцию с `api_view` в `views.py`. Здесь ручки — диспетчеры, собранные фабрикой (`countries = _collection(...)`): сторож засчитывает имя, присвоенное вызову фабрики, если тело фабрики зовёт `api_view` (докстринг `_url_view_offenders`). Маршруты, построенные циклом, сторож не видит — поэтому, если он падает с «вьюха задана выражением», развернуть цикл в явный список `path("countries", views.countries), …` и записать это в отчёт.

Run: `../.venv/Scripts/python.exe -m pytest apps/refdata/tests -q && ../.venv/Scripts/python.exe -m pytest apps/access/tests/test_gate.py -q`
Expected: всё PASS.

- [ ] **Step 7: Падающий тест загрузки курса НБРК**

Create `backend/apps/refdata/tests/test_nbrk.py`:

```python
"""Ежедневная загрузка курса НБРК (D-15): ручной курс не перезаписывается,
недоступный API не роняет задачу."""

from datetime import date
from decimal import Decimal

import httpx
import pytest

from apps.refdata.models import ExchangeRate
from apps.refdata.services import nbrk

XML = """<?xml version="1.0" encoding="utf-8"?>
<rates><date>27.09.2026</date>
<item><title>USD</title><description>470.12</description><quant>1</quant></item>
<item><title>RUB</title><description>5.43</description><quant>1</quant></item>
<item><title>KGS</title><description>53.20</description><quant>10</quant></item>
</rates>"""


class _Resp:
    status_code = 200
    text = XML

    def raise_for_status(self):
        return None


@pytest.mark.django_db
def test_rates_are_loaded_per_unit(monkeypatch):
    monkeypatch.setattr(nbrk.httpx, "get", lambda *a, **k: _Resp())
    assert nbrk.load(date(2026, 9, 27)) == 3
    rates = {r.currency_code: r.rate for r in ExchangeRate.objects.all()}
    assert rates == {"USD": Decimal("470.120000"), "RUB": Decimal("5.430000"),
                     "KGS": Decimal("5.320000")}


@pytest.mark.django_db
def test_manual_rate_wins(monkeypatch):
    ExchangeRate.objects.create(currency_code="USD", on_date=date(2026, 9, 27),
                                rate=Decimal("471.000000"), source="manual")
    monkeypatch.setattr(nbrk.httpx, "get", lambda *a, **k: _Resp())
    nbrk.load(date(2026, 9, 27))
    assert ExchangeRate.objects.get(currency_code="USD").rate == Decimal("471.000000")


@pytest.mark.django_db
def test_unavailable_api_is_an_expected_fallback(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("нет сети")

    monkeypatch.setattr(nbrk.httpx, "get", boom)
    assert nbrk.load(date(2026, 9, 27)) == 0
    assert not ExchangeRate.objects.exists()
```

Run: `../.venv/Scripts/python.exe -m pytest apps/refdata/tests/test_nbrk.py -q`
Expected: FAIL — нет модуля `apps.refdata.services.nbrk`.

- [ ] **Step 8: Загрузчик НБРК, задача, расписание**

Ответ НБРК — внешний XML, поэтому разбор через `defusedxml` (стандартный `xml.etree` уязвим к XXE и «billion laughs»). Добавить в `backend/requirements.txt` строку `defusedxml==0.7.1` и установить: `../.venv/Scripts/python.exe -m pip install defusedxml==0.7.1`. Образ `backend/Dockerfile` ставит зависимости из того же файла.

Create `backend/apps/refdata/services/nbrk.py`:

```python
"""Курсы Национального банка РК на дату (D-15).

Источник — RSS НБРК ``get_rates.cfm?fdate=ДД.ММ.ГГГГ`` (XML: ``item`` с
``title`` — код валюты, ``description`` — курс, ``quant`` — за сколько
единиц). Храним курс за ОДНУ единицу. Ручной курс ФД на ту же дату
главнее — загрузка его не трогает. Недоступный API — предусмотренная
деградация (``fallback(expected=True)``): курс можно ввести вручную.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
from defusedxml import ElementTree as ET

from apps.refdata.models import Currency, ExchangeRate, RateSource
from htqweb.fallback import fallback

URL = "https://nationalbank.kz/rss/get_rates.cfm"


def load(on_date: date) -> int:
    """Загрузить курсы на дату; вернуть число записанных валют."""
    try:
        response = httpx.get(URL, params={"fdate": on_date.strftime("%d.%m.%Y")}, timeout=15.0)
        response.raise_for_status()
        root = ET.fromstring(response.text)
    except Exception as exc:
        fallback("refdata.nbrk.fetch_failed", 0, reason="курс НБРК не загружен",
                 exc=exc, expected=True)
        return 0
    known = set(Currency.objects.values_list("code", flat=True))
    written = 0
    for item in root.iter("item"):
        code = (item.findtext("title") or "").strip()
        if code not in known or code == "KZT":
            continue
        rate = Decimal((item.findtext("description") or "0").strip())
        quant = Decimal((item.findtext("quant") or "1").strip() or "1")
        per_unit = (rate / quant).quantize(Decimal("0.000001"))
        existing = ExchangeRate.objects.filter(currency_code=code, on_date=on_date).first()
        if existing is not None and existing.source == RateSource.MANUAL:
            continue
        ExchangeRate.objects.update_or_create(
            currency_code=code, on_date=on_date,
            defaults={"rate": per_unit, "source": RateSource.NBRK})
        written += 1
    return written
```

Проверить сигнатуру `htqweb.fallback.fallback` (`grep -n "^def fallback" backend/htqweb/fallback.py`): аргументы `site, value, *, reason, exc=None, expected=False, **labels`. Если отличается — привести вызов к фактической сигнатуре.

Create `backend/apps/refdata/tasks.py`:

```python
from celery import shared_task
from django.utils import timezone

from apps.core.services import require_service


@shared_task
def load_nbrk_rates() -> int:
    require_service("refdata")
    from apps.refdata.services import nbrk

    return nbrk.load(timezone.localdate())
```

Create `backend/apps/refdata/migrations/0003_nbrk_periodic_task.py` по образцу `apps/core/migrations/0005_daily_digest_periodic_task.py`: `TASK_NAME = "refdata.load_nbrk_rates"`, cron `minute="30", hour="10", day_of_week="*"`, `timezone="Asia/Almaty"`, `"task": "apps.refdata.tasks.load_nbrk_rates"`, описание «Курсы НБРК на сегодня (10:30 Asia/Almaty); недоступный API — ручной ввод ФД». Зависимости: `("refdata", "0002_seed")`, `("django_celery_beat", "<последняя миграция, как в core/0005>")`. Обратная операция — удалить `PeriodicTask` с этим именем.

Create `backend/apps/refdata/admin.py`: регистрация всех моделей с `ServiceGatedAdminMixin` (как в задаче 2).

Run: `../.venv/Scripts/python.exe -m pytest apps/refdata/tests apps/core/tests/test_invariants.py apps/core/tests/test_app_isolation.py -q`
Expected: всё PASS.

- [ ] **Step 9: Документация и коммит**

`STRUCTURE.md` §3.1, строка **refdata**: убрать «(каркас, модели в A1.2)», дописать «интерфейс `vat_rate/mrp/contract_threshold/exchange_rate/article_brief/article_groups/uom_brief/country_brief/can_edit`; курс НБРК — Celery-beat 10:30». `API.md`: перечень ручек `/api/refdata/v1/`.

```bash
git add backend/apps/refdata backend/requirements.txt STRUCTURE.md API.md
git commit -m "feat(refdata): справочники БЗО — страны, валюты и курсы НБРК, НДС и МРП на дату, ед. изм., статьи"
```

---

## Task 5: «Проект»

**Files:**
- Create: `backend/apps/project/models.py`, `migrations/__init__.py`, `migrations/0001_initial.py` (makemigrations), `services/__init__.py`, `services/projects.py`, `schemas.py`, `admin.py`
- Modify: `backend/apps/project/interface.py`, `views.py`, `urls.py`, `holding.py`; `backend/htqweb/settings/base.py` (`TENANT_APPS`)
- Modify: `backend/apps/tasks/models.py` (`Project.project_ref`) + миграция `tasks` (makemigrations)
- Create: `backend/apps/project/management/__init__.py`, `management/commands/__init__.py`, `management/commands/project_link_tasks.py`
- Test: `backend/apps/project/tests/__init__.py`, `test_projects.py`, `test_api.py`, `test_link_tasks.py`

**Interfaces:**
- Consumes: `refdata.interface.country_brief`.
- Produces (`apps.project.interface`, мастер-план §2.6):
  - `project_brief(ids: list[str]) -> dict[str, dict]` — `{id, code, name, kind, status, country_code, manager_user_id, customer_name, customer_counterparty_id}`;
  - `is_member(project_id: str, user_id: int) -> bool`;
  - `member_project_ids(user_id: int) -> list[str]`;
  - `search_projects(query: str, *, user_id: int, only_member: bool, limit: int = 20) -> list[dict]`.
- `ProjectKind`: `project` | `company_overhead` (служебный «Общие расходы компании», умолчание Q-E13).

- [ ] **Step 1: Падающие тесты сервиса**

Create `backend/apps/project/tests/__init__.py` (пустой) и `backend/apps/project/tests/test_projects.py`:

```python
"""Проект: руководитель — участник автоматически, архив не ищется (§18, Q-E26)."""

import pytest

from apps.project import interface
from apps.project.models import Project, ProjectStatus
from apps.project.services import projects


def _make(**over):
    fields = {"code": "П-015", "name": "Объект 15", "country_code": "KZ",
              "manager_user_id": 11, "actor_id": 1}
    fields.update(over)
    return projects.create(**fields)


@pytest.mark.django_db
def test_manager_becomes_a_member(company_context):
    project = _make()
    assert interface.is_member(str(project.id), 11)
    assert interface.member_project_ids(11) == [str(project.id)]


@pytest.mark.django_db
def test_changing_manager_adds_the_new_one(company_context):
    project = _make()
    projects.update(project, manager_user_id=12, actor_id=1)
    assert interface.is_member(str(project.id), 12)
    assert interface.is_member(str(project.id), 11)  # прежний остаётся участником


@pytest.mark.django_db
def test_manager_cannot_be_removed_while_manager(company_context):
    project = _make()
    with pytest.raises(projects.ProjectError):
        projects.remove_member(project, 11, actor_id=1)


@pytest.mark.django_db
def test_code_is_unique(company_context):
    _make()
    with pytest.raises(projects.ProjectError):
        _make(name="Другой")


@pytest.mark.django_db
def test_search_hides_archive_and_respects_membership(company_context):
    mine = _make()
    other = _make(code="П-016", name="Объект 16", manager_user_id=12)
    archived = _make(code="П-017", name="Объект 17")
    projects.update(archived, status=ProjectStatus.ARCHIVED, actor_id=1)
    found = interface.search_projects("Объект", user_id=11, only_member=False)
    assert {row["code"] for row in found} == {"П-015", "П-016"}
    only_mine = interface.search_projects("Объект", user_id=11, only_member=True)
    assert [row["id"] for row in only_mine] == [str(mine.id)]
    assert interface.project_brief([str(other.id)])[str(other.id)]["manager_user_id"] == 12


@pytest.mark.django_db
def test_company_overhead_kind(company_context):
    overhead = _make(code="ОБЩ", name="Общие расходы компании", kind="company_overhead")
    assert Project.objects.get(pk=overhead.pk).kind == "company_overhead"
```

Run: `../.venv/Scripts/python.exe -m pytest apps/project/tests/test_projects.py -q`
Expected: ошибка сбора — нет `apps.project.models`.

- [ ] **Step 2: Модели и миграция, `TENANT_APPS`**

Create `backend/apps/project/models.py`:

```python
"""«Проект» модуля БЗО (D-02) — сущность, на которую ссылаются бюджет,
документы и ``tasks.Project`` (``project_ref``).

Заказчик — голая ссылка на контрагента модуля ``bpp`` плюс подпись
(межаппный FK запрещён). Страна — атрибут проекта: бюджет ведётся в стране
проекта (Q-B08).
"""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models.functions import Now


class ProjectKind(models.TextChoices):
    PROJECT = "project", "Проект"
    COMPANY_OVERHEAD = "company_overhead", "Общие расходы компании"


class ProjectStatus(models.TextChoices):
    ACTIVE = "active", "Активен"
    CLOSED = "closed", "Закрыт"
    ARCHIVED = "archived", "Архив"


class Project(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=24, choices=ProjectKind.choices,
                            default=ProjectKind.PROJECT, db_default=ProjectKind.PROJECT.value)
    status = models.CharField(max_length=16, choices=ProjectStatus.choices,
                              default=ProjectStatus.ACTIVE, db_default=ProjectStatus.ACTIVE.value)
    country_code = models.CharField(max_length=2)
    manager_user_id = models.IntegerField(null=True, blank=True)
    customer_name = models.CharField(max_length=255, default="", blank=True)
    customer_counterparty_id = models.CharField(max_length=64, default="", blank=True)
    date_start = models.DateField(null=True, blank=True)
    date_end = models.DateField(null=True, blank=True)
    ext_1c_ref = models.CharField(max_length=64, default="", blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    created_by = models.IntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        ordering = ("code",)
        verbose_name = "Проект"
        verbose_name_plural = "Проекты"


class ProjectMember(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="members")
    user_id = models.IntegerField()
    added_by = models.IntegerField(null=True, blank=True)
    added_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        constraints = [models.UniqueConstraint(fields=["project", "user_id"],
                                               name="uq_project_member")]
        verbose_name = "Участник проекта"
        verbose_name_plural = "Участники проекта"
```

Сгенерировать `0001_initial.py`:

```bash
DJANGO_SETTINGS_MODULE=htqweb.settings.dev DB_HOST=localhost DB_PORT=55432 DB_NAME=htqweb DB_USER=htqweb DB_PASSWORD=change-me JWT_SECRET=dev PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe manage.py makemigrations project --name initial
```

`backend/htqweb/settings/base.py`: `TENANT_APPS = ("hr", "tasks", "contracts", "signoff", "bpp", "project")`.

`backend/apps/project/holding.py`: `HOLDING_MODELS = ("Project",)` (докстринг: «проекты группы — для сводки A8.1»).

- [ ] **Step 3: Сервис и интерфейс**

Create `backend/apps/project/services/__init__.py` (пустой) и `backend/apps/project/services/projects.py`:

```python
"""Операции над проектами. Руководитель — участник автоматически и не
снимается, пока он руководитель (Q-E26)."""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.db.models import Q

from apps.project.models import Project, ProjectMember, ProjectStatus


class ProjectError(Exception):
    pass


def _ensure_member(project: Project, user_id: int | None, actor_id: int | None) -> None:
    if user_id:
        ProjectMember.objects.get_or_create(project=project, user_id=user_id,
                                            defaults={"added_by": actor_id})


@transaction.atomic
def create(*, code: str, name: str, country_code: str, actor_id: int,
           manager_user_id: int | None = None, **fields) -> Project:
    try:
        with transaction.atomic():
            project = Project.objects.create(code=code, name=name, country_code=country_code,
                                             manager_user_id=manager_user_id,
                                             created_by=actor_id, **fields)
    except IntegrityError as exc:
        raise ProjectError(f"Проект с кодом «{code}» уже есть") from exc
    _ensure_member(project, manager_user_id, actor_id)
    return project


@transaction.atomic
def update(project: Project, *, actor_id: int, **fields) -> Project:
    for key, value in fields.items():
        setattr(project, key, value)
    project.save()
    _ensure_member(project, project.manager_user_id, actor_id)
    return project


def add_member(project: Project, user_id: int, *, actor_id: int) -> None:
    _ensure_member(project, user_id, actor_id)


def remove_member(project: Project, user_id: int, *, actor_id: int) -> None:
    if project.manager_user_id == user_id:
        raise ProjectError("Руководитель проекта остаётся участником, пока он руководитель")
    ProjectMember.objects.filter(project=project, user_id=user_id).delete()


def brief(project: Project) -> dict:
    return {"id": str(project.id), "code": project.code, "name": project.name,
            "kind": project.kind, "status": project.status,
            "country_code": project.country_code, "manager_user_id": project.manager_user_id,
            "customer_name": project.customer_name,
            "customer_counterparty_id": project.customer_counterparty_id or None}


def search(query: str, *, user_id: int, only_member: bool, limit: int = 20) -> list[dict]:
    rows = Project.objects.exclude(status=ProjectStatus.ARCHIVED)
    if query:
        rows = rows.filter(Q(code__icontains=query) | Q(name__icontains=query))
    if only_member:
        rows = rows.filter(members__user_id=user_id)
    return [brief(p) for p in rows.order_by("code")[:limit]]
```

Replace `backend/apps/project/interface.py`:

```python
"""Межаппный интерфейс «Проекта» (мастер-план §2.6)."""

from __future__ import annotations

from apps.core.services import require_service

from .models import Project, ProjectMember
from .services import projects


def project_brief(ids: list[str]) -> dict[str, dict]:
    require_service("project")
    return {str(p.id): projects.brief(p) for p in Project.objects.filter(id__in=ids)}


def is_member(project_id: str, user_id: int) -> bool:
    require_service("project")
    return ProjectMember.objects.filter(project_id=project_id, user_id=user_id).exists()


def member_project_ids(user_id: int) -> list[str]:
    require_service("project")
    return [str(pid) for pid in ProjectMember.objects.filter(user_id=user_id)
            .values_list("project_id", flat=True)]


def search_projects(query: str, *, user_id: int, only_member: bool,
                    limit: int = 20) -> list[dict]:
    require_service("project")
    return projects.search(query, user_id=user_id, only_member=only_member, limit=limit)
```

Run: `../.venv/Scripts/python.exe -m pytest apps/project/tests/test_projects.py -q`
Expected: 6 passed.

- [ ] **Step 4: Падающие тесты API**

Create `backend/apps/project/tests/test_api.py`:

```python
"""Ручки проектов: создают директора и администраторы (узел project.projects),
участников ведут ПМ и HR (узел project.members), ПМ видит свои проекты."""

import json

import pytest
from django.test import Client

from apps.access.tests.helpers import assign, token

BASE = "/api/project/v1"


def _auth(slug, user_id=7):
    tok = token(user_id=user_id, sub=str(user_id), company=slug)
    return {"HTTP_AUTHORIZATION": f"Bearer {tok}", "HTTP_X_HTQ_COMPANY": slug}


def _create(slug, **body):
    payload = {"code": "П-015", "name": "Объект 15", "country_code": "KZ",
               "manager_user_id": 11, **body}
    return Client().post(f"{BASE}/projects", data=json.dumps(payload),
                         content_type="application/json", **_auth(slug))


@pytest.mark.django_db
def test_create_needs_write(company_context):
    slug = company_context["slug"]
    assign(slug, 7, "project", "view")
    assert _create(slug).status_code == 403
    assign(slug, 7, "project.projects", "full")
    response = _create(slug)
    assert response.status_code == 201, response.content
    assert response.json()["code"] == "П-015"


@pytest.mark.django_db
def test_duplicate_code_is_422(company_context):
    slug = company_context["slug"]
    assign(slug, 7, "project.projects", "full")
    _create(slug)
    second = _create(slug)
    assert second.status_code == 422 and second.json()["code"] == "E-PRJ-01"


@pytest.mark.django_db
def test_members(company_context):
    slug = company_context["slug"]
    assign(slug, 7, "project.projects", "full")
    assign(slug, 7, "project.members", "full")
    project_id = _create(slug).json()["id"]
    url = f"{BASE}/projects/{project_id}/members"
    added = Client().post(url, data=json.dumps({"user_id": 21}),
                          content_type="application/json", **_auth(slug))
    assert added.status_code == 201
    assert sorted(Client().get(url, **_auth(slug)).json()) == [11, 21]
    refused = Client().delete(f"{url}/11", **_auth(slug))
    assert refused.status_code == 422 and refused.json()["code"] == "E-PRJ-02"


@pytest.mark.django_db
def test_mine_filter(company_context):
    slug = company_context["slug"]
    assign(slug, 7, "project.projects", "full")
    _create(slug)
    _create(slug, code="П-016", name="Объект 16", manager_user_id=7)
    mine = Client().get(f"{BASE}/projects?mine=1", **_auth(slug)).json()
    assert [row["code"] for row in mine] == ["П-016"]
```

Run: `../.venv/Scripts/python.exe -m pytest apps/project/tests/test_api.py -q`
Expected: FAIL — 404.

- [ ] **Step 5: Схемы, вьюхи, маршруты**

Create `backend/apps/project/schemas.py`:

```python
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class ProjectIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=255)
    kind: str = Field("project", pattern="^(project|company_overhead)$")
    country_code: str = Field(..., min_length=2, max_length=2)
    manager_user_id: Optional[int] = None
    customer_name: str = Field("", max_length=255)
    customer_counterparty_id: str = Field("", max_length=64)
    date_start: Optional[date] = None
    date_end: Optional[date] = None


class ProjectPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    status: Optional[str] = Field(None, pattern="^(active|closed|archived)$")
    manager_user_id: Optional[int] = None
    customer_name: Optional[str] = Field(None, max_length=255)
    customer_counterparty_id: Optional[str] = Field(None, max_length=64)
    date_start: Optional[date] = None
    date_end: Optional[date] = None


class MemberIn(BaseModel):
    user_id: int
```

Replace `backend/apps/project/views.py`:

```python
"""Ручки «Проекта» — под гейтом модуля project с явным уровнем.

Создание и правка — ``write`` плюс узел ``project.projects`` (директора,
администраторы сайта, Q-B16). Участники — узел ``project.members`` (ПМ и
HR, Q-B17). Ключи узлов проверяет ``access.interface.flags_for``.
"""

from __future__ import annotations

from django.http import Http404

from apps.access import interface as access
from htqweb.errors import DomainError
from htqweb.http import api_view, json_error

from . import schemas
from .models import Project
from .services import projects


def _need(request, node: str, flag: str) -> None:
    company = (getattr(request, "company", None) or {}).get("slug")
    if flag not in access.flags_for(request.token, node, company):
        raise DomainError("E-ACC-01", "Недостаточно прав для этого действия.", status=403)


def _project(project_id: str) -> Project:
    project = Project.objects.filter(pk=project_id).first()
    if project is None:
        raise Http404("Проект не найден")
    return project


@api_view(methods=("GET",), module="project", level="read")
def _list(request):
    return projects.search(request.GET.get("q", ""), user_id=request.token.user_id,
                           only_member=request.GET.get("mine") == "1", limit=200)


@api_view(methods=("POST",), module="project", level="write", body=schemas.ProjectIn,
          status=201)
def _create(request, data: schemas.ProjectIn):
    _need(request, "project.projects", "create")
    try:
        project = projects.create(actor_id=request.token.user_id, **data.model_dump())
    except projects.ProjectError as exc:
        raise DomainError("E-PRJ-01", str(exc)) from exc
    return projects.brief(project)


def project_collection(request):
    if request.method == "GET":
        return _list(request)
    if request.method == "POST":
        return _create(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), module="project", level="read")
def _get(request, project_id: str):
    return projects.brief(_project(project_id))


@api_view(methods=("PATCH",), module="project", level="write", body=schemas.ProjectPatch)
def _patch(request, project_id: str, data: schemas.ProjectPatch):
    _need(request, "project.projects", "edit")
    project = projects.update(_project(project_id), actor_id=request.token.user_id,
                              **data.model_dump(exclude_unset=True))
    return projects.brief(project)


def project_item(request, project_id: str):
    if request.method == "GET":
        return _get(request, project_id=project_id)
    if request.method == "PATCH":
        return _patch(request, project_id=project_id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("GET",), module="project", level="read")
def _members(request, project_id: str):
    return sorted(_project(project_id).members.values_list("user_id", flat=True))


@api_view(methods=("POST",), module="project", level="write", body=schemas.MemberIn,
          status=201)
def _add_member(request, project_id: str, data: schemas.MemberIn):
    _need(request, "project.members", "edit")
    projects.add_member(_project(project_id), data.user_id, actor_id=request.token.user_id)
    return {"user_id": data.user_id}


def project_members(request, project_id: str):
    if request.method == "GET":
        return _members(request, project_id=project_id)
    if request.method == "POST":
        return _add_member(request, project_id=project_id)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("DELETE",), module="project", level="write", status=204)
def _remove_member(request, project_id: str, user_id: int):
    _need(request, "project.members", "edit")
    try:
        projects.remove_member(_project(project_id), user_id, actor_id=request.token.user_id)
    except projects.ProjectError as exc:
        raise DomainError("E-PRJ-02", str(exc)) from exc
    return {}


def project_member(request, project_id: str, user_id: int):
    if request.method == "DELETE":
        return _remove_member(request, project_id=project_id, user_id=user_id)
    return json_error("Method Not Allowed", 405)
```

Replace `backend/apps/project/urls.py`:

```python
"""Маршруты /api/project/v1/."""

from django.urls import path

from . import views

urlpatterns = [
    path("projects", views.project_collection),
    path("projects/", views.project_collection),
    path("projects/<str:project_id>", views.project_item),
    path("projects/<str:project_id>/", views.project_item),
    path("projects/<str:project_id>/members", views.project_members),
    path("projects/<str:project_id>/members/", views.project_members),
    path("projects/<str:project_id>/members/<int:user_id>", views.project_member),
    path("projects/<str:project_id>/members/<int:user_id>/", views.project_member),
]
```

Create `backend/apps/project/admin.py` — регистрация `Project`, `ProjectMember` с `ServiceGatedAdminMixin`.

Run: `../.venv/Scripts/python.exe -m pytest apps/project/tests apps/access/tests/test_gate.py -q`
Expected: всё PASS. `DELETE` со статусом 204 и телом `{}`: если `api_view` отдаёт 204 с телом и тест клиента падает на разборе — вернуть `HttpResponse(status=204)` (как `_no_content()` в `apps/tasks/views.py`).

- [ ] **Step 6: Связь `tasks.Project` → «Проект»**

Падающий тест — create `backend/apps/project/tests/test_link_tasks.py`:

```python
"""Команда связывания: проект задач получает ссылку на «Проект» БЗО."""

import pytest
from django.core.management import call_command

from apps.project.models import Project
from apps.tasks.models import Project as TaskProject


@pytest.mark.django_db
def test_every_task_project_gets_a_project(company_context):
    board = TaskProject.objects.create(name="Объект 15", key="OBJ15")
    call_command("project_link_tasks", "--company", company_context["slug"])
    board.refresh_from_db()
    project = Project.objects.get(pk=board.project_ref)
    assert (project.name, project.code) == ("Объект 15", "OBJ15")
    call_command("project_link_tasks", "--company", company_context["slug"])  # идемпотентно
    assert Project.objects.count() == 1
```

(Если у `tasks.Project` другие обязательные поля — посмотреть `backend/apps/tasks/models.py:606` и `seed_tasks_demo`, дополнить `create(...)`.)

В `backend/apps/tasks/models.py`, класс `Project`, добавить поле:

```python
    # Ссылка на «Проект» модуля БЗО (apps.project, D-02): строка UUID, не FK —
    # межаппный FK запрещён. Пусто у проектов, ещё не связанных командой
    # manage.py project_link_tasks.
    project_ref = models.CharField(max_length=36, default="", blank=True, db_default="")
```

Сгенерировать миграцию `tasks` (expand, CLAUDE.md «Мультикомпанейность» — на бою ей нужен `migrate_companies`):

```bash
DJANGO_SETTINGS_MODULE=htqweb.settings.dev DB_HOST=localhost DB_PORT=55432 DB_NAME=htqweb DB_USER=htqweb DB_PASSWORD=change-me JWT_SECRET=dev PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe manage.py makemigrations tasks --name project_ref
```

Create `backend/apps/project/management/__init__.py`, `management/commands/__init__.py` и `management/commands/project_link_tasks.py`:

```python
"""Связать проекты доски задач с «Проектами» БЗО (A1.3).

Для каждого ``tasks.Project`` без ``project_ref`` заводит «Проект» (код —
ключ доски, имя — имя доски, страна — KZ; руководителя и заказчика
заполняет человек потом) и пишет ссылку. Идемпотентна. Читает и пишет
``tasks`` через ``apps.tasks.interface`` — межаппный импорт моделей запрещён.
"""

from django.core.management.base import BaseCommand

from apps.project.models import Project
from apps.tasks import interface as tasks
from htqweb.tenancy.db import use_company


class Command(BaseCommand):
    help = "Связать проекты доски задач с «Проектами» модуля БЗО."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True)

    def handle(self, *args, company, **options):
        with use_company(company):
            linked = 0
            for board in tasks.projects_without_ref():
                project, _ = Project.objects.get_or_create(
                    code=board["key"], defaults={"name": board["name"], "country_code": "KZ"})
                tasks.set_project_ref(board["id"], str(project.id))
                linked += 1
        self.stdout.write(self.style.SUCCESS(f"Связано проектов: {linked}"))
```

В `backend/apps/tasks/interface.py` добавить (исполнитель A владеет `tasks`):

```python
def projects_without_ref() -> list[dict]:
    """Проекты доски без ссылки на «Проект» БЗО — для project_link_tasks."""
    require_service("tasks")
    from .models import Project

    return list(Project.objects.filter(project_ref="").values("id", "key", "name"))


def set_project_ref(project_id: int, project_ref: str) -> None:
    require_service("tasks")
    from .models import Project

    Project.objects.filter(pk=project_id).update(project_ref=project_ref)
```

Run: `../.venv/Scripts/python.exe -m pytest apps/project/tests apps/tasks/tests -q`
Expected: всё PASS.

- [ ] **Step 7: Документация и коммит**

`STRUCTURE.md` §3.1, строка **project**: убрать «каркас», дописать «`manage.py project_link_tasks --company` — связать доску задач». `CLAUDE.md`, «Мультикомпанейность»: `TENANT_APPS` — дописать `"project"`. `API.md` — ручки `/api/project/v1/projects…`.

```bash
git add backend/apps/project backend/apps/tasks/models.py backend/apps/tasks/interface.py backend/apps/tasks/migrations backend/htqweb/settings/base.py STRUCTURE.md CLAUDE.md API.md
git commit -m "feat(project): «Проект» БЗО — участники, поиск, связь с доской задач"
```

---

## Task 6: Роли модуля и проверки прав

**Files:**
- Create: `docs/plans/2026-09-27-bpp-roles-matrix.md`
- Create: `backend/apps/access/migrations/0014_seed_bpp_roles.py`
- Modify: `backend/apps/hr/management/group_structures.py` (должность «Руководитель проекта»), `backend/apps/hr/tests/test_group_structures.py`
- Create: `backend/apps/bpp/services/core/permissions.py`, `backend/apps/bpp/management/__init__.py`, `management/commands/__init__.py`, `management/commands/bpp_assign_roles.py`
- Modify: `backend/apps/hr/interface.py` (`positions_by_title`) — ⚠️ `hr` владеет A в части структуры, функция чтения — тоже A
- Test: `backend/apps/access/tests/test_bpp_roles.py`, `backend/apps/bpp/tests/test_permissions.py`, `backend/apps/bpp/tests/test_assign_roles.py`

**Interfaces:**
- Consumes: `refdata.interface.article_groups`, `access.interface.flags_for / ensure_position_role`.
- Produces:
  - системные роли `bpp-fd`, `bpp-td`, `bpp-od`, `bpp-gd`, `bpp-buh`, `bpp-sn`, `bpp-pm`, `bpp-adm`;
  - `permissions.can(request, node: str, flag: str) -> bool`;
  - `permissions.article_groups_for(request) -> list[str]` — коды групп статей, доступных пользователю (BR-010);
  - `hr.interface.positions_by_title(titles: list[str]) -> dict[str, int]`;
  - команда `bpp_assign_roles --company <slug> [--dry-run]`.

⚠️ `allowed_actions(request, obj)` из мастер-плана §2.6 зависит от статусов документов, которых ещё нет: каждый документ (B2.x, B3.x) пишет свой `allowed_actions` поверх `permissions.can`. Здесь — только `can` и `article_groups_for`.

- [ ] **Step 1: Матрица ролей на утверждение**

Create `docs/plans/2026-09-27-bpp-roles-matrix.md` — таблица «роль × узел → признаки» по ТЗ §17 (права проверяются в каждом запросе; скрытие кнопок на фронте — только удобство). Значения — ровно те, что попадут в миграцию шага 3:

```markdown
# Модуль БЗО: роли и права — на утверждение Алгазы

Основание — ТЗ §17. Признаки: V — видит, C — создаёт, E — меняет / выполняет операцию, D — удаляет. Пусто — запрет. «Свои» (свои статьи, свои проекты, свои документы) режет сервис по принадлежности, а не роль.

| Узел | ФД | ТД | ОД | ГД | БУХ | СН | ПМ | АДМ |
|---|---|---|---|---|---|---|---|---|
| `bpp.budgets` | VCED | V | V | V | | V (свои статьи) | V (свои статьи и проекты) | V |
| `bpp.budgets.approve` | E | | | | | | | |
| `bpp.requests` | V | V | V | V | | VCED (свои) | VCED (свои) | V |
| `bpp.requests.cancel_approved` | E | | | | | | | |
| `bpp.plan` | V | | | | | VE (свой) | VE (свой) | |
| `bpp.plan.all` | V | | | | | | | |
| `bpp.agreements` | VE | VE | VE | VE | V | VCE | VCE | V |
| `bpp.agreements.terminate` | E | | | | | | | |
| `bpp.invoices` | V | V | V | V | V | VCED (свои) | VCED (свои) | |
| `bpp.invoices.decision` | E | | | | | | | |
| `bpp.invoices.payment` | | | | | E | | | |
| `bpp.invoices.closing_docs` | E (от имени автора) | | | | | E (свои) | E (свои) | |
| `bpp.bank` | VCED | | | | V | | | |
| `bpp.dashboard` | V | V | V | V | V | | | |
| `bpp.counterparties` | VCE | V | V | V | VCE | VC | VC | |
| `bpp.counterparties.block` | E | | | | | | | |
| `bpp.alternatives` | V | V | V | V | | VC | V (свои документы) | |
| `bpp.alternatives.select` | E | | | E | | | | |
| `bpp.kpi` | VE | | V | V | | V (свои строки) | | |
| `bpp.accountable` | VE | | | | V | VC | VC | |
| `bpp.accountable.payment` | | | | | E | | | |
| `bpp.articles.supply` | V | V | V | V | V | V | | V |
| `bpp.articles.pm` | V | V | V | V | V | | V | V |
| `bpp.settings` | V | | | | | | | VCED |
| `refdata` | VCE | V | V | V | V | V | V | VCE |
| `project` | VCE | VCE | VCE | VCE | V | V | V | VCE |
| `project.members` | V | V | V | V | V | V | VE | VE |

Главный бухгалтер и бухгалтер — одна роль «БУХ» (D-40). АДМ не видит финансовые документы (ТЗ §17): у него только справочники, настройки, проекты и просмотр реестров без сумм — просмотр бюджетов, заявок и договоров остаётся, как в ТЗ. Роли утверждаются при создании (Q-C14): до мерджа миграции `access/0014` — подтверждение Алгазы.
```

- [ ] **Step 2: Падающий тест ролей**

Create `backend/apps/access/tests/test_bpp_roles.py`:

```python
"""Системные роли БЗО: существуют, системные, операции только у кого положено."""

import pytest

from apps.access.models import Role, RolePermission

ROLES = ("bpp-fd", "bpp-td", "bpp-od", "bpp-gd", "bpp-buh", "bpp-sn", "bpp-pm", "bpp-adm")
OPERATIONS = ("bpp.budgets.approve", "bpp.requests.cancel_approved",
              "bpp.agreements.terminate", "bpp.invoices.decision", "bpp.invoices.payment",
              "bpp.counterparties.block", "bpp.alternatives.select",
              "bpp.accountable.payment", "bpp.invoices.closing_docs")


def _flags(code: str, node: str) -> set[str]:
    row = RolePermission.objects.get(role__code=code, node=node)
    return set(row.flags)


@pytest.mark.django_db
def test_every_bpp_role_exists_and_is_system():
    found = Role.objects.filter(code__in=ROLES)
    assert {r.code for r in found} == set(ROLES)
    assert all(r.is_system and not r.company_slug for r in found)


@pytest.mark.django_db
def test_every_role_has_an_explicit_row_on_every_operation():
    """Узел из трёх сегментов наследует глубину родителя: без явной строки
    автор счёта с edit на bpp.invoices получил бы решение ФД."""
    for code in ROLES:
        for node in OPERATIONS:
            assert RolePermission.objects.filter(role__code=code, node=node).exists(), \
                (code, node)


@pytest.mark.django_db
def test_only_fd_decides_on_invoices_and_only_buh_marks_payment():
    assert [c for c in ROLES if "edit" in _flags(c, "bpp.invoices.decision")] == ["bpp-fd"]
    assert [c for c in ROLES if "edit" in _flags(c, "bpp.invoices.payment")] == ["bpp-buh"]


@pytest.mark.django_db
def test_alternatives_are_chosen_by_fd_and_gd():
    chooser = [c for c in ROLES if "edit" in _flags(c, "bpp.alternatives.select")]
    assert chooser == ["bpp-fd", "bpp-gd"]


@pytest.mark.django_db
def test_article_groups_split_supply_and_pm():
    assert "view" in _flags("bpp-sn", "bpp.articles.supply")
    assert _flags("bpp-sn", "bpp.articles.pm") == set()
    assert "view" in _flags("bpp-pm", "bpp.articles.pm")
    assert _flags("bpp-pm", "bpp.articles.supply") == set()
```

Run: `../.venv/Scripts/python.exe -m pytest apps/access/tests/test_bpp_roles.py -q`
Expected: FAIL — ролей нет.

- [ ] **Step 3: Миграция ролей**

Create `backend/apps/access/migrations/0014_seed_bpp_roles.py` по образцу `0012_seed_services_admin_role.py`. Матрица — литералами, ровно по `docs/plans/2026-09-27-bpp-roles-matrix.md`. Каждая роль получает строку на **каждом** узле из `OPERATIONS` теста (пустой набор — запрет) и на обоих узлах групп статей:

```python
"""Модуль БЗО: восемь системных ролей (ТЗ §17, матрица —
docs/plans/2026-09-27-bpp-roles-matrix.md, утверждает Алгазы, Q-C14).

Узлы-операции (три сегмента) и группы статей у КАЖДОЙ роли — явной строкой:
без неё узел наследует глубину родителя (CLAUDE.md, «Новые под-узлы
реестра заводить сразу с явными строками», образец — 0008).
"""

from django.db import migrations

V, C, E, D = "can_view", "can_create", "can_edit", "can_delete"
ALL_FLAGS = (V, C, E, D)

OPERATIONS = ("bpp.budgets.approve", "bpp.requests.cancel_approved",
              "bpp.agreements.terminate", "bpp.invoices.decision", "bpp.invoices.payment",
              "bpp.counterparties.block", "bpp.alternatives.select",
              "bpp.accountable.payment", "bpp.invoices.closing_docs",
              "bpp.articles.supply", "bpp.articles.pm", "bpp.plan.all")

ROLES = {
    "bpp-fd": ("БЗО: Финансовый директор", {
        "bpp.budgets": (V, C, E, D), "bpp.budgets.approve": (E,), "bpp.requests": (V,),
        "bpp.requests.cancel_approved": (E,), "bpp.plan": (V,), "bpp.plan.all": (V,),
        "bpp.agreements": (V, E), "bpp.agreements.terminate": (E,),
        "bpp.invoices": (V,), "bpp.invoices.decision": (E,),
        "bpp.invoices.closing_docs": (E,), "bpp.bank": (V, C, E, D),
        "bpp.dashboard": (V,), "bpp.counterparties": (V, C, E),
        "bpp.counterparties.block": (E,), "bpp.alternatives": (V,),
        "bpp.alternatives.select": (E,), "bpp.kpi": (V, E), "bpp.accountable": (V, E),
        "bpp.articles.supply": (V,), "bpp.articles.pm": (V,), "bpp.settings": (V,),
        "refdata": (V, C, E), "project": (V, C, E), "project.members": (V,),
    }),
    "bpp-td": ("БЗО: Технический директор", {
        "bpp.budgets": (V,), "bpp.requests": (V,), "bpp.agreements": (V, E),
        "bpp.invoices": (V,), "bpp.dashboard": (V,), "bpp.counterparties": (V,),
        "bpp.alternatives": (V,), "bpp.articles.supply": (V,), "bpp.articles.pm": (V,),
        "refdata": (V,), "project": (V, C, E), "project.members": (V,),
    }),
    "bpp-od": ("БЗО: Операционный директор", {
        "bpp.budgets": (V,), "bpp.requests": (V,), "bpp.agreements": (V, E),
        "bpp.invoices": (V,), "bpp.dashboard": (V,), "bpp.counterparties": (V,),
        "bpp.alternatives": (V,), "bpp.kpi": (V,), "bpp.articles.supply": (V,),
        "bpp.articles.pm": (V,), "refdata": (V,), "project": (V, C, E),
        "project.members": (V,),
    }),
    "bpp-gd": ("БЗО: Генеральный директор", {
        "bpp.budgets": (V,), "bpp.requests": (V,), "bpp.agreements": (V, E),
        "bpp.invoices": (V,), "bpp.dashboard": (V,), "bpp.counterparties": (V,),
        "bpp.alternatives": (V,), "bpp.alternatives.select": (E,), "bpp.kpi": (V,),
        "bpp.articles.supply": (V,), "bpp.articles.pm": (V,), "refdata": (V,),
        "project": (V, C, E), "project.members": (V,),
    }),
    "bpp-buh": ("БЗО: Бухгалтер", {
        "bpp.agreements": (V,), "bpp.invoices": (V,), "bpp.invoices.payment": (E,),
        "bpp.bank": (V,), "bpp.dashboard": (V,), "bpp.counterparties": (V, C, E),
        "bpp.accountable": (V,), "bpp.accountable.payment": (E,),
        "bpp.articles.supply": (V,), "bpp.articles.pm": (V,), "refdata": (V,),
        "project": (V,), "project.members": (V,),
    }),
    "bpp-sn": ("БЗО: Снабженец", {
        "bpp.budgets": (V,), "bpp.requests": (V, C, E, D), "bpp.plan": (V, E),
        "bpp.agreements": (V, C, E), "bpp.invoices": (V, C, E, D),
        "bpp.invoices.closing_docs": (E,), "bpp.counterparties": (V, C),
        "bpp.alternatives": (V, C), "bpp.kpi": (V,), "bpp.accountable": (V, C),
        "bpp.articles.supply": (V,), "refdata": (V,), "project": (V,),
        "project.members": (V,),
    }),
    "bpp-pm": ("БЗО: Руководитель проекта", {
        "bpp.budgets": (V,), "bpp.requests": (V, C, E, D), "bpp.plan": (V, E),
        "bpp.agreements": (V, C, E), "bpp.invoices": (V, C, E, D),
        "bpp.invoices.closing_docs": (E,), "bpp.counterparties": (V, C),
        "bpp.alternatives": (V,), "bpp.accountable": (V, C), "bpp.articles.pm": (V,),
        "refdata": (V,), "project": (V,), "project.members": (V, E),
    }),
    "bpp-adm": ("БЗО: Администратор модуля", {
        "bpp.budgets": (V,), "bpp.requests": (V,), "bpp.agreements": (V,),
        "bpp.articles.supply": (V,), "bpp.articles.pm": (V,),
        "bpp.settings": (V, C, E, D), "refdata": (V, C, E),
        "project": (V, C, E), "project.members": (V, E),
    }),
}


def seed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")
    for code, (title, nodes) in ROLES.items():
        role, _ = Role.objects.get_or_create(code=code,
                                             defaults={"title": title, "is_system": True})
        explicit = dict.fromkeys(OPERATIONS, ())
        explicit.update(nodes)
        for node, flags in explicit.items():
            RolePermission.objects.update_or_create(
                role=role, node=node, defaults={flag: flag in flags for flag in ALL_FLAGS})


def unseed(apps, schema_editor):
    apps.get_model("access", "Role").objects.filter(code__in=list(ROLES)).delete()


class Migration(migrations.Migration):

    dependencies = [("access", "0013_platform_admin_bpp_modules")]

    operations = [migrations.RunPython(seed, unseed)]
```

Run: `../.venv/Scripts/python.exe -m pytest apps/access/tests/test_bpp_roles.py apps/access/tests -q`
Expected: всё PASS. Если падает сторож уровня модулей для `employee-basic` или `services-admin` — они не должны меняться; разобраться, не задевает ли миграция их строки.

- [ ] **Step 4: Падающие тесты проверок прав**

Create `backend/apps/bpp/tests/test_permissions.py`:

```python
"""Группы статей по роли (BR-010): СН — «Снабжение», ПМ — «Проектное
управление», совмещающий — обе."""

import pytest
from django.test import RequestFactory

from apps.access.models import Role, RoleAssignment, ScopeKind
from apps.access.tests.helpers import token
from apps.bpp.services.core import permissions
from htqweb.authn.jwt import decode_token  # проверить фактическое имя, см. ниже


def _request(slug: str, user_id: int, *codes: str):
    for code in codes:
        RoleAssignment.objects.get_or_create(
            company_slug=slug, user_id=user_id, role=Role.objects.get(code=code),
            scope_kind=ScopeKind.COMPANY, scope_id=None)
    request = RequestFactory().get("/")
    request.token = decode_token(token(user_id=user_id, sub=str(user_id), company=slug))
    request.company = {"slug": slug}
    return request


@pytest.mark.django_db
def test_groups_follow_roles(company_context):
    slug = company_context["slug"]
    assert permissions.article_groups_for(_request(slug, 21, "bpp-sn")) == ["supply"]
    assert permissions.article_groups_for(_request(slug, 22, "bpp-pm")) == ["pm"]
    assert sorted(permissions.article_groups_for(_request(slug, 23, "bpp-sn", "bpp-pm"))) \
        == ["pm", "supply"]
    assert permissions.article_groups_for(_request(slug, 24)) == []


@pytest.mark.django_db
def test_can(company_context):
    slug = company_context["slug"]
    fd = _request(slug, 31, "bpp-fd")
    sn = _request(slug, 32, "bpp-sn")
    assert permissions.can(fd, "bpp.invoices.decision", "edit")
    assert not permissions.can(sn, "bpp.invoices.decision", "edit")
```

⚠️ Имя функции разбора токена: посмотреть, чем `htqweb.http._authenticate_jwt` превращает строку токена в объект (`grep -n "def " backend/htqweb/authn/jwt.py`), и импортировать её. Если удобнее — собрать `request.token` так же, как `apps/access/tests/test_gate.py::_request`.

Run: `../.venv/Scripts/python.exe -m pytest apps/bpp/tests/test_permissions.py -q`
Expected: FAIL — нет `permissions`.

- [ ] **Step 5: Проверки прав модуля**

Create `backend/apps/bpp/services/core/permissions.py`:

```python
"""Проверки прав модуля тоньше уровня модуля — по узлу реестра.

Роли считаются один раз на запрос: гейт ``api_view(module=…)`` кладёт расчёт
в ``request.access_resolution``, здесь он переиспользуется, если совпадают
компания и пользователь (тот же приём, что ``apps/hr/rbac.py::NodeAccess``).
Принадлежность («свой документ», «участник проекта») проверяет документ,
не эта функция.
"""

from __future__ import annotations

from apps.access import interface as access
from apps.refdata import interface as refdata


def _company(request) -> str | None:
    return (getattr(request, "company", None) or {}).get("slug")


def _resolution(request, company):
    cached = getattr(request, "access_resolution", None)
    if cached and cached[0] == company and cached[1] == request.token.user_id:
        return cached[2]
    return None


def flags(request, node: str) -> frozenset[str]:
    company = _company(request)
    return access.flags_for(request.token, node, company,
                            resolution=_resolution(request, company))


def can(request, node: str, flag: str) -> bool:
    return flag in flags(request, node)


def article_groups_for(request) -> list[str]:
    """Коды групп статей, открытых пользователю (BR-010)."""
    return [group["code"] for group in refdata.article_groups()
            if group["is_active"] and can(request, group["node_key"], "view")]
```

Run: `../.venv/Scripts/python.exe -m pytest apps/bpp/tests/test_permissions.py -q`
Expected: PASS.

- [ ] **Step 6: Должность ПМ и команда выдачи ролей**

В `backend/apps/hr/management/group_structures.py`, `_HOLDING.posts`, после строки «ГИП» добавить:

```python
        Post("Руководитель проекта", "pto", 645, 8, "middle", "Технический директор"),
```

и в `people` после «Байжанов»:

```python
        Person("Ермеков", "Тимур", "Асланович", "Руководитель проекта", "+7 (700) 100-30-04"),
```

В `backend/apps/hr/tests/test_group_structures.py` заменить `(HOLDING, 12, 12)` на `(HOLDING, 13, 13)`; прогнать файл и, если меняется раскладка уровней (`(HOLDING, {1, 2, 4})`), разобраться по докстрингу теста, а не подгонять число.

В `backend/apps/hr/interface.py` добавить:

```python
def positions_by_title(titles: list[str]) -> dict[str, int]:
    """Активные должности компании по точному названию — для сидов и выдачи
    ролей (``bpp_assign_roles``). Название неуникально — берётся первая по id."""
    require_service("hr")
    found: dict[str, int] = {}
    for row in (Position.objects.filter(title__in=titles, is_active=True)
                .order_by("id").values("id", "title")):
        found.setdefault(row["title"], row["id"])
    return found
```

Падающий тест — create `backend/apps/bpp/tests/test_assign_roles.py`:

```python
"""bpp_assign_roles: должности холдинга получают роли модуля."""

import pytest
from django.core.management import call_command

from apps.access.models import PositionRole
from apps.hr.models import Department, Position


@pytest.mark.django_db
def test_positions_get_roles(company_context):
    dep = Department.objects.create(name="Финансы", path="fin")
    fd = Position.objects.create(title="Финансовый директор", department=dep, weight=110)
    buh = Position.objects.create(title="Главный бухгалтер", department=dep, weight=610)
    call_command("bpp_assign_roles", "--company", company_context["slug"])
    given = set(PositionRole.objects.values_list("position_id", "role__code"))
    assert {(fd.id, "bpp-fd"), (buh.id, "bpp-buh")} <= given
    call_command("bpp_assign_roles", "--company", company_context["slug"])  # идемпотентно
    assert PositionRole.objects.filter(role__code="bpp-fd").count() == 1
```

Create `backend/apps/bpp/management/__init__.py`, `management/commands/__init__.py` и `management/commands/bpp_assign_roles.py`:

```python
"""Выдать должностям управляющей компании роли модуля БЗО (мастер-план §2.4).

Идемпотентна: уже выданную роль не трогает. Должности, которых нет в
компании, перечисляет в выводе. ``bpp-adm`` выдаётся лично, не должности.
"""

from django.core.management.base import BaseCommand

from apps.access import interface as access
from apps.hr import interface as hr
from htqweb.tenancy.db import use_company

POSITION_ROLES = {
    "Финансовый директор": "bpp-fd",
    "Технический директор": "bpp-td",
    "Операционный директор": "bpp-od",
    "Генеральный директор": "bpp-gd",
    "Главный бухгалтер": "bpp-buh",
    "Бухгалтер": "bpp-buh",
    "Менеджер по закупкам": "bpp-sn",
    "Руководитель проекта": "bpp-pm",
}


class Command(BaseCommand):
    help = "Выдать должностям компании роли модуля БЗО."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, company, dry_run, **options):
        with use_company(company):
            positions = hr.positions_by_title(list(POSITION_ROLES))
        for title, role in POSITION_ROLES.items():
            position_id = positions.get(title)
            if position_id is None:
                self.stdout.write(f"нет должности: {title}")
                continue
            if dry_run:
                self.stdout.write(f"выдать {role} → {title} (#{position_id})")
                continue
            created = access.ensure_position_role(company, position_id, role, "company")
            self.stdout.write(f"{'выдано' if created else 'уже есть'}: {role} → {title}")
```

Run: `../.venv/Scripts/python.exe -m pytest apps/bpp/tests apps/hr/tests/test_group_structures.py apps/access/tests -q`
Expected: всё PASS.

- [ ] **Step 7: Документация и коммит**

`CLAUDE.md`, раздел «Модуль БЗО»: строка про роли — «восемь системных ролей `bpp-*` (`access/0014`, матрица `docs/plans/2026-09-27-bpp-roles-matrix.md`, утверждает Алгазы); выдача — `manage.py bpp_assign_roles --company <slug>`». `STRUCTURE.md` §3.1, строка **bpp**: дописать `services/core/permissions.py`.

```bash
git add docs/plans/2026-09-27-bpp-roles-matrix.md backend/apps/access/migrations/0014_seed_bpp_roles.py backend/apps/access/tests/test_bpp_roles.py backend/apps/hr/management/group_structures.py backend/apps/hr/tests/test_group_structures.py backend/apps/hr/interface.py backend/apps/bpp CLAUDE.md STRUCTURE.md
git commit -m "feat(bpp): восемь ролей модуля, группы статей по роли, выдача ролей должностям холдинга"
```

---

## Task 7: Центр уведомлений

**Files:**
- Create: `backend/apps/notifications/models.py`, `migrations/__init__.py`, `migrations/0001_initial.py` (makemigrations), `services/__init__.py`, `services/center.py`, `services/delivery.py`, `services/telegram.py`, `tasks.py`, `schemas.py`, `admin.py`
- Modify: `backend/apps/notifications/interface.py`, `views.py`, `urls.py`; `backend/apps/access/self_service.py` (`SELF_SERVICE["notifications"]`); `backend/htqweb/settings/base.py` (`NOTIFY_TELEGRAM_BOT_TOKEN`, `NOTIFY_TELEGRAM_BOT_NAME`, `NOTIFY_TELEGRAM_WEBHOOK_SECRET`); `.env.example`
- Test: `backend/apps/notifications/tests/__init__.py`, `test_center.py`, `test_delivery.py`, `test_api.py`, `test_telegram.py`

**Interfaces:**
- Consumes: `users.interface.get_users_brief`, `messenger.interface.dispatch_notification`.
- Produces (`apps.notifications.interface`, мастер-план §2.6):
  - `notify(*, recipients: list[int], event: str, title: str, text: str = "", url: str = "", company_slug: str | None, target_type: str = "", target_id: str = "", actor_id: int | None = None, actor_avatar_url: str | None = None) -> list[str]` — id созданных уведомлений;
  - `latest(user_id: int, *, company_slug: str | None, limit: int = 50) -> list[dict]`;
  - `history(user_id: int, *, company_slug: str | None, page: int, limit: int, status: str, target_type: str | None) -> dict`;
  - `mark_read(notification_id: str, user_id: int)`, `mark_unread(...)`, `mark_all_read(user_id: int, *, company_slug: str | None)`, `delete(notification_id: str, user_id: int)`.
- Словарь уведомления: `{id, recipient_id, company_slug, event, title, text, url, target_type, target_id, actor_id, actor_avatar_url, is_read, read_at, created_at}`.

- [ ] **Step 1: Модели**

Create `backend/apps/notifications/models.py`:

```python
"""Хранимый центр уведомлений платформы (Q-C19, D-24), схема public.

``Notification`` — запись в колокольчике. ``Delivery`` — попытка доставки
по каналу (e-mail, Telegram): outbox, который Celery разбирает с повтором.
Колокольчик — сама запись; мгновенный показ — Socket.IO мессенджера,
best-effort. ``company_slug`` — в какой компании событие: лента на
поддомене показывает уведомления своей компании и общие (пусто).
"""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models.functions import Now


class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient_id = models.IntegerField(db_index=True)
    company_slug = models.CharField(max_length=64, default="", blank=True, db_default="")
    event = models.CharField(max_length=64)
    title = models.CharField(max_length=255)
    text = models.TextField(default="", blank=True, db_default="")
    url = models.CharField(max_length=512, default="", blank=True, db_default="")
    target_type = models.CharField(max_length=32, default="", blank=True, db_default="")
    target_id = models.CharField(max_length=64, default="", blank=True, db_default="")
    actor_id = models.IntegerField(null=True, blank=True)
    actor_avatar_url = models.CharField(max_length=1024, null=True, blank=True)
    is_read = models.BooleanField(default=False, db_default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        indexes = [models.Index(fields=["recipient_id", "company_slug", "is_read", "-created_at"],
                                name="ix_notif_feed")]
        verbose_name = "Уведомление"
        verbose_name_plural = "Уведомления"


class Channel(models.TextChoices):
    EMAIL = "email", "E-mail"
    TELEGRAM = "telegram", "Telegram"


class DeliveryState(models.TextChoices):
    PENDING = "pending", "Ожидает"
    SENT = "sent", "Отправлено"
    FAILED = "failed", "Не доставлено"
    SKIPPED = "skipped", "Пропущено"


class Delivery(models.Model):
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE,
                                     related_name="deliveries")
    channel = models.CharField(max_length=16, choices=Channel.choices)
    state = models.CharField(max_length=16, choices=DeliveryState.choices,
                             default=DeliveryState.PENDING,
                             db_default=DeliveryState.PENDING.value)
    attempts = models.PositiveSmallIntegerField(default=0, db_default=0)
    last_error = models.TextField(default="", blank=True, db_default="")
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["notification", "channel"],
                                               name="uq_notif_delivery_channel")]


class ChannelPrefs(models.Model):
    """Каналы пользователя. Нет строки — колокольчик и e-mail (ТЗ §22)."""

    user_id = models.IntegerField(unique=True)
    bell = models.BooleanField(default=True, db_default=True)
    email = models.BooleanField(default=True, db_default=True)
    telegram = models.BooleanField(default=False, db_default=False)


class TelegramLink(models.Model):
    user_id = models.IntegerField(unique=True)
    chat_id = models.CharField(max_length=64, default="", blank=True, db_default="")
    link_code = models.CharField(max_length=32, default="", blank=True, db_default="")
    code_expires_at = models.DateTimeField(null=True, blank=True)
    linked_at = models.DateTimeField(null=True, blank=True)
```

Сгенерировать `0001_initial.py`:

```bash
DJANGO_SETTINGS_MODULE=htqweb.settings.dev DB_HOST=localhost DB_PORT=55432 DB_NAME=htqweb DB_USER=htqweb DB_PASSWORD=change-me JWT_SECRET=dev PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe manage.py makemigrations notifications --name initial
```

В `backend/htqweb/settings/base.py` рядом с `TELEGRAM_BOT_TOKEN`:

```python
# Бот уведомлений пользователей (D-24, Q-E20) — ОТДЕЛЬНЫЙ от бота алертов
# Grafana: токен алертов не должен попадать в пользовательский контур.
# Пусто — канал Telegram выключен для всех (доставки помечаются skipped).
NOTIFY_TELEGRAM_BOT_TOKEN = env("NOTIFY_TELEGRAM_BOT_TOKEN", "")
NOTIFY_TELEGRAM_BOT_NAME = env("NOTIFY_TELEGRAM_BOT_NAME", "")
NOTIFY_TELEGRAM_WEBHOOK_SECRET = env("NOTIFY_TELEGRAM_WEBHOOK_SECRET", "")
```

и три строки с пустыми значениями и комментарием в `.env.example`.

- [ ] **Step 2: Падающие тесты центра**

Create `backend/apps/notifications/tests/__init__.py` (пустой) и `backend/apps/notifications/tests/test_center.py`:

```python
"""Центр уведомлений: запись, лента компании, прочтение, каналы."""

import pytest
from django.db import transaction

from apps.notifications import interface
from apps.notifications.models import ChannelPrefs, Delivery, Notification


@pytest.fixture(autouse=True)
def _no_side_effects(monkeypatch):
    from apps.notifications.services import center

    monkeypatch.setattr(center, "_enqueue", lambda ids: None)
    monkeypatch.setattr(center, "_realtime", lambda rows: None)


def _notify(**over):
    kwargs = {"recipients": [7], "event": "bpp.request_submitted",
              "title": "Заявка ЗЗ-2026-000045 ждёт согласования",
              "url": "/bpp/requests/1", "company_slug": "htq-kz"}
    kwargs.update(over)
    return interface.notify(**kwargs)


@pytest.mark.django_db(transaction=True)
def test_notify_stores_and_lists():
    with transaction.atomic():
        ids = _notify()
    rows = interface.latest(7, company_slug="htq-kz")
    assert [row["id"] for row in rows] == ids
    assert rows[0]["title"].startswith("Заявка ЗЗ-2026-000045")


@pytest.mark.django_db
def test_feed_is_per_company_plus_common():
    _notify(company_slug="htq-kz", title="в KZ")
    _notify(company_slug="htq-uz", title="в UZ")
    _notify(company_slug=None, title="общее")
    titles = {row["title"] for row in interface.latest(7, company_slug="htq-kz")}
    assert titles == {"в KZ", "общее"}


@pytest.mark.django_db
def test_default_channels_are_bell_and_email():
    _notify()
    assert set(Delivery.objects.values_list("channel", flat=True)) == {"email"}


@pytest.mark.django_db
def test_channels_follow_prefs():
    ChannelPrefs.objects.create(user_id=7, bell=True, email=False, telegram=True)
    _notify()
    assert set(Delivery.objects.values_list("channel", flat=True)) == {"telegram"}


@pytest.mark.django_db
def test_bell_off_still_delivers_but_hides_from_feed():
    ChannelPrefs.objects.create(user_id=7, bell=False, email=True, telegram=False)
    _notify()
    assert interface.latest(7, company_slug="htq-kz") == []
    assert Notification.objects.count() == 1  # запись есть — у e-mail нужен источник


@pytest.mark.django_db
def test_read_state():
    (nid,) = _notify()
    interface.mark_read(nid, 7)
    page = interface.history(7, company_slug="htq-kz", page=1, limit=25, status="unread",
                             target_type=None)
    assert page["total"] == 0 and page["unread_total"] == 0
    interface.mark_unread(nid, 7)
    interface.mark_all_read(7, company_slug="htq-kz")
    assert interface.latest(7, company_slug="htq-kz")[0]["is_read"] is True


@pytest.mark.django_db
def test_foreign_notification_is_404():
    from django.http import Http404

    (nid,) = _notify()
    with pytest.raises(Http404):
        interface.mark_read(nid, 8)
```

Run: `../.venv/Scripts/python.exe -m pytest apps/notifications/tests/test_center.py -q`
Expected: FAIL — `interface` без `notify`.

- [ ] **Step 3: Сервис центра и интерфейс**

Create `backend/apps/notifications/services/__init__.py` (пустой) и `backend/apps/notifications/services/center.py`:

```python
"""Запись, лента и прочтение уведомлений (D-24)."""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone

from apps.notifications.models import ChannelPrefs, Channel, Delivery, Notification


def prefs_of(user_id: int) -> ChannelPrefs:
    return ChannelPrefs.objects.filter(user_id=user_id).first() or ChannelPrefs(user_id=user_id)


def serialize(row: Notification) -> dict:
    return {
        "id": str(row.id), "recipient_id": row.recipient_id,
        "company_slug": row.company_slug or None, "event": row.event, "title": row.title,
        "text": row.text, "url": row.url, "target_type": row.target_type or None,
        "target_id": row.target_id or None, "actor_id": row.actor_id,
        "actor_avatar_url": row.actor_avatar_url, "is_read": row.is_read,
        "read_at": row.read_at.isoformat() if row.read_at else None,
        "created_at": row.created_at.isoformat(),
    }


def _enqueue(delivery_ids: list[int]) -> None:
    from apps.notifications.tasks import deliver

    for delivery_id in delivery_ids:
        deliver.delay(delivery_id)


def _realtime(rows: list[Notification]) -> None:
    """Мгновенный показ в колокольчике — best-effort, через Socket.IO."""
    from apps.messenger import interface as messenger

    for row in rows:
        try:
            messenger.dispatch_notification([row.recipient_id], {
                "type": "notification", "id": str(row.id), "title": row.title,
                "url": row.url, "event": row.event})
        except Exception:  # мессенджер выключен или недоступен — лента всё равно есть
            continue


def notify(*, recipients, event, title, text="", url="", company_slug=None,
           target_type="", target_id="", actor_id=None, actor_avatar_url=None) -> list[str]:
    rows, deliveries = [], []
    for user_id in dict.fromkeys(int(r) for r in recipients):
        prefs = prefs_of(user_id)
        row = Notification.objects.create(
            recipient_id=user_id, company_slug=company_slug or "", event=event,
            title=title[:255], text=text, url=url, target_type=target_type or "",
            target_id=str(target_id or ""), actor_id=actor_id,
            actor_avatar_url=actor_avatar_url,
            # Колокольчик выключен — запись создаётся прочитанной и в ленту
            # не попадает (фильтр bell ниже): источник для e-mail/Telegram нужен.
            is_read=not prefs.bell, read_at=None if prefs.bell else timezone.now(),
        )
        rows.append(row)
        for channel, enabled in ((Channel.EMAIL, prefs.email), (Channel.TELEGRAM, prefs.telegram)):
            if enabled:
                deliveries.append(Delivery.objects.create(notification=row, channel=channel).id)
    transaction.on_commit(lambda: (_enqueue(deliveries), _realtime([r for r in rows])))
    return [str(r.id) for r in rows]


def _feed(user_id: int, company_slug: str | None):
    rows = Notification.objects.filter(recipient_id=user_id)
    rows = rows.filter(Q(company_slug=company_slug or "") | Q(company_slug=""))
    if not prefs_of(user_id).bell:
        return rows.none()
    return rows


def latest(user_id: int, *, company_slug: str | None, limit: int = 50) -> list[dict]:
    return [serialize(r) for r in _feed(user_id, company_slug).order_by("-created_at")[:limit]]


def history(user_id: int, *, company_slug, page=1, limit=25, status="all",
            target_type=None) -> dict:
    feed = _feed(user_id, company_slug)
    rows = feed
    if status == "unread":
        rows = rows.filter(is_read=False)
    elif status == "read":
        rows = rows.filter(is_read=True)
    if target_type:
        rows = rows.filter(target_type=target_type)
    total = rows.count()
    items = rows.order_by("-created_at")[(page - 1) * limit:page * limit]
    return {"items": [serialize(r) for r in items], "total": total, "page": page,
            "pages": (total + limit - 1) // limit if total else 0, "limit": limit,
            "unread_total": feed.filter(is_read=False).count()}


def _own(notification_id: str, user_id: int) -> Notification:
    row = Notification.objects.filter(pk=notification_id, recipient_id=user_id).first()
    if row is None:
        raise Http404("Notification not found")
    return row


def mark_read(notification_id: str, user_id: int) -> None:
    row = _own(notification_id, user_id)
    if not row.is_read:
        row.is_read, row.read_at = True, timezone.now()
        row.save(update_fields=["is_read", "read_at"])


def mark_unread(notification_id: str, user_id: int) -> None:
    row = _own(notification_id, user_id)
    row.is_read, row.read_at = False, None
    row.save(update_fields=["is_read", "read_at"])


def mark_all_read(user_id: int, *, company_slug: str | None) -> None:
    _feed(user_id, company_slug).filter(is_read=False).update(is_read=True,
                                                               read_at=timezone.now())


def delete(notification_id: str, user_id: int) -> None:
    _own(notification_id, user_id).delete()
```

⚠️ `notify` с колокольчиком выключен: в `test_bell_off_still_delivers_but_hides_from_feed` лента пуста, потому что `_feed` при `bell=False` возвращает `none()`. Отметка `is_read` у такой записи — не главное условие, а страховка: включит пользователь колокольчик обратно — старые письма не посыплются как непрочитанные.

Replace `backend/apps/notifications/interface.py`:

```python
"""Межаппный интерфейс центра уведомлений (мастер-план §2.6)."""

from __future__ import annotations

from apps.core.services import require_service

from .services import center


def notify(*, recipients: list[int], event: str, title: str, text: str = "", url: str = "",
           company_slug: str | None, target_type: str = "", target_id: str = "",
           actor_id: int | None = None, actor_avatar_url: str | None = None) -> list[str]:
    require_service("notifications")
    return center.notify(recipients=recipients, event=event, title=title, text=text, url=url,
                         company_slug=company_slug, target_type=target_type,
                         target_id=target_id, actor_id=actor_id,
                         actor_avatar_url=actor_avatar_url)


def latest(user_id: int, *, company_slug: str | None, limit: int = 50) -> list[dict]:
    require_service("notifications")
    return center.latest(user_id, company_slug=company_slug, limit=limit)


def history(user_id: int, *, company_slug: str | None, page: int = 1, limit: int = 25,
            status: str = "all", target_type: str | None = None) -> dict:
    require_service("notifications")
    return center.history(user_id, company_slug=company_slug, page=page, limit=limit,
                          status=status, target_type=target_type)


def mark_read(notification_id: str, user_id: int) -> None:
    require_service("notifications")
    center.mark_read(notification_id, user_id)


def mark_unread(notification_id: str, user_id: int) -> None:
    require_service("notifications")
    center.mark_unread(notification_id, user_id)


def mark_all_read(user_id: int, *, company_slug: str | None) -> None:
    require_service("notifications")
    center.mark_all_read(user_id, company_slug=company_slug)


def delete(notification_id: str, user_id: int) -> None:
    require_service("notifications")
    center.delete(notification_id, user_id)
```

Run: `../.venv/Scripts/python.exe -m pytest apps/notifications/tests/test_center.py -q`
Expected: 7 passed.

- [ ] **Step 4: Падающие тесты доставки**

Create `backend/apps/notifications/tests/test_delivery.py`:

```python
"""Доставка по каналам: письмо уходит, сбой повторяется, дубля нет."""

import pytest
from django.core import mail

from apps.notifications.models import Delivery, Notification
from apps.notifications.services import delivery
from apps.users.models import User


@pytest.fixture
def row(db):
    user = User.objects.create(username="ivanov", email="ivanov@htq.test", password="x")
    note = Notification.objects.create(recipient_id=user.pk, event="e", title="Счёт оплачен",
                                       url="/bpp/invoices/1")
    return note


@pytest.mark.django_db
def test_email_is_sent_once(row, settings):
    settings.PUBLIC_BASE_URL = "https://htq.group"
    item = Delivery.objects.create(notification=row, channel="email")
    delivery.deliver(item.id)
    delivery.deliver(item.id)  # повтор той же доставки не шлёт второе письмо
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["ivanov@htq.test"]
    assert "https://htq.group/bpp/invoices/1" in mail.outbox[0].body
    assert Delivery.objects.get(pk=item.id).state == "sent"


@pytest.mark.django_db
def test_failure_is_retryable(row, monkeypatch):
    item = Delivery.objects.create(notification=row, channel="email")

    def boom(*a, **k):
        raise OSError("smtp недоступен")

    monkeypatch.setattr(delivery, "send_mail", boom)
    with pytest.raises(delivery.RetryLater):
        delivery.deliver(item.id)
    item.refresh_from_db()
    assert (item.state, item.attempts) == ("pending", 1)
    assert "smtp" in item.last_error


@pytest.mark.django_db
def test_gives_up_after_max_attempts(row, monkeypatch):
    item = Delivery.objects.create(notification=row, channel="email",
                                   attempts=delivery.MAX_ATTEMPTS - 1)
    monkeypatch.setattr(delivery, "send_mail", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    delivery.deliver(item.id)
    assert Delivery.objects.get(pk=item.id).state == "failed"


@pytest.mark.django_db
def test_telegram_without_link_is_skipped(row, settings):
    settings.NOTIFY_TELEGRAM_BOT_TOKEN = "t"
    item = Delivery.objects.create(notification=row, channel="telegram")
    delivery.deliver(item.id)
    assert Delivery.objects.get(pk=item.id).state == "skipped"
```

Run: `../.venv/Scripts/python.exe -m pytest apps/notifications/tests/test_delivery.py -q`
Expected: FAIL — нет `services.delivery`.

- [ ] **Step 5: Доставка и задача Celery**

Create `backend/apps/notifications/services/delivery.py`:

```python
"""Доставка уведомления по каналу: e-mail и Telegram, с повтором (outbox).

Состояние ``sent`` проверяется первым: повторный запуск задачи (брокер
доставил её дважды) письма не дублирует. Сбой — ``RetryLater``: задача
Celery повторит с паузой; после ``MAX_ATTEMPTS`` — ``failed`` и строка
``FALLBACK`` в лог (алерт ``htqweb-fallback-worker-logs``).
"""

from __future__ import annotations

import httpx
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from apps.notifications.models import Delivery, DeliveryState, TelegramLink
from apps.users import interface as users
from htqweb.fallback import fallback

MAX_ATTEMPTS = 5


class RetryLater(Exception):
    pass


def _absolute(url: str) -> str:
    base = getattr(settings, "PUBLIC_BASE_URL", "").rstrip("/")
    return f"{base}{url}" if url.startswith("/") and base else url


def _send_email(item: Delivery) -> bool:
    briefs = users.get_users_brief([item.notification.recipient_id])
    email = briefs[0]["email"] if briefs else ""
    if not email:
        return False
    note = item.notification
    body = "\n\n".join(part for part in (note.title, note.text, _absolute(note.url)) if part)
    send_mail(note.title, body, None, [email], fail_silently=False)
    return True


def _send_telegram(item: Delivery) -> bool:
    token = getattr(settings, "NOTIFY_TELEGRAM_BOT_TOKEN", "")
    link = TelegramLink.objects.filter(user_id=item.notification.recipient_id).exclude(
        chat_id="").first()
    if not token or link is None:
        return False
    note = item.notification
    text = "\n".join(part for part in (note.title, note.text, _absolute(note.url)) if part)
    response = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": link.chat_id, "text": text,
                                "disable_web_page_preview": True}, timeout=10.0)
    response.raise_for_status()
    return True


_SENDERS = {"email": _send_email, "telegram": _send_telegram}


def deliver(delivery_id: int) -> None:
    with transaction.atomic():
        item = (Delivery.objects.select_for_update().select_related("notification")
                .filter(pk=delivery_id).first())
        if item is None or item.state != DeliveryState.PENDING:
            return
        item.attempts += 1
        try:
            sent = _SENDERS[item.channel](item)
        except Exception as exc:
            item.last_error = str(exc)[:1000]
            if item.attempts >= MAX_ATTEMPTS:
                item.state = DeliveryState.FAILED
                item.save(update_fields=["attempts", "last_error", "state"])
                fallback("notifications.delivery.gave_up", None,
                         reason="уведомление не доставлено", exc=exc, expected=True,
                         channel=item.channel)
                return
            item.save(update_fields=["attempts", "last_error"])
            raise RetryLater(str(exc)) from exc
        item.state = DeliveryState.SENT if sent else DeliveryState.SKIPPED
        item.sent_at = timezone.now() if sent else None
        item.save(update_fields=["attempts", "state", "sent_at"])
```

⚠️ `RetryLater` поднимается ПОСЛЕ сохранения счётчика: `raise` внутри `transaction.atomic()` откатил бы `save`. Вынести сохранение и `raise` так, чтобы транзакция успела закоммититься: сохранить внутри блока, а исключение поднять после выхода из `with`. Итоговая форма — флаг `retry = True` внутри блока и `if retry: raise RetryLater(...)` после него. Тест `test_failure_is_retryable` это ловит (`attempts == 1`).

Create `backend/apps/notifications/tasks.py`:

```python
from celery import shared_task

from apps.core.services import require_service


@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def deliver(self, delivery_id: int) -> None:
    require_service("notifications")
    from apps.notifications.services import delivery

    try:
        delivery.deliver(delivery_id)
    except delivery.RetryLater as exc:
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
```

Run: `../.venv/Scripts/python.exe -m pytest apps/notifications/tests -q apps/core/tests/test_invariants.py`
Expected: всё PASS.

- [ ] **Step 6: Падающие тесты API и Telegram**

Create `backend/apps/notifications/tests/test_api.py`:

```python
"""Ручки центра — самообслуживание: только свои уведомления и свои каналы."""

import json

import pytest
from django.test import Client

from apps.access.tests.helpers import token
from apps.notifications import interface

BASE = "/api/notifications/v1"


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    from apps.notifications.services import center

    monkeypatch.setattr(center, "_enqueue", lambda ids: None)
    monkeypatch.setattr(center, "_realtime", lambda rows: None)


def _auth(user_id=7):
    return {"HTTP_AUTHORIZATION": f"Bearer {token(user_id=user_id, sub=str(user_id))}"}


@pytest.mark.django_db
def test_feed_and_mark_read():
    (nid,) = interface.notify(recipients=[7], event="e", title="Т", company_slug=None)
    feed = Client().get(f"{BASE}/notifications", **_auth()).json()
    assert [row["id"] for row in feed] == [nid]
    assert Client().post(f"{BASE}/notifications/{nid}/read", **_auth()).status_code == 204
    assert Client().post(f"{BASE}/notifications/{nid}/read", **_auth(8)).status_code == 404


@pytest.mark.django_db
def test_cannot_disable_every_channel():
    url = f"{BASE}/prefs"
    ok = Client().patch(url, data=json.dumps({"bell": True, "email": False, "telegram": False}),
                        content_type="application/json", **_auth())
    assert ok.status_code == 200
    refused = Client().patch(url, data=json.dumps({"bell": False}),
                             content_type="application/json", **_auth())
    assert refused.status_code == 422 and refused.json()["code"] == "E-NTF-01"
    assert Client().get(url, **_auth()).json() == {"bell": True, "email": False,
                                                   "telegram": False, "telegram_linked": False}
```

Create `backend/apps/notifications/tests/test_telegram.py`:

```python
"""Привязка Telegram: код из профиля → /start <код> в боте → chat_id сохранён."""

import json

import pytest
from django.test import Client

from apps.access.tests.helpers import token
from apps.notifications.models import TelegramLink

BASE = "/api/notifications/v1"


@pytest.mark.django_db
def test_link_flow(settings):
    settings.NOTIFY_TELEGRAM_BOT_NAME = "htq_notify_bot"
    settings.NOTIFY_TELEGRAM_WEBHOOK_SECRET = "s3cret"
    auth = {"HTTP_AUTHORIZATION": f"Bearer {token(user_id=7, sub='7')}"}
    started = Client().post(f"{BASE}/telegram/link", **auth).json()
    assert started["url"].startswith("https://t.me/htq_notify_bot?start=")
    code = started["url"].rsplit("=", 1)[1]

    update = {"message": {"chat": {"id": 555}, "text": f"/start {code}"}}
    wrong = Client().post(f"{BASE}/telegram/webhook", data=json.dumps(update),
                          content_type="application/json",
                          HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="nope")
    assert wrong.status_code == 403
    ok = Client().post(f"{BASE}/telegram/webhook", data=json.dumps(update),
                       content_type="application/json",
                       HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="s3cret")
    assert ok.status_code == 200
    assert TelegramLink.objects.get(user_id=7).chat_id == "555"


@pytest.mark.django_db
def test_expired_or_unknown_code_does_not_link(settings):
    settings.NOTIFY_TELEGRAM_WEBHOOK_SECRET = "s3cret"
    update = {"message": {"chat": {"id": 555}, "text": "/start nosuchcode"}}
    Client().post(f"{BASE}/telegram/webhook", data=json.dumps(update),
                  content_type="application/json", HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="s3cret")
    assert not TelegramLink.objects.exclude(chat_id="").exists()
```

Run: `../.venv/Scripts/python.exe -m pytest apps/notifications/tests/test_api.py apps/notifications/tests/test_telegram.py -q`
Expected: FAIL — 404.

- [ ] **Step 7: Привязка Telegram, настройки каналов, ручки**

Create `backend/apps/notifications/services/telegram.py`:

```python
"""Привязка чата Telegram к учётной записи (Q-E20).

Пользователь жмёт «Подключить Telegram» → получает ссылку на бота с
одноразовым кодом (15 минут) → бот присылает вебхуком ``/start <код>`` →
сохраняем ``chat_id``. Вебхук проверяет секрет Telegram
(``X-Telegram-Bot-Api-Secret-Token``) — без него любой мог бы привязать
свой чат к чужому коду.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.notifications.models import TelegramLink

CODE_TTL = timedelta(minutes=15)


def start_link(user_id: int) -> str:
    code = secrets.token_urlsafe(12)
    TelegramLink.objects.update_or_create(
        user_id=user_id, defaults={"link_code": code,
                                   "code_expires_at": timezone.now() + CODE_TTL})
    return f"https://t.me/{settings.NOTIFY_TELEGRAM_BOT_NAME}?start={code}"


def secret_ok(header_value: str) -> bool:
    expected = getattr(settings, "NOTIFY_TELEGRAM_WEBHOOK_SECRET", "")
    return bool(expected) and secrets.compare_digest(header_value or "", expected)


def complete_link(update: dict) -> bool:
    message = update.get("message") or {}
    text = (message.get("text") or "").strip()
    chat_id = (message.get("chat") or {}).get("id")
    if not text.startswith("/start ") or chat_id is None:
        return False
    code = text.split(" ", 1)[1].strip()
    link = TelegramLink.objects.filter(link_code=code,
                                       code_expires_at__gt=timezone.now()).first()
    if link is None:
        return False
    link.chat_id, link.link_code, link.linked_at = str(chat_id), "", timezone.now()
    link.save(update_fields=["chat_id", "link_code", "linked_at"])
    return True


def is_linked(user_id: int) -> bool:
    return TelegramLink.objects.filter(user_id=user_id).exclude(chat_id="").exists()
```

Create `backend/apps/notifications/schemas.py`:

```python
from typing import Optional

from pydantic import BaseModel


class PrefsPatch(BaseModel):
    bell: Optional[bool] = None
    email: Optional[bool] = None
    telegram: Optional[bool] = None
```

Replace `backend/apps/notifications/views.py`:

```python
"""Ручки центра уведомлений — самообслуживание (свои уведомления и каналы).

Под гейтом модуля их нет намеренно: лента нужна каждому вошедшему, включая
держателей ролей без единого узла (записи ``self`` в
``apps/access/self_service.py``). Получатель — всегда ``request.token.user_id``.
Вебхук Telegram — ``auth=None``, защищён секретом бота.
"""

from __future__ import annotations

import json

from django.http import HttpResponse

from htqweb.errors import DomainError
from htqweb.http import api_view, json_error

from . import interface, schemas
from .models import ChannelPrefs
from .services import center, telegram


def _company(request):
    return (getattr(request, "company", None) or {}).get("slug")


@api_view(methods=("GET",))
def feed(request):
    return interface.latest(request.token.user_id, company_slug=_company(request),
                            limit=min(int(request.GET.get("limit", 50)), 200))


@api_view(methods=("GET",))
def feed_history(request):
    return interface.history(request.token.user_id, company_slug=_company(request),
                             page=max(int(request.GET.get("page", 1)), 1),
                             limit=min(int(request.GET.get("limit", 25)), 100),
                             status=request.GET.get("status", "all"),
                             target_type=request.GET.get("target_type") or None)


@api_view(methods=("POST",))
def read_one(request, notification_id: str):
    interface.mark_read(notification_id, request.token.user_id)
    return HttpResponse(status=204)


@api_view(methods=("POST",))
def unread_one(request, notification_id: str):
    interface.mark_unread(notification_id, request.token.user_id)
    return HttpResponse(status=204)


@api_view(methods=("POST",))
def read_all(request):
    interface.mark_all_read(request.token.user_id, company_slug=_company(request))
    return HttpResponse(status=204)


@api_view(methods=("DELETE",))
def delete_one(request, notification_id: str):
    interface.delete(notification_id, request.token.user_id)
    return HttpResponse(status=204)


def _prefs_payload(user_id: int) -> dict:
    prefs = center.prefs_of(user_id)
    return {"bell": prefs.bell, "email": prefs.email, "telegram": prefs.telegram,
            "telegram_linked": telegram.is_linked(user_id)}


@api_view(methods=("GET",))
def _prefs_get(request):
    return _prefs_payload(request.token.user_id)


@api_view(methods=("PATCH",), body=schemas.PrefsPatch)
def _prefs_patch(request, data: schemas.PrefsPatch):
    user_id = request.token.user_id
    prefs = center.prefs_of(user_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(prefs, key, value)
    if not (prefs.bell or prefs.email or prefs.telegram):
        raise DomainError("E-NTF-01", "Оставьте включённым хотя бы один способ уведомлений.",
                          fields=[{"field": "bell", "message": "нужен хотя бы один канал"}])
    prefs.save()
    return _prefs_payload(user_id)


def prefs(request):
    if request.method == "GET":
        return _prefs_get(request)
    if request.method == "PATCH":
        return _prefs_patch(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("POST",))
def telegram_link(request):
    return {"url": telegram.start_link(request.token.user_id)}


@api_view(methods=("POST",), auth=None)
def telegram_webhook(request):
    if not telegram.secret_ok(request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")):
        return json_error("Forbidden", 403)
    telegram.complete_link(json.loads(request.body or b"{}"))
    return {"ok": True}
```

⚠️ Однометодный диспетчер `prefs` — строгий по признакам сторожа (`request.method` + гейтированные функции + 405). Ручки ленты и прочтения объявлены одной функцией на URL; URL с двумя методами на одном пути — `notification_item` (DELETE) и `…/read` (POST) — разведены по разным путям, чтобы не писать диспетчер.

Replace `backend/apps/notifications/urls.py`:

```python
"""Маршруты /api/notifications/v1/."""

from django.urls import path

from . import views

urlpatterns = [
    path("notifications", views.feed),
    path("notifications/", views.feed),
    path("notifications/history", views.feed_history),
    path("notifications/history/", views.feed_history),
    path("notifications/read-all", views.read_all),
    path("notifications/read-all/", views.read_all),
    path("notifications/<str:notification_id>/read", views.read_one),
    path("notifications/<str:notification_id>/read/", views.read_one),
    path("notifications/<str:notification_id>/unread", views.unread_one),
    path("notifications/<str:notification_id>/unread/", views.unread_one),
    path("notifications/<str:notification_id>/delete", views.delete_one),
    path("notifications/<str:notification_id>/delete/", views.delete_one),
    path("prefs", views.prefs),
    path("prefs/", views.prefs),
    path("telegram/link", views.telegram_link),
    path("telegram/link/", views.telegram_link),
    path("telegram/webhook", views.telegram_webhook),
    path("telegram/webhook/", views.telegram_webhook),
]
```

В `backend/apps/access/self_service.py` заменить `"notifications": {},` на:

```python
    # Центр уведомлений (задача A1.5): лента, прочтение и каналы — строго
    # свои, получатель всегда request.token.user_id, параметра «чей» нет.
    "notifications": {
        "feed": "self", "feed_history": "self", "read_one": "self",
        "unread_one": "self", "read_all": "self", "delete_one": "self",
        "_prefs_get": "self", "_prefs_patch": "self", "telegram_link": "self",
    },
```

Create `backend/apps/notifications/admin.py` — `Notification`, `Delivery`, `ChannelPrefs`, `TelegramLink` с `ServiceGatedAdminMixin`.

Run: `../.venv/Scripts/python.exe -m pytest apps/notifications/tests apps/access/tests/test_gate.py -q`
Expected: всё PASS.

- [ ] **Step 8: Документация и коммит**

`STRUCTURE.md` §3.1, строка **notifications**: убрать «каркас»; дописать модели и `services/{center,delivery,telegram}.py`. `API.md`: ручки центра и вебхук Telegram (`X-Telegram-Bot-Api-Secret-Token`). `CLAUDE.md`, раздел «Модуль БЗО»: «центр уведомлений `apps.notifications` (public) — `notify(...)`, outbox `Delivery` с повтором Celery; бот пользователей — отдельный (`NOTIFY_TELEGRAM_*`)».

```bash
git add backend/apps/notifications backend/apps/access/self_service.py backend/htqweb/settings/base.py .env.example STRUCTURE.md API.md CLAUDE.md
git commit -m "feat(notifications): хранимый центр уведомлений — колокольчик, e-mail, Telegram, каналы пользователя"
```

---

## Task 8: Ежедневная сводка ожидающих решений

**Files:**
- Create: `backend/apps/notifications/services/digest.py`, `backend/apps/notifications/migrations/0002_digest_periodic_task.py`
- Modify: `backend/apps/notifications/interface.py` (`register_digest_source`), `backend/apps/notifications/tasks.py` (`send_daily_digest`)
- Test: `backend/apps/notifications/tests/test_digest.py`

**Interfaces:**
- Produces:
  - `notifications.interface.register_digest_source(key: str, fn: Callable[[int], list[dict]], *, tenant: bool) -> None` — `fn(user_id)` возвращает `[{title, url, since}]`; `tenant=True` — вызывается внутри `use_company(slug)` по каждой действующей компании, где пользователь участник;
  - Celery-задача `apps.notifications.tasks.send_daily_digest` (09:00 Asia/Almaty, Пн–Пт).
- Consumers: signoff регистрирует `pending_for_user` в задаче B1.3; модуль `bpp` — «ждут закрывающих документов» в A3.2.

- [ ] **Step 1: Падающие тесты**

Create `backend/apps/notifications/tests/test_digest.py`:

```python
"""Сводка: одно сообщение со всем, что ждёт пользователя, по всем компаниям."""

import pytest

from apps.notifications import interface
from apps.notifications.models import Notification
from apps.notifications.services import digest


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    from apps.notifications.services import center

    monkeypatch.setattr(center, "_enqueue", lambda ids: None)
    monkeypatch.setattr(center, "_realtime", lambda rows: None)
    saved = dict(digest._SOURCES)
    digest._SOURCES.clear()
    yield
    digest._SOURCES.clear()
    digest._SOURCES.update(saved)


@pytest.mark.django_db
def test_one_message_with_links(monkeypatch):
    interface.register_digest_source(
        "probe", lambda user_id: [{"title": "Заявка ЗЗ-2026-000045", "url": "/bpp/r/45",
                                   "since": "2026-09-25"}] if user_id == 7 else [],
        tenant=False)
    monkeypatch.setattr(digest, "_recipients", lambda: [7, 8])
    assert digest.send() == 1
    note = Notification.objects.get(recipient_id=7)
    assert note.event == "digest.daily"
    assert "Заявка ЗЗ-2026-000045" in note.text and "/bpp/r/45" in note.text
    assert not Notification.objects.filter(recipient_id=8).exists()


@pytest.mark.django_db
def test_tenant_source_runs_per_company(monkeypatch):
    seen = []

    def source(user_id):
        from htqweb.tenancy.context import current_company

        seen.append(current_company())
        return []

    interface.register_digest_source("tenant-probe", source, tenant=True)
    monkeypatch.setattr(digest, "_recipients", lambda: [7])
    monkeypatch.setattr(digest, "_companies_of", lambda user_id: ["htq-kz", "htq-uz"])
    digest.send()
    assert seen == ["htq-kz", "htq-uz"]


@pytest.mark.django_db
def test_broken_source_does_not_stop_the_digest(monkeypatch, settings):
    settings.FALLBACK_MODE = "log"
    interface.register_digest_source("broken", lambda user_id: 1 / 0, tenant=False)
    interface.register_digest_source(
        "ok", lambda user_id: [{"title": "Договор", "url": "/x", "since": ""}], tenant=False)
    monkeypatch.setattr(digest, "_recipients", lambda: [7])
    assert digest.send() == 1
```

Run: `../.venv/Scripts/python.exe -m pytest apps/notifications/tests/test_digest.py -q`
Expected: FAIL — нет `services.digest`.

- [ ] **Step 2: Сводка**

Create `backend/apps/notifications/services/digest.py`:

```python
"""Ежедневная сводка ожидающих решений (D-23, Q-B21, Q-B30).

Одно сообщение на пользователя со списком «что ждёт вашего решения» —
текст-ссылками. Сроков согласования нет, сводка заменяет эскалацию.

Источники регистрируют сами аппки (``register_digest_source``): центр не
знает ни signoff, ни БЗО, и граф зависимостей идёт от источника к центру.
Тенантный источник вызывается в контексте каждой компании пользователя.
Сломанный источник не останавливает сводку — ``fallback`` и дальше.
"""

from __future__ import annotations

from typing import Callable

from apps.companies import interface as companies
from apps.users import interface as users
from htqweb.fallback import fallback
from htqweb.tenancy.db import use_company

from . import center

_SOURCES: dict[str, tuple[Callable[[int], list[dict]], bool]] = {}


def register(key: str, fn: Callable[[int], list[dict]], *, tenant: bool) -> None:
    _SOURCES[key] = (fn, tenant)


def _recipients() -> list[int]:
    return users.active_user_ids()


def _companies_of(user_id: int) -> list[str]:
    active = set(companies.active_company_slugs())
    return [slug for slug in companies.user_company_slugs(user_id) if slug in active]


def _collect(user_id: int) -> list[dict]:
    items: list[dict] = []
    for key, (fn, tenant) in _SOURCES.items():
        slugs = _companies_of(user_id) if tenant else [None]
        for slug in slugs:
            try:
                if slug is None:
                    got = fn(user_id)
                else:
                    with use_company(slug):
                        got = fn(user_id)
            except Exception as exc:
                fallback("notifications.digest.source_failed", None,
                         reason="источник сводки упал", exc=exc, expected=True, source=key)
                continue
            items.extend(got or [])
    return items


def send() -> int:
    sent = 0
    for user_id in _recipients():
        items = _collect(user_id)
        if not items:
            continue
        lines = [f"• {item['title']} — {item['url']}" for item in items]
        center.notify(recipients=[user_id], event="digest.daily",
                      title=f"Ждут вашего решения: {len(items)}",
                      text="\n".join(lines), url="/signoff/inbox", company_slug=None)
        sent += 1
    return sent
```

⚠️ `users.interface.active_user_ids()` — проверить, есть ли такая функция (`grep -n "^def " backend/apps/users/interface.py`). Если нет — добавить в `apps/users/interface.py` (A владеет `users`) функцию «id действующих пользователей», по образцу `staff_user_ids` без фильтра `is_staff`, с тестом в `apps/users/tests`.

In `backend/apps/notifications/interface.py` добавить:

```python
from typing import Callable

from .services import digest


def register_digest_source(key: str, fn: Callable[[int], list[dict]], *, tenant: bool) -> None:
    """Зарегистрировать источник ежедневной сводки. Зовётся из ``AppConfig.ready()``
    источника; ``require_service`` не нужен — регистрация не трогает БД."""
    digest.register(key, fn, tenant=tenant)
```

⚠️ Сторож `test_invariants`/isolation требует `require_service` только у Celery-задач; если сторож интерфейсов (`test_parallel_scaffold` проверяет только перечисленные функции) не требует его здесь — оставить как есть и отметить в докстринге.

In `backend/apps/notifications/tasks.py` добавить:

```python
@shared_task
def send_daily_digest() -> int:
    require_service("notifications")
    from apps.notifications.services import digest

    return digest.send()
```

Create `backend/apps/notifications/migrations/0002_digest_periodic_task.py` по образцу `apps/core/migrations/0005_daily_digest_periodic_task.py`: `TASK_NAME = "notifications.send_daily_digest"`, cron `minute="0", hour="9", day_of_week="1-5"`, `timezone="Asia/Almaty"`, `"task": "apps.notifications.tasks.send_daily_digest"`.

Run: `../.venv/Scripts/python.exe -m pytest apps/notifications/tests apps/core/tests/test_invariants.py -q`
Expected: всё PASS.

- [ ] **Step 3: Коммит**

```bash
git add backend/apps/notifications backend/apps/users
git commit -m "feat(notifications): ежедневная сводка ожидающих решений из зарегистрированных источников"
```

---

## Task 9: Лента задач переходит в центр уведомлений

**Files:**
- Modify: `backend/apps/tasks/services/notification_service.py` (фасад над `notifications.interface`), `backend/apps/tasks/interface.py:195-230` (`create_notification`), `backend/apps/tasks/services/calendar_service.py:286`, `backend/apps/tasks/services/task_service.py:360`, `backend/apps/tasks/tasks.py:81,161`, `backend/apps/tasks/schemas.py` (`NotificationResponse.id` — строка)
- Create: `backend/apps/notifications/management/__init__.py`, `management/commands/__init__.py`, `management/commands/notifications_import_tasks.py`
- Create: `frontend/src/api/notifications.ts`, `frontend/src/pages/NotificationSettings.tsx`, `frontend/src/pages/NotificationSettings.test.tsx`
- Modify: `frontend/src/types/tasks.ts` (`Notification.id: string`, `target_id: string | null`, `url?: string | null`), компонент колокольчика (переход по `url`, если тип цели неизвестен), маршруты фронта (`/settings/notifications`)
- Test: `backend/apps/tasks/tests/test_notifications_facade.py`, `backend/apps/notifications/tests/test_import_tasks.py`

**Interfaces:**
- Consumes: `notifications.interface.notify/latest/history/mark_*` (задача 7).
- Produces: ручки `/api/tasks/v1/notifications…` отвечают тем же JSON, что и раньше, но данные — из центра. `id` уведомления — строка UUID.

Почему фасад, а не перевод фронта: колокольчик и страница истории смонтированы для каждого вошедшего и читают `/api/tasks/v1/notifications` (`frontend/src/api/tasks.ts:853-880`). Фасад сохраняет контракт, писатели ленты (мессенджер, почта, календарь, конференции — все через `tasks.interface.create_notification`) переходят в центр одним местом.

- [ ] **Step 1: Падающие тесты фасада**

Create `backend/apps/tasks/tests/test_notifications_facade.py`:

```python
"""Лента задач живёт в центре уведомлений, контракт ручек прежний."""

import pytest
from django.test import Client

from apps.notifications.models import Notification as CenterNotification
from apps.tasks import interface as tasks


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    from apps.notifications.services import center

    monkeypatch.setattr(center, "_enqueue", lambda ids: None)
    monkeypatch.setattr(center, "_realtime", lambda rows: None)


@pytest.mark.django_db
def test_create_notification_writes_to_the_center(company_context):
    tasks.create_notification(recipient_id=7, actor_id=8, verb="вам написали",
                              target_type="chat", target_id=5)
    row = CenterNotification.objects.get()
    assert (row.recipient_id, row.title, row.target_type, row.target_id) == \
        (7, "вам написали", "chat", "5")
    assert row.company_slug == company_context["slug"]


@pytest.mark.django_db
def test_dedupe_window_still_holds(company_context):
    for _ in range(2):
        tasks.create_notification(recipient_id=7, actor_id=8, verb="вам написали",
                                  target_type="chat", target_id=5)
    assert CenterNotification.objects.count() == 1


@pytest.mark.django_db
def test_bell_endpoint_keeps_its_shape(company_context):
    from apps.tasks.tests.helpers import auth, token

    tasks.create_notification(recipient_id=7, actor_id=None, verb="задача назначена",
                              target_type="task", target_id=None)
    body = Client().get("/api/tasks/v1/notifications/",
                        **auth(token(user_id=7, sub="7"))).json()
    assert body[0]["verb"] == "задача назначена"
    assert set(body[0]) >= {"id", "verb", "target_type", "target_id", "is_read",
                            "created_at", "task_key", "actor_name"}
```

⚠️ Подпись `create_notification` — прочитать строки `apps/tasks/interface.py:190-200` и повторить в тесте. `apps.tasks.tests.helpers.auth/token` — проверить имена; если `token` называется иначе — взять фактическое.

Run: `../.venv/Scripts/python.exe -m pytest apps/tasks/tests/test_notifications_facade.py -q`
Expected: FAIL — строка пишется в `tasks.Notification`, а не в центр.

- [ ] **Step 2: Писатели → центр**

In `backend/apps/tasks/interface.py`, `create_notification`: оставить сигнатуру и окно дедупликации, а запись перевести в центр.

⚠️ Импорт модели соседа запрещён (`test_app_isolation`): строки `from apps.notifications.models import …` в `tasks` быть не должно. Окно дедупликации переносится в центр: добавить в `notifications.interface.notify` и в `center.notify` необязательный параметр `dedupe_window_seconds: int | None = None` (интерфейс передаёт его в сервис; в `center.py` — `from datetime import timedelta`) — при нём центр не пишет строку, если такое же уведомление (получатель, актор, заголовок, тип, id цели) уже есть за окно. Тест на это — в `apps/notifications/tests/test_center.py`:

```python
@pytest.mark.django_db
def test_dedupe_window():
    for _ in range(2):
        _notify(dedupe_window_seconds=300)
    assert Notification.objects.count() == 1
```

И реализация в `center.notify` (перед созданием строки для получателя):

```python
        if dedupe_window_seconds and Notification.objects.filter(
                recipient_id=user_id, actor_id=actor_id, title=title[:255],
                target_type=target_type or "", target_id=str(target_id or ""),
                created_at__gte=timezone.now() - timedelta(seconds=dedupe_window_seconds),
        ).exists():
            continue
```

Тогда `create_notification`:

```python
def create_notification(*, recipient_id: int, actor_id: int | None, verb: str,
                        actor_avatar_url: str | None = None,
                        target_type: str | None = None,
                        target_id: int | None = None) -> dict | None:
    require_service("tasks")
    from apps.notifications import interface as notifications
    from htqweb.tenancy.context import current_company_or_none

    ids = notifications.notify(
        recipients=[recipient_id], event=f"tasks.{target_type or 'generic'}", title=verb,
        company_slug=current_company_or_none(), target_type=target_type or "",
        target_id=str(target_id) if target_id is not None else "", actor_id=actor_id,
        actor_avatar_url=actor_avatar_url,
        dedupe_window_seconds=int(_DEDUPE_WINDOW.total_seconds()))
    if not ids:
        return None
    return {"id": ids[0], "recipient_id": recipient_id, "verb": verb,
            "target_type": target_type, "target_id": target_id}
```

Остальные писатели — `calendar_service.py:286`, `task_service.py:360`, `tasks.py:81` и `:161` — перевести на `notifications.interface.notify(...)` с `company_slug=current_company_or_none()`, `title=<verb>`, `target_type="task"`/`"calendar_event"`, `target_id=str(...)`. Каждое место прочитать и сохранить получателей и тексты как есть.

- [ ] **Step 3: Фасад ленты**

Replace `backend/apps/tasks/services/notification_service.py` целиком — те же функции (`latest`, `history`, `mark_read`, `mark_unread`, `mark_all_read`, `delete`), но данные из `notifications.interface`, а гидрация (`actor_name`, `task_key`) — прежняя:

```python
"""Колокольчик и история — фасад над центром уведомлений (A1.5).

Хранит уведомления ``apps.notifications`` (public); этот модуль сохраняет
контракт ручек ``/api/tasks/v1/notifications…``, на который смонтированы
колокольчик и страница истории, и добавляет то, что знает только домен
задач: ключ задачи (``task_key``) и имя актора.
"""

from __future__ import annotations

from apps.notifications import interface as notifications
from htqweb.tenancy.context import current_company_or_none

from .. import schemas
from ..models import Task
from . import hydration


def _hydrate(rows: list[dict]) -> list[schemas.NotificationResponse]:
    users = hydration.user_briefs([row["actor_id"] for row in rows])
    task_ids = {int(r["target_id"]) for r in rows
                if r["target_type"] == "task" and (r["target_id"] or "").isdigit()}
    task_keys = dict(Task.objects.filter(id__in=task_ids).values_list("id", "key")) \
        if task_ids else {}
    out = []
    for row in rows:
        task_id = int(row["target_id"]) if row["target_type"] == "task" and \
            (row["target_id"] or "").isdigit() else None
        out.append(schemas.NotificationResponse.model_validate({
            "id": row["id"], "recipient_id": row["recipient_id"],
            "actor_id": row["actor_id"],
            "actor_name": hydration.user_name(users, row["actor_id"]),
            "actor_avatar_url": row["actor_avatar_url"]
            or hydration.user_avatar(users, row["actor_id"]),
            "verb": row["title"], "task_id": task_id,
            "task_key": task_keys.get(task_id) if task_id else None,
            "target_type": row["target_type"], "target_id": row["target_id"],
            "url": row["url"] or None, "is_read": row["is_read"],
            "read_at": row["read_at"], "created_at": row["created_at"],
        }))
    return out


def latest(user_id: int, limit: int = 50):
    return _hydrate(notifications.latest(user_id, company_slug=current_company_or_none(),
                                         limit=limit))


def history(user_id: int, *, page: int = 1, limit: int = 25, status: str = "all",
            target_type: str | None = None):
    page_data = notifications.history(user_id, company_slug=current_company_or_none(),
                                      page=page, limit=limit, status=status,
                                      target_type=target_type)
    return schemas.NotificationsPage(
        items=_hydrate(page_data["items"]), total=page_data["total"], page=page_data["page"],
        pages=page_data["pages"], limit=page_data["limit"],
        unread_total=page_data["unread_total"])


def mark_read(notification_id: str, user_id: int) -> None:
    notifications.mark_read(notification_id, user_id)


def mark_unread(notification_id: str, user_id: int) -> None:
    notifications.mark_unread(notification_id, user_id)


def mark_all_read(user_id: int) -> None:
    notifications.mark_all_read(user_id, company_slug=current_company_or_none())


def delete(notification_id: str, user_id: int) -> None:
    notifications.delete(notification_id, user_id)
```

In `backend/apps/tasks/schemas.py`, `NotificationResponse`: `id: str`, `target_id: Optional[str]`, добавить `url: Optional[str] = None`. In `backend/apps/tasks/urls.py` конвертеры `<int:notification_id>` → `<str:notification_id>`, и аннотации вьюх `notification_id: str`.

Run: `../.venv/Scripts/python.exe -m pytest apps/tasks/tests apps/notifications/tests apps/messenger/tests apps/mail/tests apps/conference/tests apps/access/tests/test_gate.py -q`
Expected: всё PASS. Тесты, проверявшие `tasks.Notification` напрямую, переписать на центр (не удалять): поведение то же, место хранения другое.

- [ ] **Step 4: Перенос старых уведомлений**

Падающий тест — create `backend/apps/notifications/tests/test_import_tasks.py`:

```python
import pytest
from django.core.management import call_command

from apps.notifications.models import Notification
from apps.tasks.models import Notification as OldNotification


@pytest.mark.django_db
def test_old_rows_are_copied_once(company_context):
    OldNotification.objects.create(recipient_id=7, actor_id=8, verb="старое",
                                   target_type="task", target_id=3, is_read=True)
    call_command("notifications_import_tasks", "--company", company_context["slug"])
    call_command("notifications_import_tasks", "--company", company_context["slug"])
    row = Notification.objects.get()
    assert (row.title, row.target_id, row.is_read, row.company_slug) == \
        ("старое", "3", True, company_context["slug"])
```

Create `backend/apps/notifications/management/commands/notifications_import_tasks.py` (и пакеты `__init__.py`). Команда читает старые строки через новую функцию `tasks.interface.legacy_notifications()` (A владеет `tasks`; вернуть `id, recipient_id, actor_id, verb, actor_avatar_url, target_type, target_id, task_id, is_read, read_at, created_at`) и создаёт строки центра с сохранением `created_at`. Идемпотентность — по `event = f"legacy.tasks.{old_id}"`: строка с таким `event` уже есть — пропустить. `target_type`/`target_id` старой строки с `task_id` без `target_type` → `"task"` / `str(task_id)`.

Run: `../.venv/Scripts/python.exe -m pytest apps/notifications/tests/test_import_tasks.py -q`
Expected: PASS.

- [ ] **Step 5: Фронт — строковый id и настройки каналов**

1. `frontend/src/types/tasks.ts`, `Notification`: `id: string`, `target_id: string | null`, добавить `url?: string | null`. Прогнать `npx tsc --noEmit -p tsconfig.app.json | grep -c "error TS"` до и после — число не растёт; места, где `id` уведомления сравнивался как число, поправить.
2. Компонент колокольчика и `pages/NotificationsHistory.tsx`: если тип цели не входит в известную карту маршрутов и есть `url` — переход по `url`.
3. `frontend/src/api/notifications.ts`:

```ts
import { api } from '@/lib/api';
import { apiPath } from './endpoints';

export interface NotificationPrefs {
  bell: boolean;
  email: boolean;
  telegram: boolean;
  telegram_linked: boolean;
}

export const notificationsApi = {
  prefs: () => api.get<NotificationPrefs>(apiPath('notifications', 'prefs')),
  savePrefs: (body: Partial<Omit<NotificationPrefs, 'telegram_linked'>>) =>
    api.patch<NotificationPrefs>(apiPath('notifications', 'prefs'), body),
  linkTelegram: () => api.post<{ url: string }>(apiPath('notifications', 'telegram/link')),
};
```

(Имя клиента `api` — взять из соседнего `frontend/src/api/companies.ts`.)

4. Падающий тест — `frontend/src/pages/NotificationSettings.test.tsx`:

```tsx
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import NotificationSettings from './NotificationSettings';

const savePrefs = vi.fn();
vi.mock('@/api/notifications', () => ({
  notificationsApi: {
    prefs: () => Promise.resolve({ data: { bell: true, email: false, telegram: false, telegram_linked: false } }),
    savePrefs: (body: unknown) => savePrefs(body),
    linkTelegram: vi.fn(),
  },
}));

describe('NotificationSettings', () => {
  it('не даёт выключить последний канал', async () => {
    renderWithProviders(<NotificationSettings />);
    const bell = await screen.findByRole('switch', { name: /колокольчик/i });
    expect(bell).toBeDisabled();
  });

  it('сохраняет переключение канала', async () => {
    savePrefs.mockResolvedValue({ data: { bell: true, email: true, telegram: false, telegram_linked: false } });
    renderWithProviders(<NotificationSettings />);
    await userEvent.click(await screen.findByRole('switch', { name: /e-mail/i }));
    expect(savePrefs).toHaveBeenCalledWith({ email: true });
  });
});
```

5. `frontend/src/pages/NotificationSettings.tsx` — три переключателя (`Switch` из `@/components/ui/switch`, `aria-label` «Колокольчик», «E-mail», «Telegram»); переключатель, выключение которого оставило бы ноль каналов, — `disabled`; кнопка «Подключить Telegram» открывает `url` из `linkTelegram()` в новой вкладке; все строки через `t('notifications.settings.*', '…')`. Маршрут `/settings/notifications` (`requiresAuth: true`, без `requires`) в `frontend/src/app/routing/routeDefinitions.ts` и ленивый компонент в `lazyPages.ts`; ссылка из профиля пользователя.

Run (из `frontend/`): `npx vitest run src/pages/NotificationSettings.test.tsx && npm run lint`
Expected: PASS.

- [ ] **Step 6: Документация и коммит**

`CLAUDE.md` и `STRUCTURE.md`: лента колокольчика хранится в центре уведомлений (`apps.notifications`, public); `/api/tasks/v1/notifications…` — фасад с прежним контрактом; `tasks.Notification` — только для переноса (`manage.py notifications_import_tasks --company <slug>`), удаляется отдельной contract-миграцией после переноса на бою.

```bash
git add backend/apps/tasks backend/apps/notifications frontend/src CLAUDE.md STRUCTURE.md
git commit -m "feat(notifications): лента задач хранится в центре уведомлений; настройки каналов на фронте"
```

---

## После этапа

- [ ] Полный прогон backend (с исключением известных падений, как в `.github/workflows/backend-full.yml`) и `npx vitest run` — зелёные, кроме падений, которые воспроизводятся на базовом коммите.
- [ ] Финальное ревью ветки отдельным ревьюером (как на этапе 0).
- [ ] Матрица ролей отправлена Алгазы на утверждение до мерджа `access/0014`.

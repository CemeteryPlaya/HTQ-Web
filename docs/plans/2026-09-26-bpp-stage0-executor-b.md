# БЗО, этап 0 — исполнитель B (Руслан, ветка `new-module-BPP-ruslan`)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Научить движок `apps.signoff` согласовывать объекты с UUID-ключом: документы модуля БЗО (`apps.bpp`) будут адресоваться UUID, а `ApprovalProcess.subject_id` сейчас целое.

**Architecture:**
- `ApprovalProcess.subject_id` становится строкой (`CharField(64)`), хранится каноническая строка ключа модели.
- Колбэки предметной аппки получают ключ в типе ключа ЕЁ модели (`pk.to_python`): `contracts`, `approvals`, `hr` с целыми ключами не меняются.
- HTTP-ответы отдают `subject_id` строкой, а принимают и число, и строку.
- Фронт переводит типы на строку и принимает оба вида ключа в компонентах.

**Tech Stack:** Django 5.2.7, Pydantic 2.12, pytest-django (Postgres на `:55432`), React + TypeScript + vitest.

**Spec:** [мастер-план](2026-09-26-bpp-master-plan.md) — D-05 (UUID и строковые ссылки signoff), §2.6 (интерфейс signoff), §0 (правила: изменения signoff делает B и присылает A на подтверждение).

**Параллельно:** исполнитель A делает свой этап 0 в ветке `new-module-BPP-sanzhar` ([план A](2026-09-26-bpp-stage0-executor-a.md)). Файлы не пересекаются.

**Handoff в конце этапа:**
1. Запушить ветку.
2. Прислать A диф `apps/signoff` на подтверждение (правило 3 мастер-плана).
3. Смерджить к себе `origin/new-module-BPP-sanzhar`: `git fetch origin && git merge origin/new-module-BPP-sanzhar`.
4. Прогнать сторожа (шаг B0.2-9).

---

## Global Constraints

- Интерпретатор — корневой `.venv`. Все backend-команды — из `backend/`: `../.venv/Scripts/python.exe -m pytest …`. Postgres: `docker compose -f docker-compose.test-local.yml up -d db` (из корня). Одновременно — только один прогон pytest на машине.
- Ветки не создавать. Коммитить только файлы своей задачи.
- signoff — тенантная аппка: миграция `0011` применяется к схемам компаний через `manage.py migrate_companies`. Он снимает сводные представления `holding.*` до прогона: `ApprovalProcess` входит в `HOLDING_MODELS`, и смена типа столбца под живым представлением упала бы.
- Поведение для аппок с целыми ключами не меняется: те же колбэки, те же значения, те же тесты. Единственное видимое изменение — `subject_id` в JSON-ответах signoff строкой.
- Frontend typecheck — `npx tsc --noEmit -p tsconfig.app.json`. В нём есть старые ошибки: сравнивать число ошибок до и после, а не требовать ноль.

## Review Focus

1. **Два ключа одного объекта.** `5`, `"5"` и `"05"` (или UUID в разном регистре) должны адресовать ОДИН процесс. Иначе частичный уникальный индекс «один идущий процесс на объект» обходится двумя написаниями. Тест — B0.1-1 (`test_one_object_one_key_whatever_the_spelling`).
2. **Колбэк получил строку вместо целого.** `on_approved("5")` в `contracts` сделал бы `Agreement.objects.filter(pk="5")` — сработает, но `subject_id == obj.pk` в их коде тихо станет ложью. Тест — B0.1-1 (`test_integer_subject_callbacks_still_receive_an_int`).
3. **Мусорный ключ.** `subject_id="abc"` для типа с целым ключом должен давать 409 с текстом, а не 500. Тест — B0.1-1 (`test_garbage_key_is_a_conflict_not_a_crash`).
4. **Фронт с UUID.** `Number.isFinite(uuid)` — `false`: список процессов объекта с UUID-ключом никогда бы не загрузился. Тест — B0.2-1.
5. **Старый клиент шлёт число.** Операторский `POST processes` с `"subject_id": 5` обязан работать дальше. Тест — существующий `apps/signoff/tests/test_processes_api.py` (тело с `doc.pk`).

---

## Task B0.1: Строковый `subject_id` в бэкенде signoff

**Files:**
- Modify: `backend/apps/signoff/tests/testapp/models.py` (+ `UuidProbeDoc`), `backend/apps/signoff/tests/testapp/hooks.py` (+ регистрация `testapp.uuiddoc`)
- Create: `backend/apps/signoff/tests/test_string_subject.py`
- Modify: `backend/apps/signoff/services/registry.py` (протоколы, `*_for`, новые `BadSubjectId`, `native_id`, `native_ids`, `storage_key`)
- Modify: `backend/apps/signoff/models.py:579` + Create: `backend/apps/signoff/migrations/0011_process_subject_id_string.py`
- Modify: `backend/apps/signoff/services/engine.py` (`start`, `_apply_outcome`, `_emit`, `_describe`)
- Modify: `backend/apps/signoff/interface.py` (`start_process`, `get_process_for`, `approval_state_of`, `pending_step`, `pending_requirement_keys`, `list_awaiting_subject_ids`, `list_decided_subject_ids`, `is_participant`)
- Modify: `backend/apps/signoff/services/presentation.py` (`describe_many`)
- Modify: `backend/apps/signoff/schemas.py` (`ProcessStart`, `ProcessRead`, `InboxItem`)
- Modify: `backend/apps/signoff/views.py:228` (`ProcessCollectionView.get`)
- Modify: `backend/apps/signoff/tests/test_processes_api.py:279`
- Modify: `STRUCTURE.md` §3.6

**Interfaces:**
- Produces:
  - `registry.native_id(subject_type: str, subject_id) -> Any` — ключ в типе ключа модели;
  - `registry.native_ids(subject_type: str, subject_ids) -> list`;
  - `registry.storage_key(subject_type: str, subject_id) -> str`;
  - `registry.BadSubjectId(UnknownSubject)`;
  - `engine.start(..., subject_id: int | str | UUID)` и `interface.start_process(..., subject_id: int | str | UUID)`;
  - `interface.list_awaiting_subject_ids` / `list_decided_subject_ids` возвращают ключи в типе ключа модели;
  - JSON: `subject_id` — строка.
- Consumes: ничего нового.

- [ ] **Step 1: Предмет с UUID-ключом в тестовой аппке**

В `backend/apps/signoff/tests/testapp/models.py`:

1. Добавить `import uuid` над `from django.db import models`.
2. В конец файла добавить:

```python


class UuidProbeDoc(signoff.Approvable, models.Model):
    """Предмет с UUID-ключом — так устроены документы модуля БЗО
    (``apps.bpp``, мастер-план D-05). Проверяет, что движок не требует от
    объекта целого ключа."""

    SIGNOFF_SUBJECT_TYPE = "testapp.uuiddoc"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=100, default="")

    def __str__(self) -> str:
        return self.title
```

Таблицу заведёт тестовый раннер (`migrate --run-syncdb`, см. докстринг файла) — миграции не нужны.

В `backend/apps/signoff/tests/testapp/hooks.py`:

1. Заменить импорт `from .models import ProbeDoc` на `from .models import ProbeDoc, UuidProbeDoc`.
2. После `CALLS: list[tuple[str, int]] = []` добавить:

```python
# Журнал колбэков UUID-предмета: по нему видно, в каком ТИПЕ ключ дошёл до
# предметной аппки (UUID, а не строка из ApprovalProcess.subject_id).
UUID_CALLS: list[tuple[str, object]] = []
```

3. В `reset()` добавить `UUID_CALLS.clear()`.
4. Перед `def register()` добавить:

```python
def _uuid_on_started(subject_id) -> None:
    UUID_CALLS.append(("started", subject_id))


def _uuid_on_approved(subject_id) -> None:
    UUID_CALLS.append(("approved", subject_id))


def _uuid_describe(subject_id) -> dict | None:
    doc = UuidProbeDoc.objects.filter(pk=subject_id).first()
    if doc is None:
        return None
    return {"title": doc.title, "url": f"/probe-uuid/{doc.pk}"}
```

5. В конец тела `register()` добавить:

```python
    signoff.register_subject(
        UuidProbeDoc.SIGNOFF_SUBJECT_TYPE,
        label="Пробный документ с UUID",
        model=UuidProbeDoc,
        on_started=_uuid_on_started,
        on_approved=_uuid_on_approved,
        describe=_uuid_describe,
    )
```

- [ ] **Step 2: Написать падающие тесты**

Create `backend/apps/signoff/tests/test_string_subject.py`:

```python
"""Строковый ключ объекта: signoff согласует и строки с UUID-ключом.

Документы модуля БЗО (``apps.bpp``) заводятся с UUID-ключами (мастер-план
D-05), а ``ApprovalProcess.subject_id`` был целым. Теперь ключ хранится
строкой — канонической строкой ключа модели. Колбэки предметной аппки
получают его в типе ключа её модели, поэтому аппки с целыми ключами
(contracts, approvals, hr) не меняются.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.signoff import interface
from apps.signoff.models import ApprovalProcess, ApprovalState, Quorum
from apps.signoff.services import engine, registry
from apps.signoff.tests.helpers import (
    BASE,
    admin_token,
    auth,
    make_doc,
    make_route,
    make_user,
    task_for,
)
from apps.signoff.tests.testapp import hooks
from apps.signoff.tests.testapp.models import ProbeDoc, UuidProbeDoc

pytestmark = pytest.mark.django_db

UUID_SUBJECT = UuidProbeDoc.SIGNOFF_SUBJECT_TYPE


@pytest.fixture(autouse=True)
def _reset_calls():
    hooks.reset()
    yield
    hooks.reset()


def _single_stage(user, subject_type=UUID_SUBJECT):
    return make_route([(1, "Единственный", Quorum.ALL, [user.pk])], subject_type=subject_type)


def test_uuid_subject_goes_through_the_whole_route():
    a, b = make_user("a"), make_user("b")
    doc = UuidProbeDoc.objects.create(title="Счёт")
    make_route([(1, "Первый", Quorum.ALL, [a.pk]), (2, "Второй", Quorum.ALL, [b.pk])],
               subject_type=UUID_SUBJECT)

    process = engine.start(subject_type=UUID_SUBJECT, subject_id=doc.pk, initiator_id=99)
    assert ApprovalProcess.objects.get(pk=process.pk).subject_id == str(doc.pk)

    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk, decision=engine.APPROVE)
    engine.act(task_id=task_for(process, b.pk).pk, actor_id=b.pk, decision=engine.APPROVE)

    doc.refresh_from_db()
    assert doc.approval_state == ApprovalState.APPROVED
    assert interface.approval_state_of(UUID_SUBJECT, str(doc.pk)) == ApprovalState.APPROVED
    # Колбэк получает ключ в типе ключа модели — UUID, а не строку.
    assert hooks.UUID_CALLS == [("started", doc.pk), ("approved", doc.pk)]


def test_integer_subject_callbacks_still_receive_an_int():
    a = make_user("a")
    doc = make_doc()
    _single_stage(a, subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE)

    process = engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE, subject_id=doc.pk)

    assert ApprovalProcess.objects.get(pk=process.pk).subject_id == str(doc.pk)
    assert ("started", doc.pk) in hooks.CALLS
    assert all(isinstance(subject_id, int) for _kind, subject_id in hooks.CALLS)


def test_one_object_one_key_whatever_the_spelling():
    """``5``, ``"5"``, ``"05"`` — один объект; UUID в любом регистре — тоже.
    Иначе второе написание обошло бы индекс «один идущий процесс на объект»."""
    a = make_user("a")
    doc = UuidProbeDoc.objects.create(title="Счёт")
    _single_stage(a)
    engine.start(subject_type=UUID_SUBJECT, subject_id=str(doc.pk).upper())

    assert interface.get_process_for(UUID_SUBJECT, doc.pk) is not None
    with pytest.raises(engine.SignoffError):
        engine.start(subject_type=UUID_SUBJECT, subject_id=str(doc.pk))

    assert registry.storage_key(ProbeDoc.SIGNOFF_SUBJECT_TYPE, "05") == "5"
    assert registry.storage_key(ProbeDoc.SIGNOFF_SUBJECT_TYPE, 5) == "5"


def test_garbage_key_is_a_conflict_not_a_crash():
    with pytest.raises(registry.UnknownSubject):
        engine.start(subject_type=ProbeDoc.SIGNOFF_SUBJECT_TYPE, subject_id="abc")
    assert issubclass(registry.BadSubjectId, registry.UnknownSubject)


def test_awaiting_and_decided_ids_come_back_in_the_key_type_of_the_model():
    a = make_user("a")
    doc = UuidProbeDoc.objects.create(title="Счёт")
    _single_stage(a)
    process = engine.start(subject_type=UUID_SUBJECT, subject_id=doc.pk)

    assert interface.list_awaiting_subject_ids(a.pk, UUID_SUBJECT) == [doc.pk]
    engine.act(task_id=task_for(process, a.pk).pk, actor_id=a.pk, decision=engine.APPROVE)
    assert interface.list_decided_subject_ids(a.pk, UUID_SUBJECT) == [doc.pk]
    assert interface.is_participant(a.pk, UUID_SUBJECT, str(doc.pk))


def test_api_filters_by_a_string_key_and_answers_with_strings():
    a = make_user("a")
    doc = UuidProbeDoc.objects.create(title="Счёт")
    _single_stage(a)
    engine.start(subject_type=UUID_SUBJECT, subject_id=doc.pk, initiator_id=a.pk)

    response = Client().get(
        f"{BASE}/processes",
        {"subject_type": UUID_SUBJECT, "subject_id": str(doc.pk)},
        **auth(admin_token()))

    assert response.status_code == 200
    assert [row["subject_id"] for row in response.json()] == [str(doc.pk)]


def test_api_answers_an_empty_list_for_a_key_the_type_cannot_have():
    response = Client().get(
        f"{BASE}/processes",
        {"subject_type": ProbeDoc.SIGNOFF_SUBJECT_TYPE, "subject_id": "abc"},
        **auth(admin_token()))
    assert (response.status_code, response.json()) == (200, [])
```

- [ ] **Step 3: Убедиться, что тесты падают**

Run: `../.venv/Scripts/python.exe -m pytest apps/signoff/tests/test_string_subject.py -q`
Expected: FAIL. Первый тест — ошибка БД `invalid input syntax for type integer` при создании процесса с UUID; остальные — `AttributeError: module ... has no attribute 'storage_key'` / `'BadSubjectId'`.

- [ ] **Step 4: Реестр — ключ в типе модели и каноническая строка**

В `backend/apps/signoff/services/registry.py`:

1. Импорты: `from typing import Any, Callable, Protocol` и `from django.core.exceptions import ValidationError`.
2. Во всех протоколах (`Describe`, `Facts`, `ScopeOf`, `Approvers`, `OnEvent`, `CheckRequirement`) заменить `subject_id: int` на `subject_id: Any`.
3. В `Subject` и в сигнатуре `register_subject` заменить `Callable[[int], None]` на `Callable[[Any], None]` (пять колбэков `on_*`).
4. В докстринг `Subject` дописать абзац:

```python
    Ключ объекта колбэки получают в типе ключа ЕГО модели (``native_id``):
    ``int`` у целочисленных моделей, ``uuid.UUID`` у моделей с UUID-ключом.
    В ``ApprovalProcess.subject_id`` он хранится строкой (``storage_key``).
```

5. В четырёх функциях передать колбэку ключ в типе модели и поменять аннотацию `subject_id: int` на `subject_id: Any`:
   - `check_requirement_for`: `reason = subject.check_requirement(_native(subject, subject_id), key)`;
   - `scope_for`: `return str(subject.scope_of(_native(subject, subject_id)) or "")`;
   - `approvers_for`: `raw = subject.approvers(_native(subject, subject_id), key) or []`;
   - `facts_for`: `return conditions.normalize_facts(subject.facts(_native(subject, subject_id)))`.
6. В конец файла добавить:

```python


class BadSubjectId(UnknownSubject):
    """Ключ не подходит модели типа — ``"abc"`` у документа с целым ключом.

    Наследует ``UnknownSubject``, чтобы все, кто уже переводит его в 409,
    переводили и этот случай: объекта с таким ключом у типа нет и быть не может.
    """


def _native(subject: Subject, subject_id: Any) -> Any:
    try:
        return subject.model._meta.pk.to_python(subject_id)
    except ValidationError as exc:
        raise BadSubjectId(
            f"«{subject_id}» не может быть ключом объекта «{subject.label}»") from exc


def native_id(subject_type: str, subject_id: Any) -> Any:
    """Ключ объекта в типе ключа ЕГО модели: ``"5"`` → ``5``, строка UUID → ``UUID``.

    ``ApprovalProcess.subject_id`` — строка (мастер-план БЗО, D-05: документы
    ``apps.bpp`` адресуются UUID). Колбэки предметной аппки получают ключ
    таким, каким его знает её модель: аппкам с целыми ключами (contracts,
    approvals, hr) менять ничего не пришлось, и ``subject_id == obj.pk`` в их
    коде остаётся верным.
    """
    return _native(get_subject(subject_type), subject_id)


def native_ids(subject_type: str, subject_ids) -> list:
    """``native_id`` для списка; у незарегистрированного типа — ключи как есть."""
    if not is_registered(subject_type):
        return list(subject_ids)
    subject = get_subject(subject_type)
    return [_native(subject, subject_id) for subject_id in subject_ids]


def storage_key(subject_type: str, subject_id: Any) -> str:
    """Ключ так, как его хранит ``ApprovalProcess.subject_id``: каноническая
    строка ключа модели (``"5"``; UUID — в нижнем регистре с дефисами).

    Один объект, переданный целым, строкой или ``UUID``, адресует одну строку
    процесса. Иначе ``"5"`` и ``"05"`` (или UUID в разном регистре) завели бы
    два параллельных согласования в обход частичного уникального индекса.
    У незарегистрированного типа приводить не к чему — строка как есть.
    """
    if not is_registered(subject_type):
        return str(subject_id)
    return str(native_id(subject_type, subject_id))
```

- [ ] **Step 5: Модель и миграция**

В `backend/apps/signoff/models.py` заменить поле:

```python
    # Строка, а не целое: документы модуля БЗО адресуются UUID (мастер-план
    # D-05). Хранится каноническая строка ключа модели
    # (services/registry.storage_key); колбэки получают ключ в типе модели
    # (registry.native_id).
    subject_id = models.CharField(max_length=64, verbose_name="Объект")
```

В докстринг модуля (строка 5 — «``(subject_type, subject_id)`` — строка вида ``"contracts.budget"`` и id …») дописать: «id хранится строкой — каноническим ключом модели, целым или UUID».

Сгенерировать миграцию:

```bash
DJANGO_SETTINGS_MODULE=htqweb.settings.dev DB_HOST=localhost DB_PORT=55432 DB_NAME=htqweb DB_USER=htqweb DB_PASSWORD=change-me JWT_SECRET=dev PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe manage.py makemigrations signoff --name process_subject_id_string
```

Expected: `backend/apps/signoff/migrations/0011_process_subject_id_string.py` с одной операцией:

```python
        migrations.AlterField(
            model_name="approvalprocess",
            name="subject_id",
            field=models.CharField(max_length=64, verbose_name="Объект"),
        ),
```

В начало файла миграции добавить докстринг:

```python
"""ApprovalProcess.subject_id: целое → строка (мастер-план БЗО, D-05).

Postgres переписывает столбец с приведением ``USING subject_id::varchar``;
индекс ``ix_signoff_proc_subject`` и частичный уникальный индекс
перестраиваются сами. В схемах компаний — через ``manage.py
migrate_companies``: он снимает представления ``holding.*`` до прогона
(``ApprovalProcess`` входит в HOLDING_MODELS), иначе смена типа упёрлась бы
в зависящее от столбца представление.
"""
```

- [ ] **Step 6: Движок**

В `backend/apps/signoff/services/engine.py`:

1. `start`: аннотацию `subject_id: int` заменить на `subject_id: int | str`, сразу после `subject = registry.get_subject(subject_type)  # UnknownSubject → 409/422` добавить:

```python
    # Каноническая строка ключа модели: 5, "5" и "05" — один объект, и
    # частичный уникальный индекс видит одно значение (registry.storage_key).
    subject_id = registry.storage_key(subject_type, subject_id)
```

и заменить вызов `subject.on_started(subject_id)` на:

```python
        subject.on_started(registry.native_id(subject_type, subject_id))
```

2. `_apply_outcome`: заменить `callback(process.subject_id)` на:

```python
        callback(registry.native_id(process.subject_type, process.subject_id))
```

3. `_emit`: заменить `subject_id = process.subject_id` на:

```python
    subject_id = registry.native_id(process.subject_type, process.subject_id)
```

4. `_describe`: заменить `return subject.describe(process.subject_id) or {}` на:

```python
        return subject.describe(
            registry.native_id(process.subject_type, process.subject_id)) or {}
```

5. В аннотациях `_assert_submittable`, `_resolve_stages`, `_approver_ids`, `_set_subject_state` заменить `subject_id: int` на `subject_id: str`: к ним ключ приходит уже из `start()` или из процесса.

- [ ] **Step 7: Интерфейс**

В `backend/apps/signoff/interface.py`:

1. `start_process`: аннотация `subject_id: int | str`; в докстринг дописать строку «``subject_id`` — целое, строка или ``UUID``: движок приводит его к канонической строке ключа модели».
2. `get_process_for` и `approval_state_of`: аннотация `subject_id: int | str`, фильтр:

```python
               .filter(subject_type=subject_type,
                       subject_id=registry.storage_key(subject_type, subject_id))
```

3. `pending_step`: аннотация `subject_id: int | str`, фильтр `stage__process__subject_id=registry.storage_key(subject_type, subject_id)`.
4. `pending_requirement_keys`: аннотация `subject_id: int | str`.
5. `list_awaiting_subject_ids` и `list_decided_subject_ids`: аннотация возврата `-> list`, последняя строка:

```python
    return registry.native_ids(subject_type, dict.fromkeys(rows))
```

В докстринг обеих дописать: «Ключи — в типе ключа модели (``registry.native_id``): целые у целочисленных моделей, ``UUID`` у моделей с UUID-ключом».

6. `is_participant`: аннотация `subject_id: int | str`, фильтр `stage__process__subject_id=registry.storage_key(subject_type, subject_id)`.

- [ ] **Step 8: Карточки объектов**

В `backend/apps/signoff/services/presentation.py` в `describe_many`:
- аннотации `dict[tuple[str, int], dict]` заменить на `dict[tuple[str, str], dict]`;
- вызов колбэка заменить на:

```python
            info = subject.describe(registry.native_id(subject_type, subject_id)) or {}
```

Вызов остаётся внутри того же `try`: `BadSubjectId` — наследник `Exception`, и карточка с битым ключом деградирует в заголовок «Тип #ключ», как при любой ошибке `describe`.

- [ ] **Step 9: Схемы HTTP**

В `backend/apps/signoff/schemas.py`:

1. Импорты: `from typing import Annotated, Any, Literal, Optional` и `from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, model_validator`.
2. После импортов моделей добавить:

```python
# Ключ объекта согласования. Хранится и отдаётся строкой
# (ApprovalProcess.subject_id): документы модуля БЗО адресуются UUID.
# Целое от старых клиентов принимается и приводится к строке — контракт ручек
# предметных аппок не ломается.
SubjectId = Annotated[str, BeforeValidator(str), StringConstraints(min_length=1, max_length=64)]
```

3. В `ProcessStart`, `ProcessRead`, `InboxItem` заменить `subject_id: int` на `subject_id: SubjectId`.

- [ ] **Step 10: Фильтр списка процессов**

В `backend/apps/signoff/views.py`, `ProcessCollectionView.get`:

1. Заменить `subject_id = self.int_param("subject_id")` на `subject_id = self.str_param("subject_id")`.
2. Заменить блок `if subject_id is not None: query = query.filter(subject_id=subject_id)` на:

```python
        if subject_id is not None:
            try:
                key = (registry.storage_key(subject_type, subject_id)
                       if subject_type is not None else subject_id)
            except UnknownSubject:
                # Такого ключа у типа не бывает — значит, нет и процессов.
                return []
            query = query.filter(subject_id=key)
```

- [ ] **Step 11: Старый тест — ключ теперь строкой**

В `backend/apps/signoff/tests/test_processes_api.py:279`:

```python
    assert found.json()[0]["subject_id"] == str(doc.pk)
```

- [ ] **Step 12: Прогнать тесты signoff и его потребителей**

Run: `../.venv/Scripts/python.exe -m pytest apps/signoff/tests -q`
Expected: всё PASS, включая `test_string_subject.py`.

Потребители signoff — `contracts`, `approvals`, `hr` — прогоняются с тем же исключением известных падений, что и в CI (`backend/ci-known-failures.txt`, приём из `.github/workflows/backend-full.yml`). Команду запускать через Bash из `backend/`:

```bash
args=()
while IFS= read -r id; do args+=(--deselect "$id"); done < <(grep -vE '^\s*(#|$)' ci-known-failures.txt)
../.venv/Scripts/python.exe -m pytest apps/contracts/tests apps/approvals/tests apps/hr/tests/test_approval_subjects.py apps/hr/tests/test_personnel_order.py apps/core/tests/test_invariants.py apps/core/tests/test_app_isolation.py -q "${args[@]}"
```

Expected: всё PASS.

- [ ] **Step 13: Документация**

В `STRUCTURE.md` §3.6, в абзаце «**Единственный движок согласования платформы.**» после фразы `` `"approvals.request"` + pk.`` вставить:

```markdown
Ключ хранится строкой (`ApprovalProcess.subject_id`, `CharField(64)`, миграция `0011`, с 26.09.2026): документы модуля БЗО адресуются UUID. В БД лежит каноническая строка ключа модели (`services/registry.py::storage_key` — `5`, `"5"` и `"05"` адресуют один процесс), а колбэки предметной аппки получают ключ в типе ключа ЕЁ модели (`registry.native_id`: `int` или `UUID`), поэтому аппки с целыми ключами ничего не меняли. В JSON `subject_id` — строка.
```

- [ ] **Step 14: Коммит**

```bash
git add backend/apps/signoff/tests/testapp/models.py backend/apps/signoff/tests/testapp/hooks.py backend/apps/signoff/tests/test_string_subject.py backend/apps/signoff/services/registry.py backend/apps/signoff/models.py backend/apps/signoff/migrations/0011_process_subject_id_string.py backend/apps/signoff/services/engine.py backend/apps/signoff/interface.py backend/apps/signoff/services/presentation.py backend/apps/signoff/schemas.py backend/apps/signoff/views.py backend/apps/signoff/tests/test_processes_api.py STRUCTURE.md
git commit -m "feat(signoff): строковый subject_id — объекты с UUID-ключом, колбэки в типе ключа модели"
```

---

## Task B0.2: Строковый `subject_id` во фронте signoff

**Files:**
- Create: `frontend/src/components/signoff/subjectId.ts`, `frontend/src/components/signoff/subjectId.test.ts`
- Modify: `frontend/src/types/signoff.ts` (`ApprovalProcess.subject_id`, `InboxItem.subject_id`)
- Modify: `frontend/src/api/signoff.ts` (`ProcessListParams.subject_id`)
- Modify: `frontend/src/components/signoff/SubjectLink.tsx`, `SubjectProcesses.tsx`, `SubmitForApproval.tsx`
- Modify: `frontend/src/pages/signoff/ProcessDetail.tsx` (~539)

**Interfaces:**
- Consumes: JSON `subject_id` строкой (B0.1).
- Produces:
  - `type SubjectId = number | string`;
  - `isSubjectIdReady(id: SubjectId): boolean`;
  - `SubmitForApproval<Id extends SubjectId>` — `submit: (id: Id) => …`, тип ключа выводится из `subjectId`.

- [ ] **Step 1: Записать исходное число ошибок typecheck**

Run (из `frontend/`): `npx tsc --noEmit -p tsconfig.app.json | grep -c "error TS"`
Записать число — это исходное N.

- [ ] **Step 2: Написать падающий тест**

Create `frontend/src/components/signoff/subjectId.test.ts`:

```ts
import { describe, expect, it } from 'vitest';

import { isSubjectIdReady } from './subjectId';

describe('isSubjectIdReady', () => {
  it('целый ключ — только конечное число', () => {
    expect(isSubjectIdReady(5)).toBe(true);
    expect(isSubjectIdReady(Number.NaN)).toBe(false);
  });

  it('строковый ключ (UUID документа БЗО) — непустая строка', () => {
    expect(isSubjectIdReady('3f0c1a52-9d1e-4a57-9a7e-2b1c0d4e5f60')).toBe(true);
    expect(isSubjectIdReady('')).toBe(false);
    expect(isSubjectIdReady('  ')).toBe(false);
  });
});
```

Run: `npx vitest run src/components/signoff/subjectId.test.ts`
Expected: FAIL — `Failed to resolve import "./subjectId"`.

- [ ] **Step 3: Тип ключа и проверка готовности**

Create `frontend/src/components/signoff/subjectId.ts`:

```ts
/**
 * Ключ объекта согласования.
 *
 * signoff хранит и отдаёт его строкой (`ApprovalProcess.subject_id`):
 * документы модуля БЗО адресуются UUID. Предметные экраны старых доменов
 * по-прежнему держат целые id — компоненты signoff принимают оба вида.
 */
export type SubjectId = number | string;

/**
 * Можно ли уже спрашивать процессы объекта. Целый ключ — конечное число
 * (`Number(params.id)` даёт NaN, пока маршрут не разобран); строковый —
 * непустая строка. `Number.isFinite` для UUID всегда `false`, поэтому
 * одной им проверкой обойтись нельзя.
 */
export const isSubjectIdReady = (id: SubjectId): boolean =>
  typeof id === 'string' ? id.trim() !== '' : Number.isFinite(id);
```

Run: `npx vitest run src/components/signoff/subjectId.test.ts`
Expected: PASS.

- [ ] **Step 4: Типы ответа и параметры запроса**

В `frontend/src/types/signoff.ts` в `ApprovalProcess` и `InboxItem` заменить `subject_id: number;` на:

```ts
  /** Строка: целый id старых доменов или UUID документа БЗО. */
  subject_id: string;
```

В `frontend/src/api/signoff.ts`:
1. Добавить импорт `import type { SubjectId } from '@/components/signoff/subjectId';`.
2. В `ProcessListParams` заменить `subject_id?: number;` на `subject_id?: SubjectId;`.

- [ ] **Step 5: Компоненты принимают оба вида ключа**

`frontend/src/components/signoff/SubjectLink.tsx`:
- импорт `import type { SubjectId } from './subjectId';`;
- в `Props` заменить `subjectId: number;` на `subjectId: SubjectId;`.

`frontend/src/components/signoff/SubjectProcesses.tsx`:
- импорт `import { isSubjectIdReady, type SubjectId } from './subjectId';`;
- в `Props` заменить `subjectId: number;` на `subjectId: SubjectId;`;
- заменить `enabled: Number.isFinite(subjectId),` на `enabled: isSubjectIdReady(subjectId),`.

`frontend/src/components/signoff/SubmitForApproval.tsx`:
- импорт `import type { SubjectId } from './subjectId';`;
- `interface Props {` → `interface Props<Id extends SubjectId> {`;
- `subjectId: number;` → `subjectId: Id;`;
- `submit: (id: number) => Promise<AxiosResponse<ApprovalProcess>>;` → `submit: (id: Id) => Promise<AxiosResponse<ApprovalProcess>>;`;
- `export function SubmitForApproval({` → `export function SubmitForApproval<Id extends SubjectId>({`;
- `}: Props) {` → `}: Props<Id>) {`.

Вызовы менять не нужно: `subjectId={budget.id}` + `submit={contractsApi.submitBudget}` выводят `Id = number`.

- [ ] **Step 6: Карточка процесса**

В `frontend/src/pages/signoff/ProcessDetail.tsx` заменить `<SubjectView id={process.subject_id} embedded />` на:

```tsx
                  {/* Представления предметных доменов пока все с целыми id.
                      Документы БЗО (UUID) получат строковый контракт
                      SubjectViewProps в задаче B2.5 — до тех пор их типов в
                      SIGNOFF_SUBJECT_VIEWS нет, и сюда они не попадают. */}
                  <SubjectView id={Number(process.subject_id)} embedded />
```

- [ ] **Step 7: Typecheck, линт, тесты**

Run: `npx tsc --noEmit -p tsconfig.app.json | grep -c "error TS"`
Expected: число ≤ N из шага 1. Новых ошибок в `components/signoff/`, `pages/signoff/`, `api/signoff.ts`, `types/signoff.ts` нет — проверить: `npx tsc --noEmit -p tsconfig.app.json | grep -E "signoff"`, ожидается пусто.

Run: `npm run lint`
Expected: без новых ошибок.

Run: `npx vitest run src/components/signoff src/pages/signoff`
Expected: PASS.

- [ ] **Step 8: Коммит**

```bash
git add frontend/src/components/signoff/subjectId.ts frontend/src/components/signoff/subjectId.test.ts frontend/src/types/signoff.ts frontend/src/api/signoff.ts frontend/src/components/signoff/SubjectLink.tsx frontend/src/components/signoff/SubjectProcesses.tsx frontend/src/components/signoff/SubmitForApproval.tsx frontend/src/pages/signoff/ProcessDetail.tsx
git commit -m "feat(signoff): фронт принимает строковый subject_id (UUID документов БЗО)"
```

- [ ] **Step 9: Handoff — смерджить ветку A и прогнать сторожа**

После того как A запушил этап 0:

```bash
git fetch origin
git merge origin/new-module-BPP-sanzhar
```

Run (из `backend/`): `../.venv/Scripts/python.exe -m pytest apps/core/tests apps/access/tests apps/signoff/tests apps/companies/tests/test_module_service.py -q`
Expected: всё PASS.

Run (из `frontend/`): `npx vitest run`
Expected: PASS.

# Архив компании — только чтение — план

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** архивную компанию открывает на чтение только суперпользователь; запись в неё (любой метод, кроме `GET`/`HEAD`/`OPTIONS`) закрыта для всех одним правилом; остальным — 404, как сегодня.

**Architecture:** одно правило в модуле `htqweb/tenancy/archive.py`, две точки применения: `CompanyContextMiddleware` отклоняет запись до аутентификации (403 `company_archived`), `api_view` отклоняет чтение всем, кроме суперпользователя (404). Выдача токена пускает в архив только суперпользователя (без членства); `/access/v1/me` понижает уровни до `read`, фронт показывает баннер и прячет кнопки. `migrate_companies` доводит и архивные схемы, `@company_task` пропускает архив.

**Tech Stack:** Django 5.2.7, hand-rolled `htqweb.http.api_view`, схемы Postgres на компанию, pytest-django на `:55432`, React + vitest.

**Spec:** [2026-09-25-archive-read-only-spec.md](2026-09-25-archive-read-only-spec.md).

**Поправки к спеке** (найдено при планировании):
- **Переводы — `companies.archiveMode.*`, а не `companies.archived.*`** (§7.2): ключ `companies.archived` уже занят строкой — тост реестра «Компания переведена в архив» (`CompanyRegistry.tsx`); объект под тем же ключом сломал бы его.
- **Локали — две, `ru` и `en`** (`frontend/public/locales/{ru,en}/translation.json`), `kk` в проекте нет.
- Тест `api_view` — в существующем `backend/apps/core/tests/test_api_view.py`, не в новом `htqweb/tests/…` (такого каталога нет). Тесты входа — в `backend/apps/users/tests/test_auth_api.py` (там уже фикстуры `superuser`/`active_user`).
- Сквозной тест чтения `hr` — ручка `GET /api/hr/v1/departments/`.

## Global Constraints

- Зона второго разработчика не правится: `backend/apps/contracts/**`, `backend/apps/signoff/**`, `frontend/src/pages/{contracts,signoff}/**`.
- Ветки/worktree не создавать; работать в `sanzhar`; `git add` поимённо, никогда `-A`/`.`; `git stash`/`checkout`/`restore`/`reset` не использовать; не стейджить `.codebase-memory/`, `.cursor/`, `.zed/`, `.github/copilot-instructions.md`, `.github/instructions/`.
- pytest — форграунд, Bash `timeout: 600000`, одна сессия за раз, команды дольше 10 минут дробить; из `backend/`: `../.venv/Scripts/python.exe -m pytest … -q -p no:cacheprovider`; Postgres: `docker compose -f docker-compose.test-local.yml up -d db` из корня.
- Межаппное — только через `apps.<x>.interface` (сторож `apps/core/tests/test_app_isolation.py`; каталоги `tests` из-под правила выведены).
- Тексты ответов — дословно: запись — `403 {"detail": "Компания в архиве — только чтение", "code": "company_archived"}`; чтение не-суперпользователем и django-admin — `404 {"detail": "Компания не найдена"}`.
- `SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}`; `TOKEN_PATHS = {"/api/users/v1/token/", "/api/users/v1/token/refresh/"}`.
- Сводки холдинга, метрики и веер Celery по-прежнему только по действующим компаниям — `active_company_slugs` не меняется.
- Миграций БД нет (модели не меняются).
- Фронт: строки через `t('<ключ>', '<русский текст по умолчанию>')` — в тестах ресурсы i18next пусты, и тест видит текст по умолчанию.
- Коммиты на русском, последняя строка `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`; не пушить.
- Фронт: `npx tsc --noEmit -p tsconfig.app.json` — не больше 148 ошибок, `npx vitest run` — не больше 8 известных падений (`CardT2SectionDialog.test.tsx`, `EmployeeFormDialog.test.tsx`), `npm run lint` — не больше 376 проблем.

## Review Focus

- **Access-токен участника, выданный до архивации** (живёт до 60 мин) — ожидание 404 на любое чтение. Тест — задача 1, `test_member_token_issued_before_archiving_is_404`.
- **Компанию восстановили** — запись снова проходит сразу (без застрявшего 403). Тест — задача 1, `test_restored_company_accepts_writes_again`.
- **Участник архива обновляет токен на её поддомене** (refresh-cookie после перезагрузки страницы) — ожидание 403 без токена, а не токен архива. Тест — задача 2, `test_member_refresh_on_archived_subdomain_403`.
- **У суперпользователя в списке только архивная компания** — экран выбора не уводит в архив сам, а показывает список с меткой. Тест — задача 4, `CompanyPicker`: «единственную архивную компанию не открывает сам».
- **`@company_task` с незаведённым slug** — не пропускается молча, как архив, а идёт дальше (его уронит схема или сама задача). Тест — задача 3, `test_unknown_company_task_still_runs`.

## Порядок исполнения (параллельная схема)

| Волна | Разработчик A | Разработчик B |
|---|---|---|
| 1 | Задача 1 — архивный режим сервера | Задача 2 — токен и список компаний |
| 2 | Задача 3 — `/me`, фон, миграции | Задача 4 — фронт |
| 3 | Задача 5 — сквозной тест и документы | — |

Файлы задач одной волны не пересекаются. Задача 2 в своих тестах входа на поддомене архива опирается на задачу 1 (middleware пропускает `TOKEN_PATHS`) — тестировщик гоняет её после коммита задачи 1. Задача 3 зовёт `companies.interface.is_archived`/`migratable_company_slugs` из задачи 2; задача 4 читает поля `is_archived` (задача 2) и `company_archived` (задача 3) — фронт на моках, от бэкенда не зависит при прогоне.

---

### Task 1: Архивный режим сервера — middleware и `api_view`

**Files:**
- Create: `backend/htqweb/tenancy/archive.py`
- Modify: `backend/htqweb/middleware/company_context.py` (ветка `company is None or not company["is_active"]`, строки ~60–64; докстринг модуля)
- Modify: `backend/htqweb/http.py` (в `api_view`, сразу после сверки claim `company` ~строка 113 и в ветке `else:` ~строка 151)
- Test: `backend/htqweb/tenancy/tests/test_middleware.py` (заменить `test_archived_company_is_404`)
- Test: `backend/apps/core/tests/test_api_view.py` (дописать в конец)

**Interfaces:**
- Produces: `htqweb.tenancy.archive` — `SAFE_METHODS: frozenset[str]`, `TOKEN_PATHS: frozenset[str]`, `ARCHIVED_CODE = "company_archived"`, `is_archived(company: dict | None) -> bool`, `archived_response() -> JsonResponse`, `not_found_response() -> JsonResponse`. На архивном поддомене `request.company` — словарь реестра с `is_active=False` (раньше запрос туда не доходил).

- [ ] **Step 1: Падающие тесты middleware** — в `backend/htqweb/tenancy/tests/test_middleware.py` удалить функцию `test_archived_company_is_404` целиком и на её место вставить:

```python
@pytest.fixture
def dead(db):
    return Company.objects.create(
        slug="dead", name="Банкрот", kind=CompanyKind.SERVICE,
        status=CompanyStatus.ARCHIVED,
    )


def _spy_middleware():
    from htqweb.middleware.company_context import CompanyContextMiddleware

    seen = {}

    def spy(request):
        seen["context"] = current_company_or_none()
        seen["is_active"] = request.company["is_active"]
        return HttpResponse("ok")

    return CompanyContextMiddleware(spy), seen


@pytest.mark.django_db
def test_archived_company_get_reaches_the_view_in_its_context(dead, rf):
    """Архив больше не 404 целиком: чтение доходит до вьюхи в контексте
    компании. Кого пускать читать — решает api_view (только суперпользователь),
    не middleware: тот ещё не знает, кто пришёл."""
    middleware, seen = _spy_middleware()
    resp = middleware(rf.get("/api/hr/v1/departments/", HTTP_X_HTQ_COMPANY="dead"))
    assert resp.status_code == 200
    assert seen == {"context": "dead", "is_active": False}


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_archived_company_refuses_every_write(dead, method):
    resp = getattr(Client(), method)("/api/hr/v1/departments/",
                                     HTTP_X_HTQ_COMPANY="dead")
    assert resp.status_code == 403
    assert resp.json() == {"detail": "Компания в архиве — только чтение",
                           "code": "company_archived"}


@pytest.mark.django_db
def test_archived_company_write_refusal_does_not_reach_the_view(dead, rf):
    """Отказ записи — ДО вьюхи и до аутентификации: правило не зависит ни от
    роли, ни от аппки, ни от того, стоит ли на ручке api_view."""
    middleware, seen = _spy_middleware()
    resp = middleware(rf.post("/api/hr/v1/departments/", HTTP_X_HTQ_COMPANY="dead"))
    assert resp.status_code == 403
    assert seen == {}


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["head", "options"])
def test_archived_company_lets_safe_methods_through(dead, rf, method):
    middleware, seen = _spy_middleware()
    resp = middleware(getattr(rf, method)("/api/hr/v1/departments/",
                                          HTTP_X_HTQ_COMPANY="dead"))
    assert resp.status_code == 200
    assert seen["context"] == "dead"


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/api/users/v1/token/",
                                  "/api/users/v1/token/refresh/"])
def test_archived_company_lets_token_endpoints_through(dead, rf, path):
    """Без выдачи токена суперпользователь не прочтёт архив вовсе; кого
    пускать, решает сама ручка (companies.interface.user_may_enter_company)."""
    middleware, seen = _spy_middleware()
    resp = middleware(rf.post(path, HTTP_X_HTQ_COMPANY="dead"))
    assert resp.status_code == 200
    assert seen["context"] == "dead"


@pytest.mark.django_db
def test_archived_company_hides_django_admin(dead):
    """Сессии на этом шаге ещё нет (SessionMiddleware ниже) — кто пришёл,
    не узнать; django-admin живёт на голом домене."""
    resp = Client().get("/django-admin/", HTTP_X_HTQ_COMPANY="dead")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Компания не найдена"}


@pytest.mark.django_db
def test_restored_company_accepts_writes_again(dead, rf):
    from django.core.cache import cache

    dead.status = CompanyStatus.ACTIVE
    dead.save(update_fields=["status"])
    cache.clear()  # резолв метки хоста кэширован на 5 с
    middleware, seen = _spy_middleware()
    resp = middleware(rf.post("/api/hr/v1/departments/", HTTP_X_HTQ_COMPANY="dead"))
    assert resp.status_code == 200
    assert seen == {"context": "dead", "is_active": True}
```

`test_unknown_company_is_404` остаётся без изменений.

- [ ] **Step 2: Падающие тесты `api_view`** — дописать в конец `backend/apps/core/tests/test_api_view.py`:

```python
# ── Архивная компания — только чтение (спека архива §4.2) ─────────────────


@api_view(methods=("GET",), auth="jwt")
def whoami_view(request):
    return {"user_id": request.token.user_id}


@api_view(methods=("GET",), auth=None)
def anonymous_view(request):
    return {"ok": True}


# Ровно те ключи словаря реестра, которые читает api_view: слаг для сверки
# claim и is_active для архивного режима.
_ARCHIVED = {"slug": "dead", "is_active": False}
_ACTIVE = {"slug": "live", "is_active": True}


def _get_in(view, company, token=None, path="/x/"):
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
    request = RequestFactory().get(path, **headers)
    request.company = company  # ставит CompanyContextMiddleware
    return view(request)


def test_archived_company_is_read_by_superuser():
    resp = _get_in(whoami_view, _ARCHIVED,
                   _token(company="dead", is_superuser=True, is_staff=True))
    assert resp.status_code == 200


def test_member_token_issued_before_archiving_is_404():
    """Access-токен живёт до 60 минут: выданный участнику ДО архивации несёт
    claim архивной компании и сверку claim проходит. Отбивает его только
    проверка статуса — тем же 404, что участник видел бы и без токена."""
    resp = _get_in(whoami_view, _ARCHIVED, _token(company="dead"))
    assert resp.status_code == 404
    assert json.loads(resp.content) == {"detail": "Компания не найдена"}


def test_staff_without_superuser_is_404_in_archive():
    resp = _get_in(whoami_view, _ARCHIVED,
                   _token(company="dead", is_staff=True, is_admin=True))
    assert resp.status_code == 404


def test_active_company_is_not_affected():
    resp = _get_in(whoami_view, _ACTIVE, _token(company="live"))
    assert resp.status_code == 200


def test_foreign_company_token_is_still_403_in_archive():
    """Сверка claim стоит раньше архивного режима: токен чужой компании —
    по-прежнему 403, а не 404."""
    resp = _get_in(whoami_view, _ARCHIVED,
                   _token(company="live", is_superuser=True))
    assert resp.status_code == 403


def test_anonymous_view_is_404_in_archive():
    resp = _get_in(anonymous_view, _ARCHIVED)
    assert resp.status_code == 404
    assert json.loads(resp.content) == {"detail": "Компания не найдена"}


def test_anonymous_view_passes_in_active_company():
    assert _get_in(anonymous_view, _ACTIVE).status_code == 200


@pytest.mark.parametrize("path", ["/api/users/v1/token/",
                                  "/api/users/v1/token/refresh/"])
def test_token_paths_stay_open_in_archive(path):
    assert _get_in(anonymous_view, _ARCHIVED, path=path).status_code == 200
```

- [ ] **Step 3: Прогнать — падают**

Run (из `backend/`): `../.venv/Scripts/python.exe -m pytest htqweb/tenancy/tests/test_middleware.py apps/core/tests/test_api_view.py -q -p no:cacheprovider`
Expected: FAIL — middleware отвечает 404 на GET архива; `test_member_token_issued_before_archiving_is_404` получает 200.

- [ ] **Step 4: Модуль правила** — создать `backend/htqweb/tenancy/archive.py`:

```python
"""Архивная компания — только чтение.

Спека: docs/plans/2026-09-25-archive-read-only-spec.md. Одно правило, две
точки применения, и ни одна не справится одна:

- ``CompanyContextMiddleware`` отклоняет ЗАПИСЬ — любой метод вне
  ``SAFE_METHODS`` — до аутентификации. Не знает, кто пришёл, и знать не
  должен: запись в архив закрыта всем, включая суперпользователя. Видит
  каждый путь, в том числе мимо ``api_view`` (django-admin, SSE).
- ``api_view`` отклоняет ЧТЕНИЕ всем, кроме суперпользователя (решение
  заказчика 25.09): только он разбирает токен.

``TOKEN_PATHS`` открыты в обеих точках: без выдачи токена суперпользователь
архив не прочтёт вовсе, а кого пускать, решает сама ручка —
``apps.companies.interface.user_may_enter_company``.

403, а не 404, на запись — намеренно (спека §13 п. 1): суперпользователю,
нажавшему кнопку на открытой перед ним компании, «Компания не найдена»
была бы ложью. Цена — анонимный POST узнаёт, что компания есть и в архиве.
"""

from __future__ import annotations

from django.http import JsonResponse

SAFE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})

TOKEN_PATHS: frozenset[str] = frozenset({
    "/api/users/v1/token/",
    "/api/users/v1/token/refresh/",
})

ARCHIVED_CODE = "company_archived"


def is_archived(company: dict | None) -> bool:
    """Компания запроса (словарь реестра из ``request.company``) — в архиве."""
    return company is not None and not company["is_active"]


def archived_response() -> JsonResponse:
    return JsonResponse(
        {"detail": "Компания в архиве — только чтение", "code": ARCHIVED_CODE},
        status=403,
    )


def not_found_response() -> JsonResponse:
    # Тот же текст, что middleware отдаёт неизвестной метке: для всех, кроме
    # суперпользователя, архив по-прежнему неотличим от «компании нет».
    return JsonResponse({"detail": "Компания не найдена"}, status=404)
```

- [ ] **Step 5: Middleware** — в `backend/htqweb/middleware/company_context.py`:

Импорт — рядом с остальными (после `from htqweb.tenancy.context import …`):

```python
from htqweb.tenancy import archive
```

Заменить блок

```python
        company = resolve_host_label(label)
        if company is None or not company["is_active"]:
            # 404, а не 403: существование компании — само по себе сведение,
            # которое незачем подтверждать анонимному запросу.
            return JsonResponse({"detail": "Компания не найдена"}, status=404)
```

на

```python
        company = resolve_host_label(label)
        if company is None:
            # 404, а не 403: существование компании — само по себе сведение,
            # которое незачем подтверждать анонимному запросу.
            return archive.not_found_response()
        if archive.is_archived(company):
            # Архив — только чтение (htqweb/tenancy/archive.py). Здесь —
            # половина правила, которой не нужно знать, кто пришёл: запись
            # закрыта всем. Чтение пропускается дальше, отсекать
            # не-суперпользователей будет api_view.
            if request.path.startswith("/django-admin/"):
                # Сессии на этом шаге ещё нет (SessionMiddleware ниже по
                # списку) — не узнать, суперпользователь ли пришёл.
                return archive.not_found_response()
            if (request.method not in archive.SAFE_METHODS
                    and request.path not in archive.TOKEN_PATHS):
                return archive.archived_response()
```

Если после правки `JsonResponse` в файле больше не используется — убрать его импорт (`from django.http import JsonResponse`).

В докстринге модуля, после абзаца «Сброс в finally безусловен…», добавить абзац:

```
Архивная компания (спека docs/plans/2026-09-25-archive-read-only-spec.md)
НЕ отбивается целиком: чтение идёт дальше в её схему, запись и django-admin
отклоняются здесь — правило целиком в htqweb/tenancy/archive.py, вторая его
половина (чтение — только суперпользователю) в htqweb.http.api_view.
```

- [ ] **Step 6: `api_view`** — в `backend/htqweb/http.py`:

После блока

```python
                    current = getattr(request, "company", None)
                    if current is not None and payload.company != current["slug"]:
                        return json_error("Forbidden", 403)
```

вставить

```python
                    # Архив — только чтение, и читает его только
                    # суперпользователь (htqweb/tenancy/archive.py). Запись
                    # сюда уже не доходит — её отбил CompanyContextMiddleware.
                    # Стоит после сверки claim, но до admin=True и гейта
                    # модуля: суперпользователь их проходит и так, остальным
                    # считать права в архиве незачем.
                    if archive.is_archived(current) and not payload.is_superuser:
                        return archive.not_found_response()
```

Ветку

```python
                else:
                    request.token = None  # чтобы вьюхи с auth=None не падали на AttributeError
```

заменить на

```python
                else:
                    # Анонимные ручки на поддомене архива не отвечают: кто
                    # пришёл, не узнать, а читать архив может только
                    # суперпользователь. Кроме выдачи токена — без неё он
                    # архив не прочтёт вовсе.
                    if (archive.is_archived(getattr(request, "company", None))
                            and request.path not in archive.TOKEN_PATHS):
                        return archive.not_found_response()
                    request.token = None  # чтобы вьюхи с auth=None не падали на AttributeError
```

Импорт в шапке `htqweb/http.py` (к остальным `from htqweb…`):

```python
from htqweb.tenancy import archive
```

(Если импорт на уровне модуля даёт циклический импорт при старте — `htqweb/tenancy/archive.py` зависит только от `django.http`, цикла быть не должно; при ошибке импорта перенести его внутрь `view` лениво и написать почему.)

- [ ] **Step 7: Прогнать — проходят**

Run (из `backend/`): `../.venv/Scripts/python.exe -m pytest htqweb/tenancy/tests/test_middleware.py apps/core/tests/test_api_view.py -q -p no:cacheprovider`
Expected: PASS.

Затем регрессия: `../.venv/Scripts/python.exe -m pytest htqweb apps/companies/tests/test_company_archive.py apps/core/tests/test_app_isolation.py apps/access/tests/test_gate.py -q -p no:cacheprovider` — PASS.

- [ ] **Step 8: Коммит** (контроллер)

```bash
git add backend/htqweb/tenancy/archive.py backend/htqweb/middleware/company_context.py backend/htqweb/http.py backend/htqweb/tenancy/tests/test_middleware.py backend/apps/core/tests/test_api_view.py
git commit -m "feat(tenancy): архив компании — чтение суперпользователю, запись закрыта всем"
```

---

### Task 2: Токен и список компаний

**Files:**
- Modify: `backend/apps/users/interface.py` (новая функция `is_superuser`, после `staff_user_ids`)
- Modify: `backend/apps/companies/interface.py` (`user_may_enter_company`, `default_company_slug`; новые `is_archived`, `migratable_company_slugs` — после `active_company_slugs`)
- Modify: `backend/apps/companies/schemas.py` (`MyCompany`)
- Modify: `backend/apps/companies/views.py` (`MyCompaniesView.get`, ~строки 94–114)
- Test: `backend/apps/companies/tests/test_interface.py`, `backend/apps/users/tests/test_auth_api.py`, `backend/apps/companies/tests/test_api_read.py`

**Interfaces:**
- Consumes: задача 1 — middleware пропускает `TOKEN_PATHS` и GET на поддомене архива (нужно тестам входа и `me` на архиве).
- Produces: `apps.users.interface.is_superuser(user_id: int) -> bool`; `apps.companies.interface.is_archived(slug: str) -> bool` (неизвестный slug — `False`); `apps.companies.interface.migratable_company_slugs(*, fresh: bool = False) -> list[str]` (все компании реестра, по алфавиту); поле `MyCompany.is_archived: bool` в ответе `GET companies/v1/me`.

- [ ] **Step 1: Падающие тесты интерфейса** — дописать в конец `backend/apps/companies/tests/test_interface.py` (импорты — к существующим в шапке файла, дубли не заводить):

```python
from apps.companies import interface
from apps.companies.models import Company, CompanyKind, CompanyMembership, CompanyStatus
from apps.users.models import User, UserStatus


def _company(slug, status=CompanyStatus.ACTIVE):
    return Company.objects.create(slug=slug, name=slug, kind=CompanyKind.SERVICE,
                                  status=status)


def _user(username, *, superuser=False, status=UserStatus.ACTIVE):
    return User.objects.create(username=username, email=f"{username}@htq.test",
                               password="x", status=status, is_superuser=superuser)


@pytest.mark.django_db
def test_superuser_enters_archived_company_without_membership():
    _company("dead", CompanyStatus.ARCHIVED)
    root = _user("root", superuser=True)
    assert interface.user_may_enter_company(root.id, "dead") is True


@pytest.mark.django_db
def test_member_does_not_enter_archived_company():
    dead = _company("dead", CompanyStatus.ARCHIVED)
    alice = _user("alice")
    CompanyMembership.objects.create(user_id=alice.id, company=dead, is_default=True)
    assert interface.user_may_enter_company(alice.id, "dead") is False


@pytest.mark.django_db
def test_inactive_superuser_does_not_enter_archived_company():
    _company("dead", CompanyStatus.ARCHIVED)
    root = _user("root", superuser=True, status=UserStatus.SUSPENDED)
    assert interface.user_may_enter_company(root.id, "dead") is False


@pytest.mark.django_db
def test_superuser_still_needs_membership_in_active_company():
    """Асимметрия намеренная (спека §13 п. 2): в действующую компанию —
    как прежде, по членству."""
    _company("live")
    root = _user("root", superuser=True)
    assert interface.user_may_enter_company(root.id, "live") is False


@pytest.mark.django_db
def test_default_company_skips_archived():
    dead = _company("a-dead", CompanyStatus.ARCHIVED)
    live = _company("b-live")
    alice = _user("alice")
    CompanyMembership.objects.create(user_id=alice.id, company=dead, is_default=True)
    CompanyMembership.objects.create(user_id=alice.id, company=live)
    assert interface.default_company_slug(alice.id) == "b-live"


@pytest.mark.django_db
def test_default_company_is_none_when_every_membership_is_archived():
    dead = _company("dead", CompanyStatus.ARCHIVED)
    alice = _user("alice")
    CompanyMembership.objects.create(user_id=alice.id, company=dead, is_default=True)
    assert interface.default_company_slug(alice.id) is None


@pytest.mark.django_db
def test_is_archived():
    _company("dead", CompanyStatus.ARCHIVED)
    _company("live")
    assert interface.is_archived("dead") is True
    assert interface.is_archived("live") is False
    # Незаведённый slug — не архив: спрятать опечатку пропуском нельзя,
    # её уронит тот, кто полезет в схему.
    assert interface.is_archived("no-such") is False


@pytest.mark.django_db
def test_migratable_company_slugs_include_archived():
    _company("b-dead", CompanyStatus.ARCHIVED)
    _company("a-live")
    assert interface.migratable_company_slugs(fresh=True) == ["a-live", "b-dead"]
    assert interface.active_company_slugs(fresh=True) == ["a-live"]
```

- [ ] **Step 2: Падающие тесты входа** — дописать в конец `backend/apps/users/tests/test_auth_api.py` (импорт `CompanyStatus` добавить в строку `from apps.companies.models import …`):

```python
# ── Архивная компания — токен только суперпользователю (спека архива §6.1) ──


@pytest.fixture
def archived(db):
    return Company.objects.create(slug="dead", name="Архив", kind=CompanyKind.SERVICE,
                                  status=CompanyStatus.ARCHIVED)


@pytest.mark.django_db
def test_superuser_logs_in_on_archived_subdomain(superuser, archived):
    resp = Client().post(f"{BASE}/token/", data={
        "email": "root@htq.test", "password": "Adm1n!Pass",
    }, content_type="application/json", HTTP_X_HTQ_COMPANY="dead")

    assert resp.status_code == 200
    assert decode_token(resp.json()["access"]).company == "dead"


@pytest.mark.django_db
def test_member_login_on_archived_subdomain_403(active_user, archived):
    CompanyMembership.objects.create(user_id=active_user.id, company=archived,
                                     is_default=True)

    resp = Client().post(f"{BASE}/token/", data={
        "email": "alice@htq.test", "password": "S3cret!",
    }, content_type="application/json", HTTP_X_HTQ_COMPANY="dead")

    assert resp.status_code == 403
    assert resp.json() == {"detail": "Forbidden"}


@pytest.mark.django_db
def test_superuser_refresh_on_archived_subdomain(superuser, archived):
    pair = issue_token_pair(superuser)

    resp = Client().post(f"{BASE}/token/refresh/", data={
        "refresh": pair["refresh"],
    }, content_type="application/json", HTTP_X_HTQ_COMPANY="dead")

    assert resp.status_code == 200
    assert decode_token(resp.json()["access"]).company == "dead"


@pytest.mark.django_db
def test_member_refresh_on_archived_subdomain_403(active_user, archived):
    """Refresh-cookie после перезагрузки страницы на поддомене архива: токен
    архива участнику не выдаётся — иначе он прочёл бы архив, пока токен жив."""
    CompanyMembership.objects.create(user_id=active_user.id, company=archived,
                                     is_default=True)
    pair = issue_token_pair(active_user)

    resp = Client().post(f"{BASE}/token/refresh/", data={
        "refresh": pair["refresh"],
    }, content_type="application/json", HTTP_X_HTQ_COMPANY="dead")

    assert resp.status_code == 403
    assert resp.json() == {"detail": "Forbidden"}
```

- [ ] **Step 3: Падающие тесты `me`** — в `backend/apps/companies/tests/test_api_read.py`:

В `test_me_lists_active_memberships_and_marks_current` оба ожидаемых словаря дополнить ключом `"is_archived": False` (последним). Затем после `test_me_without_company_header_marks_nothing_current` вставить:

```python
@pytest.mark.django_db
def test_me_adds_archived_companies_for_superuser(client, group):
    """Суперпользователю — все архивные компании реестра, без членства, после
    действующих; компанией по умолчанию архив не бывает."""
    CompanyMembership.objects.create(company=group["htq"], user_id=9, is_default=True)

    res = client.get(f"{BASE}/me", **headers(
        "hi-tech-qazaqstan", superuser_token(company="hi-tech-qazaqstan")))

    assert res.status_code == 200
    assert [(c["slug"], c["is_archived"], c["is_default"]) for c in res.json()] == [
        ("hi-tech-qazaqstan", False, True),
        ("keg", True, False),
    ]


@pytest.mark.django_db
def test_me_on_archived_subdomain_marks_it_current(client, group):
    res = client.get(f"{BASE}/me", **headers("keg", superuser_token(company="keg")))

    assert res.status_code == 200
    assert res.json() == [
        {"slug": "keg", "subdomain": None, "name": "KEG", "kind": "service",
         "is_default": False, "is_current": True, "is_archived": True},
    ]
```

(`test_me_lists_active_memberships_and_marks_current` уже доказывает, что участнику `keg` архив не показывается.)

- [ ] **Step 4: Прогнать — падают**

Run (из `backend/`): `../.venv/Scripts/python.exe -m pytest apps/companies/tests/test_interface.py apps/users/tests/test_auth_api.py apps/companies/tests/test_api_read.py -q -p no:cacheprovider`
Expected: FAIL — нет `is_archived`/`migratable_company_slugs`, суперпользователю без членства 403, в ответе `me` нет `is_archived`.

- [ ] **Step 5: `users.interface.is_superuser`** — в `backend/apps/users/interface.py` после `staff_user_ids`:

```python
def is_superuser(user_id: int) -> bool:
    """Пользователь — суперпользователь с ДЕЙСТВУЮЩЕЙ учёткой.

    Единственный потребитель — ``apps.companies.interface.
    user_may_enter_company``: архивную компанию читает только
    суперпользователь (спека docs/plans/2026-09-25-archive-read-only-spec.md
    §6.1). Неактивная учётка — ``False`` по той же причине, что в
    ``staff_user_ids``: токена ей всё равно не выдадут.
    """
    require_service("users")
    return User.objects.filter(pk=user_id, is_superuser=True,
                               status=UserStatus.ACTIVE).exists()
```

- [ ] **Step 6: `companies.interface`** — в `backend/apps/companies/interface.py`:

После `active_company_slugs` добавить:

```python
def migratable_company_slugs(*, fresh: bool = False) -> list[str]:
    """Slug'и всех компаний реестра — действующих И архивных, по алфавиту.

    Для ``migrate_companies``: схема архивной компании обязана идти в ногу с
    кодом, иначе после первой же новой миграции её нельзя ни прочесть
    (архив — только чтение), ни восстановить (``restore_company`` упадёт на
    пересборке сводок). Сводки холдинга по-прежнему только по действующим —
    ``active_company_slugs``.
    """
    def produce():
        return sorted(Company.objects.values_list("slug", flat=True))

    if fresh:
        return produce()
    return _cached("company:migratable", produce)


def is_archived(slug: str) -> bool:
    """Компания этого слага в архиве. Незаведённый slug — ``False``.

    Для ``@company_task`` (``htqweb/tenancy/celery.py``): задача архивной
    компании не выполняется. Незаведённый slug — не архив намеренно: молча
    пропустить опечатку значило бы спрятать её; её уронит тот, кто полезет
    в схему.
    """
    company = get_company(slug)
    return bool(company) and not company["is_active"]
```

`user_may_enter_company` — докстринг оставить, дописав в конец абзац, и заменить тело:

```python
    Архивную компанию (спека docs/plans/2026-09-25-archive-read-only-spec.md
    §6.1) читает только суперпользователь, и членство ему для этого не
    нужно: заводить его в архив некому и незачем. Участникам архива — нет.
    """
    company = get_company(slug)
    if company is None:
        return False
    if not company["is_active"]:
        from apps.users import interface as users

        return users.is_superuser(user_id)
    return slug in user_company_slugs(user_id)
```

(Импорт ленивый: `apps.users.views` импортирует этот модуль на старте, и импорт `apps.users.interface` на уровне модуля замкнул бы цикл.)

`default_company_slug` — фильтр действующих:

```python
def default_company_slug(user_id: int) -> str | None:
    """Компания, куда пользователя пускать сразу после входа.

    Только действующая: архивная по умолчанию увела бы человека после входа
    в 404 (спека архива §6.2).
    """
    row = (CompanyMembership.objects
           .filter(user_id=user_id, company__status=CompanyStatus.ACTIVE)
           .order_by("-is_default", "company__slug")
           .values_list("company__slug", flat=True)
           .first())
    return row
```

- [ ] **Step 7: Схема и вьюха `me`** — в `backend/apps/companies/schemas.py` в `MyCompany` последним полем:

```python
    is_archived: bool = False
```

В `backend/apps/companies/views.py` тело `MyCompaniesView.get` заменить на:

```python
    @method_decorator(api_view(methods=("GET",), auth="jwt"))
    def get(self, request):
        current = request.company["slug"] if getattr(request, "company", None) else None
        rows = (
            CompanyMembership.objects
            .filter(user_id=request.token.user_id, company__status=CompanyStatus.ACTIVE)
            .select_related("company")
            .order_by("-is_default", "company__name")
        )
        result = [
            schemas.MyCompany(
                slug=m.company.slug, subdomain=m.company.subdomain,
                name=m.company.name, kind=m.company.kind,
                is_default=m.is_default, is_current=(m.company.slug == current),
            )
            for m in rows
        ]
        # Архив читает только суперпользователь, и членство ему не нужно
        # (спека архива §6.3) — поэтому все архивные компании реестра, а не
        # его членства; после действующих, компанией по умолчанию не бывают.
        if request.token.is_superuser:
            archived = Company.objects.filter(status=CompanyStatus.ARCHIVED).order_by("name")
            result += [
                schemas.MyCompany(
                    slug=c.slug, subdomain=c.subdomain, name=c.name, kind=c.kind,
                    is_default=False, is_current=(c.slug == current), is_archived=True,
                )
                for c in archived
            ]
        return result
```

(Докстринг класса дополнить: «Суперпользователю — плюс архивные компании реестра с `is_archived`».) `Company` в `views.py` уже импортирован — проверить; если нет, добавить к импорту моделей.

- [ ] **Step 8: Прогнать — проходят** (после коммита задачи 1)

Run (из `backend/`): `../.venv/Scripts/python.exe -m pytest apps/companies/tests/test_interface.py apps/users/tests/test_auth_api.py apps/companies/tests/test_api_read.py apps/core/tests/test_app_isolation.py -q -p no:cacheprovider`
Expected: PASS. Затем регрессия: `../.venv/Scripts/python.exe -m pytest apps/companies apps/users -q -p no:cacheprovider` (companies дробить, если дольше 10 минут: `apps/companies/tests/test_[a-l]*.py`, `test_m*.py`, `test_[s-z]*.py`) — PASS.

- [ ] **Step 9: Коммит** (контроллер)

```bash
git add backend/apps/users/interface.py backend/apps/companies/interface.py backend/apps/companies/schemas.py backend/apps/companies/views.py backend/apps/companies/tests/test_interface.py backend/apps/users/tests/test_auth_api.py backend/apps/companies/tests/test_api_read.py
git commit -m "feat(companies): токен архивной компании — только суперпользователю, архив в списке компаний"
```

---

### Task 3: `/access/v1/me` в архиве, фон и миграции

**Files:**
- Modify: `backend/apps/access/schemas.py` (`MeRead`)
- Modify: `backend/apps/access/views.py` (`MeView.get`, ~строки 367–410)
- Modify: `backend/htqweb/tenancy/celery.py` (`company_task.wrapper`)
- Modify: `backend/apps/companies/management/commands/migrate_companies.py`
- Modify: `backend/apps/companies/services/lifecycle.py` (докстринг модуля, текст `LastActiveCompany` в `archive_company`)
- Modify: `frontend`-часть не трогать (задача 4)
- Test: `backend/apps/access/tests/test_me.py`, `backend/htqweb/tenancy/tests/test_celery.py`, `backend/apps/companies/tests/test_company_archive.py`

**Interfaces:**
- Consumes: задача 1 — `htqweb.tenancy.archive.is_archived(company: dict | None)`, GET архива доходит до вьюхи; задача 2 — `apps.companies.interface.is_archived(slug: str) -> bool`, `migratable_company_slugs(*, fresh: bool = False) -> list[str]`.
- Produces: поле `company_archived: bool` в ответе `GET access/v1/me` (фронт задачи 4 читает его как `company_archived`).

- [ ] **Step 1: Падающие тесты `/me`** — в `backend/apps/access/tests/test_me.py`:

В двух тестах с полным сравнением тела (`test_me_without_company_is_not_an_error`, `test_me_returns_permissions_of_the_request_company`) добавить в ожидаемый словарь `"company_archived": False` (последним ключом). В шапку — импорт `from apps.companies.models import Company, CompanyStatus`. В конец файла:

```python
@pytest.mark.django_db
def test_me_in_archived_company_caps_everything_at_read(client, company_schema):
    """Архив — только чтение (спека архива §7.1): сюда доходит только
    суперпользователь, и его ``admin`` везде понижается до ``read`` — кнопки,
    скрытые по usePermissions, исчезают сами. Сервер на уровень не опирается:
    запись закрыта middleware."""
    slug = company_schema["slug"]
    Company.objects.filter(slug=slug).update(status=CompanyStatus.ARCHIVED)

    resp = client.get(f"{BASE}/me", HTTP_X_HTQ_COMPANY=slug,
                      **auth(superuser_token(company=slug)))

    assert resp.status_code == 200
    body = resp.json()
    assert body["company_archived"] is True
    assert body["permissions"], "у суперпользователя модули есть всегда"
    assert {entry["level"] for entry in body["permissions"].values()} == {"read"}
    assert body["depth"]
    assert all(flags == ["view"] for flags in body["depth"].values())


@pytest.mark.django_db
def test_me_in_active_company_is_not_capped(client, company_schema):
    slug = company_schema["slug"]

    resp = client.get(f"{BASE}/me", HTTP_X_HTQ_COMPANY=slug,
                      **auth(superuser_token(company=slug)))

    body = resp.json()
    assert body["company_archived"] is False
    assert {entry["level"] for entry in body["permissions"].values()} == {"admin"}
```

- [ ] **Step 2: Падающие тесты Celery** — дописать в конец `backend/htqweb/tenancy/tests/test_celery.py`:

```python
@pytest.mark.django_db
def test_archived_company_task_is_skipped():
    """Задача, поставленная до архивации, не должна дописать данные в архив
    (спека архива §8.2). Пропуск — штатный, не fallback."""
    from apps.companies.models import Company, CompanyKind, CompanyStatus

    Company.objects.create(slug="dead", name="Архив", kind=CompanyKind.SERVICE,
                           status=CompanyStatus.ARCHIVED)
    ran = []

    @company_task
    def _task():
        ran.append(current_company_or_none())
        return "done"

    assert _task(company_slug="dead") is None
    assert ran == []


@pytest.mark.django_db
def test_unknown_company_task_still_runs():
    """Незаведённый slug — не архив: пропустить его молча значило бы
    спрятать опечатку. Тело выполняется в контексте этого slug."""
    ran = []

    @company_task
    def _task():
        ran.append(current_company_or_none())
        return "done"

    assert _task(company_slug="no-such") == "done"
    assert ran == ["no-such"]
```

- [ ] **Step 3: Падающие тесты миграций** — дописать в конец `backend/apps/companies/tests/test_company_archive.py` (импорты `io` и `from apps.companies.services import lifecycle` — в шапку):

```python
@pytest.mark.django_db
def test_migrate_companies_includes_archived_schema(two_companies):
    """Схема архива идёт в ногу с кодом (спека архива §8.1): иначе после
    первой новой миграции её не прочесть и не восстановить."""
    live, dead = list(two_companies)
    Company.objects.filter(slug=dead).update(status=CompanyStatus.ARCHIVED)
    out = io.StringIO()

    call_command("migrate_companies", "--plan", stdout=out)

    assert f"{dead}:" in out.getvalue()
    assert f"{live}:" in out.getvalue()


@pytest.mark.django_db
def test_migrate_companies_migrates_archived_and_restore_succeeds(two_companies, monkeypatch):
    """Настоящий прогон, а не --plan: схема архива мигрируется, после чего
    восстановление пересобирает сводки без ошибки. Сами миграции подменены —
    тем же приёмом, что в test_holding_views.py (схемы пула уже на текущей
    версии, а настоящий migrate_company внутри транзакции теста не нужен)."""
    from apps.companies.services import migration_service

    live, dead = list(two_companies)
    lifecycle.archive_company(dead)
    migrated = []

    def fake_migrate(slug, *, app_label=None, target=None, plan=False):
        migrated.append(slug)
        return {"applied": {}, "planned": []}

    monkeypatch.setattr(migration_service, "migrate_company", fake_migrate)
    call_command("migrate_companies", stdout=io.StringIO())

    assert sorted(migrated) == sorted([live, dead])
    company, changed = lifecycle.restore_company(dead)
    assert changed is True
    assert Company.objects.get(slug=dead).status == CompanyStatus.ACTIVE
```

- [ ] **Step 4: Прогнать — падают**

Run (из `backend/`): `../.venv/Scripts/python.exe -m pytest apps/access/tests/test_me.py htqweb/tenancy/tests/test_celery.py apps/companies/tests/test_company_archive.py -q -p no:cacheprovider`
Expected: FAIL — нет `company_archived`, задача архива выполняется, `--plan` не печатает архивную компанию.

- [ ] **Step 5: `MeRead` и `MeView`** — в `backend/apps/access/schemas.py` в `MeRead` последним полем:

```python
    # Компания запроса в архиве (спека архива §7.1): уровни выше уже
    # понижены до read, depth — только view. Фронту — баннер «только
    # чтение» без второго запроса.
    company_archived: bool = False
```

В `backend/apps/access/views.py` — импорты (к существующим): `from apps.access import depth as depth_flags` (если `depth` из `apps.access` уже импортирован под своим именем — использовать его) и `from htqweb.tenancy import archive`; `LEVEL_ORDER`, `Level` — из `apps.access.models` (проверить, не импортированы ли уже). Тело `MeView.get` заменить на:

```python
    @method_decorator(api_view(methods=("GET",), auth="jwt"))
    def get(self, request):
        company = self.company
        resolution = (None if request.token.is_superuser
                      else resolve.resolve_for(request.token, company))
        permissions = resolve.permissions_for(request.token, company,
                                              resolution=resolution)
        depth_map = resolve.depth_map(request.token, company, resolution=resolution)
        archived = archive.is_archived(getattr(request, "company", None))
        if archived:
            # Архив — только чтение (спека архива §7.1). Понижение — ТОЛЬКО в
            # ответе: сервер на уровень не опирается, запись в архив закрыта
            # CompanyContextMiddleware для всех. Сюда доходит лишь
            # суперпользователь (api_view), но правило не завязано на это.
            permissions = {
                module: ({**entry, "level": Level.READ}
                         if LEVEL_ORDER[entry["level"]] > LEVEL_ORDER[Level.READ]
                         else entry)
                for module, entry in permissions.items()
            }
            depth_map = {node: [depth_flags.VIEW]
                         for node, flags in depth_map.items()
                         if depth_flags.VIEW in flags}
        return schemas.MeRead(
            company=company,
            permissions=permissions,
            depth=depth_map,
            hidden_pages=[
                row["route"] for row in registry.page_nodes()
                if resolve.page_hidden(request.token, row["route"], company,
                                       resolution=resolution)
            ],
            subordinate_companies=hierarchy.subordinate_companies(
                request.token, company),
            # Суперпользователю ``resolution`` не строится вовсе (полный
            # доступ уже без единого запроса) — его права ниоткуда не
            # наследуются, поэтому [] и без обращения к resolution.
            inherited_from=(list(resolution.inherited_from)
                            if resolution is not None else []),
            company_archived=archived,
        )
```

- [ ] **Step 6: `@company_task`** — в `backend/htqweb/tenancy/celery.py` в `company_task.wrapper` перед `with use_company(slug):` вставить:

```python
        # Архив — только чтение и для фона (спека архива §8.2): задача,
        # поставленная до архивации, не должна дописать данные. Веер
        # (fan_out_to_companies) архив и так не ставит — это для задач уже в
        # очереди. Пропуск штатный, поэтому logger.info, а не fallback().
        # Импорт ленивый — как в fan_out_to_companies ниже.
        from apps.companies.interface import is_archived

        if is_archived(slug):
            logger.info("company_task %s.%s skipped: company %s is archived",
                        fn.__module__, fn.__qualname__, slug)
            return None
```

В докстринг модуля (раздел «Шаблон „диспетчер + веер“», в конец) — строка: «Задача архивной компании не выполняется вовсе (`is_archived` в обёртке `company_task`) — архив только для чтения».

- [ ] **Step 7: `migrate_companies`** — в `backend/apps/companies/management/commands/migrate_companies.py`:
- импорт `active_company_slugs` → `migratable_company_slugs`;
- `help` → `"Довести схемы компаний до текущей версии миграций. Без --company обрабатывает все компании реестра — действующие и архивные."`;
- `else active_company_slugs(fresh=True))` → `else migratable_company_slugs(fresh=True))`;
- `raise CommandError("Нет действующих компаний.")` → `raise CommandError("В реестре нет компаний.")`;
- над выбором `slugs` — комментарий: `# Архивные — тоже: схема архива обязана идти в ногу с кодом, иначе её не прочесть (архив — только чтение) и не восстановить. Сводки собираются только по действующим — rebuild_holding_views сам берёт active_company_slugs.`

Перед правкой — `grep -rn "Нет действующих компаний" backend/apps` : если тест ждёт старый текст, обновить его ожидание на новый. `test_migration_service.py::test_command_refuses_when_there_are_no_companies` (пустой реестр → `CommandError`) остаётся зелёным без правок.

- [ ] **Step 8: `LastActiveCompany`** — в `backend/apps/companies/services/lifecycle.py`:
- в докстринге модуля абзац «Гейт ``LastActiveCompany`` — требование режима перехода … архив = 404 на весь трафик компании, и пока компания одна, это 404 на contracts/signoff целиком.» заменить на: «Гейт ``LastActiveCompany`` — требование режима перехода (docs/plans/2026-09-14-group-structure-roadmap.md, §3 п.4): архив — только чтение (docs/plans/2026-09-25-archive-read-only-spec.md), и без действующей компании платформе негде писать — contracts/signoff живут только в схемах компаний. Гейт стоит здесь, а не во вьюхе, чтобы действовать и для CLI.»
- текст ошибки в `archive_company`:

```python
        raise LastActiveCompany(
            f"{slug} — единственная действующая компания: в архиве она "
            "закрылась бы на запись, и платформе негде было бы работать — "
            "contracts и signoff живут только в схемах компаний."
        )
```

(Тест `test_cli_archive_refuses_the_last_active_company` ищет «единственная действующая» — фраза сохранена.)

- [ ] **Step 9: Прогнать — проходят**

Run (из `backend/`): `../.venv/Scripts/python.exe -m pytest apps/access/tests/test_me.py htqweb/tenancy/tests/test_celery.py apps/companies/tests/test_company_archive.py apps/companies/tests/test_lifecycle.py apps/core/tests/test_invariants.py apps/core/tests/test_app_isolation.py -q -p no:cacheprovider`
Expected: PASS. Затем регрессия: `../.venv/Scripts/python.exe -m pytest apps/access -q -p no:cacheprovider` — PASS.

- [ ] **Step 10: Коммит** (контроллер)

```bash
git add backend/apps/access/schemas.py backend/apps/access/views.py backend/htqweb/tenancy/celery.py backend/apps/companies/management/commands/migrate_companies.py backend/apps/companies/services/lifecycle.py backend/apps/access/tests/test_me.py backend/htqweb/tenancy/tests/test_celery.py backend/apps/companies/tests/test_company_archive.py
git commit -m "feat(access,tenancy): права в архиве до read, фон архив пропускает, migrate_companies доводит архивные схемы"
```

---

### Task 4: Фронт — баннер, списки компаний, реестр, отказ записи

**Files:**
- Modify: `frontend/src/types/companies.ts` (`MyCompany`), `frontend/src/types/access.ts` (`AccessMe`)
- Modify: `frontend/src/hooks/usePermissions.ts` (`Permissions`, `usePermissions`)
- Create: `frontend/src/components/companies/ArchivedCompanyBanner.tsx`
- Modify: `frontend/src/components/Header.tsx` (импорт, вставка баннера перед блоком `CreateTaskModal`)
- Modify: `frontend/src/components/companies/CompanySwitcher.tsx`
- Modify: `frontend/src/pages/CompanyPicker.tsx`
- Modify: `frontend/src/pages/companies/CompanyRegistry.tsx`
- Modify: `frontend/src/api/client.ts` (перехватчик ответа, перед блоком `// ── 403: возможно устаревшие claims`)
- Modify: `frontend/public/locales/ru/translation.json`, `frontend/public/locales/en/translation.json` (раздел `companies`)
- Test: `frontend/src/components/companies/ArchivedCompanyBanner.test.tsx` (новый), `CompanySwitcher.test.tsx`, `frontend/src/pages/__tests__/CompanyPicker.test.tsx`, `frontend/src/pages/companies/CompanyRegistry.test.tsx`, `frontend/src/api/client.test.ts`

**Interfaces:**
- Consumes: ответ `GET companies/v1/me` — поле `is_archived: boolean` (задача 2); ответ `GET access/v1/me` — поле `company_archived: boolean` (задача 3); отказ записи — 403 `{"code": "company_archived"}` (задача 1).
- Produces: `Permissions.companyArchived: boolean`; компонент `ArchivedCompanyBanner`; ключи `companies.archiveMode.{banner,badge,writeRefused,restoreElsewhere}`.

- [ ] **Step 1: Падающие тесты**

`frontend/src/components/companies/ArchivedCompanyBanner.test.tsx`:

```tsx
/** Баннер «компания в архиве — только чтение» (спека архива §7.2). */
import { screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/renderWithProviders';

import { ArchivedCompanyBanner } from './ArchivedCompanyBanner';

const permissions = vi.fn();
vi.mock('@/hooks/usePermissions', () => ({ usePermissions: () => permissions() }));

describe('ArchivedCompanyBanner', () => {
  it('виден в архивной компании', () => {
    permissions.mockReturnValue({ companyArchived: true });
    renderWithProviders(<ArchivedCompanyBanner />);
    expect(screen.getByRole('status')).toHaveTextContent('Компания в архиве — только чтение');
  });

  it('скрыт в действующей компании', () => {
    permissions.mockReturnValue({ companyArchived: false });
    renderWithProviders(<ArchivedCompanyBanner />);
    expect(screen.queryByRole('status')).toBeNull();
  });
});
```

В `CompanySwitcher.test.tsx` — в `describe` добавить:

```tsx
  it('помечает архивную компанию', async () => {
    const dead: MyCompany = { slug: 'keg', name: 'KEG', kind: 'service', is_default: false, is_current: false, is_archived: true };
    companyFromHost.mockReturnValue('hi-tech-qazaqstan');
    myCompanies.mockResolvedValue({ data: [htq, dead] });
    renderWithProviders(<CompanySwitcher />);
    await userEvent.click(await screen.findByRole('combobox'));
    expect(await screen.findByRole('option', { name: /KEG · архив/ })).toBeInTheDocument();
  });
```

В `frontend/src/pages/__tests__/CompanyPicker.test.tsx` — рядом с `HTQ`/`HTS` константа и два теста в `describe`:

```tsx
const KEG_ARCHIVED: MyCompany = { slug: 'keg', subdomain: 'keg', name: 'KEG', kind: 'service', is_default: false, is_current: false, is_archived: true };
```

```tsx
  it('единственную архивную компанию не открывает сам, а показывает с меткой', async () => {
    const assign = stubBareHost();
    mockMyCompanies([KEG_ARCHIVED]);

    render(<CompanyPicker />, { wrapper });

    expect(await screen.findByText('KEG')).toBeInTheDocument();
    expect(screen.getByText('архив')).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();
  });

  it('с действующей и архивной — список, без автоперехода', async () => {
    const assign = stubBareHost();
    mockMyCompanies([HTQ, KEG_ARCHIVED]);

    render(<CompanyPicker />, { wrapper });

    expect(await screen.findByText('HTQ')).toBeInTheDocument();
    expect(screen.getByText('KEG')).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();
  });
```

В `frontend/src/pages/companies/CompanyRegistry.test.tsx` — рядом с моком `useActiveProfile`:

```tsx
const companyArchived = vi.fn(() => false);
vi.mock('@/hooks/usePermissions', () => ({
  usePermissions: () => ({ companyArchived: companyArchived() }),
}));
```

В `beforeEach` — `companyArchived.mockReturnValue(false);`. Новый тест в `describe`:

```tsx
  it('на поддомене архива не даёт ничего менять и подсказывает, где восстановить', async () => {
    roles.mockReturnValue(['admin']);
    companyArchived.mockReturnValue(true);
    renderWithProviders(<CompanyRegistry />);
    await userEvent.click(await screen.findByText('Hi-Tech Qazaqstan'));
    expect(screen.queryByRole('button', { name: /В архив/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Изменить/ })).toBeNull();
    expect(screen.getByText(/Восстановить компанию можно из реестра/)).toBeInTheDocument();
  });
```

В `frontend/src/api/client.test.ts` — шапку заменить и добавить тест:

```ts
import axios, { AxiosError, type AxiosAdapter, type InternalAxiosRequestConfig } from 'axios';
import { describe, it, expect, vi } from 'vitest';

const toastError = vi.fn();
vi.mock('sonner', () => ({ toast: { error: (m: string) => toastError(m) } }));

import api from './client';
```

```ts
  it('403 company_archived — без обновления токена и повтора, с тостом', async () => {
    const calls: string[] = [];
    const refresh = vi.spyOn(axios, 'post');
    const original = api.defaults.adapter;
    api.defaults.adapter = (async (config: InternalAxiosRequestConfig) => {
      calls.push(config.url ?? '');
      throw new AxiosError('Forbidden', 'ERR_BAD_REQUEST', config, null, {
        status: 403, statusText: 'Forbidden', headers: {}, config,
        data: { detail: 'Компания в архиве — только чтение', code: 'company_archived' },
      });
    }) as AxiosAdapter;
    try {
      await expect(api.post('hr/v1/departments/', {})).rejects.toBeTruthy();
      expect(calls).toHaveLength(1);
      expect(refresh).not.toHaveBeenCalled();
      expect(toastError).toHaveBeenCalledWith('Нельзя изменить: компания в архиве — только чтение');
    } finally {
      api.defaults.adapter = original;
      refresh.mockRestore();
    }
  });
```

- [ ] **Step 2: Прогнать — падают**

Run (из `frontend/`): `npx vitest run src/components/companies src/pages/__tests__/CompanyPicker.test.tsx src/pages/companies/CompanyRegistry.test.tsx src/api/client.test.ts`
Expected: FAIL — нет компонента, метки, подсказки; клиент зовёт `axios.post` (refresh).

- [ ] **Step 3: Типы и хук**

`frontend/src/types/companies.ts`, в `MyCompany` после `is_current`:

```ts
  /** Компания в архиве — только чтение; приходит только суперпользователю. */
  is_archived?: boolean;
```

`frontend/src/types/access.ts`, в `AccessMe` последним полем:

```ts
  /** Компания запроса в архиве: уровни уже понижены до `read` (спека архива §7.1). */
  company_archived?: boolean;
```

`frontend/src/hooks/usePermissions.ts` — в интерфейс `Permissions` после `inheritedFrom`:

```ts
  /**
   * Компания запроса в архиве — только чтение. Уровни в `level`/`atLeast` уже
   * понижены сервером; флаг — для баннера и кнопок, которые идут не по уровню
   * (платформенные операции реестра).
   */
  companyArchived: boolean;
```

и в возвращаемый объект после `inheritedFrom: …`:

```ts
      companyArchived: data?.company_archived ?? false,
```

Затем `npx tsc --noEmit -p tsconfig.app.json` — если число ошибок выросло выше 148 из-за объектов, собранных как `Permissions` без нового поля (моки в не-тестовом коде, `useHRLevel`), дописать им `companyArchived: false`.

- [ ] **Step 4: Баннер** — `frontend/src/components/companies/ArchivedCompanyBanner.tsx`:

```tsx
import { Archive } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { usePermissions } from '@/hooks/usePermissions';

/**
 * Полоса «компания в архиве — только чтение» (спека архива §7.2).
 *
 * Стоит в `Header` — он есть во всех раскладках, поэтому одна точка. Кнопки,
 * скрытые по `usePermissions`, исчезают сами (уровни в архиве не выше `read`);
 * те, что по уровню не прячутся, получат 403 `company_archived` и тост —
 * баннер предупреждает заранее.
 */
export function ArchivedCompanyBanner() {
  const { t } = useTranslation();
  const { companyArchived } = usePermissions();
  if (!companyArchived) return null;
  return (
    <div
      role="status"
      className="mt-3 border-t border-amber-300/70 bg-amber-50/90 text-amber-900 dark:border-amber-800/70 dark:bg-amber-950/40 dark:text-amber-200"
    >
      <div className="container-custom flex items-center gap-2 py-1.5 text-sm">
        <Archive className="h-4 w-4 shrink-0" />
        <span>{t('companies.archiveMode.banner', 'Компания в архиве — только чтение')}</span>
      </div>
    </div>
  );
}

export default ArchivedCompanyBanner;
```

`frontend/src/components/Header.tsx` — импорт после строки `import { CompanySwitcher } …`:

```tsx
import { ArchivedCompanyBanner } from '@/components/companies/ArchivedCompanyBanner';
```

и непосредственно перед блоком

```tsx
      {isLoggedIn && (
        <Suspense fallback={null}>
          <CreateTaskModal
```

вставить

```tsx
      {isLoggedIn && <ArchivedCompanyBanner />}

```

- [ ] **Step 5: Переключатель и экран выбора**

`CompanySwitcher.tsx` — пункт списка:

```tsx
        {companies.map((c) => (
          <SelectItem key={c.slug} value={hostLabelOf(c)}>
            {c.is_archived ? `${c.name} · ${t('companies.archiveMode.badge', 'архив')}` : c.name}
          </SelectItem>
        ))}
```

`CompanyPicker.tsx` — после `const target = targetPath(location.state);`:

```tsx
  // Сам уводит только в единственную ДЕЙСТВУЮЩУЮ компанию: архив (его видит
  // только суперпользователь) — только по явному выбору (спека архива §7.2).
  const autoTarget = companies.length === 1 && !companies[0].is_archived ? companies[0] : null;
```

эффект:

```tsx
  useEffect(() => {
    if (!isLoading && autoTarget) switchCompany(autoTarget, target);
  }, [isLoading, autoTarget, target]);
```

ветку `} else if (companies.length === 1) {` → `} else if (autoTarget) {`; в пункте списка после бейджа по умолчанию:

```tsx
                  {c.is_archived && <Badge variant="outline">{t('companies.archiveMode.badge', 'архив')}</Badge>}
```

- [ ] **Step 6: Реестр** — `CompanyRegistry.tsx`:
- импорт `import { usePermissions } from '@/hooks/usePermissions';`;
- после `const platformAdmin = …`:

```tsx
  // На поддомене архива запись закрыта всем (403 company_archived), включая
  // платформенные операции — они идут по суперпользователю, не по уровню,
  // и сами не спрячутся (спека архива §7.2).
  const { companyArchived } = usePermissions();
  const canWrite = platformAdmin && !companyArchived;
```

- `{platformAdmin && (` у блока кнопок «Изменить»/«В архив»/«Вернуть из архива» → `{canWrite && (`; сразу после этого блока:

```tsx
                {platformAdmin && companyArchived && (
                  <p className="text-sm text-muted-foreground">
                    {t('companies.archiveMode.restoreElsewhere', 'Восстановить компанию можно из реестра на поддомене действующей компании.')}
                  </p>
                )}
```

- панели: `canEdit={platformAdmin}` → `canEdit={canWrite}`, `canRevoke={platformAdmin}` → `canRevoke={canWrite}`;
- текст подтверждения архива: `'Архив закрывает весь трафик компании: её поддомен ответит 404. Данные остаются на месте.'` → `'Архив закрывает компанию на запись: её поддомен откроется только администратору платформы и только на чтение. Данные остаются на месте.'`.

- [ ] **Step 7: Клиент** — `frontend/src/api/client.ts`: импорт `import { toast } from 'sonner';` к остальным; непосредственно перед комментарием `// ── 403: возможно устаревшие claims — одна попытка обновления ──`:

```ts
    // ── 403 company_archived: запись в архивную компанию (спека архива §7.2) ──
    // Не устаревшие claims: обновлять токен и повторять бессмысленно — сервер
    // ответит тем же. Тост вместо молчаливого отказа.
    if (status === 403) {
      const data = error.response?.data as { code?: string } | undefined;
      if (data?.code === 'company_archived') {
        toast.error(i18next.t('companies.archiveMode.writeRefused',
          'Нельзя изменить: компания в архиве — только чтение'));
        return Promise.reject(error);
      }
    }

```

- [ ] **Step 8: Переводы** — в обоих файлах сразу после строки `"subdomainHint": …,` раздела `companies` вставить (Edit по строке `subdomainHint`, файлы не переформатировать):

`ru/translation.json`:

```json
    "archiveMode": {
      "banner": "Компания в архиве — только чтение",
      "badge": "архив",
      "writeRefused": "Нельзя изменить: компания в архиве — только чтение",
      "restoreElsewhere": "Восстановить компанию можно из реестра на поддомене действующей компании."
    },
```

`en/translation.json`:

```json
    "archiveMode": {
      "banner": "This company is archived — read only",
      "badge": "archived",
      "writeRefused": "Cannot change: the company is archived — read only",
      "restoreElsewhere": "Restore the company from the registry on an active company's subdomain."
    },
```

Проверка: `../.venv/Scripts/python.exe -c "import json;[json.load(open(f'frontend/public/locales/{l}/translation.json',encoding='utf-8')) for l in ('ru','en')]"` из корня — без ошибок.

- [ ] **Step 9: Прогнать — проходят**

Run (из `frontend/`): `npx vitest run src/components/companies src/pages/__tests__/CompanyPicker.test.tsx src/pages/companies/CompanyRegistry.test.tsx src/api/client.test.ts src/components/__tests__` — PASS; затем `npx vitest run` (≤ 8 известных), `npx tsc --noEmit -p tsconfig.app.json` (≤ 148), `npm run lint` (≤ 376).

- [ ] **Step 10: Коммит** (контроллер)

```bash
git add frontend/src/types/companies.ts frontend/src/types/access.ts frontend/src/hooks/usePermissions.ts frontend/src/components/companies/ArchivedCompanyBanner.tsx frontend/src/components/companies/ArchivedCompanyBanner.test.tsx frontend/src/components/Header.tsx frontend/src/components/companies/CompanySwitcher.tsx frontend/src/components/companies/CompanySwitcher.test.tsx frontend/src/pages/CompanyPicker.tsx frontend/src/pages/__tests__/CompanyPicker.test.tsx frontend/src/pages/companies/CompanyRegistry.tsx frontend/src/pages/companies/CompanyRegistry.test.tsx frontend/src/api/client.ts frontend/src/api/client.test.ts frontend/public/locales/ru/translation.json frontend/public/locales/en/translation.json
git commit -m "feat(frontend): архив компании — баннер, метка в списках, реестр без записи, отказ без повтора"
```

(Плюс файлы, которые пришлось дополнить `companyArchived: false` по шагу 3, — поимённо.)

---

### Task 5: Сквозной тест и документы

**Files:**
- Create: `backend/apps/hr/tests/test_archive_read_only.py`
- Modify: `docs/multi-company-tenancy-design.md`, `CLAUDE.md`, `docs/plans/2026-09-14-group-structure-roadmap.md`, `docs/deploy/subdomains-runbook.md`

**Interfaces:**
- Consumes: задачи 1–3 целиком.

- [ ] **Step 1: Сквозной тест** — `backend/apps/hr/tests/test_archive_read_only.py`:

```python
"""Архивная компания — только чтение, сквозь весь стек (спека архива §1, §9).

Через настоящий Client: middleware → api_view → вьюха → схема компании.
Юнит-тесты задач 1–3 проверяют точки по отдельности; этот — что они
сложились: суперпользователь читает данные схемы архива, запись закрыта
всем и в тенантной, и в общей аппке, участник архив не видит.
"""

import json

import pytest
from django.test import Client

from apps.access.tests.helpers import auth, superuser_token, token
from apps.companies.models import Company, CompanyStatus


@pytest.fixture
def archived(company_schema):
    slug = company_schema["slug"]
    # До первого запроса теста: резолв метки хоста кэшируется на 5 с.
    Company.objects.filter(slug=slug).update(status=CompanyStatus.ARCHIVED)
    return slug


def _headers(slug, tok):
    return {"HTTP_X_HTQ_COMPANY": slug, **auth(tok)}


@pytest.mark.django_db
def test_superuser_reads_archived_company(archived):
    resp = Client().get("/api/hr/v1/departments/",
                        **_headers(archived, superuser_token(company=archived)))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_superuser_cannot_write_to_archived_company(archived):
    resp = Client().post("/api/hr/v1/departments/", data=json.dumps({"name": "Новый"}),
                         content_type="application/json",
                         **_headers(archived, superuser_token(company=archived)))
    assert resp.status_code == 403
    assert resp.json() == {"detail": "Компания в архиве — только чтение",
                           "code": "company_archived"}


@pytest.mark.django_db
def test_shared_app_write_is_refused_on_archived_subdomain(archived):
    """Правило одно для всех аппок, включая общие (решение заказчика 25.09)."""
    resp = Client().post("/api/messenger/v1/rooms/", data=json.dumps({"name": "x"}),
                         content_type="application/json",
                         **_headers(archived, superuser_token(company=archived)))
    assert resp.status_code == 403
    assert resp.json()["code"] == "company_archived"


@pytest.mark.django_db
def test_member_of_archived_company_sees_nothing(archived):
    resp = Client().get("/api/hr/v1/departments/",
                        **_headers(archived, token(company=archived)))
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Компания не найдена"}
```

- [ ] **Step 2: Прогнать**

Run (из `backend/`): `../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_archive_read_only.py -q -p no:cacheprovider`
Expected: PASS (задачи 1–3 уже в дереве). Если `GET departments/` отвечает не 200 по причине, не связанной с архивом (например, 503 выключенного модуля у фикстуры), — сверить с соседним тестом ручки в `apps/hr/tests/test_module_gate.py`, как он поднимает компанию, и повторить его подготовку; сам архивный режим не трогать.

- [ ] **Step 3: Дизайн мультикомпанейности** — `docs/multi-company-tenancy-design.md`:
- шапка «Состояние на 23.09.2026» → «Состояние на 25.09.2026»; фраза «**выполнен частично: создание, архив и восстановление есть; архив «только чтение» и банкротство с преемником — нет.** Архив по-прежнему закрывает 100% трафика компании 404 (§6);» → «**выполнен частично: создание, архив «только чтение» и восстановление есть; банкротство с преемником — нет.** Архив читает только суперпользователь, запись в него закрыта всем ([спека](plans/2026-09-25-archive-read-only-spec.md), §6);»;
- таблица §4 строка 4 «⚠️ частично — …; архив «только чтение» и банкротство …» → «⚠️ частично — создание, архив «только чтение» (спека 25.09) и восстановление компании есть; банкротство с переносом людей/техники/договоров **не выполнено**, см. §6»;
- §6: строку «Неизвестный или архивный slug → 404 до всякой аутентификации.» → «Неизвестный slug → 404 до всякой аутентификации; архивный — режим «только чтение» ниже.»; абзацы «**Архив сегодня — это 404 …**» и «**На 23.09.2026 это по-прежнему не выполнено** …» (до «**Модели tenant-аппок не меняются.**») заменить одним:

```
**Архив — только чтение** ([спека](plans/2026-09-25-archive-read-only-spec.md),
25.09.2026). Правило — `htqweb/tenancy/archive.py`, две точки: в
`CompanyContextMiddleware` любой метод кроме `GET`/`HEAD`/`OPTIONS` на
поддомене архива — 403 `company_archived` до аутентификации (всем, включая
суперпользователя; кроме `token/` и `token/refresh/`), django-admin — 404; в
`api_view` чтение — только суперпользователю, остальным 404 «Компания не
найдена», как раньше, — в том числе по access-токену, выданному до
архивации. Токен архива выдаётся только суперпользователю, без членства
(`companies.interface.user_may_enter_company`); `/access/v1/me` понижает
уровни до `read`, фронт показывает баннер. `migrate_companies` доводит и
архивные схемы (иначе архив не прочесть и не восстановить после первой новой
миграции); `@company_task` задачу архива пропускает; сводки холдинга,
метрики и веер Celery — только по действующим. Вне режима: WebSocket
мессенджера и SSE `approvals/stream` (мимо middleware/`api_view`, данных
компании не пишут).
```

- §12 пункт «Тест архивной компании: **и запись, и чтение отклоняются** …» заменить на: «Тест архивной компании: **чтение — суперпользователю, запись — 403 `company_archived` всем**, участнику — 404 (`htqweb/tenancy/tests/test_middleware.py`, `apps/core/tests/test_api_view.py`, сквозной `apps/hr/tests/test_archive_read_only.py`).»

- [ ] **Step 4: `CLAUDE.md`** — в разделе «Мультикомпанейность»:
- в последнем абзаце (строка с командами) фразу «Архив сегодня — 404 на весь трафик компании; «архив — только чтение» остаётся невыполненным требованием заказчика, адресовано подпроекту 4 (см. `docs/multi-company-tenancy-design.md` §6).» заменить на «**Архив — только чтение** (`htqweb/tenancy/archive.py`, спека `docs/plans/2026-09-25-archive-read-only-spec.md`): читает только суперпользователь (токен без членства), любой не-`GET` на поддомене архива — 403 `company_archived` всем, остальным — 404; `migrate_companies` доводит и архивные схемы, `@company_task` архив пропускает.»;
- в пункте «**Контекст компании обязателен, а не подставляется.**» после фразы о `search_path=public` без заголовка добавить: «Архивную компанию middleware не отбивает целиком: чтение идёт в её схему, запись отклоняется (см. «Архив — только чтение» ниже).»

- [ ] **Step 5: Roadmap** — `docs/plans/2026-09-14-group-structure-roadmap.md`:
- §4 строка «Реестр компаний…», последняя ячейка «архив «только чтение» не выполнен — сегодня архив закрывает весь трафик компании 404 (`docs/multi-company-tenancy-design.md` §6)» → «архив «только чтение» — **закрыт** ([спека](2026-09-25-archive-read-only-spec.md), [план](2026-09-25-archive-read-only.md)); банкротство с преемником — нет»;
- §10: строку «Архив «только чтение» — отдельной спекой.» → «Архив «только чтение» — закрыт ([спека](2026-09-25-archive-read-only-spec.md), [план](2026-09-25-archive-read-only.md)).»; в абзаце «Сознательно оставлено — архив компании «только чтение» (сегодня архив закрывает 404 весь трафик), банкротство…» убрать «архив компании «только чтение» (сегодня архив закрывает 404 весь трафик),».

- [ ] **Step 6: Runbook** — в конец `docs/deploy/subdomains-runbook.md`:

```markdown
## Архив компании — только чтение

Спека — [2026-09-25-archive-read-only-spec.md](../plans/2026-09-25-archive-read-only-spec.md).
Миграций БД нет; порядок относительно поддоменов не важен — без заголовка
компании режим не включается.

1. `manage.py tenancy_status` — слепок до.
2. `manage.py migrate_companies` — доведёт схемы архивных компаний, отставшие
   со дня их архивации (до этой выкатки их не мигрировал никто). Архивных
   компаний нет — шаг ничего не меняет, но остаётся в чеклисте.
3. Проверка на стенде: заархивировать одну из компаний `seed_group_demo`
   (`manage.py company_archive --company <slug>`), затем:
   - суперпользователь открывает её поддомен — баннер «Компания в архиве —
     только чтение», списки читаются, кнопок записи нет;
   - `curl -X POST -H 'X-HTQ-Company: <метка>' …/api/hr/v1/departments/` →
     403 `{"code": "company_archived"}`;
   - участник этой компании на её поддомене — 404 «Компания не найдена»;
   - `manage.py company_restore --company <slug>` — запись снова проходит.
4. `manage.py tenancy_status` — слепок после; расхождение — стоп-сигнал.
```

- [ ] **Step 7: Коммит** (контроллер)

```bash
git add backend/apps/hr/tests/test_archive_read_only.py docs/multi-company-tenancy-design.md CLAUDE.md docs/plans/2026-09-14-group-structure-roadmap.md docs/deploy/subdomains-runbook.md
git commit -m "test,docs: архив только чтение — сквозной тест, дизайн, CLAUDE.md, roadmap, чеклист выкатки"
```

---

## Итоговая проверка (тестировщик, после задачи 5)

Весь бэкенд частями ≤ 10 минут (как итоговый прогон блока L: `core+htqweb`, `access`, `companies` тремя частями, `users`, `hr` тремя частями, `tasks` двумя, `mail` двумя, `messenger+approvals`, `conference+cms+media_files`, `contracts`, `signoff`) — падают только 6 тестов из `backend/ci-known-failures.txt`; `manage.py makemigrations --check --dry-run` — «No changes detected»; фронт — `npx tsc --noEmit -p tsconfig.app.json` ≤ 148, `npx vitest run` ≤ 8 известных, `npm run lint` ≤ 376.

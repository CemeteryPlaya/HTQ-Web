# БЗО, этап 0 — исполнитель A (Санжар, ветка `new-module-BPP-sanzhar`)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Подготовить платформу к модулю БЗО:
- рубильники подмодулей;
- четыре новые аппки (`project`, `refdata`, `notifications`, `bpp`) — зарегистрированы, смонтированы, отключаемы, их узлы есть в реестре прав;
- сторожа прав видят вьюхи, разнесённые по `views_<подмодуль>.py`.

**Architecture:**
- Реестр `KNOWN_SUBMODULES` (подмодуль → родитель) живёт рядом с `KNOWN_SERVICES`.
- Проверка статуса идёт по слоям: сначала родитель, потом сам подмодуль. Ответ 503 называет выключенный слой.
- Аппки заводятся каркасом без моделей. Тенантные (`project`, `bpp`) попадают в `TENANT_APPS` только вместе с первой миграцией (задачи A1.1, A1.3).

**Tech Stack:** Django 5.2.7, pytest-django (Postgres на `:55432`), React + vitest.

**Spec:** [мастер-план](2026-09-26-bpp-master-plan.md) — §2.1 (аппки), §2.3 (подмодули), §2.4 (узлы прав), §0 (правила работы двух исполнителей).

**Параллельно:** исполнитель B делает свой этап 0 в ветке `new-module-BPP-ruslan` ([план B](2026-09-26-bpp-stage0-executor-b.md)). Файлы не пересекаются.

**Handoff в конце этапа:**
1. Запушить ветку.
2. Написать B, что готовы A0.2 (аппка `bpp` и её подмодули) и A0.3 (сторожа).
3. Смерджить к себе `origin/new-module-BPP-ruslan`: `git fetch origin && git merge origin/new-module-BPP-ruslan`.
4. Прогнать полный набор сторожей (шаг A0.3-8).

---

## Global Constraints

- Интерпретатор — корневой `.venv`. Все backend-команды — из `backend/`: `../.venv/Scripts/python.exe -m pytest …`.
- Postgres для тестов: `docker compose -f docker-compose.test-local.yml up -d db` (из корня репозитория). Одновременно — только один прогон pytest на машине.
- Ветки не создавать. Коммитить только файлы своей задачи (`git add <файлы>`).
- Межаппный доступ — только `apps.<x>.interface`. Первая строка каждой функции `interface.py` — `require_service("<сервис>")`.
- Имена подмодулей — `bpp_<часть>`. Родитель подмодуля обязан быть в `KNOWN_SERVICES`, вложенность одна.
- Новые строки фронта — `t('<ключ>', 'Русский текст')`, переводы не добавлять.

## Review Focus

1. **Гейт по первому совпадению.** `ServiceGateMiddleware` берёт первый подходящий префикс. Если префикс `/api/bpp/` окажется выше `/api/bpp/v1/budgets`, рубильник `bpp_budget` молча перестанет работать. Тест — A0.2-1 (`test_submodule_prefixes_precede_their_module_prefix`).
2. **503 называет не тот слой.** Выключен `bpp`, а ответ говорит `bpp_budget` — оператор включает `bpp_budget`, и ничего не происходит. Тест — A0.1-1 (`test_http_gate_names_the_disabled_layer`) и A0.2-1 (`test_bpp_switch_closes_every_submodule_and_names_itself`).
3. **Подмодуль в редакторе ролей.** Если подмодуль попадёт в `KNOWN_SERVICES`, в редакторе ролей появится пустой модуль, на который можно выдать права без смысла. Тест — A0.2-1 (`test_bpp_nodes_are_in_the_access_registry`: имён подмодулей в реестре нет).
4. **Сторож слепнет к новому файлу.** Ручка в `views_budget.py` без `level=` проходит сторожей, читавших только `views.py`. Тест — A0.3-1.
5. **`platform-admin` без новых модулей.** Роль-минимум теряет полный доступ, и `test_bootstrap` падает у соседа после мерджа. Тест — существующий `apps/access/tests/test_bootstrap.py::test_seeded_role_grants_admin_on_every_module` после A0.2.

---

## Task A0.1: Реестр подмодулей

**Files:**
- Modify: `backend/apps/core/models.py` (после `KNOWN_SERVICES`)
- Modify: `backend/apps/core/services.py` (импорт, `service_status`, `require_service`, новая `disabled_layer`)
- Modify: `backend/htqweb/middleware/service_gate.py` (`ServiceGateMiddleware.__call__`)
- Modify: `backend/apps/core/management/commands/service.py`
- Modify: `backend/apps/companies/services/module_service.py`
- Modify: `backend/apps/companies/schemas.py` (`ModuleRead`)
- Modify: `backend/apps/companies/tests/test_module_service.py`, `backend/apps/companies/tests/test_api_modules_memberships.py:54`
- Create: `backend/apps/core/tests/test_submodules.py`
- Modify: `frontend/src/types/companies.ts` (`CompanyModule`), `frontend/src/components/companies/CompanyModulesPanel.tsx`, `frontend/src/components/companies/CompanyPanels.test.tsx`

**Interfaces:**
- Produces:
  - `apps.core.models.KNOWN_SUBMODULES: dict[str, str]`;
  - `apps.core.services.disabled_layer(name: str) -> tuple[str, str] | None` — `(имя выключенного слоя, сообщение)`;
  - `service_status(name)` и `require_service(name)` понимают подмодули;
  - `ServiceDisabled.service` — имя выключенного слоя;
  - строка модуля компании получает ключ `"parent": str | None`.

- [ ] **Step 1: Написать падающие тесты бэкенда**

Create `backend/apps/core/tests/test_submodules.py`:

```python
"""Рубильники подмодулей: подмодуль гаснет вместе с родителем и сам по себе.

Реестр подмодулей — ``apps.core.models.KNOWN_SUBMODULES``. Здесь он
подменяется образцом ``probe_sub`` под существующим сервисом ``tasks``:
тесты проверяют механизм, а не список подмодулей БЗО (его проверяет
``test_bpp_scaffold.py``).
"""

import pytest
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import Client

from apps.companies.models import Company, CompanyKind, CompanyModule
from apps.companies.services import module_service
from apps.core.models import KNOWN_SERVICES, KNOWN_SUBMODULES, ServiceStatus
from apps.core.services import ServiceDisabled, disabled_layer, require_service, service_status
from htqweb.tenancy.db import use_company

PROBE = "probe_sub"


@pytest.fixture
def probe(monkeypatch):
    monkeypatch.setitem(KNOWN_SUBMODULES, PROBE, "tasks")
    return PROBE


@pytest.fixture
def kz(db):
    return Company.objects.create(slug="htq-kz", name="KZ", kind=CompanyKind.REGIONAL)


def _off(name: str, message: str = "Выключено") -> None:
    ServiceStatus.objects.update_or_create(
        app_label=name, defaults={"enabled": False, "message": message})
    cache.delete(f"svc-status:{name}")


def test_every_submodule_hangs_off_a_known_service():
    for sub, parent in KNOWN_SUBMODULES.items():
        assert parent in KNOWN_SERVICES, sub
        assert sub not in KNOWN_SERVICES, sub


@pytest.mark.django_db
def test_submodule_is_enabled_by_default(probe):
    assert service_status(probe) == (True, "")
    assert disabled_layer(probe) is None


@pytest.mark.django_db
def test_parent_switch_turns_the_submodule_off(probe):
    _off("tasks", "Регламент")
    assert service_status(probe) == (False, "Регламент")
    assert disabled_layer(probe) == ("tasks", "Регламент")
    with pytest.raises(ServiceDisabled) as exc:
        require_service(probe)
    # Оператор должен видеть, ЧТО включать: включать сам подмодуль бесполезно.
    assert exc.value.service == "tasks"


@pytest.mark.django_db
def test_own_switch_turns_off_only_the_submodule(probe):
    _off(probe, "Подмодуль закрыт")
    assert disabled_layer(probe) == (probe, "Подмодуль закрыт")
    assert service_status("tasks") == (True, "")


@pytest.mark.django_db
def test_company_switch_of_the_submodule(probe, kz):
    CompanyModule.objects.create(company=kz, app_label=probe, enabled=False,
                                 message="Не подключён")
    with use_company("htq-kz"):
        assert disabled_layer(probe) == (probe, "Не подключён")
    # Вне контекста компании действует только глобальный слой.
    assert service_status(probe) == (True, "")


@pytest.mark.django_db
def test_company_switch_of_the_parent_turns_the_submodule_off(probe, kz):
    CompanyModule.objects.create(company=kz, app_label="tasks", enabled=False,
                                 message="Нет задач")
    with use_company("htq-kz"):
        assert disabled_layer(probe) == ("tasks", "Нет задач")


@pytest.mark.django_db
def test_http_gate_names_the_disabled_layer(probe, monkeypatch):
    from htqweb.middleware import service_gate

    monkeypatch.setattr(service_gate, "PREFIX_TO_SERVICE",
                        {"/api/tasks/v1/probe": probe, **service_gate.PREFIX_TO_SERVICE})
    _off(probe)
    response = Client().get("/api/tasks/v1/probe/x")
    assert response.status_code == 503
    assert response.json()["service"] == probe
    # Родитель жив: его ручки доходят до авторизации вьюхи.
    assert Client().get("/api/tasks/v1/tasks/").status_code == 401

    _off("tasks")
    assert Client().get("/api/tasks/v1/probe/x").json()["service"] == "tasks"


@pytest.mark.django_db
def test_service_command_accepts_a_submodule(probe):
    call_command("service", probe, "--off")
    assert ServiceStatus.objects.get(app_label=probe).enabled is False


@pytest.mark.django_db
def test_service_command_still_rejects_unknown_names(probe):
    with pytest.raises(CommandError):
        call_command("service", "probe_sub_typo", "--off")


@pytest.mark.django_db
def test_company_modules_list_submodules_right_under_their_parent(probe, kz):
    rows = module_service.list_modules(kz)
    labels = [row["app_label"] for row in rows]
    assert labels[labels.index("tasks") + 1] == probe
    assert rows[labels.index(probe)] == {
        "app_label": probe, "enabled": True, "message": "", "is_core": False,
        "parent": "tasks",
    }
    assert all(row["parent"] is None for row in rows if row["app_label"] in KNOWN_SERVICES)


@pytest.mark.django_db
def test_company_submodule_can_be_switched(probe, kz):
    row = module_service.set_module(kz, probe, enabled=False, message="Позже")
    assert (row["parent"], row["enabled"]) == ("tasks", False)
    assert CompanyModule.objects.filter(company=kz, app_label=probe, enabled=False).exists()
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `../.venv/Scripts/python.exe -m pytest apps/core/tests/test_submodules.py -q`
Expected: ошибка сбора — `ImportError: cannot import name 'KNOWN_SUBMODULES'`.

- [ ] **Step 3: Реестр подмодулей**

В `backend/apps/core/models.py` сразу после списка `KNOWN_SERVICES` добавить:

```python

# Подмодули с собственным рубильником: подмодуль → родительский сервис из
# KNOWN_SERVICES (вложенность одна). Подмодуль гаснет вместе с родителем
# (apps.core.services.disabled_layer). В реестр прав подмодули не входят
# намеренно: права выдаются на модуль целиком, подмодуль — только
# выключатель, и редактор ролей не должен показывать пустые модули.
KNOWN_SUBMODULES: dict[str, str] = {}
```

- [ ] **Step 4: Статус по слоям**

В `backend/apps/core/services.py` заменить импорт `from .models import ServiceStatus` на:

```python
from .models import KNOWN_SUBMODULES, ServiceStatus
```

Затем заменить всё от `def service_status(name: str) -> tuple[bool, str]:` до конца файла на:

```python
def _own_status(name: str) -> tuple[bool, str]:
    """Статус одного слоя: глобальный рубильник И рубильник текущей компании.

    Два независимых слоя. Глобальный (ServiceStatus) гасит домен на всей
    платформе; компанейский (CompanyModule) — у одной компании.

    Компанейский слой живёт ЗДЕСЬ, а не только в require_service, потому
    что HTTP-гейт (ServiceGateMiddleware) спрашивает статус через эту же
    цепочку. Будь проверка только в require_service, запрос к /api/<домен>/ у
    компании с выключенным модулем прошёл бы гейт насквозь: вьюхи зовут
    свои сервисы напрямую, а не через interface, и require_service для
    собственных эндпоинтов аппки может не сработать вовсе.

    Кэш не объединяется: глобальный ключ svc-status:{name} остаётся
    честно глобальным (иначе он отравился бы значением одной компании),
    а компанейский слой уже кэшируется внутри module_enabled по ключу со
    слагом компании.
    """
    enabled, message = _global_status(name)
    if not enabled:
        return (False, message)
    return _company_module_status(name)


def disabled_layer(name: str) -> tuple[str, str] | None:
    """Первый выключенный слой домена: ``(имя, сообщение)`` или ``None``.

    У подмодуля (``KNOWN_SUBMODULES``) слоя два, и родитель проверяется
    первым: выключенный модуль гасит все свои подмодули, какими бы ни были
    их собственные рубильники. Имя слоя уходит в поле ``service`` ответа 503
    и в ``ServiceDisabled.service`` — оператор должен видеть, ЧТО включать:
    при выключенном ``bpp`` включать ``bpp_budget`` бесполезно.
    """
    parent = KNOWN_SUBMODULES.get(name)
    for layer in ((parent, name) if parent else (name,)):
        enabled, message = _own_status(layer)
        if not enabled:
            return (layer, message)
    return None


def service_status(name: str) -> tuple[bool, str]:
    """Статус домена или подмодуля с учётом всех слоёв (см. ``disabled_layer``)."""
    off = disabled_layer(name)
    return (True, "") if off is None else (False, off[1])


def service_enabled(name: str) -> bool:
    return service_status(name)[0]


def require_service(name: str) -> None:
    off = disabled_layer(name)
    if off is not None:
        raise ServiceDisabled(*off)
```

- [ ] **Step 5: HTTP-гейт называет выключенный слой**

В `backend/htqweb/middleware/service_gate.py`:

1. Заменить импорт:

```python
from apps.core.services import disabled_layer, disabled_payload
```

2. Заменить тело `ServiceGateMiddleware.__call__`:

```python
    def __call__(self, request):
        for prefix, name in PREFIX_TO_SERVICE.items():
            if request.path.startswith(prefix):
                off = disabled_layer(name)
                if off is not None:
                    return JsonResponse(disabled_payload(*off), status=503)
                break
        return self.get_response(request)
```

- [ ] **Step 6: Команда `service` принимает подмодули**

В `backend/apps/core/management/commands/service.py`:

1. Заменить импорт:

```python
from apps.core.models import KNOWN_SERVICES, KNOWN_SUBMODULES, ServiceStatus
```

2. Заменить проверку имени в `handle`:

```python
        name = options["name"]
        known = [*KNOWN_SERVICES, *KNOWN_SUBMODULES]
        if name not in known:
            raise CommandError(
                f"Неизвестный сервис '{name}'. Допустимые имена: "
                f"{', '.join(known)}"
            )
```

- [ ] **Step 7: Модули компании видят подмодули**

В `backend/apps/companies/services/module_service.py`:

1. Заменить импорт:

```python
from apps.core.models import KNOWN_SERVICES, KNOWN_SUBMODULES
```

2. Заменить `_row`, `list_modules` и начало `set_module`:

```python
def _row(app_label: str, stored: CompanyModule | None) -> dict:
    return {
        "app_label": app_label,
        "enabled": True if stored is None else stored.enabled,
        "message": "" if stored is None else stored.message,
        "is_core": app_label in CORE_MODULES,
        # Подмодуль (apps.core.models.KNOWN_SUBMODULES) гаснет вместе с
        # родителем — экрану нужно знать, под чьим рубильником он стоит.
        "parent": KNOWN_SUBMODULES.get(app_label),
    }


def list_modules(company: Company) -> list[dict]:
    """Модули платформы; подмодули — сразу под своим родителем."""
    stored = {m.app_label: m for m in company.modules.all()}
    rows = []
    for name in KNOWN_SERVICES:
        rows.append(_row(name, stored.get(name)))
        rows.extend(_row(sub, stored.get(sub))
                    for sub, parent in KNOWN_SUBMODULES.items() if parent == name)
    return rows


def set_module(company: Company, app_label: str, *, enabled: bool,
               message: str | None = None) -> dict:
    if app_label not in KNOWN_SERVICES and app_label not in KNOWN_SUBMODULES:
        raise UnknownModule(app_label)
```

Остаток `set_module` не менять.

3. В `backend/apps/companies/schemas.py` в `ModuleRead` добавить поле после `is_core: bool`:

```python
    parent: str | None = None
```

- [ ] **Step 8: Поправить старые тесты под новое поле `parent`**

В `backend/apps/companies/tests/test_module_service.py`:

```python
@pytest.mark.django_db
def test_list_covers_every_known_service_and_defaults_to_enabled(company):
    rows = module_service.list_modules(company)
    assert [r["app_label"] for r in rows if r["parent"] is None] == list(KNOWN_SERVICES)
    assert all(r["enabled"] for r in rows)
    assert {r["app_label"] for r in rows if r["is_core"]} == set(CORE_MODULES) & set(KNOWN_SERVICES)


@pytest.mark.django_db
def test_disable_writes_row_and_interface_sees_it(company):
    row = module_service.set_module(company, "tasks", enabled=False, message="Пока закрыто")
    assert row == {"app_label": "tasks", "enabled": False, "message": "Пока закрыто",
                   "is_core": False, "parent": None}
    cache.clear()  # interface кэширует ответ на 5 секунд
    assert interface.module_enabled("htq", "tasks") == (False, "Пока закрыто")
```

В `backend/apps/companies/tests/test_api_modules_memberships.py:54`:

```python
    assert tasks == {"app_label": "tasks", "enabled": True, "message": "",
                     "is_core": False, "parent": None}
```

- [ ] **Step 9: Прогнать тесты бэкенда**

Run: `../.venv/Scripts/python.exe -m pytest apps/core/tests/test_submodules.py apps/core/tests/test_service_gate.py apps/core/tests/test_company_module_gate.py apps/core/tests/test_service_command.py apps/companies/tests/test_module_service.py apps/companies/tests/test_api_modules_memberships.py apps/core/tests/test_invariants.py -q`
Expected: всё PASS.

- [ ] **Step 10: Падающий тест экрана модулей**

В `frontend/src/components/companies/CompanyPanels.test.tsx` внутрь `describe('CompanyModulesPanel', …)` после существующего `it(...)` добавить:

```tsx
  it('подмодуль выключенного модуля не переключается и стоит под родителем', async () => {
    modules.mockResolvedValue({ data: [
      { app_label: 'bpp', enabled: false, message: '', is_core: false, parent: null },
      { app_label: 'bpp_budget', enabled: true, message: '', is_core: false, parent: 'bpp' },
    ] });
    renderWithProviders(<CompanyModulesPanel slug="htq" canEdit />);
    const sub = await screen.findByRole('switch', { name: 'bpp_budget' });
    expect(sub).toBeDisabled();
    expect(sub).not.toBeChecked();
    expect(screen.getByText(/выключен вместе с bpp/)).toBeInTheDocument();
  });
```

Run (из `frontend/`): `npx vitest run src/components/companies/CompanyPanels.test.tsx`
Expected: новый тест FAIL — переключатель подмодуля доступен.

- [ ] **Step 11: Экран модулей**

В `frontend/src/types/companies.ts` в `CompanyModule` добавить после `is_core: boolean;`:

```ts
  /** Родительский модуль подмодуля (`apps.core.models.KNOWN_SUBMODULES`); null — модуль. */
  parent?: string | null;
```

В `frontend/src/components/companies/CompanyModulesPanel.tsx`:
1. Добавить импорт `import { cn } from '@/lib/utils';`.
2. Заменить `<ul …>…</ul>` на:

```tsx
      <ul className="divide-y rounded-lg border">
        {(query.data ?? []).map((m) => {
          // Подмодуль гаснет вместе с родителем: пока родитель выключен,
          // собственный рубильник подмодуля ничего не решает.
          const parent = m.parent ? query.data?.find((row) => row.app_label === m.parent) : undefined;
          const parentOff = parent !== undefined && !parent.enabled;
          return (
            <li key={m.app_label} className={cn('flex items-center justify-between px-3 py-2 text-sm', m.parent && 'pl-8')}>
              <span className="font-mono">
                {m.parent && <span aria-hidden className="mr-1 text-muted-foreground">↳</span>}
                {m.app_label}
                {m.is_core && <span className="ml-2 text-xs text-muted-foreground">{t('companies.modules.core', 'ядро')}</span>}
                {parentOff && (
                  <span className="ml-2 font-sans text-xs text-muted-foreground">
                    {t('companies.modules.parentOff', 'выключен вместе с {{parent}}', { parent: m.parent })}
                  </span>
                )}
              </span>
              <Switch aria-label={m.app_label} checked={m.enabled && !parentOff}
                disabled={m.is_core || parentOff || !canEdit || mutation.isPending}
                onCheckedChange={(enabled) => mutation.mutate({ appLabel: m.app_label, enabled })} />
            </li>
          );
        })}
      </ul>
```

Run: `npx vitest run src/components/companies/CompanyPanels.test.tsx`
Expected: PASS (оба теста панели модулей).

- [ ] **Step 12: Коммит**

```bash
git add backend/apps/core/models.py backend/apps/core/services.py backend/htqweb/middleware/service_gate.py backend/apps/core/management/commands/service.py backend/apps/companies/services/module_service.py backend/apps/companies/schemas.py backend/apps/companies/tests/test_module_service.py backend/apps/companies/tests/test_api_modules_memberships.py backend/apps/core/tests/test_submodules.py frontend/src/types/companies.ts frontend/src/components/companies/CompanyModulesPanel.tsx frontend/src/components/companies/CompanyPanels.test.tsx
git commit -m "feat(core): рубильники подмодулей — KNOWN_SUBMODULES, статус по слоям, экран модулей"
```

---

## Task A0.2: Регистрация аппок `project`, `refdata`, `notifications`, `bpp`

**Files:**
- Create: `backend/apps/{project,refdata,notifications,bpp}/__init__.py`, `apps.py`, `interface.py`, `urls.py`, `views.py`
- Create: `backend/apps/{project,refdata,bpp}/access_functions.py`, `backend/apps/{project,bpp}/holding.py`
- Create: `backend/apps/access/migrations/0013_platform_admin_bpp_modules.py`
- Create: `backend/apps/core/tests/test_bpp_scaffold.py`
- Modify: `backend/htqweb/settings/base.py` (`INSTALLED_APPS`), `backend/apps/core/models.py`, `backend/apps/core/services.py` (`CORE_MODULES`), `backend/htqweb/middleware/service_gate.py` (`PREFIX_TO_SERVICE`), `backend/apps/access/self_service.py` (`TRANSLATED_APPS`, `SELF_SERVICE`)
- Modify: `frontend/src/api/endpoints.ts`, `frontend/vite.config.ts`
- Modify: `STRUCTURE.md` §3.1, `CLAUDE.md` (пункт «Apps are disableable»), `API.md` (таблица маршрутов)

**Interfaces:**
- Consumes: `KNOWN_SUBMODULES`, `disabled_layer` (A0.1).
- Produces:
  - сервисы `project`, `refdata`, `notifications`, `bpp`; первые три — в `CORE_MODULES`;
  - подмодули `bpp_budget`, `bpp_requests`, `bpp_agreements`, `bpp_invoices`, `bpp_bank`, `bpp_alternatives`, `bpp_accountable` и их префиксы (мастер-план §2.1);
  - узлы реестра прав (мастер-план §2.4);
  - `apiPath('project' | 'refdata' | 'notifications' | 'bpp', …)` на фронте.

- [ ] **Step 1: Написать падающий тест каркаса**

Create `backend/apps/core/tests/test_bpp_scaffold.py`:

```python
"""Модуль БЗО, этап 0: четыре новые аппки установлены, смонтированы и
отключаемы; подмодули bpp гейтятся раньше модуля и называют выключенный слой.

Мастер-план: docs/plans/2026-09-26-bpp-master-plan.md, §2.1 и §2.3.
"""

from __future__ import annotations

import pytest
from django.apps import apps as django_apps
from django.core.cache import cache
from django.test import Client
from django.urls import get_resolver
from django.urls.resolvers import URLResolver

from apps.access import registry
from apps.core.models import KNOWN_SERVICES, KNOWN_SUBMODULES, ServiceStatus
from apps.core.services import CORE_MODULES
from htqweb.middleware.service_gate import PREFIX_TO_SERVICE

SCAFFOLD = [
    ("project", "api/project/v1/"),
    ("refdata", "api/refdata/v1/"),
    ("notifications", "api/notifications/v1/"),
    ("bpp", "api/bpp/v1/"),
]

SUBMODULE_PATHS = [
    ("bpp_budget", "/api/bpp/v1/budgets/x"),
    ("bpp_requests", "/api/bpp/v1/requests/x"),
    ("bpp_requests", "/api/bpp/v1/plan/x"),
    ("bpp_agreements", "/api/bpp/v1/agreements/x"),
    ("bpp_invoices", "/api/bpp/v1/invoices/x"),
    ("bpp_bank", "/api/bpp/v1/bank/x"),
    ("bpp_alternatives", "/api/bpp/v1/alternatives/x"),
    ("bpp_alternatives", "/api/bpp/v1/kpi/x"),
    ("bpp_accountable", "/api/bpp/v1/accountable/x"),
]


def _off(name: str) -> None:
    ServiceStatus.objects.update_or_create(app_label=name, defaults={"enabled": False})
    cache.delete(f"svc-status:{name}")


@pytest.mark.parametrize("label,prefix", SCAFFOLD)
def test_app_is_installed_registered_and_mounted(label, prefix):
    config = django_apps.get_app_config(label)
    assert config.name == f"apps.{label}"
    assert config.API_PREFIX == prefix
    assert label in KNOWN_SERVICES
    mounted = {str(entry.pattern) for entry in get_resolver().url_patterns
               if isinstance(entry, URLResolver)}
    assert prefix in mounted


@pytest.mark.django_db
@pytest.mark.parametrize("label,prefix", SCAFFOLD)
def test_app_404s_when_enabled_and_503s_when_disabled(label, prefix):
    assert Client().get(f"/{prefix}__probe__").status_code == 404
    _off(label)
    body = Client().get(f"/{prefix}__probe__").json()
    assert (body["code"], body["service"]) == ("service_disabled", label)


def test_platform_parts_are_core_and_bpp_is_switchable_per_company():
    assert {"project", "refdata", "notifications"} <= CORE_MODULES
    assert "bpp" not in CORE_MODULES


def test_every_bpp_submodule_is_declared_and_gated():
    assert set(KNOWN_SUBMODULES) == {sub for sub, _path in SUBMODULE_PATHS}
    assert set(KNOWN_SUBMODULES.values()) == {"bpp"}
    assert set(KNOWN_SUBMODULES) <= set(PREFIX_TO_SERVICE.values())


def test_submodule_prefixes_precede_their_module_prefix():
    """Гейт берёт ПЕРВОЕ совпадение: префикс модуля выше префикса подмодуля
    молча отключил бы рубильник подмодуля."""
    order = list(PREFIX_TO_SERVICE)
    for prefix, name in PREFIX_TO_SERVICE.items():
        parent = KNOWN_SUBMODULES.get(name)
        if parent is None:
            continue
        covering = [p for p, n in PREFIX_TO_SERVICE.items()
                    if n == parent and prefix.startswith(p)]
        assert covering, f"{prefix}: нет префикса родителя {parent}"
        assert all(order.index(prefix) < order.index(p) for p in covering), prefix


@pytest.mark.django_db
@pytest.mark.parametrize("sub,path", SUBMODULE_PATHS)
def test_submodule_switch_closes_only_its_paths(sub, path):
    _off(sub)
    response = Client().get(path)
    assert response.status_code == 503
    assert response.json()["service"] == sub
    assert Client().get("/api/bpp/v1/dashboard/x").status_code == 404


@pytest.mark.django_db
def test_bpp_switch_closes_every_submodule_and_names_itself():
    _off("bpp")
    for _sub, path in SUBMODULE_PATHS:
        assert Client().get(path).json()["service"] == "bpp", path


def test_bpp_nodes_are_in_the_access_registry():
    paths = registry.paths()
    for node in ("bpp", "bpp.budgets", "bpp.invoices.decision", "bpp.articles.supply",
                 "bpp.articles.pm", "project.projects", "refdata.articles", "notifications"):
        assert node in paths, node
    # Подмодуль — выключатель, а не модуль прав.
    assert not set(KNOWN_SUBMODULES) & paths
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `../.venv/Scripts/python.exe -m pytest apps/core/tests/test_bpp_scaffold.py -q`
Expected: FAIL — `LookupError: No installed app with label 'project'`.

- [ ] **Step 3: Каркас аппки `project`**

`backend/apps/project/__init__.py` — пустой файл.

`backend/apps/project/apps.py`:

```python
from django.apps import AppConfig


class ProjectConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.project"
    verbose_name = "Проекты"
    # Сущность «Проект» модуля БЗО (docs/plans/2026-09-26-bpp-master-plan.md,
    # D-02). Тенантная: в settings.TENANT_APPS попадает вместе с первой
    # миграцией (задача A1.3) — migrate_companies прогоняет каждую аппку
    # списка, и аппка без миграций уронила бы прогон.
    API_PREFIX = "api/project/v1/"
```

`backend/apps/project/interface.py`:

```python
"""Межаппный интерфейс «Проекта».

Функции появляются в задаче A1.3 (сигнатуры — мастер-план §2.6). Каждая
первой строкой зовёт ``require_service("project")``.
"""
```

`backend/apps/project/urls.py`:

```python
"""Маршруты /api/project/v1/ — наполняются в задаче A1.3."""

urlpatterns: list = []
```

`backend/apps/project/views.py`:

```python
"""Ручки «Проекта» — задача A1.3. Каждая под ``api_view(module="project", level=…)``."""
```

`backend/apps/project/access_functions.py`:

```python
"""Функции «Проекта» для реестра прав (``apps.access.registry``)."""

FUNCTIONS = (
    ("project.projects", "Проекты"),
    ("project.members", "Участники проектов"),
)
```

`backend/apps/project/holding.py`:

```python
"""Модели «Проекта» для сводных представлений холдинга.

Пусто, пока моделей нет (задача A1.3). См. apps/tasks/holding.py про
соглашение автообнаружения.
"""

HOLDING_MODELS = ()
```

- [ ] **Step 4: Каркас аппки `refdata`**

`backend/apps/refdata/__init__.py` — пустой файл.

`backend/apps/refdata/apps.py`:

```python
from django.apps import AppConfig


class RefdataConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.refdata"
    verbose_name = "Справочники"
    # Общие справочники модуля БЗО (страны, валюты, курсы, НДС, МРП, единицы
    # измерения, статьи): одна копия на группу в схеме public, правят только
    # роли управляющей компании (мастер-план, D-03).
    API_PREFIX = "api/refdata/v1/"
```

`backend/apps/refdata/interface.py`:

```python
"""Межаппный интерфейс справочников.

Функции появляются в задаче A1.2 (сигнатуры — мастер-план §2.6). Каждая
первой строкой зовёт ``require_service("refdata")``.
"""
```

`backend/apps/refdata/urls.py`:

```python
"""Маршруты /api/refdata/v1/ — наполняются в задаче A1.2."""

urlpatterns: list = []
```

`backend/apps/refdata/views.py`:

```python
"""Ручки справочников — задача A1.2. Каждая под ``api_view(module="refdata", level=…)``."""
```

`backend/apps/refdata/access_functions.py`:

```python
"""Функции справочников для реестра прав (``apps.access.registry``).

Правка разрешена только в управляющей компании — это проверяет сервис
(``refdata.interface.can_edit``), а не узел: узел отвечает на вопрос «может
ли роль», компания — «здесь ли».
"""

FUNCTIONS = (
    ("refdata.articles", "Статьи и группы статей"),
    ("refdata.rates", "НДС, МРП и курсы валют"),
    ("refdata.catalogs", "Страны, валюты, единицы измерения"),
)
```

- [ ] **Step 5: Каркас аппки `notifications`**

`backend/apps/notifications/__init__.py` — пустой файл.

`backend/apps/notifications/apps.py`:

```python
from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.notifications"
    verbose_name = "Уведомления"
    # Хранимый центр уведомлений платформы (колокольчик, e-mail, Telegram),
    # схема public (мастер-план, D-24). Ручки — самообслуживание (свои
    # уведомления и свои каналы), поэтому access_functions.py у аппки нет.
    API_PREFIX = "api/notifications/v1/"
```

`backend/apps/notifications/interface.py`:

```python
"""Межаппный интерфейс центра уведомлений.

``notify(...)`` появляется в задаче A1.5 (сигнатура — мастер-план §2.6);
первой строкой зовёт ``require_service("notifications")``.
"""
```

`backend/apps/notifications/urls.py`:

```python
"""Маршруты /api/notifications/v1/ — наполняются в задаче A1.5."""

urlpatterns: list = []
```

`backend/apps/notifications/views.py`:

```python
"""Ручки центра уведомлений — задача A1.5 (самообслуживание, SELF_SERVICE)."""
```

- [ ] **Step 6: Каркас аппки `bpp`**

`backend/apps/bpp/__init__.py` — пустой файл.

`backend/apps/bpp/apps.py`:

```python
from django.apps import AppConfig


class BppConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "apps.bpp"
    verbose_name = "Закупки и оплаты"
    # Модуль БЗО «Бюджет, закупки и оплаты» (docs/plans/2026-09-26-bpp-
    # master-plan.md). Тенантная: в settings.TENANT_APPS — вместе с первой
    # миграцией (задача A1.1). Подмодули с собственными рубильниками —
    # apps.core.models.KNOWN_SUBMODULES; их префиксы — в PREFIX_TO_SERVICE
    # ВЫШЕ префикса модуля.
    API_PREFIX = "api/bpp/v1/"
```

`backend/apps/bpp/interface.py`:

```python
"""Межаппный интерфейс модуля БЗО (для tasks и notifications).

Каждая функция первой строкой зовёт ``require_service("bpp")``.
"""
```

`backend/apps/bpp/urls.py`:

```python
"""Маршруты /api/bpp/v1/.

Подмодуль держит маршруты в ``urls_<подмодуль>.py`` и вьюхи в
``views_<подмодуль>.py`` (импорт ``from . import views_<подмодуль> as views``) —
так у двух исполнителей нет общего файла, а сторожа прав
(``apps/access/tests/test_gate.py``) видят пару ``urls_x.py`` ↔ ``views_x.py``.
Здесь — только ``include`` подмодулей.
"""

urlpatterns: list = []
```

`backend/apps/bpp/views.py`:

```python
"""Общие ручки модуля (история изменений, файлы документа) — задача A1.1."""
```

`backend/apps/bpp/holding.py`:

```python
"""Модели БЗО для сводных представлений холдинга.

Пусто, пока моделей нет. Сводка группы по БЗО — задача A8.1. См.
apps/tasks/holding.py про соглашение автообнаружения.
"""

HOLDING_MODELS = ()
```

`backend/apps/bpp/access_functions.py`:

```python
"""Функции модуля БЗО для реестра прав (``apps.access.registry``).

Узлы из трёх сегментов — операции внутри функции (решение ФД, блокировка
контрагента). Реестр считает их «полями», и глубину они наследуют от
функции-родителя. Поэтому КАЖДАЯ системная роль несёт по ним явную строку
(миграция access/0014, задача A1.4): иначе автор счёта с ``edit`` на
``bpp.invoices`` унаследовал бы решение ФД.

Группы статей (BR-010): ключ узла хранится в самой группе
(``refdata.ArticleGroup.node_key``), и доступ к статьям считается по нему.
"""

_OP = ("edit",)      # операция: право её выполнить
_SEE = ("view",)     # только видимость

FUNCTIONS = (
    ("bpp.budgets", "Бюджеты"),
    ("bpp.budgets.approve", "Утверждение, корректировка и закрытие бюджета", _OP),
    ("bpp.requests", "Заявки на закупку"),
    ("bpp.requests.cancel_approved", "Отмена утверждённой заявки", _OP),
    ("bpp.plan", "План закупок"),
    ("bpp.plan.all", "План закупок: позиции всех исполнителей", _SEE),
    ("bpp.agreements", "Договоры"),
    ("bpp.agreements.terminate", "Исполнение и расторжение договора", _OP),
    ("bpp.invoices", "Счета"),
    ("bpp.invoices.decision", "Решение финансового директора по счёту", _OP),
    ("bpp.invoices.payment", "Оплата: документы, отметки, очередь бухгалтерии", _OP),
    ("bpp.invoices.closing_docs", "Закрывающие документы", _OP),
    ("bpp.bank", "Банковские выписки и сверка"),
    ("bpp.dashboard", "Дашборд оплат", _SEE),
    ("bpp.counterparties", "Контрагенты"),
    ("bpp.counterparties.block", "Блокировка контрагента и метка «Проверенный»", _OP),
    ("bpp.alternatives", "Альтернативные предложения"),
    ("bpp.alternatives.select", "Выбор альтернативы", _OP),
    ("bpp.kpi", "KPI снабжения", ("view", "edit")),
    ("bpp.accountable", "Подотчётные средства"),
    ("bpp.accountable.payment", "Выдача и проведение подотчёта", _OP),
    ("bpp.articles", "Доступ к группам статей", _SEE),
    ("bpp.articles.supply", "Группа статей «Снабжение»", _SEE),
    ("bpp.articles.pm", "Группа статей «Проектное управление»", _SEE),
    ("bpp.settings", "Настройки модуля: счета организации, шаблоны выписок"),
)
```

- [ ] **Step 7: Установить аппки**

В `backend/htqweb/settings/base.py` в `INSTALLED_APPS` после строки `"apps.signoff",` добавить:

```python
    # Модуль БЗО «Бюджет, закупки и оплаты» и его платформенные аппки
    # (docs/plans/2026-09-26-bpp-master-plan.md). project и bpp — тенантные,
    # но в TENANT_APPS попадают вместе с первой миграцией (задачи A1.3, A1.1).
    "apps.refdata",        # справочники, public · /api/refdata/v1/
    "apps.notifications",  # центр уведомлений, public · /api/notifications/v1/
    "apps.project",        # «Проект» · /api/project/v1/
    "apps.bpp",            # закупки и оплаты · /api/bpp/v1/
```

- [ ] **Step 8: Реестр сервисов, ядро, подмодули**

В `backend/apps/core/models.py`:

```python
KNOWN_SERVICES = ["users", "hr", "tasks", "approvals", "cms",
                  "media", "mail", "messenger", "conference", "contracts",
                  "signoff", "companies", "access",
                  "project", "refdata", "notifications", "bpp"]
```

и заменить `KNOWN_SUBMODULES: dict[str, str] = {}` на:

```python
KNOWN_SUBMODULES: dict[str, str] = {
    "bpp_budget": "bpp",
    "bpp_requests": "bpp",        # заявки и план закупок
    "bpp_agreements": "bpp",
    "bpp_invoices": "bpp",
    "bpp_bank": "bpp",
    "bpp_alternatives": "bpp",    # альтернативы и KPI
    "bpp_accountable": "bpp",
}
```

В `backend/apps/core/services.py`:

```python
CORE_MODULES = frozenset({"users", "companies", "core", "hr", "messenger",
                          "media", "cms", "access",
                          # Платформенные аппки модуля БЗО: «Проект» нужен и
                          # задачам, справочники и уведомления — всем.
                          "project", "refdata", "notifications"})
```

- [ ] **Step 9: Префиксы HTTP-гейта**

В `backend/htqweb/middleware/service_gate.py` в `PREFIX_TO_SERVICE` после `"/api/access/": "access",` добавить:

```python
    "/api/project/": "project",
    "/api/refdata/": "refdata",
    "/api/notifications/": "notifications",
    # Подмодули БЗО — ВЫШЕ префикса модуля: гейт берёт первое совпадение, а
    # родителя подмодуль проверяет сам (apps.core.services.disabled_layer).
    "/api/bpp/v1/budgets": "bpp_budget",
    "/api/bpp/v1/requests": "bpp_requests",
    "/api/bpp/v1/plan": "bpp_requests",
    "/api/bpp/v1/agreements": "bpp_agreements",
    "/api/bpp/v1/invoices": "bpp_invoices",
    "/api/bpp/v1/bank": "bpp_bank",
    "/api/bpp/v1/alternatives": "bpp_alternatives",
    "/api/bpp/v1/kpi": "bpp_alternatives",
    "/api/bpp/v1/accountable": "bpp_accountable",
    "/api/bpp/": "bpp",
```

- [ ] **Step 10: Аппки под перевёрнутым сторожем прав**

В `backend/apps/access/self_service.py`:

```python
TRANSLATED_APPS: frozenset[str] = frozenset({"access", "users", "hr", "tasks", "companies",
                                             "media_files", "conference", "messenger", "mail",
                                             "cms", "approvals",
                                             "project", "refdata", "notifications", "bpp"})
```

В комментарий над `SELF_SERVICE` дописать четыре новых ключа к перечню аппок. В конец словаря `SELF_SERVICE` перед закрывающей `}` добавить:

```python
    # Модуль БЗО (docs/plans/2026-09-26-bpp-master-plan.md): аппки рождаются
    # под гейтом — каждая ручка с первого дня под api_view(module=…, level=…).
    # Центр уведомлений — самообслуживание: записи "self" заводит задача A1.5
    # вместе с ручками.
    "project": {},
    "refdata": {},
    "notifications": {},
    "bpp": {},
```

- [ ] **Step 11: `platform-admin` на новые модули**

Create `backend/apps/access/migrations/0013_platform_admin_bpp_modules.py`:

```python
"""Модуль БЗО: полный доступ роли-минимума на четыре новых модуля.

``platform-admin`` (0002) несёт полный доступ на КАЖДЫЙ модуль реестра —
иначе права некому выдать. Список модулей в 0002 заморожен литералом, и
новые модули к роли сами не прирастают (см. её докстринг), поэтому
project/refdata/notifications/bpp добавляются здесь явно — тем же приёмом,
что у 0012 (RolePermission, все четыре признака глубины).
"""

from django.db import migrations

ROLE_CODE = "platform-admin"
MODULES = ("project", "refdata", "notifications", "bpp")
_FULL = {"can_view": True, "can_create": True, "can_edit": True, "can_delete": True}


def seed(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    RolePermission = apps.get_model("access", "RolePermission")
    role = Role.objects.filter(code=ROLE_CODE).first()
    if role is None:
        return
    for module in MODULES:
        RolePermission.objects.update_or_create(role=role, node=module, defaults=_FULL)


def unseed(apps, schema_editor):
    RolePermission = apps.get_model("access", "RolePermission")
    RolePermission.objects.filter(role__code=ROLE_CODE, node__in=MODULES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0012_seed_services_admin_role"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
```

- [ ] **Step 12: Прогнать тесты каркаса и сторожей**

Run: `../.venv/Scripts/python.exe -m pytest apps/core/tests/test_bpp_scaffold.py apps/core/tests/test_submodules.py apps/core/tests/test_invariants.py apps/core/tests/test_app_isolation.py apps/core/tests/test_parallel_scaffold.py apps/access/tests/test_gate.py apps/access/tests/test_bootstrap.py apps/access/tests/test_depth.py apps/access/tests/test_me.py apps/companies/tests/test_module_service.py -q`
Expected: всё PASS.

Если `test_gate.py::test_every_url_view_of_translated_apps_carries_api_view` падает с `FileNotFoundError` — значит, у одной из четырёх аппок нет `views.py`. Шаги 3–6 создают его у каждой.

- [ ] **Step 13: Фронт — адреса доменов и dev-прокси**

В `frontend/src/api/endpoints.ts` перед строкой `// Django "core" app (Phase 0)` добавить:

```ts
  // Модуль БЗО «Бюджет, закупки и оплаты» и его платформенные аппки
  // (docs/plans/2026-09-26-bpp-master-plan.md): «Проект», справочники,
  // центр уведомлений, сам модуль.
  project: 'project/v1',
  refdata: 'refdata/v1',
  notifications: 'notifications/v1',
  bpp: 'bpp/v1',
```

Run (из `frontend/`): `npx vitest run src/api/endpoints.proxy.test.ts`
Expected: FAIL — `project → /api/project/`, `refdata → /api/refdata/`, `notifications → /api/notifications/`, `bpp → /api/bpp/`.

В `frontend/vite.config.ts` после блока `"^/api/companies/": { … },` добавить:

```ts
    // Модуль БЗО и его платформенные аппки. Легаси-путей без /v1/ нет — по
    // строке на домен; без неё запрос уйдёт в сам dev-сервер и вернёт
    // index.html (сторож src/api/endpoints.proxy.test.ts).
    "^/api/project/": {
      target: backendTarget,
      changeOrigin: true,
    },
    "^/api/refdata/": {
      target: backendTarget,
      changeOrigin: true,
    },
    "^/api/notifications/": {
      target: backendTarget,
      changeOrigin: true,
    },
    "^/api/bpp/": {
      target: backendTarget,
      changeOrigin: true,
    },
```

Run: `npx vitest run src/api/endpoints.proxy.test.ts`
Expected: PASS.

- [ ] **Step 14: Документация**

1. `STRUCTURE.md` §3.1 — в таблицу после строки **access** добавить:

```markdown
| **project** | `api/project/v1/` | `project` | «Проект» модуля БЗО (с 26.09.2026 — каркас, модели в задаче A1.3): код, вид, страна, руководитель, заказчик, участники. Тенантная; `tasks.Project` ссылается на него строкой `project_ref`. Часть `CORE_MODULES` |
| **refdata** | `api/refdata/v1/` | `refdata` | Общие справочники БЗО в `public` (каркас, модели в A1.2): страны, валюты и курсы НБРК, НДС «страна × дата», МРП, единицы измерения, статьи и группы статей. Правят только роли управляющей компании. Часть `CORE_MODULES` |
| **notifications** | `api/notifications/v1/` | `notifications` | Хранимый центр уведомлений платформы (каркас, модели в A1.5): колокольчик, e-mail, Telegram, выбор каналов, ежедневная сводка ожидающих решений. `public`, ручки — самообслуживание. Часть `CORE_MODULES` |
| **bpp** | `api/bpp/v1/` | `bpp` + подмодули `bpp_*` | ⭐ Модуль БЗО «Бюджет, закупки и оплаты» (каркас с 26.09.2026): бюджет проекта → заявка → план закупок → договор/счёт → решение ФД и оплата → сверка с выпиской; альтернативы и KPI. Тенантная (в `TENANT_APPS` — с первой миграцией). Вьюхи и маршруты — по подмодулям: `views_<подмодуль>.py` + `urls_<подмодуль>.py`. План — [docs/plans/2026-09-26-bpp-master-plan.md](docs/plans/2026-09-26-bpp-master-plan.md) |
```

и после абзаца «Полный список канонических имён сервисов…» добавить:

```markdown
**Подмодули.** У части модуля может быть свой рубильник: `apps.core.models.KNOWN_SUBMODULES` (подмодуль → родитель из `KNOWN_SERVICES`, вложенность одна; сейчас — семь `bpp_*`). Подмодуль гаснет вместе с родителем (`apps.core.services.disabled_layer` проверяет родителя первым), ответ 503 называет выключенный слой. `manage.py service` и экран модулей компании принимают подмодули; префиксы подмодулей стоят в `PREFIX_TO_SERVICE` ВЫШЕ префикса модуля. В реестр прав подмодули не входят — права выдаются на модуль.
```

2. `CLAUDE.md`, пункт «**Apps are disableable at runtime**» — в конец пункта дописать:

```markdown
 A part of an app can carry its own switch: `apps.core.models.KNOWN_SUBMODULES` (submodule → parent service, one level; today the seven `bpp_*`) — `apps.core.services.disabled_layer()` checks the parent first, and the 503 names whichever layer is off. Submodule prefixes must sit ABOVE the module prefix in `PREFIX_TO_SERVICE` (the gate takes the first match; guard `apps/core/tests/test_bpp_scaffold.py`).
```

3. `API.md` — в таблицу маршрутов после строки `/api/conference/v1/*` добавить:

```markdown
| `/api/project/v1/*`                 | `backend` (WSGI)   | «Проект» модуля БЗО: проекты и участники |
| `/api/refdata/v1/*`                 | `backend` (WSGI)   | Общие справочники БЗО: страны, валюты, курсы, НДС, МРП, ед. изм., статьи |
| `/api/notifications/v1/*`           | `backend` (WSGI)   | Центр уведомлений: лента, прочтение, каналы доставки |
| `/api/bpp/v1/*`                     | `backend` (WSGI)   | Модуль БЗО: бюджеты, заявки, план закупок, договоры, счета, выписки, альтернативы, KPI. Подмодули `budgets`/`requests`+`plan`/`agreements`/`invoices`/`bank`/`alternatives`+`kpi`/`accountable` выключаются отдельно |
```

- [ ] **Step 15: Коммит**

```bash
git add backend/apps/project backend/apps/refdata backend/apps/notifications backend/apps/bpp backend/apps/access/migrations/0013_platform_admin_bpp_modules.py backend/apps/core/tests/test_bpp_scaffold.py backend/htqweb/settings/base.py backend/apps/core/models.py backend/apps/core/services.py backend/htqweb/middleware/service_gate.py backend/apps/access/self_service.py frontend/src/api/endpoints.ts frontend/vite.config.ts STRUCTURE.md CLAUDE.md API.md
git commit -m "feat(bpp): каркас аппок project, refdata, notifications, bpp и подмодули bpp_*"
```

---

## Task A0.3: Сторожа прав читают `views*.py` и `urls*.py`

**Files:**
- Modify: `backend/apps/access/tests/test_gate.py` — три цикла `rglob("views.py")` (строки ~175, ~508, ~551) и `test_every_url_view_of_translated_apps_carries_api_view` (~1338–1380)

**Interfaces:**
- Produces (внутри файла тестов):
  - `_view_files(apps_dir: pathlib.Path) -> list[pathlib.Path]`;
  - `_app_of(path: pathlib.Path, apps_dir: pathlib.Path) -> str`;
  - `_url_pairs(app_dir: pathlib.Path) -> list[tuple[pathlib.Path, pathlib.Path, str]]`.
- Соглашение для исполнителей B и A: модуль маршрутов подмодуля `urls_<x>.py` импортирует свои вьюхи как `from . import views_<x> as views` и ссылается на них как `views.<функция>`.

- [ ] **Step 1: Написать падающие тесты помощников**

В `backend/apps/access/tests/test_gate.py` сразу после определения `_OUT_OF_SCOPE_APPS` добавить тесты:

```python
def test_view_files_include_submodule_views_and_skip_tests(tmp_path):
    """Модуль БЗО разносит ручки по ``views_<подмодуль>.py``: сторож, читающий
    только ``views.py``, пропустил бы ручку без ``level=`` молча."""
    apps_dir = tmp_path / "apps"
    for rel in ("x/views.py", "x/views_budget.py", "x/sub/views.py",
                "x/tests/views.py", "x/migrations/views_0001.py", "x/viewsets.py"):
        (apps_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        (apps_dir / rel).write_text("", encoding="utf-8")
    found = _view_files(apps_dir)
    assert [p.relative_to(apps_dir).as_posix() for p in found] == [
        "x/sub/views.py", "x/views.py", "x/views_budget.py"]
    # Аппка — первый сегмент пути, а не имя папки файла.
    assert {_app_of(p, apps_dir) for p in found} == {"x"}


def test_url_pairs_match_urls_and_views_by_suffix(tmp_path):
    app_dir = tmp_path / "x"
    app_dir.mkdir()
    for name, text in (("urls.py", ""), ("views.py", "A = 1\n"),
                       ("urls_budget.py", ""), ("views_budget.py", "B = 2\n"),
                       ("urls_orphan.py", ""), ("urlsfoo.py", "")):
        (app_dir / name).write_text(text, encoding="utf-8")
    pairs = {urls.name: text for urls, _views, text in _url_pairs(app_dir)}
    # Нет парного views_orphan.py — текст пуст, и каждая ручка такого файла
    # честно упадёт как «не найдена»; urlsfoo.py — не модуль маршрутов.
    assert pairs == {"urls.py": "A = 1\n", "urls_budget.py": "B = 2\n", "urls_orphan.py": ""}


def test_submodule_url_view_without_api_view_is_caught():
    urls = ('from . import views_budget as views\n'
            'urlpatterns = [path("budgets", views.budget_list)]\n')
    views = 'def budget_list(request):\n    return {}\n'
    assert [name for name, _why in _url_view_offenders(urls, views)] == ["budget_list"]
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `../.venv/Scripts/python.exe -m pytest apps/access/tests/test_gate.py -q -k "view_files or url_pairs or submodule_url_view"`
Expected: FAIL — `NameError: name '_view_files' is not defined`, то же для `_url_pairs`. Третий тест проходит уже сейчас: он фиксирует соглашение `as views`.

- [ ] **Step 3: Помощники**

Перед добавленными тестами (сразу после `_OUT_OF_SCOPE_APPS`) вставить:

```python
def _view_files(apps_dir: pathlib.Path) -> list[pathlib.Path]:
    """Модули вьюх: ``views.py`` и ``views_<подмодуль>.py`` на любой глубине
    аппки, кроме ``tests/`` и ``migrations/``.

    Модуль БЗО (``apps/bpp``) держит ручки подмодулей в отдельных файлах,
    чтобы у двух исполнителей не было одного файла на весь модуль. Сторожа,
    читавшие только ``views.py``, таких файлов не видели бы вовсе.
    """
    found = []
    for path in sorted(apps_dir.rglob("views*.py")):
        rel = path.relative_to(apps_dir).parts
        if "tests" in rel or "migrations" in rel:
            continue
        if path.stem == "views" or path.stem.startswith("views_"):
            found.append(path)
    return found


def _app_of(path: pathlib.Path, apps_dir: pathlib.Path) -> str:
    """Аппка файла — первый сегмент пути под ``apps/``: ``apps/bpp/sub/views.py``
    принадлежит ``bpp``, а не ``sub``."""
    return path.relative_to(apps_dir).parts[0]


def _url_pairs(app_dir: pathlib.Path) -> list[tuple[pathlib.Path, pathlib.Path, str]]:
    """``(urls, views, текст views)`` для каждого модуля маршрутов аппки.

    Пара — по суффиксу: ``urls.py`` ↔ ``views.py``, ``urls_budget.py`` ↔
    ``views_budget.py``. Модуль маршрутов подмодуля импортирует свои вьюхи
    как ``from . import views_budget as views``, и разбор ``views.<имя>``
    работает для него без изменений. Нет парного модуля — текст пуст, и
    каждая ручка такого ``urls_*.py`` падает как «не найдена».
    """
    pairs = []
    for urls in sorted(app_dir.glob("urls*.py")):
        suffix = urls.stem[len("urls"):]
        if suffix and not suffix.startswith("_"):
            continue
        views = app_dir / f"views{suffix}.py"
        text = views.read_text(encoding="utf-8") if views.exists() else ""
        pairs.append((urls, views, text))
    return pairs
```

Run: `../.venv/Scripts/python.exe -m pytest apps/access/tests/test_gate.py -q -k "view_files or url_pairs or submodule_url_view"`
Expected: PASS.

- [ ] **Step 4: `test_gate_is_not_hung_on_apps_without_a_translation_plan` — на `_view_files`**

Заменить цикл в теле теста:

```python
    backend = pathlib.Path(__file__).resolve().parents[3]
    apps_dir = backend / "apps"
    offenders = []
    for path in _view_files(apps_dir):
        posix_path = path.relative_to(backend).as_posix()
        if posix_path in _GATE_ALLOWLIST:
            continue
        app = _app_of(path, apps_dir)
        if app in _RBAC_APPS or app in _OUT_OF_SCOPE_APPS:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "module=" in line and "api_view" in line:
                offenders.append(f"{posix_path}:{lineno}")
    assert offenders == [], f"гейт навешен раньше времени: {offenders}"
```

- [ ] **Step 5: `test_every_module_gate_names_its_level` и `test_text_parser_sees_every_api_view_call` — на `_view_files`**

В `test_every_module_gate_names_its_level` заменить цикл:

```python
    backend = pathlib.Path(__file__).resolve().parents[3]
    apps_dir = backend / "apps"
    offenders = []
    for path in _view_files(apps_dir):
        if _app_of(path, apps_dir) in _OUT_OF_SCOPE_APPS:
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, name, why in _level_offenders(text):
            offenders.append(f"{path.relative_to(backend).as_posix()}:{lineno} ({name}): {why}")
    assert offenders == [], f"гейт модуля без явного уровня: {offenders}"
```

В `test_text_parser_sees_every_api_view_call` заменить цикл:

```python
    backend = pathlib.Path(__file__).resolve().parents[3]
    apps_dir = backend / "apps"
    mismatched = []
    for path in _view_files(apps_dir):
        if _app_of(path, apps_dir) in _OUT_OF_SCOPE_APPS:
            continue
        text = path.read_text(encoding="utf-8")
        by_text = sum(1 for _call in _iter_api_view_calls(text))
        by_ast = sum(1 for node in ast.walk(ast.parse(text))
                     if isinstance(node, ast.Call) and _base_name(node.func) == "api_view")
        if by_text != by_ast:
            mismatched.append(f"{path.relative_to(backend).as_posix()}: текст {by_text}, ast {by_ast}")
    assert mismatched == [], f"текстовый разбор расходится с ast: {mismatched}"
```

- [ ] **Step 6: URL-сторож — на пары `urls*.py` ↔ `views*.py`**

В `test_every_url_view_of_translated_apps_carries_api_view` заменить тело после докстринга:

```python
    backend = pathlib.Path(__file__).resolve().parents[3]
    offenders = []
    for app in sorted(self_service.TRANSLATED_APPS):
        app_dir = backend / "apps" / app
        exempt = _DISPATCHERS_WITH_OWN_LOGIC.get(app, {})
        outside = _URL_VIEWS_OUTSIDE_API_VIEW.get(app, {})
        seen: set[str] = set()
        siblings = {path.stem: path.read_text(encoding="utf-8")
                    for path in app_dir.glob("*.py")
                    if path.stem != "__init__"
                    and not path.stem.startswith(("views", "urls"))}
        for urls, views, views_text in _url_pairs(app_dir):
            for name, why in _url_view_offenders(urls.read_text(encoding="utf-8"),
                                                 views_text, siblings):
                seen.add(name)
                if name in exempt or name in outside:
                    continue
                offenders.append(f"{urls.relative_to(backend).as_posix()}: {name} — {why}")
            for name, why in _exempt_return_offenders(views_text, set(exempt) & seen):
                offenders.append(f"{views.relative_to(backend).as_posix()}: {why}")
        for name in sorted((set(exempt) | set(outside)) - seen):
            offenders.append(f"исключение устарело: {app}.{name}")
    assert offenders == [], offenders
```

В конец докстринга теста дописать абзац:

```python
    Модуль маршрутов подмодуля (``urls_<x>.py``) проверяется в паре со своим
    ``views_<x>.py`` (``_url_pairs``); ``include(...)`` в ``urls.py`` сторож
    по-прежнему пропускает — подключённый файл проверяется сам, своей парой.
```

- [ ] **Step 7: Прогнать сторож целиком**

Run: `../.venv/Scripts/python.exe -m pytest apps/access/tests/test_gate.py -q`
Expected: всё PASS. Число проверенных файлов не меняется: в репозитории пока нет ни одного `views_*.py`/`urls_*.py`.

- [ ] **Step 8: Handoff — смерджить ветку B и прогнать сторожа**

После того как B запушил этап 0:

```bash
git fetch origin
git merge origin/new-module-BPP-ruslan
```

Run: `../.venv/Scripts/python.exe -m pytest apps/core/tests apps/access/tests apps/signoff/tests apps/companies/tests/test_module_service.py -q`
Expected: всё PASS.

- [ ] **Step 9: Коммит**

```bash
git add backend/apps/access/tests/test_gate.py
git commit -m "test(access): сторожа гейта читают views_*.py и пары urls_*.py ↔ views_*.py"
```

# БЗО, этап 2 — исполнитель A (Санжар, ветка `new-module-BPP-sanzhar`)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать модулю всё общее, на чём исполнитель B строит бюджет, заявку и план закупок:
- **каркас раздела `/bpp`** — меню, реестр, форма документа, формат денег и дат, защита от двойного клика, автосохранение черновика;
- **контрагенты** — справочник с проверкой БИН/ИИН, блокировкой и меткой «Проверенный»;
- **экспорт реестров в xlsx и печать PDF**;
- **экраны справочников, проектов и контрагентов**.

**Architecture:**
- **Подмодули подключаются сами.** `bpp/models/__init__.py` импортирует все модули пакета, `bpp/urls.py` подключает все `urls_*.py`, фронт собирает маршруты и пункты меню из `features/bpp/*/module.tsx` через `import.meta.glob`. Исполнитель B добавляет свои файлы и не правит файлы A.
- **Общие куски документа — на сервере в `services/core/`:**
  - `registry.py` — пагинация, сортировка и фильтры реестра;
  - `export.py` — xlsx;
  - `printing.py` — PDF;
  - `files` и `history` — с реестром проверок доступа по типу владельца.
- **На фронте — в `features/bpp/core/`:**
  - `BppRegistry` — реестр;
  - `BppDocumentShell` — шапка, кнопки по `allowed_actions`, вкладки;
  - хуки `useIdempotentAction`, `useDraftAutosave`, `useUnsavedChangesGuard`;
  - формат `lib/bpp/format.ts`.
- **Контрагенты** — подмодуль A (`models/counterparties.py`, `services/counterparties/`). Для документов B — функции `services/counterparties/lookup.py`: `brief`, `assert_usable` (E-CTR-01), `needs_confirmation`, `record_success`.

**Tech Stack:** Django 5.2.7, PostgreSQL (схема на компанию), Celery, openpyxl 3.1.5 (уже в `requirements.txt`), WeasyPrint (новая зависимость), pytest-django; React 18 + TypeScript + react-query + react-router 6 (`BrowserRouter`), vitest.

**Spec:** [мастер-план](2026-09-26-bpp-master-plan.md): §1 (D-20, D-28, D-29, D-32, D-34, D-39), §2.2, §2.4, §2.6, §2.7, §5 «Этап 2» (A2.1–A2.4); ТЗ [§05](../tz/TZ-budget-procurement-payments-v1.0.md) (интерфейс), §13.2–13.4, §18 (справочники, алгоритм БИН), §19 (реестры), §21, §23, §26.

**Как задачи соотносятся с мастер-планом:**

| Мастер-план | Этот план |
|---|---|
| — (новое, снимает общие файлы между A и B) | задача 1 |
| A2.3 | задачи 2, 3 |
| A2.1 | задачи 4, 5, 6, 7, 8 |
| A2.2 | задачи 9, 10 |
| A2.4 | задача 11 |
| стык этапа 1 | задача 12 |

## Порядок, волны и сведение веток

Ветки сводятся через `new-module-BPP-merge` (CLAUDE.md, «Модуль БЗО»).

- **До старта этапа** в `new-module-BPP-merge` должны быть этапы 0 и 1 обоих исполнителей: строковый `subject_id` (B0.1), флаги маршрута (B1.2), `current_holders` и `pending_for_user` (B1.3). Обе ветки подтягивают `new-module-BPP-merge`. Без этого задачи 7 и 8 (колонка «Сейчас у», вкладка «Согласование») и задача 12 не собираются.
- **Волна 1** — задачи 1–10. Параллельно B делает бэкенд бюджета, заявки, плана и расчёта (B2.1–B2.4).
- **Сведение внутри этапа.** PR обеих веток в `new-module-BPP-merge`, затем обе подтягивают. Второй PR первым подтягивает `new-module-BPP-merge` и добавляет `manage.py makemigrations bpp --merge`: у A и B будут миграции `bpp` от одного родителя `0002_files`. Без merge-миграции `migrate` откажется запускаться («Conflicting migrations»).
- **Волна 2** — задача 11 и задача 12. Параллельно B делает экраны (B2.5) на каркасе задач 4–8.

---

## Global Constraints

- Интерпретатор — корневой `.venv` (Python 3.13.10, Django 5.2.7); команды из `backend/`: `../.venv/Scripts/python.exe …`. Postgres: `docker compose -f docker-compose.test-local.yml up -d db`. **Один прогон pytest за раз на машине.**
- Ветки не создавать. Коммитить только файлы своей задачи, строка соавторства — от агента.
- Межаппный доступ — только `apps.<x>.interface`; первая строка функции `interface.py` и Celery-задачи — `require_service("<сервис>")`; задачи тенантной аппки — `@company_task`.
- Каждая ручка — `api_view(module="bpp", level="read"|"write"|"admin")` с явным уровнем; проверки тоньше модуля — `services/core/permissions.can(request, node, flag)`.
- Ошибки — `DomainError(code, message, fields=…, status=…)`; тексты — из ТЗ §26.1 и правил BR дословно, где они там есть.
- Модели: UUID-ключ, `created_at/by`, `updated_at/by`; документы — `version` (`VersionedModel`) и `check_version` → 409 E-CON-01.
- Записывающие ручки документов и справочников — `api_view(idempotent=True)`; фронт шлёт `Idempotency-Key`.
- Суммы на проводе — строки (`"1250000.00"`), никогда `float`; на экране — `1 250 000,00 KZT`; даты — `ДД.ММ.ГГГГ`, дата-время — `ДД.ММ.ГГГГ ЧЧ:ММ` по Asia/Almaty.
- Новые строки фронта — `t('bpp.<ключ>', 'Русский текст')`, переводы не добавлять. Typecheck — `npx tsc --noEmit -p tsconfig.app.json`: число ошибок не растёт (на 27.09 — 148).
- Ошибки в `onError` — только через `reportApiError(err, 'запасная фраза')` (сторож `src/lib/ux/__tests__/uxContract.test.ts`).
- `bpp` — тенантная: миграции схем компаний — `manage.py migrate_companies`; изменение схемы — только expand.
- `STRUCTURE.md`, `CLAUDE.md`, `API.md` — в той же задаче, что меняет структуру или ручки.

## Review Focus

1. **БИН на границе.**
   - Контрольный разряд на втором проходе с остатком 10 — номер недействителен.
   - ИИН физлица проверяется тем же алгоритмом.
   - Нерезидент — свободный номер до 30 символов, без проверки разряда.
   - Пробелы и дефисы при вводе отбрасываются.
   - Тест — задача 2 (`test_bin_check_*`).
2. **Одновременное создание одного контрагента.** Два запроса с одной парой «страна + номер»: создаётся один, второй получает 422 E-CTR-02 со ссылкой на существующего, а не 500 из `IntegrityError`. Тест — задача 3 (`test_parallel_duplicate_is_422`).
3. **Двойной клик по кнопке документа.**
   - Второй клик не шлёт второй запрос.
   - Повтор после 5xx идёт с тем же `Idempotency-Key`, новое действие — с новым.
   - Тест — задача 5 (`useIdempotentAction.test.ts`).
4. **Граница экспорта.** 10 000 строк — файл сразу, 10 001 — фоном со ссылкой в уведомлении; пустая выборка — файл с заголовками. Тест — задача 9 (`test_export_*`).
5. **Деньги и время.**
   - `"1250000.5"`, `"0"`, `"-15.00"`, `"99999999999999.99"` форматируются без потери копеек (без `float`).
   - Время `2026-09-27T20:30:00Z` показывается как `28.09.2026 01:30` (Asia/Almaty).
   - Тест — задача 5 (`format.test.ts`).

---

## Task 1: Подмодули `bpp` подключаются сами (бэк и фронт)

**Files:**
- Modify: `backend/apps/bpp/models/__init__.py`, `backend/apps/bpp/urls.py`, `backend/apps/bpp/apps.py`
- Create: `backend/apps/bpp/tests/test_autodiscovery.py`
- Create: `frontend/src/features/bpp/modules.ts`, `frontend/src/features/bpp/modules.test.ts`
- Modify: `STRUCTURE.md` (раскладка `apps/bpp`, `features/bpp`)

**Interfaces:**
- Produces: правило для B — модели в `apps/bpp/models/<подмодуль>.py`, маршруты в `apps/bpp/urls_<подмодуль>.py` (переменная `urlpatterns`), экраны в `frontend/src/features/bpp/<подмодуль>/module.tsx` (экспорт `bppModule: BppModule`), регистрация предметов signoff — `apps/bpp/approval_hooks.py` с функцией `register()`. Ни `models/__init__.py`, ни `urls.py`, ни `apps.py`, ни `routeDefinitions.ts` B не правит.
- `BppModule` (TypeScript): `{ key: string; order: number; menu?: { label: string; to: string; icon: LucideIcon; visible: (p: Permissions) => boolean }[]; routes: { path: string; element: React.ReactElement; visible?: (p: Permissions) => boolean }[] }`.

- [ ] **Step 1: Падающие тесты (бэк)**

```python
"""Подмодули bpp подключаются без правки общих файлов (мастер-план §0, правило 5)."""

import importlib
import pkgutil

from django.urls import resolve

import apps.bpp.models as bpp_models
from apps.bpp import urls as bpp_urls


def test_every_models_module_is_imported():
    for info in pkgutil.iter_modules(bpp_models.__path__):
        assert f"apps.bpp.models.{info.name}" in importlib.sys.modules, info.name


def test_every_urls_submodule_is_included():
    """Каждый ``urls_<подмодуль>.py`` пакета попадает в маршруты аппки."""
    import apps.bpp as pkg

    names = {info.name for info in pkgutil.iter_modules(pkg.__path__)
             if info.name.startswith("urls_")}
    included = {getattr(p.urlconf_module, "__name__", "").rsplit(".", 1)[-1]
                for p in bpp_urls.urlpatterns if hasattr(p, "urlconf_module")}
    assert names <= included


def test_history_route_still_resolves():
    assert resolve("/api/bpp/v1/history/bpp.x/1").func.__name__ == "object_history"
```

Пока подмодулей нет, `test_every_urls_submodule_is_included` проходит впустую, поэтому механизм проверяется отдельно подставным модулем:

```python
def test_urls_discovery_picks_a_new_module(monkeypatch):
    import sys
    import types

    from apps.bpp import urls

    probe = types.ModuleType("apps.bpp.urls_probe")
    probe.urlpatterns = []
    monkeypatch.setitem(sys.modules, "apps.bpp.urls_probe", probe)
    monkeypatch.setattr(urls, "_submodule_names", lambda: ["urls_probe"])
    assert any(getattr(p, "urlconf_module", None) is probe for p in urls._submodule_patterns())
```

Run: `../.venv/Scripts/python.exe -m pytest apps/bpp/tests/test_autodiscovery.py -q`
Expected: FAIL — `_submodule_names` нет.

- [ ] **Step 2: Реализация (бэк)**

`backend/apps/bpp/models/__init__.py`:

```python
"""Модели модуля БЗО.

Каждый модуль пакета импортируется автоматически: исполнитель B добавляет
``models/<подмодуль>.py`` и не правит этот файл (мастер-план §0, правило 5).
Имена моделей наружу — через ``from apps.bpp.models.<подмодуль> import …``
или отсюда же (всё, что модуль объявил в ``__all__``).
"""

import importlib
import pkgutil

from .core import AuditLog, BppModel, NumberSequence, VersionedModel  # noqa: F401
from .files import DocumentFile, FileDownload  # noqa: F401

for _info in pkgutil.iter_modules(__path__):
    _module = importlib.import_module(f"{__name__}.{_info.name}")
    for _name in getattr(_module, "__all__", ()):
        globals()[_name] = getattr(_module, _name)
```

`backend/apps/bpp/urls.py`:

```python
"""Маршруты /api/bpp/v1/.

Подмодуль держит маршруты в ``urls_<подмодуль>.py`` (``urlpatterns``) и
вьюхи в ``views_<подмодуль>.py``; этот файл подключает все ``urls_*.py``
пакета сам — у двух исполнителей нет общего файла, а сторожа прав
(``apps/access/tests/test_gate.py``) видят пару ``urls_x.py`` ↔ ``views_x.py``.
"""

import importlib
import pkgutil

from django.urls import include, path

from . import views


def _submodule_names() -> list[str]:
    import apps.bpp as package

    return sorted(info.name for info in pkgutil.iter_modules(package.__path__)
                  if info.name.startswith("urls_"))


def _submodule_patterns() -> list:
    return [path("", include(importlib.import_module(f"apps.bpp.{name}")))
            for name in _submodule_names()]


urlpatterns = [
    path("history/<str:object_type>/<str:object_id>", views.object_history),
    path("history/<str:object_type>/<str:object_id>/", views.object_history),
    *_submodule_patterns(),
]
```

`backend/apps/bpp/apps.py`, в `BppConfig.ready()`:

```python
    def ready(self):
        # Предметы согласования модуля (заявка, договор, счёт…) регистрирует
        # approval_hooks.py исполнителя B; пока файла нет — регистрировать нечего.
        try:
            from . import approval_hooks
        except ModuleNotFoundError as exc:
            if exc.name != "apps.bpp.approval_hooks":
                raise
        else:
            approval_hooks.register()
```

(`ModuleNotFoundError` с чужим именем — сломанный импорт внутри файла B — пробрасывается, а не глотается.) Тест: `test_ready_tolerates_missing_approval_hooks` и `test_ready_reraises_broken_import` (подменить `sys.modules`).

Run: `../.venv/Scripts/python.exe -m pytest apps/bpp/tests apps/access/tests/test_gate.py apps/core/tests/test_invariants.py -q`
Expected: всё PASS (сторож гейта читает `views.py`/`urls.py` как раньше).

- [ ] **Step 3: Падающий тест (фронт)**

Create `frontend/src/features/bpp/modules.test.ts`:

```ts
import { describe, expect, it } from 'vitest';

import { collectModules } from './modules';

const perms = { can: () => true } as never;

describe('collectModules', () => {
  it('сортирует модули по order и склеивает меню и маршруты', () => {
    const mods = collectModules({
      './b/module.tsx': { bppModule: { key: 'b', order: 20, routes: [{ path: 'b', element: null }], menu: [] } },
      './a/module.tsx': { bppModule: { key: 'a', order: 10, routes: [{ path: 'a', element: null }], menu: [] } },
    } as never);
    expect(mods.map((m) => m.key)).toEqual(['a', 'b']);
  });

  it('модуль без экспорта bppModule — ошибка сборки, а не молчаливый пропуск', () => {
    expect(() => collectModules({ './x/module.tsx': {} } as never)).toThrow(/bppModule/);
  });

  it('пункт меню скрыт без права', () => {
    const [mod] = collectModules({
      './a/module.tsx': { bppModule: { key: 'a', order: 1, routes: [], menu: [
        { label: 'A', to: '/bpp/a', icon: () => null, visible: () => false }] } },
    } as never);
    expect(mod.menu?.filter((m) => m.visible(perms))).toEqual([]);
  });
});
```

Run: `npx vitest run src/features/bpp/modules.test.ts` → FAIL (нет `./modules`).

- [ ] **Step 4: Реализация (фронт)**

Create `frontend/src/features/bpp/modules.ts`:

```ts
/**
 * Подмодули раздела «Закупки и оплаты» (/bpp) собираются сами: каждый кладёт
 * `features/bpp/<подмодуль>/module.tsx` с экспортом `bppModule`, и ни меню,
 * ни маршруты раздела править не нужно. Так у двух исполнителей нет общего
 * файла (мастер-план §0, правило 5).
 */
import type { LucideIcon } from 'lucide-react';
import type React from 'react';

import type { Permissions } from '@/hooks/usePermissions';

export interface BppMenuItem {
  label: string;
  to: string;
  icon: LucideIcon | (() => null);
  visible: (p: Permissions) => boolean;
}

export interface BppRoute {
  path: string; // относительно /bpp
  element: React.ReactElement | null;
  visible?: (p: Permissions) => boolean;
}

export interface BppModule {
  key: string;
  order: number;
  menu?: BppMenuItem[];
  routes: BppRoute[];
}

type Loaded = Record<string, { bppModule?: BppModule }>;

export function collectModules(loaded: Loaded): BppModule[] {
  return Object.entries(loaded)
    .map(([file, mod]) => {
      if (!mod.bppModule) throw new Error(`${file}: нет экспорта bppModule`);
      return mod.bppModule;
    })
    .sort((a, b) => a.order - b.order);
}

export const bppModules: BppModule[] = collectModules(
  import.meta.glob<{ bppModule?: BppModule }>('./*/module.tsx', { eager: true }),
);
```

Run: `npx vitest run src/features/bpp/modules.test.ts` → PASS.

- [ ] **Step 5: Документация и коммит**

`STRUCTURE.md`, строка **bpp** и раздел фронта: «подмодули подключаются сами — `models/<подмодуль>.py`, `urls_<подмодуль>.py`, `features/bpp/<подмодуль>/module.tsx`».

```bash
git add backend/apps/bpp/models/__init__.py backend/apps/bpp/urls.py backend/apps/bpp/tests/test_autodiscovery.py frontend/src/features/bpp/modules.ts frontend/src/features/bpp/modules.test.ts STRUCTURE.md
git commit -m "feat(bpp): подмодули подключаются сами — модели, маршруты, экраны раздела"
```

---

## Task 2: Контрагенты — модели и проверки

**Files:**
- Create: `backend/apps/bpp/models/counterparties.py`, `backend/apps/bpp/models/settings.py`, миграция `bpp/0003_counterparties` (makemigrations)
- Create: `backend/apps/bpp/services/counterparties/__init__.py`, `validation.py`
- Create: `backend/apps/bpp/services/core/settings.py`
- Test: `backend/apps/bpp/tests/test_counterparty_validation.py`

**Interfaces:**
- Produces:
  - `models.counterparties`: `Counterparty`, `CounterpartyBankAccount`, `CounterpartyKind` (`legal|ip|individual|nonresident`), `CounterpartyStatus` (`active|blocked|archived`);
  - `models.settings.ModuleSetting(key, value: JSON)`;
  - `services/core/settings.get_setting(key: str, default)`, `set_setting(key, value, *, actor_id)`;
  - `services/counterparties/validation`: `normalize_reg_number(raw) -> str`, `bin_iin_is_valid(value: str) -> bool`, `check_reg_number(kind, country_code, value) -> str` (DomainError E-CTR-03), `iban_is_valid(value) -> bool`, `bic_is_valid(value) -> bool`.

- [ ] **Step 1: Падающие тесты проверок**

```python
"""БИН/ИИН, IBAN и БИК (ТЗ §18)."""

import pytest

from apps.bpp.services.counterparties import validation as v
from htqweb.errors import DomainError


def _with_control(first11: str) -> str:
    """Дописать контрольный разряд по алгоритму РК (для тестовых данных)."""
    digits = [int(c) for c in first11]
    s = sum(d * w for d, w in zip(digits, range(1, 12))) % 11
    if s == 10:
        s = sum(d * w for d, w in zip(digits, [3, 4, 5, 6, 7, 8, 9, 10, 11, 1, 2])) % 11
    assert s != 10
    return first11 + str(s)


@pytest.mark.parametrize("raw", ["990340001234", "12345678901"])
def test_bin_check_rejects_bad_numbers(raw):
    assert v.bin_iin_is_valid(raw) is False


def test_bin_check_accepts_generated_number():
    assert v.bin_iin_is_valid(_with_control("99034000123")) is True


def test_bin_check_second_pass_ten_is_invalid():
    """Остаток 10 и на втором проходе — номер недействителен (ТЗ §18)."""
    for n in range(10**10, 10**10 + 5000):
        first11 = f"{n:011d}"
        digits = [int(c) for c in first11]
        s1 = sum(d * w for d, w in zip(digits, range(1, 12))) % 11
        s2 = sum(d * w for d, w in zip(digits, [3, 4, 5, 6, 7, 8, 9, 10, 11, 1, 2])) % 11
        if s1 == 10 and s2 == 10:
            for last in "0123456789":
                assert v.bin_iin_is_valid(first11 + last) is False
            return
    pytest.fail("не нашлось номера с двумя остатками 10 — расширьте диапазон")


def test_spaces_and_dashes_are_dropped():
    assert v.normalize_reg_number(" 9903 4000-1234 ") == "990340001234"


def test_nonresident_is_free_text_up_to_30():
    assert v.check_reg_number("nonresident", "RU", "ОГРН 1027700132195") == "ОГРН 1027700132195"
    with pytest.raises(DomainError) as exc:
        v.check_reg_number("nonresident", "RU", "X" * 31)
    assert exc.value.code == "E-CTR-03"


def test_kz_legal_entity_needs_valid_bin():
    with pytest.raises(DomainError) as exc:
        v.check_reg_number("legal", "KZ", "990340001234")
    assert exc.value.code == "E-CTR-03"
    assert "контрольн" in exc.value.message


def _iban(bban: str) -> str:
    rearranged = bban + "KZ00"
    number = int("".join(str(int(c, 36)) for c in rearranged))
    return f"KZ{98 - number % 97:02d}{bban}"


def test_iban():
    good = _iban("125KZT5004100100")  # 16 знаков BBAN + 4 = 20
    assert len(good) == 20 and v.iban_is_valid(good)
    assert not v.iban_is_valid(good[:-1] + ("0" if good[-1] != "0" else "1"))
    assert not v.iban_is_valid("KZ" + "1" * 17)


@pytest.mark.parametrize("bic,ok", [("HSBKKZKX", True), ("HSBKKZKXXXX", True),
                                    ("HSBK", False), ("HSBKKZKX12345", False)])
def test_bic(bic, ok):
    assert v.bic_is_valid(bic) is ok
```

Run: `../.venv/Scripts/python.exe -m pytest apps/bpp/tests/test_counterparty_validation.py -q` → FAIL (нет модуля).

- [ ] **Step 2: Проверки**

Create `backend/apps/bpp/services/counterparties/__init__.py` (пустой) и `validation.py`:

```python
"""Проверки реквизитов контрагента (ТЗ §18)."""

from __future__ import annotations

import re

from htqweb.errors import DomainError

KZ_KINDS = {"legal", "ip", "individual"}
_W1 = list(range(1, 12))
_W2 = [3, 4, 5, 6, 7, 8, 9, 10, 11, 1, 2]


def normalize_reg_number(raw: str) -> str:
    return re.sub(r"[\s\-]", "", raw or "")


def bin_iin_is_valid(value: str) -> bool:
    """12 цифр, контрольный разряд по алгоритму РК: веса 1…11, при остатке 10 —
    3…11, 1, 2; остаток 10 во втором проходе — номер недействителен."""
    if not re.fullmatch(r"\d{12}", value or ""):
        return False
    digits = [int(c) for c in value]
    control = sum(d * w for d, w in zip(digits, _W1)) % 11
    if control == 10:
        control = sum(d * w for d, w in zip(digits, _W2)) % 11
        if control == 10:
            return False
    return control == digits[11]


def check_reg_number(kind: str, country_code: str, raw: str) -> str:
    value = normalize_reg_number(raw) if kind in KZ_KINDS and country_code == "KZ" else (raw or "").strip()
    if kind in KZ_KINDS and country_code == "KZ":
        if not bin_iin_is_valid(value):
            raise DomainError(
                "E-CTR-03",
                f"БИН/ИИН «{raw}» недействителен: нужно 12 цифр и верный контрольный разряд. "
                f"Проверьте номер по документам контрагента.",
                fields=[{"field": "reg_number", "message": "неверный БИН/ИИН"}])
        return value
    if not value or len(value) > 30:
        raise DomainError(
            "E-CTR-03", "Регистрационный номер нерезидента: от 1 до 30 символов.",
            fields=[{"field": "reg_number", "message": "от 1 до 30 символов"}])
    return value


def iban_is_valid(value: str) -> bool:
    """KZ + 18 знаков, контрольные цифры по ISO 13616 (mod 97)."""
    value = (value or "").replace(" ", "").upper()
    if not re.fullmatch(r"KZ\d{2}[0-9A-Z]{16}", value):
        return False
    rearranged = value[4:] + value[:4]
    return int("".join(str(int(c, 36)) for c in rearranged)) % 97 == 1


def bic_is_valid(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9]{8}([A-Z0-9]{3})?", (value or "").upper()))
```

Run: → PASS.

- [ ] **Step 3: Модели и настройки модуля**

Create `backend/apps/bpp/models/counterparties.py`:

```python
"""Контрагенты модуля (ТЗ §18, D-20). Без согласования: карточку заводят
ФД, БУХ, СН и ПМ; блокирует ФД. Метка «Проверенный» — автоматически по числу
удачных документов (порог — настройка модуля) либо вручную ФД."""

from __future__ import annotations

from django.db import models

from .core import BppModel, VersionedModel

__all__ = ["Counterparty", "CounterpartyBankAccount", "CounterpartyKind", "CounterpartyStatus"]


class CounterpartyKind(models.TextChoices):
    LEGAL = "legal", "Юридическое лицо"
    IP = "ip", "Индивидуальный предприниматель"
    INDIVIDUAL = "individual", "Физическое лицо"
    NONRESIDENT = "nonresident", "Нерезидент"


class CounterpartyStatus(models.TextChoices):
    ACTIVE = "active", "Активен"
    BLOCKED = "blocked", "Заблокирован"
    ARCHIVED = "archived", "Архив"


class Counterparty(BppModel, VersionedModel):
    name = models.CharField(max_length=255)
    short_name = models.CharField(max_length=100, default="", blank=True)
    kind = models.CharField(max_length=16, choices=CounterpartyKind.choices)
    country_code = models.CharField(max_length=2)
    reg_number = models.CharField(max_length=30)
    is_vat_payer = models.BooleanField(default=False, db_default=False)
    vat_cert_series = models.CharField(max_length=20, default="", blank=True)
    vat_cert_number = models.CharField(max_length=30, default="", blank=True)
    address = models.CharField(max_length=500, default="", blank=True)
    contact_person = models.CharField(max_length=255, default="", blank=True)
    phone = models.CharField(max_length=50, default="", blank=True)
    email = models.EmailField(default="", blank=True)
    status = models.CharField(max_length=16, choices=CounterpartyStatus.choices,
                              default=CounterpartyStatus.ACTIVE,
                              db_default=CounterpartyStatus.ACTIVE.value)
    block_reason = models.CharField(max_length=500, default="", blank=True)
    blocked_at = models.DateTimeField(null=True, blank=True)
    blocked_by = models.IntegerField(null=True, blank=True)
    successful_documents = models.PositiveIntegerField(default=0, db_default=0)
    # None — метку считает порог; True/False — решение ФД, порог не трогает.
    verified_override = models.BooleanField(null=True, blank=True)
    ext_1c_ref = models.CharField(max_length=64, default="", blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["country_code", "reg_number"],
                                               name="uq_bpp_counterparty_reg")]
        verbose_name = "Контрагент"
        verbose_name_plural = "Контрагенты"


class CounterpartyBankAccount(BppModel):
    counterparty = models.ForeignKey(Counterparty, on_delete=models.PROTECT,
                                     related_name="bank_accounts")
    iban = models.CharField(max_length=34, unique=True)
    bank_name = models.CharField(max_length=255)
    bic = models.CharField(max_length=11)
    currency_code = models.CharField(max_length=3, default="KZT", db_default="KZT")
    is_main = models.BooleanField(default=False, db_default=False)
    is_active = models.BooleanField(default=True, db_default=True)

    class Meta:
        verbose_name = "Банковский счёт контрагента"
        verbose_name_plural = "Банковские счета контрагентов"
```

Create `backend/apps/bpp/models/settings.py`:

```python
"""Настройки модуля в схеме компании (узел ``bpp.settings``, АДМ)."""

from django.db import models

__all__ = ["ModuleSetting"]


class ModuleSetting(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    value = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.IntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "Настройка модуля"
        verbose_name_plural = "Настройки модуля"
```

Create `backend/apps/bpp/services/core/settings.py`:

```python
"""Настройки модуля БЗО: значение из схемы компании, иначе умолчание кода."""

from __future__ import annotations

from apps.bpp.models.settings import ModuleSetting

DEFAULTS = {
    "counterparty_verified_threshold": 3,  # D-20, умолчание Q-E23
}


def get_setting(key: str, default=None):
    row = ModuleSetting.objects.filter(key=key).first()
    if row is not None:
        return row.value
    return DEFAULTS.get(key, default)


def set_setting(key: str, value, *, actor_id: int | None) -> None:
    ModuleSetting.objects.update_or_create(key=key, defaults={"value": value,
                                                              "updated_by": actor_id})
```

Сгенерировать миграцию (dev-окружение из CLAUDE.md): `manage.py makemigrations bpp --name counterparties` → `0003_counterparties.py`.

Run: `../.venv/Scripts/python.exe -m pytest apps/bpp/tests -q` → PASS.

- [ ] **Step 4: Коммит**

```bash
git add backend/apps/bpp/models backend/apps/bpp/migrations backend/apps/bpp/services backend/apps/bpp/tests/test_counterparty_validation.py
git commit -m "feat(bpp): контрагенты — модели, проверка БИН/ИИН, IBAN и БИК, настройки модуля"
```

---

## Task 3: Контрагенты — сервис, функции для документов B, ручки

**Files:**
- Create: `backend/apps/bpp/services/counterparties/service.py`, `lookup.py`
- Create: `backend/apps/bpp/schemas/__init__.py` (если нет), `schemas/counterparties.py`
- Create: `backend/apps/bpp/views_counterparties.py`, `backend/apps/bpp/urls_counterparties.py`
- Modify: `backend/apps/bpp/admin.py`, `API.md`
- Test: `backend/apps/bpp/tests/test_counterparties.py`, `test_counterparties_api.py`

**Interfaces:**
- Consumes: `refdata.interface.country_brief`, `services/core/{audit,errors,settings,permissions,registry}` (registry — задача 4; до неё список без пагинации запрещён — выполнять задачу 4 раньше или вместе).
- Produces для B (`services/counterparties/lookup.py`):
  - `brief(ids: list[str]) -> dict[str, dict]` — `{id, name, short_name, reg_number, country_code, is_vat_payer, status, is_verified}`;
  - `assert_usable(counterparty_id: str) -> None` — E-CTR-01 для «Заблокирован» и «Архив» (BR-030);
  - `needs_confirmation(counterparty_id: str) -> bool` — непроверенный, окно подтверждения автора (D-20);
  - `record_success(counterparty_id: str) -> None` — +1 удачный документ; зовёт B при «Действует»/«Исполнен» договора и «Оплачено» счёта.
- Ручки `/api/bpp/v1/counterparties…` (ТЗ §23: SearchCounterparties, CreateCounterparty, BlockCounterparty).

- [ ] **Step 1: Падающие тесты сервиса**

```python
"""Контрагент: создание, дубль, блокировка, метка «Проверенный» (D-20)."""

import threading

import pytest
from django.db import connection

from apps.bpp.models.counterparties import Counterparty
from apps.bpp.services.counterparties import lookup, service
from htqweb.errors import DomainError

from .test_counterparty_validation import _with_control

BIN = _with_control("99034000123")


def _create(**over):
    data = {"name": "ТОО «Альфа»", "kind": "legal", "country_code": "KZ", "reg_number": BIN}
    data.update(over)
    return service.create(data, actor_id=7)


@pytest.mark.django_db
def test_create_normalizes_number(company_context):
    row = _create(reg_number=f"{BIN[:4]} {BIN[4:]}")
    assert row["reg_number"] == BIN and row["status"] == "active"


@pytest.mark.django_db
def test_duplicate_points_to_existing(company_context):
    first = _create()
    with pytest.raises(DomainError) as exc:
        _create(name="Другое имя")
    assert exc.value.code == "E-CTR-02"
    assert exc.value.fields[0]["existing_id"] == first["id"]


@pytest.mark.django_db(transaction=True)
def test_parallel_duplicate_is_422():
    codes = []

    def worker():
        try:
            _create()
            codes.append("ok")
        except DomainError as exc:
            codes.append(exc.code)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes) == ["E-CTR-02", "E-CTR-02", "ok"]


@pytest.mark.django_db
def test_blocked_is_not_usable(company_context):
    row = _create()
    service.block(row["id"], reason="нет оригиналов документов", actor_id=1)
    with pytest.raises(DomainError) as exc:
        lookup.assert_usable(row["id"])
    assert exc.value.code == "E-CTR-01"
    assert "нет оригиналов документов" in exc.value.message
    assert "ТОО «Альфа»" in exc.value.message


@pytest.mark.django_db
def test_block_needs_reason_of_10(company_context):
    row = _create()
    with pytest.raises(DomainError) as exc:
        service.block(row["id"], reason="коротко", actor_id=1)
    assert exc.value.code == "E-REQ-02"


@pytest.mark.django_db
def test_verified_by_threshold_and_override(company_context):
    row = _create()
    assert lookup.needs_confirmation(row["id"]) is True
    for _ in range(3):
        lookup.record_success(row["id"])
    assert lookup.needs_confirmation(row["id"]) is False
    service.set_verified(row["id"], False, actor_id=1)  # ФД снял метку вручную
    lookup.record_success(row["id"])
    assert lookup.needs_confirmation(row["id"]) is True
    service.set_verified(row["id"], None, actor_id=1)  # вернуть счёт по порогу
    assert lookup.needs_confirmation(row["id"]) is False


@pytest.mark.django_db
def test_update_checks_version(company_context):
    row = _create()
    service.update(row["id"], {"phone": "+7 700 000 00 00"}, version=row["version"], actor_id=7)
    with pytest.raises(DomainError) as exc:
        service.update(row["id"], {"phone": "x"}, version=row["version"], actor_id=8)
    assert exc.value.code == "E-CON-01"
```

- [ ] **Step 2: Сервис и функции для документов**

`services/counterparties/service.py` — `create(data, *, actor_id)`, `update(id, data, *, version, actor_id)`, `block(id, *, reason, actor_id)`, `unblock(id, *, actor_id)`, `archive(id, *, actor_id)`, `set_verified(id, value: bool | None, *, actor_id)`, `serialize(row)`, `add_bank_account(id, data, *, actor_id)`, `update_bank_account(account_id, data, *, actor_id)`.

Правила:
- `create`: `check_reg_number` → нормализованный номер; страна должна быть в `refdata.interface.country_brief` и активна (E-REF-03 «Страна „XX“ не найдена в справочнике»); вставка в `transaction.atomic()` — `IntegrityError` по `uq_bpp_counterparty_reg` → поиск существующего → `DomainError("E-CTR-02", "Контрагент с номером {reg} уже есть: {name}. Откройте существующую карточку.", fields=[{"field": "reg_number", "message": "дубль", "existing_id": id}])`; `audit.record(row, "created", …)`.
- `update`: `check_version`; менять `kind/country_code/reg_number` — с повторной проверкой номера и дубля; `version += 1`; в аудит — только изменённые поля `{поле: [старое, новое]}`.
- `block`: причина ≥ 10 символов (BR-060) — иначе `DomainError("E-REQ-02", "Опишите причину: комментарий не короче 10 символов.", fields=[{"field": "reason", …}])`; статус «Заблокирован», `blocked_at/by`, аудит; уведомлений нет.
- `record_success`: `Counterparty.objects.filter(pk=…).update(successful_documents=F("successful_documents") + 1)`.
- `is_verified(row)`: `row.verified_override` если не `None`, иначе `row.successful_documents >= get_setting("counterparty_verified_threshold")`.

`lookup.py`:
- `assert_usable`: E-CTR-01 дословно ТЗ §26.1 с подстановкой — «Контрагент {name} заблокирован {ДД.ММ.ГГГГ}: „{reason}“. Выберите другого контрагента или обратитесь к финансовому директору.»; для архива — «Контрагент {name} в архиве. Выберите другого контрагента или обратитесь к финансовому директору.»

Run: `../.venv/Scripts/python.exe -m pytest apps/bpp/tests/test_counterparties.py -q` → PASS.

- [ ] **Step 3: Падающие тесты ручек**

`test_counterparties_api.py` (хелперы — `apps/bpp/tests/helpers.py::auth/assign`):
- `GET /api/bpp/v1/counterparties?q=альф&status=active&page=1&page_size=25` — только активные, поиск по имени и номеру, конверт реестра `{items, total, page, page_size}` (задача 4);
- `POST` без `create` на `bpp.counterparties` → 403; с правом → 201 и `Idempotency-Key` повтор → тот же id (`idempotent=True`);
- `POST <id>/block` без `bpp.counterparties.block:edit` → 403 (у СН право `create` на `bpp.counterparties` есть, а блокировки нет — матрица);
- `POST <id>/verified {"value": null}` — только ФД;
- `PATCH <id>` с устаревшей `version` → 409 E-CON-01;
- `GET <id>` на неверный UUID → 404;
- `POST <id>/accounts` с неверным IBAN → 422 E-CTR-04 «IBAN „…“ неверен: KZ и 18 знаков, контрольные цифры не сходятся.».

- [ ] **Step 4: Ручки**

`views_counterparties.py` — все ручки `api_view(module="bpp", level=…)`; `GET` — `read`; запись — `write` + `permissions.can(request, "bpp.counterparties", "create"|"edit")`; блокировка и метка — `permissions.can(request, "bpp.counterparties.block", "edit")`; записывающие — `idempotent=True`. Диспетчеры коллекции и карточки — строгие (ветвление только по `request.method`, сторож `test_gate.py`). `urls_counterparties.py` — оба написания пути (со слэшем и без), `<str:counterparty_id>` + `uuid_or_404`.

`admin.py`: `CounterpartyAdmin`, `CounterpartyBankAccountAdmin`, `ModuleSettingAdmin` с `ServiceGatedAdminMixin`, удаление контрагента запрещено (BR-080).

Run: `../.venv/Scripts/python.exe -m pytest apps/bpp/tests apps/access/tests/test_gate.py apps/core/tests/test_invariants.py -q` → PASS.

- [ ] **Step 5: Документация и коммит**

`API.md` — раздел `apps.bpp` → «Контрагенты» (ручки, коды E-CTR-01…04). `STRUCTURE.md` — `services/counterparties/`.

```bash
git commit -m "feat(bpp): контрагенты — сервис, блокировка ФД, метка «Проверенный», ручки и функции для документов"
```

---

## Task 4: Общие ручки документов — реестр, «кто я», файлы, «Сейчас у»

**Files:**
- Create: `backend/apps/bpp/services/core/registry.py`, `backend/apps/bpp/services/core/owners.py`, `backend/apps/bpp/services/core/money.py`
- Modify: `backend/apps/bpp/views.py`, `backend/apps/bpp/urls.py`, `backend/apps/bpp/services/core/files.py` (проверка доступа через реестр владельцев)
- Test: `backend/apps/bpp/tests/test_registry.py`, `test_documents_api.py`

**Interfaces:**
- Produces (для B — все реестры и документы):
  - `registry.page(queryset, request, *, sort: dict[str, str], default_sort: str, search: tuple[str, ...] = ()) -> dict` — `{"items": QuerySet, "total", "page", "page_size"}`; `page_size ∈ {25, 50, 100}` (иначе 50), `sort=-amount` → поле из белого списка `sort`, неизвестный ключ — 422 `E-REQ-03`; `q` — `icontains` по `search`;
  - `owners.register(object_type: str, *, resolve: Callable[[str], object | None], can_view: Callable[[request, obj], bool], can_edit_files: Callable[[request, obj], bool])` — тип владельца файлов и журнала. Регистрация одновременно зовёт `audit.register_history_access(object_type, …)` (проверка журнала из этапа 1) — один вызов на тип документа;
  - `GET /api/bpp/v1/me` → `{"article_groups": ["supply", …], "initiator_roles": ["sn" | "pm", …]}` (группа `supply` → роль `sn`, `pm` → `pm`; ТЗ §23 GetCurrentUser);
  - `GET/POST /api/bpp/v1/files/<owner_type>/<owner_id>` (список / загрузка `multipart`: `file`, `file_type`), `POST files/<file_id>/replace`, `GET files/<file_id>/download` → 302 на подписанный адрес + журнал скачиваний; незарегистрированный тип или нет доступа — 404;
  - `GET /api/bpp/v1/holders?type=<subject_type>&ids=a,b` → `signoff.interface.current_holders` (B1.3), только типы `bpp.*`;
  - `money.round_money(value) -> Decimal` (`ROUND_HALF_UP` до 0,01), `money.format_money(amount: Decimal, currency: str = "KZT") -> str` (`1 250 000,00 KZT` — для текстов ошибок E-BUD-01 и др.), `money.vat_inside(amount, rate) -> Decimal` (CALC-008: `round(сумма × ставка / (100 + ставка), 2)`).

- [ ] **Step 1: Падающие тесты**
  - `test_money.py`: `round_money("0.005") == Decimal("0.01")`, `format_money(Decimal("1250000.5")) == "1 250 000,50 KZT"`, отрицательные и ноль; `vat_inside(Decimal("1120000"), Decimal("12")) == Decimal("120000.00")` (AC-006).
  - `test_registry.py`: страница 2 из 3 при `page_size=25`; `page_size=30` → 50; `sort=-name` работает, `sort=password` → 422 E-REQ-03; `q` ищет по полям `search`.
  - `test_documents_api.py`: `me` у СН → `["supply"]`/`["sn"]`, у совмещающего — обе; файлы у незарегистрированного типа → 404; зарегистрированный тип без `can_view` → 404; загрузка PDF → 201 с паспортом; `download` пишет `FileDownload` и отвечает 302; `holders` на тип вне `bpp.*` → 404.

- [ ] **Step 2: Реализация**

`owners.py`:

```python
"""Типы документов модуля: как найти владельца файлов и журнала и кто его видит.

Каждый документ (заявка, бюджет, договор, счёт…) регистрирует себя здесь
одним вызовом рядом с моделью. Незарегистрированный тип не отдаёт ни
файлов, ни истории — забытая регистрация закрывает, а не открывает.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import audit


@dataclass(frozen=True)
class Owner:
    resolve: Callable[[str], object | None]
    can_view: Callable[[object, object], bool]
    can_edit_files: Callable[[object, object], bool]


_OWNERS: dict[str, Owner] = {}


def register(object_type: str, *, resolve, can_view, can_edit_files) -> None:
    _OWNERS[object_type] = Owner(resolve, can_view, can_edit_files)
    audit.register_history_access(
        object_type, lambda request, object_id: _visible(request, object_type, object_id))


def _visible(request, object_type: str, object_id: str):
    owner = _OWNERS.get(object_type)
    obj = owner.resolve(object_id) if owner else None
    return obj if obj is not None and owner.can_view(request, obj) else None


def visible(request, object_type: str, object_id: str):
    """Объект, если тип зарегистрирован и вызывающий его видит, иначе ``None``."""
    return _visible(request, object_type, object_id)


def can_edit_files(request, object_type: str, obj) -> bool:
    owner = _OWNERS.get(object_type)
    return bool(owner and owner.can_edit_files(request, obj))
```

Вьюхи файлов — `api_view(module="bpp", level="read"|"write")`, отказ — `Http404`; загрузка — `files.attach(obj, file_type, data=…, filename=…, mime=upload.content_type, actor_id=…)`; размер запроса ограничен настройкой Django `DATA_UPLOAD_MAX_MEMORY_SIZE` не ниже 25 МБ (ТЗ §27) — проверить `settings/base.py` и выставить явно, если меньше.

Run: `../.venv/Scripts/python.exe -m pytest apps/bpp/tests apps/access/tests/test_gate.py -q` → PASS.

- [ ] **Step 3: Документация и коммит** — `API.md` (`me`, `files`, `holders`), `CLAUDE.md` (правило «каждый документ модуля — `owners.register` рядом с моделью»; заменяет формулировку про `register_history_access`).

```bash
git commit -m "feat(bpp): общие ручки документов — реестр, «кто я», файлы по типу владельца, «Сейчас у»"
```

---

## Task 5: Фронт — формат, защита от двойного клика, автосохранение, несохранённые изменения

**Files:**
- Create: `frontend/src/lib/bpp/format.ts` + `format.test.ts`
- Create: `frontend/src/features/bpp/core/useIdempotentAction.ts` + test
- Create: `frontend/src/features/bpp/core/useDraftAutosave.ts` + test
- Create: `frontend/src/features/bpp/core/useUnsavedChangesGuard.tsx` + test
- Create: `frontend/src/api/bpp.ts` (клиент: `apiPath('bpp', …)`, заголовок `Idempotency-Key`)

**Interfaces:**
- `formatMoney(amount: string | null | undefined, currency = 'KZT'): string` — `"1250000.5"` → `"1 250 000,50 KZT"` (разделитель разрядов — обычный пробел, ТЗ §05); без `float`: разбор строки; `null` → `'—'`.
- `parseMoneyInput(text: string): string | null` — `"1 250 000,00"` → `"1250000.00"`; больше двух знаков, буквы → `null` (ТЗ §13.2).
- `formatDate(iso)`, `formatDateTime(iso)` — `ДД.ММ.ГГГГ` и `ДД.ММ.ГГГГ ЧЧ:ММ` в `Asia/Almaty` через `Intl.DateTimeFormat('ru-RU', { timeZone: 'Asia/Almaty', … })`.
- `useIdempotentAction<T>(fn: (key: string) => Promise<T>)` → `{ run, pending }`: пока `pending` — повторный `run` ничего не шлёт; ответ 5xx или сеть — следующий `run` того же действия с ТЕМ ЖЕ ключом; успех или 4xx — ключ сбрасывается.
- `useDraftAutosave<T>(storageKey: string, value: T, { enabled, intervalMs = 30_000 })` → `{ draft: { savedAt, value } | null, discard() }`; `try/catch` вокруг `localStorage` (приватный режим).
- `useUnsavedChangesGuard({ dirty, onSaveDraft })` → `beforeunload` плюс перехват кликов по внутренним ссылкам (фаза захвата `document`), диалог «Есть несохранённые изменения. Сохранить черновик / Уйти без сохранения / Отмена» (ТЗ §05). **Решение:** роутер — `BrowserRouter`, `useBlocker` недоступен; кнопку «Назад» браузера перехват не ловит — это остаётся за `beforeunload` и автосохранением. Переход на data router — вне этапа.

- [ ] **Step 1: Падающие тесты** — по одному файлу на модуль, кейсы из Review Focus 3 и 5, плюс: `formatMoney("-15")` → `"-15,00 KZT"`, `formatMoney("99999999999999.99")` без потери разрядов; `useDraftAutosave` — сохраняет через 30 с (фейковые таймеры `vi.useFakeTimers`), восстанавливает при повторном монтировании, `discard` очищает; `useUnsavedChangesGuard` — клик по `<a href="/bpp/x">` при `dirty` не уходит и открывает диалог, «Уйти без сохранения» уходит, без `dirty` — уходит сразу.
- [ ] **Step 2: Реализация**, **Step 3:** `npx vitest run src/lib/bpp src/features/bpp && npm run lint` → PASS; `tsc` — не больше 148.
- [ ] **Step 4: Коммит** — `feat(bpp): формат денег и дат, защита от двойного клика, автосохранение черновика, диалог несохранённых изменений`.

---

## Task 6: Фронт — раздел `/bpp`, меню и «Мои согласования»

**Files:**
- Create: `frontend/src/features/bpp/BppLayout.tsx` + test, `frontend/src/features/bpp/approvals/module.tsx`, `frontend/src/features/bpp/approvals/MyApprovals.tsx` + test
- Modify: `frontend/src/app/routing/routeDefinitions.ts`, `lazyPages.ts` (один маршрут `/bpp/*`), пункт «Закупки и оплаты» в `app/navigation/navItems.ts` (видим при `atLeast('bpp', 'read')`)

**Interfaces:**
- Consumes: `bppModules` (задача 1), `usePermissions`, `signoffApi.inbox()` (`api/signoff.ts`).
- Produces: `BppLayout` — левое меню из `bppModules` (пункты с `visible(p) === false` не рисуются, ТЗ §05) и `<Routes>` из их `routes`; «Мои согласования» (D-34) — общий инбокс signoff с фильтром `subject_type.startsWith('bpp.')`.

- [ ] Тесты: меню без прав пустое; пункт с правом виден; маршрут без права — «Нет доступа»; «Мои согласования» показывает только задачи `bpp.*`, строка ведёт на карточку процесса signoff.
- [ ] Коммит — `feat(bpp): раздел «Закупки и оплаты» — меню по правам и «Мои согласования»`.

---

## Task 7: Фронт — реестр `BppRegistry`

**Files:**
- Create: `frontend/src/features/bpp/core/BppRegistry.tsx`, `useRegistryState.ts` + tests

**Interfaces:**
- `BppRegistry<Row>({ endpoint, columns, defaultColumns, filters, rowKey, onRowClick, selectable, massActions, totals, exportable, currentHolderType })`:
  - серверные фильтры, сортировка, пагинация 25/50/100 (по умолчанию 50);
  - быстрый поиск `q`;
  - набор колонок и фильтров — в `localStorage` под ключом `bpp:registry:<endpoint>`;
  - флажки и массовые действия с результатом по каждой строке;
  - итоговая строка (`totals` из ответа сервера);
  - кнопка «Экспорт» (задача 9);
  - колонка «Сейчас у» при `currentHolderType` — пакетный запрос `holders` по видимым id.
- Ответ сервера — конверт `registry.page` (задача 4) плюс необязательный `totals`.

- [ ] Тесты: смена страницы и сортировки уходит в запрос; скрытая колонка остаётся скрытой после перемонтирования; «Сейчас у» — один запрос на страницу; массовое действие показывает успехи и отказы с причинами.
- [ ] Коммит — `feat(bpp): реестр раздела — серверные фильтры, колонки, массовые действия, «Сейчас у»`.

---

## Task 8: Фронт — форма документа `BppDocumentShell`

**Files:**
- Create: `frontend/src/features/bpp/core/BppDocumentShell.tsx`, `StatusBadge.tsx`, `FilesTab.tsx`, `HistoryTab.tsx`, `ApprovalTab.tsx` + tests

**Interfaces:**
- `BppDocumentShell({ number, status, statusLabel, author, createdAt, allowedActions, actions, tabs, dirty, onSaveDraft, children })`:
  - шапка — номер, цветной бейдж статуса, автор, дата;
  - справа — кнопки ТОЛЬКО из `allowedActions` (ТЗ §05), каждая через `useIdempotentAction`;
  - внизу — вкладки «Согласование» (процесс signoff документа и «Сейчас у»), «Файлы» (`files/<type>/<id>`, типы и лимиты — с сервера) и «История изменений» (`history/<type>/<id>`);
  - `useUnsavedChangesGuard` и `useDraftAutosave` встроены.
- `actions: Record<string, { label; variant?; confirm?: { title; commentMin?: number }; run: (key: string) => Promise<unknown> }>` — диалог комментария (≥ 10 символов, BR-060) рисует оболочка.

- [ ] Тесты: кнопки не из `allowedActions` не рисуются; кнопка заблокирована на время запроса; «Отклонить» с 9 символами не отправляется; вкладка «Файлы» показывает ошибку 415 текстом сервера; «История» рисует записи журнала с датой-временем Almaty.
- [ ] Коммит — `feat(bpp): форма документа — шапка, действия по allowed_actions, вкладки согласования, файлов и истории`.

---

## Task 9: Экспорт реестров в xlsx

**Files:**
- Create: `backend/apps/bpp/services/core/export.py`, `backend/apps/bpp/tasks.py` (`export_registry`), вьюха `GET /api/bpp/v1/exports/<export_id>` в `views.py`
- Test: `backend/apps/bpp/tests/test_export.py`

**Interfaces:**
- `export.Column(key, title, kind: Literal["text", "money", "decimal", "date", "datetime"])`.
- `export.respond(request, *, name: str, columns: list[Column], rows: Iterable[dict], count: int, rebuild: tuple[str, dict]) -> HttpResponse | dict`:
  - `count ≤ 10 000` — xlsx сразу (`openpyxl` write-only, деньги — числовые ячейки с форматом `# ##0.00`);
  - `count > 10 000` — Celery `export_registry.delay(company_slug=…, rebuild=…, user_id=…)` → `{"queued": true}`. Задача пересобирает выборку функцией из `rebuild` (путь `"apps.bpp.services.<…>.export_rows"`, аргументы — фильтры запроса), кладёт файл в `media` (scope `bpp_doc`) и шлёт `notifications.notify(…, url=<ссылка на скачивание>)`.
- Предел — `EXPORT_SYNC_LIMIT = 10_000` (D-32); верхний предел выборки — 50 000 строк (ТЗ §19), сверх — 422 `E-EXP-01` «Слишком большая выборка: N строк. Сузьте фильтры до 50 000.»

- [ ] Тесты (Review Focus 4): 10 000 строк → `Content-Type` xlsx и `openpyxl.load_workbook` читает заголовки и первую сумму числом; 10 001 → `{"queued": true}` и задача поставлена (`CELERY_TASK_ALWAYS_EAGER` в тестах — проверить файл в хранилище в памяти и уведомление); пустая выборка — один ряд заголовков; 50 001 → 422.
- [ ] Коммит — `feat(bpp): экспорт реестров в xlsx — сразу до 10 000 строк, больше — фоном с уведомлением`.

---

## Task 10: Печать документов в PDF

**Files:**
- Modify: `backend/requirements.txt` (`weasyprint==<актуальная 6x>`), `backend/Dockerfile` (системные `libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b fonts-dejavu-core`), `.github/workflows/backend-full.yml` (те же пакеты `apt-get install` перед pytest)
- Create: `backend/apps/bpp/services/core/printing.py`, `backend/apps/bpp/templates/bpp/print/base.html`
- Test: `backend/apps/bpp/tests/test_printing.py`

**Interfaces:**
- `printing.render_html(template: str, context: dict) -> str` — всегда;
- `printing.render_pdf(template, context) -> bytes`;
- `printing.pdf_response(template, context, *, filename) -> HttpResponse` (`Content-Disposition: inline`).
- Базовый шаблон: бланк (место под колонтитулы — Q-B31, пришлёт команда), номер, статус, таблица, лист согласования (блок, который B наполняет из процесса signoff).

**Решение по окружению.** WeasyPrint требует системных библиотек Pango. В Docker и CI они ставятся явно. На Windows-хосте разработчика их может не быть: тест `render_pdf` тогда пропускается с явной причиной `pytest.skip("WeasyPrint: нет системных библиотек Pango — PDF проверяется в Docker/CI")` при `OSError` импорта. Тест `render_html` идёт всегда. Цена, если неверно: локально PDF не проверяется, ошибка найдётся только в CI.

- [ ] Тесты: HTML содержит номер и строки листа согласования; PDF начинается с `%PDF-`; кириллица не превращается в квадраты (в PDF есть встроенный шрифт DejaVu).
- [ ] Коммит — `feat(bpp): печать документов в PDF — WeasyPrint, базовый шаблон с местом под бланк`.

---

## Task 11 (волна 2): Экраны справочников, проектов и контрагентов

**Files:**
- Create: `frontend/src/features/bpp/refdata/module.tsx` + экраны: статьи и группы, НДС, МРП, валюты и курсы (ручной курс на пропущенную дату), ед. изм., страны (`/api/refdata/v1/*`)
- Create: `frontend/src/features/bpp/projects/module.tsx` + реестр и карточка проекта, участники (`/api/project/v1/*`)
- Create: `frontend/src/features/bpp/counterparties/module.tsx` + L-08 и карточка контрагента (БИН — `components/ui/bin-iin-input.tsx`, проверка разряда на фронте — тот же алгоритм, что в задаче 2), банковские счета, блокировка ФД, метка «Проверенный», окно подтверждения непроверенного контрагента — компонент `ConfirmCounterpartyDialog` для документов B
- Tests: vitest на каждый экран

**Правила:**
- **Справочники.** Правка только в управляющей компании. Кнопки правки рисуются по ответу сервера: `can_edit` приходит в списке справочника. Добавить в ответы `refdata` поле `"can_edit": bool` (ручки справочников этапа 1), тест в `apps/refdata/tests/test_api.py`.
- **Архив.** Архивная запись скрыта из выбора в новых документах (`?active=1`), но видна в списке с меткой «Архив».
- **Проекты.** Видимость по серверу (ПМ — только участия). Создание — `project.projects:create`, участники — `project.members:edit`.
- **Контрагенты.** Меню «Справочники» видно АДМ, ФД, СН и ПМ (ТЗ §05 п.9): СН и ПМ — только создание контрагента.

- [ ] Коммит — `feat(bpp): экраны справочников, проектов и контрагентов`.

---

## Task 12 (волна 2): Стык с этапом 1 исполнителя B

**Files:**
- Test: `backend/apps/notifications/tests/test_digest_signoff.py`

- [ ] **Ежедневная сводка с настоящим источником signoff.** Процесс БЗО ждёт пользователя 7 в компании A:
  - сводка содержит ссылку на поддомен компании A;
  - выключенный у компании модуль `signoff` не роняет сводку — источник упал, `fallback`, остальные разделы на месте.
- [ ] **Уведомления signoff идут через центр.** Проверить интеграционным тестом: отправка документа БЗО на согласование создаёт `notifications.Notification` получателям этапа с доставкой по e-mail (события модуля — колокольчик и e-mail, ТЗ §22). Signoff на центр переводит задача 1 плана B этапа 2; этот тест фиксирует результат с нашей стороны.
- [ ] Коммит — `test(notifications): сводка и уведомления согласования БЗО — сквозная проверка с signoff`.

---

## После этапа

- [ ] Полный прогон бэкенда (без `ci-known-failures.txt`) и `npx vitest run` — зелёные, кроме падений, которые воспроизводятся на базовом коммите.
- [ ] Финальное ревью ветки отдельным ревьюером; важные замечания исправить, мелкие — отдельным планом, как на этапе 1.
- [ ] PR в `new-module-BPP-merge`.

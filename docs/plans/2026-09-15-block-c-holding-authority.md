# Блок C «Права холдинга в подчинённых компаниях» — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сотрудник холдинга, обслуживающий дочерние компании, получает в них права своей должности — не поимённой раздачей, а признаком на должности; дочерняя компания при этом может видеть, кто из холдинга к ней допущен, если платформенный администратор включил это в настройках компании.

**Architecture:** Всё разрешение прав платформы сходится в одну функцию — `apps/access/services/resolve.py::_role_scopes`. Наследование добавляется ровно туда: к ролям должности в компании запроса добавляются роли должности пользователя в **вышестоящей** компании, если та должность помечена обслуживающей. Обход идёт вверх по дереву владения (`Company.parent`), чтение кадровой карточки предка — через `htqweb.tenancy.db.use_company`. Перед этим отдельной задачей снимается веер вызовов: сегодня `/me` зовёт `_role_scopes` **35 раз за запрос** (1 + 1 + 32 страницы), и наследование умножило бы на 35 ещё и переключения схемы.

**Tech Stack:** Django 5.2.7 / Python 3.13 (корневой `.venv`), Pydantic-схемы, pytest-django против Postgres `:55432`; React + Vite, TanStack Query, vitest + RTL, i18next с инлайн-фолбэками `t('key', 'текст')`.

**Spec:** [2026-09-14-group-structure-roadmap.md](2026-09-14-group-structure-roadmap.md) §5.C (и §3 — режим перехода). Модель доступа — [stage2-spec](2026-08-29-stage2-access-and-roles-spec.md) §1.2, §1.5. Документы руководства: оргструктура холдинга (4 руководителя + 8 менеджеров) и HR-FRM-005 (RACI: УК ставит политику и ведёт кадровое администрирование, ДО применяет).

## Global Constraints

- Интерпретатор — **корневой** `.venv`. Из `backend/`: `../.venv/Scripts/python.exe -m pytest <path> -q`.
- **Один прогон pytest за раз, всегда в форграунде.** Параллельные сессии делят `test_htqweb` и пулы схем — второй прогон даёт десятки ложных падений. Полный сьют ~38 мин, `apps/access` ~2 мин, `apps/hr` ~9 мин.
- Межаппный доступ — только через `apps.<x>.interface`; межаппных FK нет; `apps.core` — общий фундамент, его импортировать можно.
- `hr` — **тенантная** аппка: миграции доводит `manage.py migrate_companies` отдельным шагом выкатки. Только expand.
- `companies` и `access` — **общие** аппки (схема `public`), обычные миграции.
- Режим перехода (roadmap §3): одна действующая компания; ничего не переносим, не переименовываем, не удаляем.
- **Зона:** `apps/contracts/**`, `apps/signoff/**` и их экраны не трогаются.
- **Ветки не создавать** — работа в выданной ветке (сейчас `sanzhar`).
- Трейлер коммитов: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- Фронт: перед коммитом `npx tsc --noEmit -p tsconfig.json` и `npx vitest run <файлы>`. Базовая линия: ~331 ошибка линта в нетронутых файлах и 8 падающих тестов в `src/components/hr/__tests__/{EmployeeFormDialog,CardT2SectionDialog}.test.tsx` — они были до блока A.
- Известные падения бэкенда — ровно `backend/ci-known-failures.txt` (8 штук). Девятое — наше.

---

## Решения заказчика (приняты 15.09.2026, обязательны к исполнению)

1. **Механизм — наследование по должности.** Должность холдинга, помеченная обслуживающей, несёт СВОЙ набор ролей во все компании ниже по дереву владения. Поимённая раздача остаётся исключением (личные `RoleAssignment`), а не штатным путём.
2. **Признак — отдельный, «обслуживает дочерние компании».** НЕ переиспользуем `is_manager`/`external_hierarchy` из блока B. Причина названа документами: в холдинге 4 руководителя и 8 менеджеров, а обслуживают ДО именно 8 менеджеров (главбух, кадровый бухгалтер, экономист-аналитик, ГИП, менеджер ПТО и КК, менеджер по кадрам, менеджер по закупкам, системный администратор). Пометить их руководящими значило бы объявить главбуха холдинга начальником сотрудников ДО — неправда, и она попала бы во внешнюю иерархию блока B.
3. **Членство остаётся явным.** `CompanyMembership` по-прежнему заводится руками (`company_grant` или экран участников из блока A). Наследование даёт ПРАВА, вход в компанию открывает отдельное решение человека — две независимые двери.
4. **Видимость внешних держателей — настройка компании, менять её может платформенный администратор.** Не администратор ДО и не «всегда показывать»: у компании появляется переключатель, и правит его тот же, кто правит саму компанию (`is_superuser`, как у прочих мутаций реестра в блоке A).

### Уточнения к решениям (приняты 15.09.2026 вторым кругом)

5. **Риск «отложенной роли» снимается видимостью, а не вторым флагом.** Признак «групповая» на роли не вводится. Вместо него обе точки, где рождаются последствия, перестают быть слепыми: предпросмотр при включении галочки на должности (что и куда выдаётся) и предупреждение в диалоге ролей должности (роль поедет в ДО). Причина: отложенный сценарий — роль добавляют должности через полгода, и она молча уезжает во все ДО; предупреждение приходит ровно в тот момент, когда это происходит. Признак на роли остаётся возможным потом и ничего не ломает.
6. **Членство остаётся явным, но перестаёт быть забываемым** — тремя вещами сразу: `company_grant --serving`, напоминание в `company_create`, метрика разрыва с панелью.
7. **Два краевых правила:** роли ВСЕХ вышестоящих компаний, где человек работает, складываются (приоритет между компаниями вывести не из чего); **архивная компания-предок наследование вниз не раздаёт** — она выведена из эксплуатации, и права её должностей не должны продолжать действовать в живых ДО.

## Что из этого следует, и что я решил сам

Решения 1 и 3 вместе дают **двухшаговую операцию, где второй шаг невидим из первого**: пометив должность обслуживающей, администратор не даёт держателям ничего, пока кому-то не заведут членство в ДО. Молча ничего не делающая галочка — худший исход блока, поэтому задача 3 обязана показать это в интерфейсе: рядом с переключателем перечисляются держатели должности и то, в каких ДО у них нет членства, со ссылкой на экран участников. Это не украшение, а единственное, что отличает «не настроено» от «не работает».

Остальное, что спрашивать не о чем, но сказать надо:

- **Наследование идёт вниз по всему поддереву** компании, где человек работает, а не только на прямых детей. Ограничителем служит РОЛЬ: набор прав менеджера ПТО открывает задачи и договоры, а не кадры, — поэтому широкий охват не означает широких прав. Сегодня дерево плоское (холдинг → 3 ДО), и разницы нет вовсе.
- **Область наследованной роли — вся компания** (`ScopeKind.COMPANY`). Сузить её до отдела нельзя: отдела у человека в чужой компании нет.
- **Наследованные роли складываются с собственными** — тем же объединением, что и всегда. Если у человека есть и карточка в ДО, и наследование, он получает и то, и другое.
- **Берутся роли должности, как они назначены в ДОМАШНЕЙ компании** (`PositionRole.company_slug = <дом>`): роль одна на всю платформу, а набор ролей у должности — свой в каждой компании.
- **Настройка видимости по умолчанию — включена.** Скрывать по умолчанию значит прятать факт доступа от той компании, чьи данные читают; включённый по умолчанию переключатель честнее, а выключить его может тот же платформенный администратор.

---

## Файловая структура

**Backend (изменить):**
- `apps/companies/management/commands/company_grant.py`, `company_create.py` — флаг `--serving` и вывод разрыва.
- `apps/access/metrics.py` + панель в `infra/logging/grafana-dashboards/` — метрика разрыва.
- `apps/hr/models.py` — поле `serves_subsidiaries` на `Position`.
- `apps/hr/migrations/0022_position_serves_subsidiaries.py` — expand, один `AddField`.
- `apps/hr/interface.py` — ключ в `get_employee_brief` (аддитивно).
- `apps/hr/services/position_service.py` — ключ в `serialize`.
- `apps/hr/schemas.py` — поле в `PositionCreate`/`PositionUpdate`.
- `apps/access/services/resolve.py` — `Resolution` + наследование.
- `apps/access/views.py`, `apps/access/schemas.py` — источник прав в `/me`.
- `apps/access/interface.py` — `external_holders(company)`.
- `apps/companies/models.py`, `migrations/0004_company_show_external_holders.py`, `schemas.py`, `services/lifecycle.py`, `views.py` — настройка видимости.

**Backend (создать):**
- `apps/access/services/inheritance.py` — обход предков и чтение их кадровых карточек.
- `apps/access/tests/test_inheritance.py`, `apps/access/tests/test_resolution_context.py`, `apps/access/tests/test_external_holders.py`.
- `apps/hr/tests/test_position_serves_subsidiaries.py`.

**Frontend (изменить):**
- `src/types/hr.ts`, `src/pages/hr/HRPositions.tsx` — переключатель, предупреждение о членстве, предпросмотр выдаваемого.
- `src/components/access/PositionRolesDialog.tsx` — предупреждение, что роль поедет в дочерние компании.
- `src/types/access.ts`, `src/hooks/usePermissions.ts` — источник прав.
- `src/types/companies.ts`, `src/components/companies/CompanyFormDialog.tsx`, `src/api/companies.ts` — настройка видимости.
- `src/components/companies/CompanyMembersPanel.tsx` — список внешних держателей.

**Документы:** `docs/plans/2026-09-14-group-structure-roadmap.md` (§4, §5.C), `docs/plans/2026-08-29-stage2-access-and-roles-spec.md` (§1.2 — решение о том, что кросс-компанейский доступ норма, а не исключение), `API.md`, `STRUCTURE.md`, `CLAUDE.md`.

---

### Task 1: Признак «обслуживает дочерние компании» на должности

**Files:**
- Modify: `backend/apps/hr/models.py` (класс `Position`, рядом с `is_manager`)
- Create: `backend/apps/hr/migrations/0022_position_serves_subsidiaries.py` (через `makemigrations`)
- Create: `backend/apps/hr/tests/test_position_serves_subsidiaries.py`

**Interfaces:**
- Produces: `Position.serves_subsidiaries: bool` (по умолчанию `False`, `db_index=True`).

- [ ] **Step 1: Написать падающие тесты**

```python
# backend/apps/hr/tests/test_position_serves_subsidiaries.py
"""Признак «должность обслуживает дочерние компании» (roadmap §5.C).

Отдельный от ``is_manager`` намеренно, и это решение заказчика, а не вкус:
в холдинге 4 руководителя и 8 менеджеров, а обслуживают дочерние компании
именно менеджеры — главбух, кадровый бухгалтер, экономист, ГИП, менеджер ПТО,
менеджер по кадрам, менеджер по закупкам, системный администратор. Пометить их
руководящими значило бы объявить главбуха холдинга начальником сотрудников ДО
и вывести его во внешнюю иерархию блока B, где ему делать нечего.
"""

import pytest

from apps.hr.models import Department, Position


@pytest.fixture
def department(db):
    return Department.objects.create(name="Финансы", path="fin")


@pytest.mark.django_db
def test_position_does_not_serve_subsidiaries_by_default(department):
    """Бэкфилла нет: права в чужих компаниях не раздаются догадкой."""
    pos = Position.objects.create(title="Инженер", department=department, weight=100)
    pos.refresh_from_db()
    assert pos.serves_subsidiaries is False


@pytest.mark.django_db
def test_serving_position_need_not_be_managerial(department):
    """Главбух холдинга обслуживает ДО, но начальником их сотрудников не является."""
    pos = Position.objects.create(
        title="Главный бухгалтер", department=department, weight=110,
        serves_subsidiaries=True,
    )
    pos.full_clean()
    pos.refresh_from_db()
    assert (pos.serves_subsidiaries, pos.is_manager) == (True, False)


@pytest.mark.django_db
def test_the_two_flags_are_independent(department):
    """Руководящая и обслуживающая — разные вопросы, любое сочетание законно."""
    pos = Position.objects.create(
        title="Финансовый директор", department=department, weight=20,
        is_manager=True, serves_subsidiaries=True,
    )
    pos.full_clean()
    pos.refresh_from_db()
    assert (pos.is_manager, pos.serves_subsidiaries) == (True, True)
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_position_serves_subsidiaries.py -q`
Expected: FAIL — `TypeError: Position() got unexpected keyword argument 'serves_subsidiaries'`.

- [ ] **Step 3: Добавить поле**

В `backend/apps/hr/models.py`, в классе `Position`, сразу после `external_hierarchy`:

```python
    # Обслуживает ли должность дочерние компании: её роли действуют во всех
    # компаниях ниже по дереву владения (apps/access/services/inheritance.py).
    #
    # Отдельно от is_manager СОЗНАТЕЛЬНО, решением заказчика: «начальник людей»
    # и «работает на всю группу» — разные вещи. В холдинге обслуживают
    # дочерние компании 8 менеджеров из 12 человек, и ни один из них не
    # руководит сотрудниками ДО; переиспользовать is_manager значило бы либо
    # не дать прав бухгалтеру, либо соврать во внешней иерархии блока B.
    #
    # Умолчание False и никакого бэкфилла: догадка «кто обслуживает» раздала
    # бы права в чужих компаниях молча.
    serves_subsidiaries = models.BooleanField(
        default=False, db_default=False, db_index=True,
    )
```

- [ ] **Step 4: Сгенерировать миграцию**

Run: `cd backend && DJANGO_SETTINGS_MODULE=htqweb.settings.test ../.venv/Scripts/python.exe manage.py makemigrations hr -n position_serves_subsidiaries`
Expected: один `AddField`. Если автодетектор добавил что-то ещё — остановиться и доложить DONE_WITH_CONCERNS.

Дописать модульный докстринг по образцу `0021_position_external_hierarchy.py`: аппка тенантная, миграция идёт `migrate_companies`, шаг чисто аддитивный, `Position` входит в `HOLDING_MODELS` и сводки пересобираются прогоном.

- [ ] **Step 5: Убедиться, что тесты проходят**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_position_serves_subsidiaries.py apps/hr/tests/test_positions_api.py -q`
Expected: passed. ⚠️ `test_positions_api.py:124` фиксирует ТОЧНЫЙ набор ключей `PositionOut` — он сломается в задаче 2, когда поле попадёт в `serialize`, а не сейчас.

- [ ] **Step 6: Коммит**

```bash
git add backend/apps/hr/models.py backend/apps/hr/migrations/0022_position_serves_subsidiaries.py backend/apps/hr/tests/test_position_serves_subsidiaries.py
git commit -m "feat(hr): признак «должность обслуживает дочерние компании»

Отдельно от is_manager по решению заказчика: обслуживают ДО 8 менеджеров
холдинга из 12 человек, и начальниками сотрудников ДО они не являются.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Признак наружу — бриф, сериализация, схемы

**Files:**
- Modify: `backend/apps/hr/interface.py` (`get_employee_brief`), `backend/apps/hr/services/position_service.py` (`serialize`), `backend/apps/hr/schemas.py` (`PositionCreate`, `PositionUpdate`), `backend/apps/hr/tests/test_positions_api.py` (набор ключей), `backend/apps/hr/tests/test_position_serves_subsidiaries.py` (дописать)

**Interfaces:**
- Consumes: `Position.serves_subsidiaries` (Task 1).
- Produces: `get_employee_brief` отдаёт `serves_subsidiaries`; `serialize` — то же; обе схемы принимают `bool` / `bool | None`.

Делается **точно по образцу задачи 2 блока B** (коммит `349b180`) — откройте её диффом и повторите форму: `position__serves_subsidiaries` в `.values(...)`, ключ в возвращаемом словаре с комментарием о том, кто его читает, поле в `serialize` после `external_hierarchy`, поля в обеих схемах, расширение ожидаемого набора ключей в `test_positions_api.py:124`.

- [ ] **Step 1: Дописать падающие тесты** в `test_position_serves_subsidiaries.py` — по образцу блока B: бриф несёт ключ и сохраняет все прежние; `serialize` отдаёт; `PATCH /api/hr/v1/positions/<id>/` ставит и возвращает. Фикстуры `client`/`admin_headers` взять ровно те, что уже используются в этом файле после блока B.
- [ ] **Step 2: Прогнать и увидеть падение.** Run: `cd backend && ../.venv/Scripts/python.exe -m pytest apps/hr/tests/test_position_serves_subsidiaries.py -q`
- [ ] **Step 3: Расширить бриф, сериализацию и схемы.**
- [ ] **Step 4: Починить `test_positions_api.py:124`** — добавить `"serves_subsidiaries"` в ожидаемый набор ключей. НЕ ослаблять `==` до подмножества: этот тест пинит контракт `PositionOut`, и это его работа.
- [ ] **Step 5: Прогнать.** Run: `cd backend && ../.venv/Scripts/python.exe -m pytest apps/hr -q` — ожидаются ровно два известных падения `test_employees_api.py::test_*_card_t2_*`.
- [ ] **Step 6: Коммит** — `feat(hr): признак обслуживания дочерних компаний доходит до apps.access`.

---

### Task 3: Переключатель в карточке должности + видимая вторая половина операции

**Files:**
- Modify: `frontend/src/types/hr.ts`, `frontend/src/pages/hr/HRPositions.tsx`
- Create: `frontend/src/pages/hr/__tests__/HRPositionsServesSubsidiaries.test.tsx`

Переключатель добавляется в тот же блок «Внешняя иерархия», что и поля блока B, но **отдельной строкой с собственной подписью** — он не про иерархию подчинения, а про обслуживание, и подпись обязана это разделить.

**Обязательная часть задачи — предупреждение о членстве.** Решения заказчика 1 и 3 вместе означают, что галочка сама по себе не даёт держателям должности ничего, пока им не заведено членство в дочерней компании. Рядом с включённым переключателем должен стоять текст, который называет второй шаг и ведёт к нему:

> Права начнут действовать, когда держателям этой должности заведут членство в дочерней компании — на странице «Компании группы» → участники. Без членства токен на поддомен ДО не выдаётся, и признак не даёт ничего.

**Вторая обязательная часть — предпросмотр (решение 5).** При включённом переключателе рядом показывается, что именно выдаётся: **роли этой должности** (из существующей `accessApi.getPositionRoles(positionId)`) и **в какие компании** они поедут (поддерево текущей компании из `companiesApi.tree()`). Новых ручек не заводить — обе уже есть. Если дерево недоступно (у кадровика может не быть права `companies:read`, ручка ответит 403), перечень компаний заменяется фразой «во все компании ниже по дереву владения» — тот же приём деградации, что в `ExternalHierarchy.tsx`, и точно так же без слова «ошибка».

**Третья часть — предупреждение в диалоге ролей должности** (`frontend/src/components/access/PositionRolesDialog.tsx`, он открывается с этой же страницы). Если должность помечена обслуживающей, диалог говорит это до сохранения: «Эта должность обслуживает дочерние компании — добавленная роль начнёт действовать и в них». Это и есть защита от отложенного сценария: роль добавляют через полгода, и предупреждение приходит в тот момент, когда это происходит. Флаг в диалог передаётся пропсом со страницы — она уже держит объект должности.

- [ ] **Step 1: Написать падающий тест** — пять проверок: переключатель отражает значение должности; включение отправляет `serves_subsidiaries: true` в PATCH; при включённом переключателе виден текст про членство (подстрока «членство»); при включённом виден предпросмотр с названиями ролей должности; в `PositionRolesDialog` у обслуживающей должности виден текст про действие роли в ДО, а у обычной — нет. Мок API и запросы к разметке — сверить с фактическим `HRPositions.tsx`, как это делалось в блоке B (страница ходит не через `@/api/hr`, а через `@/api/client` — проверьте и повторите приём из `HRPositionsExternalHierarchy.test.tsx`).
- [ ] **Step 2: Прогнать и увидеть падение.**
- [ ] **Step 3: Тип, состояние формы (включая ВСЕ места сброса и заполнения из `editingPos`), разметка, предпросмотр, предупреждение в диалоге ролей.**
- [ ] **Step 4:** Run: `cd frontend && npx vitest run src/pages/hr src/components/access && npx tsc --noEmit -p tsconfig.json && npm run lint`
- [ ] **Step 5: Коммит** — `feat(hr): обслуживание дочерних компаний правится в карточке должности и видно, что оно выдаёт`.

---

### Task 4: Контекст разрешения — снять веер вызовов (поведение не меняется)

**Files:**
- Modify: `backend/apps/access/services/resolve.py`, `backend/apps/access/views.py` (`MeView`)
- Create: `backend/apps/access/tests/test_resolution_context.py`

**Interfaces:**
- Produces: `resolve.Resolution` (датакласс с `scopes` и `rows`), `resolve.resolution(user, company) -> Resolution`, и необязательный параметр `resolution=` у `flags_for`, `can`, `page_hidden`, `depth_map`, `permissions_for`, `permission_level`.

**Зачем это отдельная задача и почему до наследования.** `GET /access/v1/me` зовёт `page_hidden` в цикле по 32 узлам-страницам плюс `permissions_for` и `depth_map` — то есть `_role_scopes` отрабатывает **35 раз за один запрос**, и каждый раз делает три запроса в БД. Задача 5 добавит в `_role_scopes` чтение кадровой карточки в схеме вышестоящей компании — с переключением `search_path`. Умножить это на 35 нельзя; чинить постфактум, когда механика уже написана, — значит переписывать её же. Поэтому сначала шов, потом механика.

**Решение — явный параметр, а не глобальный кэш.** Мемоизация в `contextvar` выглядит короче, но заводит состояние, живущее дольше вызова, и требует сброса между запросами и между тестами; ошибка в сбросе отдаёт права одного пользователя другому — цена несопоставима с экономией. Явный `resolution=` не может протечь: он живёт в кадре вызывающего.

- [ ] **Step 1: Написать падающие тесты**

```python
# backend/apps/access/tests/test_resolution_context.py
"""Контекст разрешения: один расчёт на запрос вместо 35.

/me зовёт page_hidden по каждому узлу-странице (их 32) плюс permissions_for и
depth_map. Пока расчёт был внутри каждой функции, один запрос /me стоил 35
пересчётов ролей; после наследования (задача 5) каждый из них стоил бы ещё и
переключения схемы. Тест считает ЗАПРОСЫ, а не время: он обязан падать, если
кто-нибудь снова начнёт считать роли внутри цикла.
"""

import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection

from apps.access.services import resolve


@pytest.mark.django_db
def test_resolution_is_computed_once_and_reused(user, employee_with_position):
    res = resolve.resolution(user, "htq-holding")
    with CaptureQueriesContext(connection) as ctx:
        resolve.permissions_for(user, "htq-holding", resolution=res)
        resolve.depth_map(user, "htq-holding", resolution=res)
        for route in ("/hr/employees", "/tasks", "/companies"):
            resolve.page_hidden(user, route, "htq-holding", resolution=res)
    assert len(ctx.captured_queries) == 0, (
        "переданный Resolution не должен порождать запросов: "
        f"{[q['sql'] for q in ctx.captured_queries]}"
    )


@pytest.mark.django_db
def test_without_resolution_the_answer_is_the_same(user, employee_with_position):
    """Параметр — оптимизация, а не второй ответ."""
    res = resolve.resolution(user, "htq-holding")
    assert (resolve.permissions_for(user, "htq-holding")
            == resolve.permissions_for(user, "htq-holding", resolution=res))
    assert (resolve.depth_map(user, "htq-holding")
            == resolve.depth_map(user, "htq-holding", resolution=res))


@pytest.mark.django_db
def test_me_endpoint_computes_roles_once(client, user, employee_with_position):
    """Сторож на сам эндпоинт: 32 страницы не должны стоить 32 расчётов."""
    # Токен и заголовки — как в apps/access/tests/helpers.py.
    ...
```

Третий тест допишите по фактическим помощникам `apps/access/tests/helpers.py`: снимите `CaptureQueriesContext` вокруг запроса `GET /api/access/v1/me` и проверьте, что число запросов к `access_rolepermission` не растёт со числом страниц (например, что оно не больше трёх). Точное число подберите по факту и зафиксируйте в тесте с комментарием, откуда оно взялось.

- [ ] **Step 2: Прогнать и увидеть падение** — `resolve.resolution` не существует.

- [ ] **Step 3: Ввести `Resolution`**

В `resolve.py` добавить датакласс и функцию-фабрику, а каждую публичную функцию научить принимать готовый контекст:

```python
@dataclass(frozen=True)
class Resolution:
    """Роли пользователя в компании и их явные узлы — один расчёт на запрос.

    Существует затем, что /me зовёт page_hidden по каждому узлу-странице:
    без общего контекста один запрос стоил бы 35 пересчётов ролей, а после
    наследования (inheritance.py) — ещё и 35 переключений схемы.

    Передаётся ЯВНО, а не живёт в contextvar: состояние, переживающее вызов,
    пришлось бы сбрасывать между запросами и между тестами, и ошибка в сбросе
    отдала бы права одного пользователя другому.
    """

    scopes: dict[int, tuple[str, int | None]]
    rows: dict[int, dict[str, frozenset[str]]]


def resolution(user, company: str | None) -> Resolution:
    scopes = _role_scopes(user, company)
    return Resolution(scopes=scopes, rows=_rows_by_role(scopes))
```

Каждая публичная функция получает `resolution: Resolution | None = None` и в начале делает `res = resolution or globals()["resolution"](user, company)` — нет, так нельзя: имя занято. Назовите фабрику `resolution()` и внутри функций используйте локальную переменную другого имени, например:

```python
def permissions_for(user, company, *, resolution: Resolution | None = None) -> dict[str, dict]:
    ...
    res = resolution if resolution is not None else globals()["resolution"](user, company)
```

Это некрасиво. Вместо этого назовите фабрику **`resolve_for(user, company)`**, а параметр — `resolution`; тогда тело читается прямо: `res = resolution or resolve_for(user, company)`. Тесты выше используют `resolve.resolution(...)` — приведите их к `resolve.resolve_for(...)` при написании, имя фабрики решается здесь и один раз.

⚠️ Ветка суперпользователя во всех функциях должна остаться ПЕРЕД построением контекста: у суперпользователя прав полный набор без единого запроса, и строить ему `Resolution` значит вернуть в горячий путь ровно то, что эта задача убирает.

- [ ] **Step 4: Пересадить `MeView`** — построить контекст один раз и передать во все четыре вызова.

- [ ] **Step 5: Прогнать** — `cd backend && ../.venv/Scripts/python.exe -m pytest apps/access -q`. Поведение не меняется, поэтому ВСЕ существующие тесты домена обязаны остаться зелёными без правок. Если какой-то пришлось поправить — это сигнал, что поведение всё-таки изменилось: остановиться и доложить.

- [ ] **Step 6: Коммит** — `perf(access): один расчёт ролей на запрос вместо тридцати пяти`.

---

### Task 5: Наследование прав от вышестоящей компании

**Files:**
- Create: `backend/apps/access/services/inheritance.py`, `backend/apps/access/tests/test_inheritance.py`
- Modify: `backend/apps/access/services/resolve.py` (`_role_scopes`)

**Interfaces:**
- Consumes: `Position.serves_subsidiaries` через `hr.get_employee_brief` (Task 2); `companies.interface.get_company` (`parent_slug`); `htqweb.tenancy.db.use_company`.
- Produces: `inheritance.inherited_role_scopes(user_id, company) -> dict[int, tuple[str, int | None]]` и `inheritance.ancestors_of(company) -> list[str]`.

Это ядро блока. Алгоритм:

1. Подняться от `company` вверх по `parent_slug` (`companies.interface.get_company`, кэш 5 с). Обход защитить от цикла набором пройденных — как `companies_below` в `hierarchy.py`: цикл, заведённый мимо приложения, не должен вешать разрешение прав.
2. **Архивные предки пропускаются** (решение 7): `get_company` отдаёт `is_active`, и по нему предок отбрасывается — но обход на нём НЕ останавливается, выше могут быть действующие. Архив — это вывод компании из эксплуатации, и права её должностей не должны продолжать действовать в живых ДО.
3. Для каждого действующего предка `A`: войти в его схему (`use_company(A)`) и спросить `hr.get_employee_brief(user_id)`. Карточка есть и `brief["serves_subsidiaries"]` истинно → взять `PositionRole.objects.filter(company_slug=A, position_id=brief["position_id"])`.
4. **Предки НЕ взаимоисключающи** (решение 7): обход не прерывается на первой найденной карточке, роли всех вышестоящих компаний, где человек работает, складываются. Приоритет между компаниями вывести не из чего, а объединение — то же правило, по которому складываются все прочие роли.
5. Все найденные роли отдать с областью `(ScopeKind.COMPANY, None)`.
6. Кадровый модуль недоступен → `fallback("access.inheritance.hr_unavailable", …, expected=True)` и пустой результат, ровно как `_position_role_ids` уже делает: выключенный `hr` не должен молча снимать права.

⚠️ **`use_company(A)` переводит не только `search_path`, но и контекст компании**, поэтому `require_service("hr")` внутри `get_employee_brief` спросит `CompanyModule` у ПРЕДКА, а не у компании запроса. Это правильно и намеренно: читается кадровая карточка предка, его рубильником она и должна управляться — выключенный в холдинге `hr` перестаёт раздавать наследование, и это честно. Проверено по `htqweb/tenancy/db.py:46-62` (контекст восстанавливается в `finally`, вложенность поддержана) и `apps/hr/interface.py:40`. Зафиксируйте это тестом: выключенный `hr` у ПРЕДКА даёт пустое наследование, выключенный у компании запроса — не мешает наследованию приехать.

В `_role_scopes` наследованные роли добавляются **до** личных назначений, чтобы личное назначение могло только расширить область, но не сузить (правило `_SCOPE_WIDTH` уже это обеспечивает).

- [ ] **Step 1: Написать падающие тесты**

Файл `apps/access/tests/test_inheritance.py`. Обязательный состав (каждый пункт — отдельный тест):

- сотрудник холдинга с должностью `serves_subsidiaries=True` получает в ДО роли этой должности, как они назначены В ХОЛДИНГЕ;
- он же с `serves_subsidiaries=False` не получает в ДО ничего;
- сотрудник ДО ничего не наследует «вверх» — проверка направления: обход идёт только к предкам;
- сотрудник соседней ветки (компания вне поддерева) не получает ничего;
- наследованные роли СКЛАДЫВАЮТСЯ с собственными правами человека в ДО, а не заменяют их;
- **человек с обслуживающими должностями в ДВУХ вышестоящих компаниях получает роли обеих** (решение 7): обход не прерывается на первой найденной карточке;
- **архивная компания-предок не раздаёт ничего**, и обход на ней не останавливается — действующий предок выше по дереву наследование по-прежнему даёт;
- область наследованной роли — `company`;
- цикл в дереве владения не вешает разрешение (завести `parent` по кругу прямым `update`, минуя валидацию);
- выключенный модуль `hr` даёт пустое наследование и пишет `FALLBACK` с `expected=True`, а не тихо.

Схемы компаний нужны настоящие: используйте фикстуру `two_company_schemas` из корневого `conftest.py` и заведите родство между ними через `Company.parent`. Кадровые карточки создаются каждая в СВОЕЙ схеме (`use_company`), иначе тест проверит не то.

- [ ] **Step 2: Прогнать и увидеть падение.**
- [ ] **Step 3: Написать `inheritance.py`** по алгоритму выше, с докстрингом, объясняющим решения заказчика 1 и 2 и почему обход идёт вверх, а не вниз.
- [ ] **Step 4: Подключить в `_role_scopes`.**
- [ ] **Step 5: Прогнать** — `cd backend && ../.venv/Scripts/python.exe -m pytest apps/access -q`, затем убедиться, что сторож из задачи 4 (число запросов) всё ещё зелёный: наследование обязано считаться один раз на запрос, а не на каждый узел-страницу.
- [ ] **Step 6: Коммит** — `feat(access): должность холдинга несёт свои роли в дочерние компании`.

---

### Task 6: `/me` объясняет, откуда взялись права

**Files:**
- Modify: `backend/apps/access/schemas.py` (`MeRead`), `backend/apps/access/views.py` (`MeView`), `backend/apps/access/services/resolve.py` (источник роли), `frontend/src/types/access.ts`, `frontend/src/hooks/usePermissions.ts`
- Create: тесты рядом с существующими (`apps/access/tests/test_me.py` дописать; фронт — в тесте хука)

Права, приехавшие из другой компании, обязаны быть объяснимы: человек, открывший ДО и увидевший там кадровый доступ, должен узнать, что он у него от должности в холдинге, а не гадать. `MeRead` получает необязательное поле `inherited_from: str | null` — слаг компании, чья должность дала права (пусто, если наследования нет). Фронт прокидывает его в `usePermissions` и показывает одной строкой там, где уже показывается компания.

Контракт §4.5 спеки стадии 2 расширяется аддитивно; правку зафиксировать в спеке в задаче 8.

- [ ] Тест: у наследующего `/me` отдаёт `inherited_from` = слаг холдинга; у обычного сотрудника ДО — `null`; у суперпользователя — `null` (его права ниоткуда не наследуются).
- [ ] Реализация, прогон `apps/access`, фронт: `npx vitest run src/hooks`, `tsc`, линт.
- [ ] Коммит — `feat(access): /me называет компанию, от должности в которой пришли права`.

---

### Task 7: Настройка видимости внешних держателей + список для дочерней компании

**Files:**
- Modify: `backend/apps/companies/models.py`, `schemas.py`, `services/lifecycle.py`, `views.py`; create `backend/apps/companies/migrations/0004_company_show_external_holders.py`
- Modify: `backend/apps/access/interface.py`, `backend/apps/access/services/holders.py` (**дописать туда, не заводить новый файл**: этот модуль уже отвечает на вопрос «кто держит права» и уже умеет обходить компании со входом в их схемы — его докстринг и `_describe` готовы к переиспользованию)
- Create: `backend/apps/access/tests/test_external_holders.py`
- Modify: `frontend/src/types/companies.ts`, `src/api/companies.ts`, `src/components/companies/CompanyFormDialog.tsx`, `src/components/companies/CompanyMembersPanel.tsx`

Решение заказчика 4: видимость — **настройка компании**, менять её может **платформенный администратор**.

1. `Company.show_external_holders` — `BooleanField(default=True, db_default=True)`. Включено по умолчанию: скрывать по умолчанию значит прятать факт доступа от той компании, чьи данные читают.
2. Поле попадает в `CompanyRead` и `CompanyPatch`; правится через `PATCH companies/<slug>`, который после блока A уже требует `deny_unless_platform_admin()` — то есть ровно тот, кого назвал заказчик. Никакого нового гейта заводить не нужно, и это надо проверить тестом, а не предположить.
3. `GET companies/<slug>/external-holders` — список внешних держателей: ФИО, домашняя компания, должность, набор модулей с уровнями. Гейт — тот же `deny_unless_own_company(slug)` из блока A (своя компания либо платформенный администратор). Если у компании `show_external_holders=False`, ручка отдаёт **403 с внятным телом**, а не пустой список: пустой список означал бы «внешних нет», и это была бы ложь.
4. Панель участников на странице компании получает раздел «Из холдинга» — только когда настройка включена.

⚠️ Сбор списка идёт по компаниям-предкам и читает их кадровые карточки — это раскрытие данных о сотрудниках холдинга дочерней компании, и именно им управляет настройка. Отдавать только имя, домашнюю компанию, должность и уровни модулей; ничего сверх этого.

- [ ] Тесты: поле правится только платформенным администратором (403 остальным); при выключенной настройке ручка 403 с телом, а не пустой ответ; список содержит наследующего и не содержит обычного сотрудника ДО; фронт — раздел появляется и исчезает по настройке.
- [ ] Реализация, прогон `apps/companies` и `apps/access`, фронт-проверки.
- [ ] Два коммита: `feat(companies): настройка видимости внешних держателей прав` и `feat(access): список держателей прав из вышестоящих компаний`.

---

### Task 8: Разрыв «признак есть, членства нет» — команда, напоминание, метрика

**Files:**
- Modify: `backend/apps/companies/management/commands/company_grant.py`, `company_create.py`, `backend/apps/access/metrics.py`, `backend/apps/access/interface.py`
- Modify: `infra/logging/grafana-dashboards/` — панель для новой метрики
- Create: `backend/apps/companies/tests/test_company_grant_serving.py`, дописать `backend/apps/access/tests/test_metrics.py`

Решения заказчика 3 и 6: членство остаётся явным фактом в таблице, но перестаёт быть забываемым. Три вещи, каждая независимо полезна:

1. **`manage.py company_grant --company <slug> --serving`** — завести членство всем, чья должность в вышестоящей компании помечена обслуживающей. Флаг встаёт третьим в существующую `mutually_exclusive_group` рядом с `--user` и `--all-users`. Идемпотентно (`grant_membership` уже `get_or_create`). Список держателей берётся через `apps.access.interface` — новая функция `serving_holders(company)`, которая переиспользует обход предков из задачи 5; прямых импортов моделей соседней аппки не появляется.
2. **`company_create` в конце печатает разрыв**: сколько держателей обслуживающих должностей вышестоящих компаний ещё не имеют членства в только что созданной компании, и называет команду из п.1. Печатает, а не делает: заведение членства — отдельное решение человека (решение 3).
3. **Метрика разрыва** в `apps/access/metrics.py`, рядом с существующим счётчиком «роль без единого права» — он там ровно по той же причине: типовой результат недоведённой настройки, который снаружи выглядит как «нет доступа». Имя без цифр, по маске `htqweb_[a-z_]+`.

⚠️ `apps/core/tests/test_metrics_are_observed.py` требует, чтобы считаемую метрику рисовала панель или проверяло правило, **но у него есть список исключений `_KNOWN_UNOBSERVED`, и все пять нынешних метрик `access` уже там** (строки 85-89). Лёгкий выход существует — и для ЭТОЙ метрики он запрещён: её единственный смысл в том, чтобы разрыв был виден, а счётчик, на который никто не смотрит, делает её бессмысленной. Панель обязательна, в `_KNOWN_UNOBSERVED` имя не вносить. Панели у домена `access` сегодня нет вовсе — заведите раздел в `infra/logging/grafana-dashboards/htqweb-domains.json` рядом с остальными доменами, по образцу соседних панелей того же файла.

Правило алерта не заводить: разрыв — не инцидент, а незавершённая настройка; шумное правило обесценило бы остальные (см. заголовок `infra/logging/grafana-provisioning/alerting/`).

- [ ] **Step 1: Написать падающие тесты** — `--serving` заводит членство держателю обслуживающей должности предка и не заводит обычному сотруднику; повторный вызов идемпотентен; `--serving` вместе с `--user` отвергается (взаимоисключающая группа); `company_create` печатает число без членства; метрика считает разрыв и равна нулю, когда членство выдано.
- [ ] **Step 2: Прогнать и увидеть падение.**
- [ ] **Step 3: Реализация** — интерфейсная функция, флаг команды, вывод при создании, метрика, панель.
- [ ] **Step 4:** Run: `cd backend && ../.venv/Scripts/python.exe -m pytest apps/companies apps/access apps/core/tests/test_metrics_are_observed.py -q`
- [ ] **Step 5: Коммит** — `feat(companies): разрыв «обслуживающая должность без членства» виден и закрывается одной командой`.

---

### Task 9: Сквозная проверка и документы

- [ ] **Полный backend-сьют** (форграунд, таймаут 3600000 мс): `cd backend && ../.venv/Scripts/python.exe -m pytest -q`. Ожидается ровно 8 известных падений `ci-known-failures.txt`; любое девятое разобрать и классифицировать (`git log --oneline <база блока>..HEAD --name-only` по файлу теста).
- [ ] **Фронт целиком:** `npx tsc --noEmit -p tsconfig.json && npm run lint && npm test` — ожидается 8 известных падений в HR-диалогах.
- [ ] **Документы:**
  - `docs/plans/2026-09-14-group-structure-roadmap.md` — §5.C закрыт, строка §4 про права холдинга приведена к факту;
  - `docs/plans/2026-08-29-stage2-access-and-roles-spec.md` — §1.2 («личное назначение — исключение») дополнить: для группы компаний кросс-компанейский доступ по должности стал штатным путём, решением заказчика от 15.09.2026; §4.5 — новое поле `inherited_from`;
  - `API.md` — `external-holders`, новое поле компании, `inherited_from` в `/me`;
  - `STRUCTURE.md` — `apps/access/services/inheritance.py`;
  - `CLAUDE.md` — абзац о том, что права в компании могут приходить от должности в вышестоящей компании, и что членство при этом остаётся отдельным явным фактом.
- [ ] **Коммит** — `docs: блок C закрыт — права холдинга действуют в дочерних компаниях`.

---

## Рантбук выкатки блока C

1. До выкатки: `manage.py tenancy_status --json > before.json`.
2. Выкатка образов. `migrate_shared` применит миграцию `companies/0004` (настройка компании, схема `public`) и НЕ применит `hr/0022` — аппка тенантная.
3. **`manage.py migrate_companies`** без фильтров — доводит схемы всех действующих компаний и пересобирает сводки холдинга.
4. После: `manage.py tenancy_status --json > after.json`; `diff` — состав таблиц и компаний не меняется.
5. **Раздача прав — два шага, и второй обязателен:**
   а. пометить обслуживающие должности холдинга в карточке должности (по документам это 8 менеджеров: главбух, кадровый бухгалтер, экономист-аналитик, ГИП, менеджер ПТО и КК, менеджер по кадрам, менеджер по закупкам, системный администратор). Экран покажет предпросмотр: какие роли и в какие компании поедут;
   б. завести держателям этих должностей членство в каждой дочерней компании: `manage.py company_grant --company <slug> --serving` разом по всем держателям, либо `--user <id>` поимённо, либо экран участников. **Без шага «б» признак не даёт ничего**: токен на поддомен ДО не выдаётся без членства. Разрыв виден на дашборде и печатается `company_create` при заведении новой ДО.
6. Проверить: сотрудник холдинга с обслуживающей должностью открывает поддомен ДО и видит там свои модули; `/me` называет холдинг в `inherited_from`.

## Что блок C не делает

- **Не режет данные по внешней иерархии** — множество подчинённых компаний по-прежнему только вычисляется и отображается (stage2-spec §7). Наследование прав и фильтрация данных — разные вещи.
- **Не заводит членство автоматически** — решение заказчика 3.
- **Не даёт дочерней компании отказаться** от внешнего доступа: настройка управляет ВИДИМОСТЬЮ, а не самим доступом, и правит её платформенный администратор.
- Не трогает `apps/contracts/**` и `apps/signoff/**`: если холдинговому финансисту нужны согласования в ДО, это следует из его ролей и работает само.
- Не переводит `junior/middle/senior/lead` в роли и не снимает `hr-level` — это блок I.

## Self-review (выполнен)

- **Покрытие roadmap §5.C:** механизм наследования — задачи 1, 2, 5; признак на должности — 1, 3; членство остаётся явным — задачи 3, 8 и рантбук; видимость — задача 7; документы — 9.
- **Покрытие ответов заказчика:** (1) наследование по должности — задача 5; (2) отдельный признак — задача 1, с обоснованием из документов; (3) членство явное — задачи 3 (предупреждение) и 8 (команда, напоминание, метрика); (4) настройка компании под платформенным администратором — задача 7; (5) предпросмотр и предупреждение вместо признака на роли — задача 3; (6) три инструмента против забытого членства — задача 8; (7) объединение предков и пропуск архивных — задача 5, оба пункта в списке тестов.
- **Плейсхолдеры:** в задаче 4 имя фабрики решено по ходу текста (`resolve_for`) — при исполнении тесты писать сразу с этим именем; в задачах 6 и 7 код не приведён целиком, вместо него названы состав тестов и точные решения (коды ответов, гейты, умолчания) — это осознанный размер: обе задачи повторяют формы, уже построенные в блоках A и B, и их образцы названы поимённо.
- **Согласованность имён:** `serves_subsidiaries` (1 → 2 → 3 → 5); `Resolution`/`resolve_for`/`resolution=` (4 → 5, 6); `inherited_role_scopes` (5 → 6); `show_external_holders` (7); `deny_unless_own_company`/`deny_unless_platform_admin` — из блока A, существуют.
- **Сторож `apps/access/tests/test_guards.py`** требует, чтобы каждая выборка домена несла фильтр по компании, а исключение помечалось комментарием `cross-company:` с объяснением. Запросы задачи 5 фильтруются по `company_slug` предка и под исключение не попадают; в задаче 7 переиспользуемый `holders.py` своё исключение уже имеет. Если при исполнении появится выборка без фильтра — маркер обязателен, молчаливо обойти сторожа нельзя.
- **Риск, названный явно:** задача 5 добавляет чтение чужой схемы в путь разрешения прав. Задача 4 идёт до неё именно поэтому, и её сторож на число запросов остаётся зелёным в задаче 5 — это проверяется, а не предполагается.

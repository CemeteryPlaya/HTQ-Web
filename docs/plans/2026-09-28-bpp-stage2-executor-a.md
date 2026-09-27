# БЗО, этап 2 — план после сведения 27.09 (A — Санжар, остаток B — Руслан)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Стартовая точка:** `new-module-BPP-merge` = PR #35 (Руслан) + этап 1 A с мелкими замечаниями; обе ветки её подтянули (у A — мердж `a63e501`).

**Что уже сделано к старту** (по коду сведённой ветки):

| Мастер-план | Состояние |
|---|---|
| B0–B1 (строковый `subject_id`, временные исполнители, флаги маршрута, API движка, источник сводки) | сделано |
| B2.1–B2.4 (бюджет, заявка, план закупок, «Задействовано» и ночная сверка) — бэкенд | сделано ([план B](2026-09-27-bpp-stage2-executor-b.md), отступления — [сверка §7](2026-09-26-bpp-reconciliation-B.md)) |
| B4.1 (подотчёт), B5.1 (выбор варианта — часть движка), B6.3 (снятие шаблона закупа) | сделано заранее |
| Уведомления движка через центр, документы заявки | сделано |
| A2.1 каркас фронта, A2.2 экспорт и печать, A2.3 контрагенты, A2.4 экраны справочников | **не начато — этот план** |
| B2.5 экраны бюджета, заявки, плана | ждёт A2.1 |
| Этап 3 B (договор и счёт) | ждёт A2.3 |

**Решения этого плана:**
- **Одна файловая подсистема — платформенная `apps.files`** (решение Санжара 28.09, предложение B в сверке §1.2). `DocumentFile`/`FileDownload` из `bpp` удаляются: они нигде не выкатывались. `bpp/services/core/files.py` остаётся тонкой обёрткой с прежними функциями, поэтому код заявки и подотчёта B не меняется. Сканер `BPP_FILE_SCANNER` уходит в пользу антивируса `apps.files` (флаг раздела хранилища). Это закрывает двойной крючок из сверки §7.1.
- **Узлы прав, которые предложил B** (сверка §7.3), вводятся:
  - `bpp.requests.all` — видит все заявки. Сейчас это правило «просмотр без создания»;
  - `bpp.plan.reassign` — переназначение исполнителя позиций. Сейчас это `bpp.settings:edit`.

  Смысл матрицы Алгазы не меняется: у каждой роли явная строка ровно с тем, что роль и так получала.
- **Каркас фронта строится на том, что уже есть у B:**
  - `features/bpp/format.ts` — формат денег и дат, дополняется;
  - `components/files/FilesPanel.tsx` — вкладка «Файлы»;
  - `components/signoff/SubjectProcesses.tsx`, `ProcessTimeline.tsx` — вкладка «Согласование»;
  - временная `features/bpp/DocumentPage.tsx` заменяется каркасом.

**Волны:**
- **Волна 1 (A).** Задачи 1–8 — всё, что разблокирует B.
  - Одна подсистема файлов.
  - Автоподключение подмодулей.
  - Узлы и функции интерфейсов.
  - Контрагенты — ждёт этап 3 B.
  - Экспорт и печать.
  - Каркас фронта.
  - B в это время может брать задачи этапа 3, не зависящие от контрагентов (в его плане этапа 3 — отметить).
- **Сведение** через `new-module-BPP-merge` (подтверждено 27.09).
- **Волна 2.**
  - A: задачи 9–10 — экраны справочников, проектов и контрагентов, сквозная проверка.
  - B: раздел «Остаток B» ниже — экраны B2.5 и переход документов на общие куски.

**Tech Stack:** Django 5.2.7, PostgreSQL (схема на компанию), Celery, openpyxl 3.1.5, WeasyPrint (новая), pytest-django; React 18 + TypeScript + react-query + react-router 6 (`BrowserRouter`), vitest.

**Spec:** [мастер-план](2026-09-26-bpp-master-plan.md): §1 (D-20, D-28, D-29, D-30, D-31, D-32, D-34, D-39), §2.2, §2.4, §2.6, §2.7, §5 «Этап 2»; ТЗ §05, §13.2–13.4, §16.2 п.1, §18, §19, §21, §23, §25.2, §26; [сверка B](2026-09-26-bpp-reconciliation-B.md) §1.2, §7.

---

## Global Constraints

- Интерпретатор — корневой `.venv`; команды из `backend/`: `../.venv/Scripts/python.exe …`. **Один прогон pytest за раз на машине.**
- Ветки не создавать; коммитить только файлы своей задачи. Правки в чужой зоне (§2.7: `signoff`, `files`, `bpp/services/{budget,requests,accountable}`, экраны B) — отдельным коммитом с пометкой в сообщении, B подтверждает при сведении.
- Межаппный доступ — только `apps.<x>.interface`; `require_service` первой строкой функций `interface.py` и Celery-задач; задачи тенантных аппок — `@company_task`.
- Ручки — `api_view(module=…, level=…)` с явным уровнем; тонкие права — `services/core/permissions.can` или `services/actor.Actor` (B) — у одного документа одна схема.
- Ошибки — `DomainError`; коды не пересекаются с уже занятыми B (сверка §7.3): комментарий короче 10 — код `BR-060`; «страна не найдена» — `E-REF-04`; контрагенты — `E-CTR-01…04`; экспорт — `E-EXP-01`.
- Суммы на проводе — строки; на экране — `1 250 000,00 KZT`; даты — `ДД.ММ.ГГГГ`, дата-время — `ДД.ММ.ГГГГ ЧЧ:ММ` Asia/Almaty. Округление и формат сумм на бэке — `apps/bpp/services/money.py` (B; второго модуля денег не заводить).
- Фронт: строки — `t('bpp.<ключ>', 'Русский текст')`; ошибки в `onError` — `reportApiError`; `tsc` не выше 148 ошибок.
- Миграции `bpp`, `files`, `access` — одной цепочкой поверх сведённой ветки; изменение схемы тенантной аппки — expand.
- `STRUCTURE.md`, `CLAUDE.md`, `API.md` — в задаче, что меняет структуру или ручки.

## Review Focus

1. **Файл после перехода на `apps.files`.** Заявка B прикладывает КП тем же вызовом `files.attach(...)`, что и раньше, а файл виден в `/api/files/v1` панели, журналируется с IP и user-agent и не удаляется после отправки заявки. Тест — задача 1 (`test_bpp_adapter_writes_into_apps_files`) плюс неизменённые тесты заявки B.
2. **Одновременное создание одного контрагента.** Два запроса с одной парой «страна + номер»: один создан, второй получает 422 `E-CTR-02` со ссылкой на существующего, а не 500. Тест — задача 4 (`test_parallel_duplicate_is_422`).
3. **БИН на границе.**
   - Второй проход с остатком 10 — номер недействителен.
   - Нерезидент — свободный номер до 30 символов.
   - Пробелы и дефисы отбрасываются.
   - Тест — задача 4 (`test_bin_check_*`).
4. **Граница экспорта.** 10 000 строк — файл сразу; 10 001 — фоном со ссылкой в уведомлении; 50 001 — 422; пустая выборка — только заголовки. Тест — задача 6.
5. **Двойной клик и время.**
   - Второй клик по кнопке документа не шлёт второй запрос; повтор после 5xx идёт с тем же `Idempotency-Key`.
   - `2026-09-27T20:30:00Z` показывается как `28.09.2026 01:30`.
   - Тест — задача 7.

---

## Task 1: Одна файловая подсистема — `apps.files`

**Files:**
- Modify (зона B, подтверждение при сведении): `backend/apps/files/interface.py`, `backend/apps/files/services/documents.py` — загрузка байтов из кода
- Create: миграция `files/00NN_fileevent_append_only` (триггер `BEFORE UPDATE OR DELETE` на журнале `FileEvent`, D-30 — как `bpp_auditlog`)
- Modify: `backend/apps/bpp/services/core/files.py` → обёртка над `apps.files`
- Delete: `backend/apps/bpp/models/files.py`, `backend/apps/bpp/services/core/scanner.py`; миграция `bpp/00NN_drop_document_files` (DeleteModel ×2)
- Modify: `backend/apps/media_files/services/scope_policy.py` (снять `bpp_doc` из `_POLICIES` и `RESTRICTED_SCOPES`) и два инвентарных теста media
- Modify: регистрация владельцев `bpp.*` — `backend/apps/bpp/approval_hooks.py` (зона B) или новый `backend/apps/bpp/file_owners.py` (A), вызов из `BppConfig.ready()`
- Tests: `backend/apps/files/tests/test_attach_bytes.py`, `backend/apps/files/tests/test_event_append_only.py`; переписать `backend/apps/bpp/tests/test_files.py` на обёртку

**Interfaces:**
- Produces:
  - `apps.files.interface.attach_bytes(owner_type: str, owner_id, *, file_type: str, data: bytes, filename: str, mime: str, actor_id: int | None) -> dict` — версия 1 нового документа; квоты, форматы, размер, антивирус — как у HTTP-загрузки, отказ — `FilesError` с конвертом D-28;
  - `apps.files.interface.replace_bytes(owner_type, owner_id, document_id, *, data, filename, mime, actor_id) -> dict` — новая версия документа;
  - `apps.files.interface.download_link(owner_type, owner_id, document_id, *, actor_id, ip, user_agent) -> str` — ссылка через журнал.
- Обёртка `bpp/services/core/files.py` сохраняет сигнатуры, которые уже зовёт B:
  - `attach(owner, file_type, *, data, filename, mime, actor_id) -> dict`;
  - `replace(file_id, *, data, filename, mime, actor_id) -> dict`;
  - `list_files(owner) -> list[dict]`;
  - `download_url(file_id, *, user_id) -> str`.

  Коды ошибок `E-FILE-01…04` превращаются в коды `apps.files`. Задача сверяет, какие коды проверяют тесты B, и сохраняет их через обёртку.
- `FILE_RULES` (ТЗ §21) переезжают в `FileTypeSpec` владельцев: заявка — `request_attachment`; договор, счёт и прочие — их задачи этапа 3; подотчёт — `advance_report`.

- [ ] **Step 1: Падающие тесты:**
  - `attach_bytes` создаёт документ, пишет `FileEvent` и соблюдает квоту;
  - `UPDATE` и `DELETE` строки `FileEvent` падают на уровне БД;
  - `test_bpp_adapter_writes_into_apps_files` — Review Focus 1.
- [ ] **Step 2: Реализация и перенос.** Бывшие тесты `bpp/tests/test_files.py` на лимиты, версии, отказ медиа и «сироту» в S3 переписываются на обёртку: поведение то же, хранилище `apps.files`.
- [ ] **Step 3:** `pytest apps/files apps/bpp apps/media_files apps/core/tests/test_app_isolation.py apps/core/tests/test_invariants.py` → PASS; весь набор заявки и подотчёта B — без правок тестов.
- [ ] **Step 4: Документация.**
  - `STRUCTURE.md` — строка `bpp`: файлы — через `apps.files`;
  - `CLAUDE.md` — одна подсистема файлов;
  - сверка B §1.2 — отметить решение.
- [ ] **Step 5: Коммит** — `refactor(bpp): файлы документов модуля — через платформенную apps.files, DocumentFile снят`.

## Task 2: Подмодули `bpp` подключаются сами

**Files:** `backend/apps/bpp/models/__init__.py`, `backend/apps/bpp/urls.py`, `frontend/src/features/bpp/modules.ts` + тесты `backend/apps/bpp/tests/test_autodiscovery.py`, `frontend/src/features/bpp/modules.test.ts`.

**Interfaces:**
- Бэкенд:
  - `models/__init__.py` импортирует все модули пакета и поднимает имена из их `__all__`;
  - `urls.py` подключает все `urls_*.py` (`_submodule_names()`, `_submodule_patterns()`).

  Нынешние явные строки B (`budget`, `requests`, `accountable`) заменяются автоматикой, модули B получают `__all__`.
- Фронт: `bppModules` из `import.meta.glob('./*/module.tsx', { eager: true })`, у каждого — `bppModule: { key, order, menu?, routes }`. Модуль без экспорта — ошибка сборки, а не молчаливый пропуск.

- [ ] Тесты:
  - каждый модуль пакета импортирован;
  - подставной `urls_probe` подключается;
  - маршрут `history/…` цел;
  - `collectModules` сортирует по `order`, а без `bppModule` падает.
- [ ] Коммит — `feat(bpp): подмодули подключаются сами — модели, маршруты, экраны раздела`.

## Task 3: Узлы прав и функции для уведомлений

**Files:**
- Modify: `backend/apps/bpp/access_functions.py`
- Create: `backend/apps/access/migrations/00NN_bpp_requests_all_plan_reassign.py`
- Modify: `backend/apps/project/interface.py`, `backend/apps/access/interface.py`, `docs/plans/2026-09-27-bpp-roles-matrix.md`

**Interfaces:**
- Узлы:
  - `bpp.requests.all` (`view`) — ФД, ТД, ОД, ГД, АДМ: те, у кого `bpp.requests` — просмотр без создания (сверка §7.3);
  - `bpp.plan.reassign` (`edit`) — АДМ: сейчас переназначение стоит на `bpp.settings:edit`.

  Явные строки у всех восьми ролей `bpp-*`: у остальных — пусто.
- `project.interface.member_user_ids(project_id: str) -> list[int]`.
- `access.interface.holders_of(node: str, flag: str, company: str) -> list[int]` — пользователи с признаком на узле через должности и личные назначения. Нужна B для уведомления СН и ПМ об утверждении бюджета (ТЗ §16.2 п.1, сверка §7.3 «ещё не сделано»).

- [ ] Тесты:
  - у каждой роли явная строка на обоих узлах;
  - `holders_of` находит держателя через должность и через личное назначение и не находит в другой компании;
  - `member_user_ids` — руководитель плюс участники.
- [ ] Коммит — `feat(access): узлы bpp.requests.all и bpp.plan.reassign; держатели признака и участники проекта для уведомлений`.
- **Переход сервисов B на новые узлы** — задача B в волне 2 (раздел «Остаток B»).

## Task 4: Контрагенты (A2.3)

**Files:**
- `backend/apps/bpp/models/counterparties.py`, `models/settings.py` (`ModuleSetting`) + миграция
- `backend/apps/bpp/services/counterparties/{validation,service,lookup}.py`, `services/core/settings.py`
- `backend/apps/bpp/schemas/counterparties.py`, `views_counterparties.py`, `urls_counterparties.py`, `admin.py`
- Тесты `backend/apps/bpp/tests/counterparties/`

**Модели и правила** — как в ТЗ §18 и D-20:
- `Counterparty`:
  - `kind` — `legal|ip|individual|nonresident`;
  - `country_code`, `reg_number` (UNIQUE пара);
  - НДС и свидетельство;
  - контакты;
  - `status` — `active|blocked|archived`;
  - `block_reason/at/by`;
  - `successful_documents` и `verified_override` (null — по порогу, true/false — решение ФД);
  - `ext_1c_ref`, `version`.
- `CounterpartyBankAccount` — IBAN KZ + 18, mod 97; БИК 8 или 11.
- Порог «Проверенный» — `ModuleSetting("counterparty_verified_threshold")`, по умолчанию 3.

**Interfaces (для B, этап 3)** — `services/counterparties/lookup.py`:
- `brief(ids) -> {id: {id, name, short_name, reg_number, country_code, is_vat_payer, status, is_verified}}`;
- `assert_usable(id)` — E-CTR-01 дословно ТЗ §26.1 для заблокированного, отдельный текст для архивного;
- `needs_confirmation(id) -> bool`;
- `record_success(id)` — B зовёт при «Действует»/«Исполнен» договора и «Оплачено» счёта.

**Ручки** `/api/bpp/v1/counterparties…`:
- реестр L-08 — конверт `{items, total, page, page_size}` как у реестров B, поиск по имени и номеру, фильтры «страна», «статус»; экспорт — задача 6;
- создание — `bpp.counterparties:create` (СН и ПМ тоже, ТЗ §05 п.9); правка — `edit`;
- блокировка, разблокировка и метка — `bpp.counterparties.block:edit`;
- банковские счета;
- все записывающие — `idempotent=True`, `version`.

**Ошибки:**
- `E-CTR-02` — дубль, `fields[0].existing_id`; `IntegrityError` ловится и превращается в него;
- `E-CTR-03` — неверный БИН/ИИН или номер нерезидента;
- `E-CTR-04` — IBAN или БИК;
- `BR-060` — причина блокировки короче 10;
- `E-REF-04` — страны нет в справочнике.

- [ ] Тесты:
  - Review Focus 2 и 3;
  - заблокированный → `assert_usable` E-CTR-01 с датой и причиной;
  - метка по порогу; ручное снятие ФД не перебивается порогом, возврат к порогу — `null`;
  - устаревшая `version` → 409 E-CON-01;
  - СН создаёт, но не блокирует (403);
  - неверный UUID → 404.
- [ ] Коммит — `feat(bpp): контрагенты — проверка БИН/ИИН, блокировка ФД, метка «Проверенный», функции для договоров и счетов`.

## Task 5: «Кто я» в модуле

**Files:** `backend/apps/bpp/views.py`, `backend/apps/bpp/urls.py`; тест `backend/apps/bpp/tests/test_me.py`.

**Interfaces:** `GET /api/bpp/v1/me` → `{"article_groups": [...], "initiator_roles": ["sn" | "pm", …]}` (ТЗ §23 GetCurrentUser). Правило: группа `supply` — роль `sn`, `pm` — `pm`; источник — `services/actor.Actor` B, чтобы правило было одно.

- [ ] Тесты: у СН — `["supply"]`/`["sn"]`, у совмещающего — обе, без ролей — пусто.
- [ ] Коммит — `feat(bpp): ручка «кто я» — группы статей и роли инициатора`.

## Task 6: Экспорт xlsx и печать PDF (A2.2)

**Files:**
- `backend/apps/bpp/services/core/export.py`, `services/core/printing.py`, `backend/apps/bpp/templates/bpp/print/base.html`
- `backend/apps/bpp/tasks.py` (зона B — только новая задача `export_registry`, отдельным коммитом) или `backend/apps/bpp/tasks_export.py` (A)
- вьюха `GET /api/bpp/v1/exports/<id>`
- `backend/requirements.txt` (WeasyPrint), `backend/Dockerfile`, `.github/workflows/backend-full.yml` (системные библиотеки Pango, шрифт DejaVu)

**Interfaces:**
- `export.Column(key, title, kind)` — `kind`: `text|money|decimal|date|datetime`.
- `export.respond(request, *, name, columns, rows, count, rebuild) -> HttpResponse | dict`:
  - `count ≤ 10 000` — xlsx сразу (деньги — числа с форматом `# ##0.00`);
  - больше — Celery: пересобрать выборку функцией `rebuild`, положить файл в `apps.files`/media, прислать ссылку уведомлением центра;
  - больше 50 000 — 422 `E-EXP-01` (ТЗ §19).
- `printing.render_html(template, context)`, `render_pdf(...)`, `pdf_response(..., filename)`. Базовый шаблон: место под бланк (колонтитулы — Q-B31), номер, статус, таблица, блок «Лист согласования».
- Без системных библиотек Pango на Windows-хосте тест PDF пропускается с явной причиной; HTML проверяется всегда. В Docker и CI библиотеки ставятся явно.

- [ ] Тесты: Review Focus 4; xlsx читается `openpyxl` с заголовками и числовой суммой; PDF начинается с `%PDF-`, кириллица встроена.
- [ ] Коммит — `feat(bpp): экспорт реестров в xlsx и печать документов в PDF`.

## Task 7: Фронт — формат, хуки, раздел и меню

**Files:**
- Modify: `frontend/src/features/bpp/format.ts` (B) — добавить и покрыть тестами:
  - `formatMoney` из строки без `float`;
  - `formatDateTime` в Asia/Almaty;
  - `parseMoneyInput` (ТЗ §13.2).

  Сигнатуры B сохраняются.
- Create: `frontend/src/features/bpp/core/useIdempotentAction.ts`, `useDraftAutosave.ts`, `useUnsavedChangesGuard.tsx` + тесты.
  - Роутер — `BrowserRouter`, `useBlocker` недоступен. Диалог несохранённых изменений — перехват кликов по внутренним ссылкам плюс `beforeunload`; кнопку «Назад» браузера закрывает автосохранение.
- Create: `frontend/src/features/bpp/BppLayout.tsx`, `features/bpp/approvals/module.tsx` («Мои согласования» — инбокс signoff с фильтром `bpp.*`, D-34).
- Modify: `routeDefinitions.ts`, `lazyPages.ts` (один маршрут `/bpp/*`), `navItems.ts` (пункт «Закупки и оплаты» при `atLeast('bpp', 'read')`).
- Delete: `frontend/src/features/bpp/DocumentPage.tsx` (временная рамка B). Её маршруты `/bpp/requests/:id` и `/bpp/accountable/:id` до экранов B2.5 обслуживает раздел через модули B.

- [ ] Тесты: Review Focus 5; меню по правам; «Мои согласования» — только `bpp.*`.
- [ ] Коммит — `feat(bpp): раздел «Закупки и оплаты» — меню по правам, «Мои согласования», формат и защита действий`.

## Task 8: Фронт — реестр и форма документа

**Files:** `frontend/src/features/bpp/core/BppRegistry.tsx`, `useRegistryState.ts`, `BppDocumentShell.tsx`, `StatusBadge.tsx`, `HistoryTab.tsx` + тесты.

**Interfaces:**
- `BppRegistry` — поверх конверта реестров B `{items, total, page, page_size}`:
  - серверные фильтры, сортировка, пагинация 25/50/100;
  - набор колонок и фильтров в `localStorage`;
  - массовые действия с результатом по строкам;
  - итоговая строка;
  - кнопка «Экспорт» (задача 6);
  - колонка «Сейчас у» — поле строки, его уже отдают реестры B.
- `BppDocumentShell`:
  - шапка — номер, бейдж статуса, автор, дата;
  - кнопки только из `allowed_actions`, через `useIdempotentAction`; диалог комментария ≥ 10 (BR-060);
  - вкладки — «Согласование» (`SubjectProcesses`/`ProcessTimeline` B), «Файлы» (`FilesPanel` B поверх `apps.files`) и «История изменений» (`/bpp/v1/history/<type>/<id>`);
  - встроенные автосохранение и диалог несохранённых изменений.

- [ ] Тесты:
  - кнопки вне `allowed_actions` не рисуются;
  - кнопка заблокирована на время запроса;
  - «Отклонить» с 9 символами не отправляется;
  - скрытая колонка остаётся скрытой после перемонтирования.
- [ ] Коммит — `feat(bpp): реестр и форма документа раздела`.

---

**Сведение волны 1** — PR в `new-module-BPP-merge`, обе ветки подтягивают.

---

## Task 9 (волна 2): Экраны справочников, проектов и контрагентов (A2.4)

**Files:** `frontend/src/features/bpp/refdata/module.tsx`, `projects/module.tsx`, `counterparties/module.tsx` с экранами; `ConfirmCounterpartyDialog` — окно подтверждения непроверенного контрагента для документов этапа 3.

**Правила:**
- **Справочники.** Правка только в управляющей компании: в ответы `refdata` добавить `can_edit`, кнопки правки — по нему. Архив скрыт в выборе для новых документов (`?active=1`), но виден в списке с меткой «Архив».
- **Проекты.** ПМ видит только проекты-участия (сервер).
- **Контрагенты.** Проверка БИН на фронте — тем же алгоритмом, что на сервере. СН и ПМ создают контрагента, но не блокируют.

- [ ] Коммит — `feat(bpp): экраны справочников, проектов и контрагентов`.

## Task 10 (волна 2): Сквозная проверка сводки и уведомлений

- [ ] Процесс заявки ждёт пользователя — ежедневная сводка содержит ссылку на поддомен компании; выключенный у компании `signoff` не роняет сводку.
- [ ] Отправка заявки на согласование создаёт уведомление центра с доставкой e-mail получателям этапа (события модуля — колокольчик и e-mail).
- [ ] Коммит — `test(notifications): сводка и уведомления согласования БЗО — сквозная проверка`.

---

## Остаток B (Руслан) — волна 2

По [плану B этапа 2](2026-09-27-bpp-stage2-executor-b.md) плюс то, что появилось после сведения:

| # | Что | На чём стоит |
|---|---|---|
| B-1 | **Экраны B2.5.** L-01/F-01, L-02/F-02, L-04 + мастер F-03 — как модули `features/bpp/budgets|requests|plan/module.tsx` на `BppRegistry`/`BppDocumentShell`. Вставка позиций из Excel, «Остаток после заявки» на лету, жёлтая плашка возврата. Роль инициатора — из `GET /bpp/v1/me` | задачи 2, 5, 7, 8 |
| B-2 | **Файлы документов через `apps.files`.** Владельцы `bpp.purchase_request`, `bpp.accountable_*` с типами ТЗ §21. Ручки `requests/<id>/files…` снять в пользу `/api/files/v1` и `FilesPanel`, если тесты B это позволяют | задача 1 |
| B-3 | Экспорт реестров бюджета, заявок и плана; печать заявки с листом согласования | задача 6 |
| B-4 | Сервисы заявки и плана — на узлы `bpp.requests.all` и `bpp.plan.reassign` вместо обходных правил | задача 3 |
| B-5 | Уведомление СН и ПМ об утверждении бюджета (ТЗ §16.2 п.1) | задача 3 (`holders_of`, `member_user_ids`) |
| B-6 | Реестры: страница по умолчанию — 50 строк (ТЗ §19); сейчас в `read.py` — 25 | — |
| B-7 | Этап 3 (договор и счёт) — после сведения волны 1: нужен `services/counterparties/lookup.py` | задача 4 |

## После этапа

- [ ] Весь бэкенд (без `ci-known-failures.txt`) и `npx vitest run` зелёные, кроме падений, воспроизводящихся на базовом коммите (8 тестов `hr` — известны).
- [ ] Финальное ревью ветки отдельным ревьюером; важные замечания — исправить, мелкие — отдельным планом.
- [ ] PR в `new-module-BPP-merge`.

# БЗО — отступления исполнителя B от плана (к общей сверке)

Исполнитель B — Руслан, ветка `new-module-BPP-ruslan`. Порядок работы (Санжар, 26.09): один план, в процессе части расходятся, сверка с [мастер-планом](2026-09-26-bpp-master-plan.md) — общая, когда свои части закончены. Здесь — всё, что на этой сверке надо увидеть: что сделано не так, не там или раньше, чем в плане. Пополняется по ходу работы.

## 1. Сделано до старта этапов

Работа, начатая до плана и подогнанная под него 26.09.

### 1.1 Варианты голоса в `signoff` — часть B1.3

- **Что сделано.** Механизм «выбор варианта»:
  - `register_subject(..., options=, check_option=, on_option=)`;
  - `ApprovalTask.option_key` / `option_label`, миграция `signoff/0011_task_option`;
  - «согласовать» без варианта или с неизвестным вариантом — 422;
  - итог — голос последнего этапа, `interface.final_option`;
  - тесты — `apps/signoff/tests/test_options.py`.

  Имена и сигнатура `on_option(subject_id, stage_order, user_id, option_key)` — по §2.6. Сверх плана — `check_option`: предмет может отвергнуть голос своей причиной.
- **Чего нет из B1.3:** `decide_many` (с `option_key` на элемент), `current_holders`, `pending_for_user`, `start_process(preapproved=…)`.
- **Отступление от D-25/D-26.** Вариант сейчас обязан назвать **каждый** этап, как в ТЗ §12.4. По плану голосуют только ФД и ГД. Как отличить их этапы — решить в B5.1.
- **Потребителей нет.** Черновая реализация альтернатив в `contracts` снята (§3).

### 1.2 Файловая подсистема `apps.files` — пересекается с A1.1

- **Что это.** Платформенная аппка в `public` (`/api/files/v1`), а не `DocumentFile` внутри `bpp`, как в A1.1. Что в ней есть:
  - справочник «Типы файлов», таблица `file_object`, версии («номер один раз», «Заменён», 409 `E-CON-01`);
  - SHA-256 и `Idempotency-Key`;
  - журнал `FileEvent`: загрузка, версия, удаление, выдача ссылки — с IP и user-agent (ТЗ §25.2);
  - ссылка на скачивание — только через ручку, которая пишет журнал;
  - компания в ключе у тенантного владельца;
  - конверт ошибок D-28;
  - ключ владельца — строка (UUID, D-05);
  - xml принимается и отдаётся вложением (D-31, Q-C28).

  Владельцев в коде нет, тесты идут на пробных (`apps/files/tests/testapp`).
- **Предложение к сверке.** A1.1 берёт `apps.files` за основу, а не пишет вторую таблицу версий: документы `bpp` регистрируются владельцами через `apps.files.interface.register_owner` (с `model=` для UUID), их типы — миграцией `bpp`. Решение — за Санжаром.
- **Решение 28.09 (Санжар): apps.files, `DocumentFile` снят.** Одна файловая подсистема на платформу (план этапа 2 A, задача 1) — предложение выше принято как есть: `bpp/models/files.py` (`DocumentFile`, `FileDownload`) и `services/core/scanner.py` удалены миграцией `bpp/0007_drop_document_files`, `services/core/files.py` стал тонкой обёрткой над `apps.files.interface.attach_bytes/replace_bytes/download_link/find_version` с прежними сигнатурами, владельцы — `apps/bpp/file_owners.py` (`bpp.purchase_request`, `bpp.advance_report`), их типы — миграция `files/0003_bpp_file_types`. Заодно закрыто и «чего нет» ниже: загрузка байтов из кода владельца (не только HTTP) и триггер БД «только вставка» у `FileEvent` (`files/0002_fileevent_append_only`, как `bpp_auditlog`) — сделаны той же задачей.
- **Чего нет относительно A1.1 / §2.6:**
  - внутрипроцессной загрузки байтов `attach(owner, file_type, *, data, filename, actor_id)`. Есть HTTP-загрузка и `adopt_media_file` — перенос уже лежащего в media файла, он пригодится B6.1;
  - триггера БД «только вставка» у `FileEvent` (D-30 — это про `AuditLog` A1.1; журнал файлов защищён только кодом).
- **Гейт.** Правка справочника — `api_view(module="files", level="write")` (узел `files.types`); остальные ручки — в `access/self_service.py` (`scoped` / `open`); `files` добавлена в `TRANSLATED_APPS`. Диспетчеры `urls.py` переписаны в форму, которую признаёт сторож `test_gate.py`.

### 1.3 ClamAV — по сути A7.4

Клиент `htqweb/antivirus.py` (INSTREAM), сервис `clamav` во всех трёх compose-файлах и флаг `ScopePolicy.antivirus` в `media_files`. По D-31 **выключен по умолчанию**: `ANTIVIRUS_CLAMD_HOST` пуст, сервис стоит под профилем `antivirus`. Включение — `.env` + `--profile antivirus`.

## 2. Правки в зоне исполнителя A (§2.7, правило 5)

Все нужны `apps.files` / ClamAV, на сверке их просмотреть:

| Файл | Что |
|---|---|
| `backend/apps/core/models.py`, `core/services.py` | сервис `files` в `KNOWN_SERVICES` и `CORE_MODULES` |
| `backend/htqweb/middleware/service_gate.py` | префикс `/api/files/` → `files` |
| `backend/htqweb/settings/base.py`, `settings/test.py` | `INSTALLED_APPS`, `FILES_UPLOAD_CEILING_MB`, `ANTIVIRUS_*`, тестовая аппка файлов |
| `backend/htqweb/http.py` | `ApiError`: отказ со своим статусом вместо 500 (отказы пайплайна media сквозь чужие вьюхи) |
| `backend/htqweb/antivirus.py` | клиент clamd |
| `backend/apps/access/self_service.py` | `files` в `TRANSLATED_APPS` + записи `SELF_SERVICE["files"]` |
| `backend/apps/access/migrations/0013_grant_files_module.py` | `platform-admin` получает модуль `files` |
| `backend/apps/media_files/**` | scope `file_object` (папка владельца, `owner_gated`, xml), `copy_file`, флаг антивируса по scope, сигнатуры xml/OOXML |
| `backend/apps/companies/management/commands/tenancy_bootstrap.py` | `files.assign_company` в транзакции переноса |
| `backend/apps/companies/services/migration_service.py` | `signoff/0014_retry_no_executor_periodic_task` в `SHARED_EFFECT_MIGRATIONS` (расписание beat живёт в `public`, этап 1, B1.2) |
| `docker-compose*.yml`, `.env.example`, `infra/nginx/default.conf`, `frontend/vite.config.ts`, `frontend/src/api/endpoints.ts` | сервис `clamav`, локация `/api/files/v1/` (21M), прокси |

## 3. Снято по D-01 (в ветке этого нет)

Черновая работа до плана, противоречащая D-01, убрана. Код не потерян — он лежит в `git stash` у Руслана, его можно взять как образец:

- **альтернативы §12 и KPI в `contracts`** (модели, миграция `0028`, сервисы, экраны `/contracts/alternatives`, `/contracts/kpi`) — по плану это A5.1, B5.1, A5.2 в `bpp`;
- **файлы договора в `contracts`** (владелец `contracts.agreement`, файл «Договор» обязателен к отправке, команда `migrate_agreement_files`) — по плану B3.1;
- **файлы заявки в `approvals`** (владелец `approvals.request`) — по плану B2.2 (типизированная заявка `bpp`).

## 4. Миграции и номера

- `signoff/0011` занята вариантами голоса, поэтому миграция B0.1 (строковый `subject_id`) — **`0012_process_subject_id_string`**, а не `0011`, как в плане этапа 0.
- `access/0013_grant_files_module` (B) и `access/0013_platform_admin_bpp_modules` (A0.2) — один номер. При слиянии: `makemigrations access --merge` или включить `files` в миграцию A и удалить эту.
- B0.1 провёл ключ через `native_id` / `storage_key` и в функциях вариантов голоса: `options_for`, `check_option_for`, `on_option_for`, `final_option` — в плане этапа 0 их нет (писался от `main`). Тест сверх плана — `test_vote_options_reach_a_uuid_subject_in_its_key_type`.

## 6. Этап 1 — отступления и решения ([план этапа](2026-09-26-bpp-stage1-executor-b.md))

- **B1.2, флаги заданы должностями, а не ролями.** В мастер-плане — `no_executor_notify_roles`. В словаре `signoff` «роль» — HR-должность, а у `access.interface` нет функции «держатели роли». Поэтому флаг называется `no_executor_notify_position_ids`.
- **Два флага сверх четырёх из плана:**
  - `escalation_position_id` — кому уходит группа автора при самосогласовании (ГД, BR-061 «иначе ГД»);
  - `self_skip_notify_position_ids` — кого уведомить, когда автор — сам ГД (ФД, D-22).

  В плане это описано словами, но флагом не названо.
- **B1.2, права на маршруты БЗО** (ФД и АДМ, В-09) отложены до ролей A1.4. До этого правка маршрутов остаётся за администратором.
- **B1.2, BR-060 для «Отменить».** Правило касается и отмены автором. Но `engine.cancel` комментария не принимает, поэтому проверку делает предметная ручка `bpp` (B2.2, B3.2).
- **B1.3, «Сейчас у» — ключ сверх контракта §2.6.** В ответе `current_holders` есть ещё `no_executor` (bool). Без него реестр не отличил бы этап «Нет исполнителя» от этапа, у которого просто пуст список людей.
- **B1.3, `preapproved` хранится на процессе** (`ApprovalProcess.preapproved`, та же миграция `0013`). Иначе ленивый маршрут поставил бы задачи предсогласованной должности при активации этапа. Формат элемента — `{position_id, actor_id, label}`: этап определяется должностью, а не порядковым номером, потому что маршрут настраиваемый.
- **B1.2, время активации этапа.** `ApprovalProcessStage.activated_at` заведено уже в миграции `0013` — нужно для «Сейчас у» (B1.3).

## 7. Этап 2 — сделано заранее

- **B2.5, строковый id в карте представлений** (27.09, пока ждём A0.2/A1.1). В плане этапа 2 — `SubjectViewProps.id: SubjectId`. Сделано иначе: `id: string` — ключ, как его хранит signoff. Представления старых доменов (`id: number`) подключены переходником `intKeyed`, документы БЗО — через `stringKeyed`. С `SubjectId` каждое старое представление пришлось бы переписать на объединённый тип, а TypeScript не принял бы `ComponentType<{id: number}>` в карту с `{id: number | string}`.

## 7. Слияние с веткой A и этап 2 ([план этапа](2026-09-27-bpp-stage2-executor-b.md))

### 7.1 Слияние

- **Ветка A вмержена в B локально 27.09, по просьбе Руслана — ради кода этапа 2.** Правило 2 мастер-плана в редакции A (26.09) говорит: «Исполнители не мерджат ветки друг друга», когда синхронизировать — решает пользователь. Без фундамента A (`BppModel`, `refdata`, `project`, роли) код этапа 2 не написать и не проверить, поэтому слияние сделано, но **не отправлено**. Если ветка `new-module-BPP-merge` — это общая точка слияния, то после неё ветка B вливается в неё без повторного разбора конфликтов.
- **Конфликты (8 файлов) — объединение обеих сторон:**
  - списки аппок: `core/models.py`, `core/services.py`, `access/self_service.py`, `frontend/vite.config.ts`, `CLAUDE.md`;
  - `htqweb/http.py`: идемпотентность и `DomainError` из A, после них — `ApiError` из B (через него отказы пайплайна media проходят сквозь чужие вьюхи своим статусом);
  - `media_files/services/scope_policy.py` и его тест: оба scope — `file_object` (B, `apps.files`) и `bpp_doc` (A, `DocumentFile`).
- **Миграция `access/0013_grant_files_module` (B) перенумерована в `0016_grant_files_module`** и зависит от `0015_project_all_node` (A). Ни одна из них не выкатывалась.
- **Две подсистемы файлов (к §1.2) — решено 28.09.** A сделал `DocumentFile` внутри `bpp` (scope `bpp_doc`, `FileDownload`, `scanner.scan` через `BPP_FILE_SCANNER`), у B — платформенная `apps.files`. Решение (см. §1.2): `apps.files`, `DocumentFile` снят вместе со scope `bpp_doc` и `BPP_FILE_SCANNER` — один антивирус на платформу (флаг `ScopePolicy.antivirus` у scope `file_object`), документы этапа 2 (заявка, подотчёт) прикладываются через обёртку `services/core/files.py` без изменения кода B.
- **Источник сводки `signoff` включён после слияния.** Регистрирует `holders.digest_items` (в `SignoffConfig.ready()`, только если установлена `apps.notifications`), а не голый `pending_for_user`: у строки сводки нужен заголовок с этапом и ссылка, даже когда предмет не отдаёт своих (тогда — карточка процесса). Выключенный у компании `signoff` отдаёт пустой список, а не ошибку источника.

### 7.2 Правки в зоне A для этапа 2 (правило 5)

| Файл | Что |
|---|---|
| `backend/apps/bpp/models/__init__.py` | импорт `budget.py` и `requests.py` |
| `backend/apps/bpp/urls.py` | `include` `urls_budget` и `urls_requests` |
| `backend/apps/bpp/apps.py` | `ready()` → `approval_hooks.register()` (мастер-план §2.2) |
| `backend/apps/companies/services/migration_service.py` | `bpp/0004_committed_check_periodic_task` в `SHARED_EFFECT_MIGRATIONS` |

### 7.3 Этап 2 — отступления и решения

- **`allowed_actions` — в сервисе каждого документа** (`services/budget/budgets.py`, `services/requests/requests.py`), поверх `permissions.can`. Так и записано в плане этапа 1 A: общего `allowed_actions` нет.
- **Кто видит все заявки.** ТЗ §7.1: ТД, ОД, ФД, ГД — все, СН и ПМ — свои. Отдельного узла нет, поэтому правило такое: `view` на `bpp.requests` без `create`. Предложение — узел `bpp.requests.all` (как `bpp.plan.all`, `project.all`).
- **Переназначение исполнителя позиций** — узел `bpp.settings` (`edit`), а не `bpp.plan`. У роли `bpp-adm` нет `bpp.plan`, а `edit` на нём есть у СН и ПМ. Предложение — узел `bpp.plan.reassign`.
- **Коды ошибок сверх каталога ТЗ §26.1:**
  - `E-BUD-03` — статьи нет в бюджете;
  - `E-BUD-04` — утверждение с Σ = 0;
  - `E-BUD-05` — удаление строки в корректировке;
  - `E-BUD-06` — закрытие при заявках на согласовании;
  - `E-REQ-02` — больше 200 позиций;
  - `E-PLAN-01` / `E-PLAN-02` — остаток 0 / позиции недоступны;
  - `E-STATE-01` — действие в неподходящем статусе (409);
  - `E-SGN-01` — отказ движка при отправке (409);
  - `E-PRJ-03` — проект не активен;
  - `E-REF-03` — статья в архиве;
  - `E-VAL-01` — формат поля;
  - `E-NOT-FOUND` — 404.

  У правил без кода в ТЗ код — номер правила (`BR-001`, `BR-002`, `BR-004`, `BR-021`, `BR-060`). `E-PRJ-01` и `E-REF-01` у A заняты другим смыслом, поэтому у B — `03`.
- **Позиция черновика — либо полная, либо её нет.** ТЗ §7.7 разрешает сохранять черновик без обязательных полей, кроме проекта. Для шапки так и сделано, но позиция без количества, цены или единицы не хранится: ограничения БД (`qty > 0`, `price > 0`).
- **Корректировка бюджета:** строку действующей версии удалить нельзя, только уменьшить лимит (ТЗ §6.4, строже плана этапа 2 — «нельзя, если задействовано > 0»).
- **Закрытие бюджета** проверяет только заявки на согласовании; неоплаченные счета — с этапа 3.
- **Ещё не сделано в этапе 2:**
  - печать PDF (ждёт A2.2);
  - экспорт реестров (A2.2);
  - экраны B2.5 (ждут A2.1);
  - уведомление СН и ПМ об утверждении бюджета (ТЗ §16.2 п.1): нет функции «участники проекта» в `project.interface` и «держатели роли» в `access.interface`;
  - метрика `htqweb_bpp_committed_mismatch_total` — вместе с панелью A3.2, до этого только `fallback`.

### 7.4 Сделано после этапа 2, пока ветка A не продвинулась (27.09)

Этап 3 ждёт контрагентов A2.3, поэтому взяты задачи без этой зависимости:

- **Документы заявки** (`services/requests/files.py`) — поверх `services/core/files.py` A, тип `request_attachment`. Подтипа «КП / ТЗ / спецификация / прочее» у `DocumentFile` нет — один тип на все. Удаления в ядре файлов нет — добавить в A1.1, если нужно удалять файл черновика.
- **Уведомления движка — через центр уведомлений** (B1.2 после A1.5). Колокольчик фронта слушает события `notification` центра, а прямые события мессенджера `signoff.*` не показывает никто. Тексты — описание документа + событие (`engine._CENTER_TITLES`). Без центра — по-старому, мессенджером.
- **Подотчёт B4.1** раньше этапа 4: зависит только от B2.4.
  - Номер `ПО-ГГГГ-NNNNNN` — сверх перечня номеров §2.5.
  - «Видит все» — как у заявок: просмотр без права создавать.
  - Маршруты подотчёта и авансовых отчётов не заводятся командой: в ТЗ их нет, настраивает администратор.
  - Экраны — после A2.1.
- **B5.1, часть движка:** признак этапа `votes_option` (`signoff/0015`) — вариант выбирают только отмеченные этапы, решает последний из них (ГД). Предметная часть (выбор АП, KPI) ждёт A5.1.
- **B6.3:** команда `retire_purchase_request_template` (в `approvals`). Запускать при выкатке, после переноса данных.
- **Правка в зоне A:** `backend/apps/bpp/services/core/files.py` — тип файла `advance_report` (PDF/JPG/PNG, 10 МБ, 1 на отчёт).
- **Страницы документа по прямой ссылке до каркаса A2.1.** `/bpp/requests/:id` и `/bpp/accountable/:id` вели в 404, а на них ссылаются согласование и колокольчик. Временная рамка — `frontend/src/features/bpp/DocumentPage.tsx` (гейт `bpp:read`). Каркас раздела заменит её своей.
- **Правка в зоне A (фронт):** `frontend/src/lib/auth/modules.ts` — в зеркало `KNOWN_SERVICES` добавлены `files`, `bpp`, `project`, `refdata`, `notifications`. Без них сторож маршрутов не принимал гейт `bpp`, а редактор ролей, по комментарию в файле, при сохранении снимал бы уровень по незнакомым модулям. Переводы `access.modules.*` для них не добавлены (D-39).

## 5. Прочее

- **Handoff этапа 0 отложен до сверки.** B0.1 и B0.2 сделаны (коммиты `2da6b53`, `e94f906`), но шаг 9 плана этапа 0 не выполнялся: слияние `origin/new-module-BPP-sanzhar` и прогон сторожей (`apps/core/tests`, `apps/access/tests`, `apps/signoff/tests`, `test_module_service.py`, `vitest`) переносятся на общую сверку (порядок работы Санжара от 26.09). На 26.09 в ветке A был только коммит с планами.
- `approvals/services/instance_service.py`: PATCH черновика заявки — под `select_for_update` и `update_fields`, чтобы не затирать параллельную отправку. Исправление гонки, не новая функциональность.
- **Известные падения, не от этой ветки.** 8 тестов vitest в `src/components/hr/__tests__/` (`CardT2SectionDialog`, `EmployeeFormDialog`: не находится поле «Оклад»). Файлы и переводы `hr` здесь не менялись — падения есть и на `main`.

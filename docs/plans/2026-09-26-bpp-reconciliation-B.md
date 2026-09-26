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

## 5. Прочее

- **Handoff этапа 0 отложен до сверки.** B0.1 и B0.2 сделаны (коммиты `2da6b53`, `e94f906`), но шаг 9 плана этапа 0 не выполнялся: слияние `origin/new-module-BPP-sanzhar` и прогон сторожей (`apps/core/tests`, `apps/access/tests`, `apps/signoff/tests`, `test_module_service.py`, `vitest`) переносятся на общую сверку (порядок работы Санжара от 26.09). На 26.09 в ветке A был только коммит с планами.
- `approvals/services/instance_service.py`: PATCH черновика заявки — под `select_for_update` и `update_fields`, чтобы не затирать параллельную отправку. Исправление гонки, не новая функциональность.
- **Известные падения, не от этой ветки.** 8 тестов vitest в `src/components/hr/__tests__/` (`CardT2SectionDialog`, `EmployeeFormDialog`: не находится поле «Оклад»). Файлы и переводы `hr` здесь не менялись — падения есть и на `main`.

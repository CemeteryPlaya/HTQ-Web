# БЗО, этап 3 — план исполнителя A (Санжар, ветка `new-module-BPP-sanzhar`)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Всё, что нужно исполнителю B для договора и счёта (ТЗ §09–§10), плюс своя часть этапа 3:
- типы файлов договора и счёта в `apps.files`;
- счета организации и шаблоны выписок;
- загрузка выписки — перенесена сюда из этапа 4, см. решение D-S3-2;
- метрики и дашборд БЗО;
- раздел ежедневной сводки о закрывающих документах.

**Стартовая точка:** `new-module-BPP-merge` после сведения волны 1 этапа 2. Туда входят PR #36 (Руслан, волна 1 B) и PR этапа 2 A (задачи 1–10, мердж с #36 — merge-миграция `bpp/0009`). Обе ветки подтягивают её до старта.

**Architecture:** Новые подмодули A — `bank`: `models/bank.py`, `services/bank/`, `views_bank.py`, `urls_bank.py` за рубильником `bpp_bank`. Модели регистрируются автоподключением `models/__init__.py` и `urls.py` из этапа 2, общих строк с B нет. Файлы выписки лежат в `apps.files` (владелец `bpp.bank_import`). Разбор файла идёт в Celery (`@company_task`), экран опрашивает состояние загрузки. Метрики модуля — `apps/bpp/metrics.py` по конвенции `apps/core/metrics.py`: сбор по компаниям, метка `company`.

**Tech Stack:** Django 5.2.7, PostgreSQL (схема на компанию), Celery, openpyxl 3.1.5, pytest-django; React 18 + TypeScript + react-query, vitest; Grafana provisioning (JSON-дашборды, alerting YAML).

**Spec:**
- [мастер-план](2026-09-26-bpp-master-plan.md) — §1 (D-13, D-27, D-30, D-32), §2.4, §2.6, §2.7, §5: этап 3 (A3.1, A3.2) и этап 4 (A4.1);
- ТЗ — §11.1–11.3, §15.5, §18 (строка «Банковские счета организации и шаблоны выписок»), §19 (L-07), §21, §22, BR-075, E-IMP-01;
- [план B этапа 3](2026-09-27-bpp-stage3-executor-b.md) — контракты B3.2, которые здесь потребляются.

---

## Что уже сделано к старту

| Мастер-план | Состояние |
|---|---|
| A0–A2 (каркас, ядро, справочники, проекты, роли, центр уведомлений, фронт-каркас, экспорт и печать, контрагенты, экраны) | сделано |
| B0–B2.4, B4.1 (бэкенд бюджета, заявки, плана, «задействовано», подотчёт) | сделано |
| B2.5 (экраны бюджета, заявки, плана) и остаток B этапа 2 (B-1…B-6) | в работе у B — волна 2 этапа 2 |
| B3.1–B3.3 (договор, счёт, «задействовано» полностью) | не начато, [план B](2026-09-27-bpp-stage3-executor-b.md) |
| A3.1, A3.2 | **не начато — этот план** |
| A4.1 (загрузка выписки) | **перенесено в этот план** |

## Решения этого плана

**D-S3-1. Файлы договора и счёта заводит A, колбэки прав пишет B.**
- План B этапа 3 прикладывает файлы через `services/core/files.py`. После перехода на `apps.files` (этап 2 A, задача 1) типы файлов и владельцы регистрируются в `apps.files`.
- A заводит типы §21 в справочнике `files` (одна миграция) и автоподключение владельцев. Модуль `services/<подмодуль>/file_owner.py` с функцией `register()` подхватывается сам, так же как `models/*.py` и `urls_*.py`. Строку в `file_owners.py` под новый документ править не нужно.
- B пишет `services/agreements/file_owner.py` и `services/invoices/file_owner.py` со своими правилами прав.

**D-S3-2. Загрузка выписки (A4.1) переезжает в этап 3.**
- На этапе 3 у A две небольшие задачи, у B — две большие. A4.1 зависит только от A3.1: ей нужны счёт организации и шаблон, счета B не нужны.
- Сверка A4.2 остаётся в этапе 4: ей нужны `Invoice`, `find_by_number` и поля сверки из B3.2.
- Строки выписки поэтому загружаются в статусе «Не сопоставлена», а загрузка — в статусе «Загружена». «Сверена» появится вместе с A4.2.

**D-S3-3. Примеров выписок ещё нет (В-13, Q-B26).**
- Разбор 1CClientBankExchange пишется по стандарту формата. Имена полей берутся с синонимами казахстанского варианта: `ПлательщикСчет`/`ПлательщикИИК`, `ПолучательИНН`/`ПолучательБИН`/`ПолучательИИН`, `ДатаСписано`/`Дата`.
- Excel и CSV разбираются только через шаблон, и шаблон ведёт АДМ. Код не знает ни одного банка.
- Когда примеры появятся в `docs`, правка ограничится шаблоном или словарём синонимов. Прогон примеров — пункт сведения.

**D-S3-4. Метрика ночной сверки не пересчитывает её каждую минуту.**
- Сбор метрик идёт раз в 60 с, а эталонный пересчёт «Задействовано» стоит дорого.
- Ночная задача B2.4 пишет итог (число расхождений и время) в строку `ModuleSetting`, а `metrics.collect()` читает эту строку.
- Файл `services/budget/check.py` принадлежит B. Правка — одна строка записи итога, отдельным коммитом с пометкой «зона B».

---

## Global Constraints

- Интерпретатор — корневой `.venv`; команды из `backend/`: `../.venv/Scripts/python.exe …`. **Один прогон pytest за раз на машине.**
- Ветки не создавать; коммитить только файлы своей задачи. Правки в зоне B (`services/budget/*`, `signoff`, экраны B) — отдельным коммитом с пометкой; B подтверждает при сведении.
- Межаппный доступ — только `apps.<x>.interface`. `require_service` — первой строкой функций `interface.py` и Celery-задач. Задачи тенантной аппки — `@company_task` с `company_slug`.
- Ручки — `api_view(module="bpp", level=…)` с явным уровнем. Тонкие права — узлы `bpp.bank` (ФД — всё, БУХ — просмотр) и `bpp.settings` (АДМ) через `services/core/permissions.can`.
- Модели — `BppModel`: UUID, created/updated, `version` у изменяемых документов.
- Ошибки — `DomainError` с текстами ТЗ дословно. Новые коды:
  - `E-IMP-01` — не тот формат файла;
  - `E-IMP-02` — не найдена обязательная колонка шаблона;
  - `E-IMP-03` — в файле больше 10 000 строк;
  - `E-BNK-01` — IBAN организации уже заведён.

  Занятые коды: `BR-060`, `E-REF-*`, `E-CTR-*`, `E-EXP-01`, `E-FIL-*` и коды B.
- Деньги — `Decimal`, никогда не `float`. Числовая ячейка xlsx приходит из openpyxl как `float`, поэтому переводится через `Decimal(repr(value)).quantize(Decimal("0.01"), ROUND_HALF_UP)`, а текст с запятой и пробелами — через разбор строки.
- Фронт:
  - строки — `t('bpp.<ключ>', 'Русский текст')`;
  - ошибки — `reportApiError`;
  - селект из запроса объясняет пустоту через `PrerequisiteNotice` (сторож `lib/ux/__tests__/uxContract.test.ts` — гонять **полным** vitest, не только раздел);
  - `tsc` — не выше 148 ошибок.
- Метрика попадает в код только вместе с панелью или правилом (`test_metrics_are_observed`); тенантные метрики — с меткой `company` и переменной «Компания» на дашборде.
- `STRUCTURE.md`, `CLAUDE.md`, `API.md` — в той задаче, которая меняет структуру или ручки.

## Review Focus

1. **Грязный файл 1С.** Кодировка CP1251 и CRLF. Строка с датой «31.02.2026» уходит в список ошибок с номером строки, остальные строки загружаются. Файл без `1CClientBankExchange` → 422 `E-IMP-01`. Тест — задача 3 (`test_onec_*`).
2. **Повторная загрузка той же выписки.** Второй раз — «Пропущено дублей: N», новых строк 0. Две одновременные загрузки одного файла — дублей в базе нет: уникальный `dedup_hash` плюс перехват `IntegrityError`, а не 500. Тест — задача 3 (`test_reupload_skips_duplicates`, `test_parallel_upload_no_duplicates`).
3. **Шаблон по заголовкам.**
   - Колонки читаются в любом порядке.
   - Заголовок может стоять не в первой строке.
   - Лишние колонки игнорируются.
   - Нет обязательной колонки → `E-IMP-02` с её названием.
   - Сумма «1 250 000,00» строкой и 1250000.1 числом ячейки дают `Decimal` без потерь.
   - Тест — задача 2 (`test_template_*`) и задача 3.
4. **Только списания своего счёта.**
   - Поступления (кредит) не загружаются.
   - Документ, где плательщик — другой счёт, не загружается.
   - Итог показывает «списаний N из M строк».
   - Тест — задача 3.
5. **Сводка и метрики не падают из-за одной компании.**
   - `bpp` выключен у компании — сводка остальным уходит, коллектор метрик собирает остальные компании.
   - У автора без счетов «Ждёт закрывающих» раздела в сводке нет.
   - Тест — задачи 4 и 8.

---

## Волны

- **Волна 1 (A)** — задачи 1–6:
  - задача 1 — первой и отдельным коммитом, её ждёт B для B3.1;
  - B параллельно ведёт B3.1–B3.3 и B2.5.
- **Сведение** через `new-module-BPP-merge` после бэкенда B3.1–B3.2. Условие — handoff B этапа 3 п.4: `find_by_number`, поля сверки, `closing_docs_pending_for_user`.
- **Волна 2 (A)** — задачи 7–9, на моделях счёта B.

---

## Task 1: Файлы договора, счёта и выписки в `apps.files` (для B)

**Files:**
- Create: `backend/apps/files/migrations/0004_bpp_stage3_file_types.py` — типы §21 (таблица ниже), идемпотентно, как `0003_bpp_file_types`.
- Modify: `backend/apps/media_files/services/scope_policy.py` — scope `file_object` получает `text/plain` и `text/csv`. Это отложенное замечание этапа 2, нужное выписке. Инвентарные тесты media — тоже.
- Modify: `backend/apps/bpp/file_owners.py` — `register()` после своих владельцев подхватывает `apps/bpp/services/*/file_owner.py` и зовёт у каждого `register()`. Порядок — по алфавиту, нет функции → `ImproperlyConfigured` с именем модуля.
- Tests: `backend/apps/bpp/tests/test_file_owner_discovery.py`, дополнение `backend/apps/files/tests/` — типы на месте, форматы и размеры по таблице.

| Тип | Форматы | МБ | Шт. | Владелец (кто регистрирует) |
|---|---|---|---|---|
| `agreement` — договор | PDF DOCX JPG PNG | 20 | 1 (+ версии) | `bpp.agreement` (B) |
| `agreement_annex` — приложение | PDF DOCX JPG PNG | 20 | 30 | `bpp.agreement` (B) |
| `invoice` — счёт на оплату | PDF JPG PNG | 10 | 5 | `bpp.invoice` (B) |
| `act` — АВР | PDF JPG PNG | 10 | 10 | `bpp.invoice` (B) |
| `waybill` — накладная | PDF JPG PNG | 10 | 10 | `bpp.invoice` (B) |
| `vat_invoice` — счёт-фактура | PDF JPG PNG XML | 10 | 10 | `bpp.invoice` (B) |
| `bank_statement` — выписка | TXT XLSX CSV | 20 | 1 | `bpp.bank_import` (A, задача 3) |

Тип `alternative_offer` (КП альтернативы) — с A5.1.

**Interfaces:**
- Produces для B — модуль `apps/bpp/services/<подмодуль>/file_owner.py` с функцией `register() -> None`, которая зовёт `apps.files.interface.register_owner(...)`. Колбэки владельца — те же, что у `bpp.purchase_request` в `file_owners.py`: видимость, право менять, «отправлялся ли», блокировка строки. Образец — владелец заявки.
- Правила §21 (1 действующий + версии, лимиты) — `FileTypeSpec` в `register()` владельца.

- [ ] **Step 1: Падающие тесты:**
  - типы из таблицы есть в справочнике с форматами и размерами;
  - `text/csv` принимается scope `file_object`;
  - пробный модуль `services/probe/file_owner.py` в тесте (monkeypatch `pkgutil`) регистрируется сам;
  - модуль без `register` → `ImproperlyConfigured`.
- [ ] **Step 2: Реализация**, прогон `apps/files apps/media_files apps/bpp/tests/test_files.py apps/bpp/tests/test_file_owner_discovery.py` + сторожа.
- [ ] **Step 3: Документация:** `STRUCTURE.md` (строка `files`, строка `bpp`), `CLAUDE.md` (абзац о `apps.files` — владельцы этапа 3 и автоподключение), мастер-план §2.6 — контракт `file_owner.register()`.
- [ ] **Коммит** — `feat(bpp): типы файлов договора, счёта и выписки; владельцы файлов подключаются сами`. Написать Руслану: B3.1 может прикладывать файлы.

## Task 2: Счета организации и шаблоны выписок (A3.1)

**Files:**
- Create: `backend/apps/bpp/models/bank.py`:
  - `StatementTemplate` (`BppModel`, `version`): `name`, `format` (`onec`/`xlsx`/`csv`), `encoding` (по умолчанию `cp1251` для 1С и CSV, `utf-8` для xlsx), `delimiter` (CSV), `date_format`, `columns` (JSON: поле → текст заголовка), `amount_mode` (`signed` — одна колонка суммы со знаком; `split` — колонки «Дебет» и «Кредит»), `is_active`.
  - `OrgBankAccount` (`BppModel`, `version`): `iban` (проверка — `services/counterparties/validation.iban`, уникален), `bank_name`, `bic`, `currency`, `template` (FK `PROTECT`), `is_active`.
  - `__all__`.
- Create: `backend/apps/bpp/services/bank/settings.py` (CRUD, архив вместо удаления, аудит) и `services/bank/templates.py`:
  - `resolve_columns(header_row, template) -> dict[field, index]` — поиск строки заголовка в первых 30 строках, регистр и пробелы не важны;
  - `preview(file, template) -> {columns, rows[:20], errors}`.
- Create: `backend/apps/bpp/views_bank.py`, `urls_bank.py`:
  - `bank/accounts` GET/POST, `bank/accounts/<id>` GET/PATCH;
  - `bank/templates` GET/POST, `bank/templates/<id>` GET/PATCH;
  - `bank/templates/<id>/preview` POST (файл образца, без сохранения).

  Чтение — `bpp.bank` view или `bpp.settings`; запись — `bpp.settings` edit (АДМ).
- Миграция `bpp/00NN_bank_settings` (генерирует контроллер).
- Поля шаблона: `date`, `doc_number`, `amount` | (`debit`, `credit`), `currency`, `payer_account`, `recipient_name`, `recipient_bin`, `recipient_iban`, `purpose`. Обязательные: `date`, `doc_number`, сумма, `purpose`.
- Tests: `backend/apps/bpp/tests/bank/test_settings.py`, `test_templates.py`.

**Interfaces:**
- Produces (задача 3): `templates.resolve_columns`, `OrgBankAccount.template`, `StatementTemplate.columns/amount_mode/encoding/delimiter/date_format`.

- [ ] **Step 1: Падающие тесты:**
  - `test_template_reads_columns_by_header_in_any_order` (Review Focus 3);
  - заголовок в 4-й строке;
  - нет обязательной колонки → `E-IMP-02` с названием;
  - IBAN организации с неверной суммой mod 97 → 422, дубль → `E-BNK-01`;
  - правка без `bpp.settings` → 403;
  - архивный счёт не предлагается в загрузке (`?active=1`).
- [ ] **Step 2: Реализация**, контроллер генерирует миграцию; тесты задачи + сторожа (`test_gate`, `test_app_isolation`, `test_invariants`, `test_bpp_scaffold`).
- [ ] **Step 3:** `API.md` (раздел bpp — ручки `bank/*`), `STRUCTURE.md` (строка `bpp`).
- [ ] **Коммит** — `feat(bpp): счета организации и шаблоны выписок (A3.1)`.

## Task 3: Загрузка выписки (A4.1, перенесено)

**Files:**
- Modify: `backend/apps/bpp/models/bank.py`:
  - `BankImport` (`BppModel`): `number` («ВП-ГГГГ-0001», `next_number("ВП", width=4)`), `account` (FK), `format`, `period_from/to`, `status` (`processing`/`loaded`/`failed`/`cancelled`; `reconciled` — в A4.2), `rows_total`, `rows_done`, `debits`, `duplicates`, `errors` (JSON-список «Строка 17: …»), `comment`, `author_id`;
  - `BankStatementLine` (`BppModel`): `bank_import` (FK), `account` (FK), `row_no`, `doc_date`, `doc_number`, `amount`, `currency`, `recipient_name`, `recipient_bin`, `recipient_iban`, `purpose`, `dedup_hash`, `match_status` (`unmatched`; остальные — A4.2), `cancelled_at`;
  - частичный `UNIQUE(dedup_hash) WHERE cancelled_at IS NULL`.
- Create: `backend/apps/bpp/services/bank/parsers/onec.py`:
  - 1CClientBankExchange; заголовок обязателен, иначе `E-IMP-01`;
  - `СекцияДокумент` … `КонецДокумента`, синонимы полей (D-S3-3);
  - списание = плательщик — счёт организации.
- Create: `parsers/tabular.py` — xlsx (openpyxl `read_only`) и CSV по шаблону (задача 2).
- Create: `services/bank/imports.py`:
  - `start_import(account_id, file, period, comment, actor)`:
    - проверка формата по расширению и шаблону;
    - файл → `apps.files` (владелец `bpp.bank_import`, тип `bank_statement`);
    - строка `BankImport` в `processing`, `transaction.on_commit` → задача;
  - `run_import(import_id)`:
    - разбор;
    - только списания;
    - `dedup_hash` = SHA-256 от «счёт + дата + № документа + сумма + БИН получателя» (BR-075);
    - вставка пачками по 500 с `ON CONFLICT DO NOTHING`, счёт пропущенных — в `duplicates`;
    - прогресс в `rows_done`;
    - итог → `loaded`, падение → `failed` + текст.
- Create: `backend/apps/bpp/tasks_bank.py` — `@company_task` `bpp.bank_import_run`, первой строкой `require_service("bpp_bank")`. В `htqweb/celery.py` — `autodiscover_tasks(related_name="tasks_bank")`, сторож `test_invariants` (`_TASK_MODULE_RELATED_NAMES`) — тоже.
- Create: `backend/apps/bpp/services/bank/file_owner.py` — владелец `bpp.bank_import`: видит `bpp.bank` view, менять нельзя — файл выписки неизменен после загрузки.
- Modify: `views_bank.py`, `urls_bank.py`:
  - `bank/imports` GET (L-07: номер, банк, период, дата загрузки, кто, строк, списаний, дублей, ошибок, статус; фильтры банк/период/статус; `?format=xlsx`) / POST (multipart);
  - `bank/imports/<id>` GET (состояние + итог + ошибки — опрос экрана);
  - `bank/imports/<id>/lines` GET (страница строк).
- Tests: `backend/apps/bpp/tests/bank/test_onec.py`, `test_tabular.py`, `test_imports.py`. Фикстуры — синтетические файлы в `tests/bank/fixtures/`: 1С в CP1251 с CRLF, xlsx, CSV с `;`.

**Interfaces:**
- Produces для A4.2 (этап 4): `BankStatementLine` (поля выше), `BankImport.status`, `match_status`, `cancelled_at`.
- Consumes: задача 1 (тип `bank_statement`, автоподключение владельцев), задача 2 (шаблон), `apps.files.interface.attach_bytes`.

- [ ] **Step 1: Падающие тесты** — Review Focus 1, 2, 4:
  - файл 1С на 3 документа, один с «31.02.2026» → 2 строки и ошибка «Строка N: не распознана дата „31.02.2026“»;
  - без заголовка → `E-IMP-01`;
  - повтор → `duplicates == 2`, строк не прибавилось;
  - два параллельных запуска (`transaction=True`, потоки) → строк 2;
  - поступление и чужой плательщик не загружаются;
  - 10 001 строка → `E-IMP-03`;
  - xlsx с суммой-числом `1250000.1` → `Decimal("1250000.10")`.
- [ ] **Step 2: Реализация**; тесты задачи, `apps/bpp`, сторожа.
- [ ] **Step 3:** `API.md`, `STRUCTURE.md`, `CLAUDE.md` (абзац «Модуль БЗО» — выписка грузится, сверка — этап 4).
- [ ] **Коммит** — `feat(bpp): загрузка банковской выписки — 1С, Excel, CSV по шаблону, дубли и ошибки строк (A4.1)`.

## Task 4: Метрики и дашборд БЗО — часть 1 (A3.2)

**Files:**
- Create: `backend/apps/bpp/metrics.py` — `collect()` по моделям своей компании, без `require_service`:
  - `htqweb_bpp_requests_in_approval` — заявки «На согласовании»;
  - `htqweb_bpp_requests_in_approval_stale` — заявки «На согласовании» дольше 5 рабочих дней по `ApprovalProcessStage.activated_at` через `signoff.interface.current_holders`;
  - `htqweb_bpp_committed_mismatches` — итог последней ночной сверки (D-S3-4);
  - `htqweb_bpp_committed_check_age_seconds` — возраст этого итога: сверка не бежала больше 26 ч → алерт;
  - `htqweb_bpp_bank_imports_failed` — загрузки в `failed` за 7 дней.
- Modify (зона B, отдельный коммит): `backend/apps/bpp/services/budget/check.py::run` — запись итога в `ModuleSetting` (`committed_check_last`: `{count, at}`).
- Create: `infra/logging/grafana-dashboards/htqweb-bpp.json`:
  - переменная «Компания»;
  - панели по каждой метрике: `sum/max without (company)` или по выбранной компании.
- Modify: `infra/logging/grafana-provisioning/alerting/*.yml` — два правила: `htqweb-bpp-committed-mismatch` (> 0, severity warning, канал incident — это корректность денег, а не бизнес-событие) и `htqweb-bpp-committed-check-stale`. Аннотации `threshold`, `__dashboardUid__`/`__panelId__`, метка `company` сохраняется. Заголовок файла правил — строка о том, почему `requests_in_approval_stale` не алертится (бизнес-очередь видна в сводке).
- Tests: `backend/apps/bpp/tests/test_metrics.py`; сторожа `test_metrics_are_observed`, `test_tenant_metrics_on_dashboards_follow_the_company_variable`, `test_alert_rules_keep_the_company_of_tenant_metrics`; `./scripts/check-monitoring-config.sh`.

- [ ] **Step 1: Падающие тесты:**
  - подложенные данные → значения метрик;
  - `bpp` выключен у одной компании → остальные собраны (Review Focus 5);
  - нет итога сверки → метрика возраста не экспортируется (пустое ≠ ноль, правило CLAUDE.md).
- [ ] **Step 2: Реализация**, сторожа, `check-monitoring-config.sh`.
- [ ] **Step 3:** `CLAUDE.md` (Observability — число правил, 11 дашбордов, `bpp` в списке аппок с `metrics.py`).
- [ ] **Коммит** — `feat(bpp): метрики и дашборд БЗО — очередь заявок, ночная сверка, загрузки выписок (A3.2, часть 1)`.

## Task 5: Экраны настроек и загрузки выписки

**Files** (`frontend/src/features/bpp/`):
- Create `settings/`:
  - `module.tsx` (пункт «Настройки», видимость — `bpp.settings`);
  - `SettingsPage.tsx`, вкладки в `?tab=`: «Счета организации», «Шаблоны выписок», «Параметры модуля» (`ModuleSetting`: порог «Проверенного» — ручка из A2.3, если её нет — вкладка откладывается);
  - `TemplateEditor.tsx` — сопоставление полей заголовкам + «Проверить на образце» (превью первых 20 строк и ошибок).
- Create `bank/`:
  - `module.tsx` (пункт «Оплаты факт», `bpp.bank`);
  - `BankImportsPage.tsx` — L-07 на `BppRegistry`, экспорт `?format=xlsx`;
  - `BankImportForm.tsx` — §11.2: счёт организации (`PrerequisiteNotice`, если счетов нет, ссылка в настройки), формат по шаблону, период, файл до 20 МБ, комментарий;
  - `BankImportPage.tsx`:
    - прогресс опросом раз в 2 с до `loaded`/`failed`;
    - итог — строк, списаний, дублей, ошибок;
    - список ошибок строк;
    - таблица строк, вкладки сверки — задача A4.2;
  - `api.ts`, тесты.

- [ ] **Step 1: Тесты vitest:**
  - пункты меню по правам;
  - форма не отправляется без счёта и файла;
  - опрос останавливается на `loaded`;
  - ошибки строк показаны;
  - редактор шаблона показывает недостающие обязательные поля.
- [ ] **Step 2: Реализация.** Полный `npx vitest run` (сторож uxContract), `eslint src/features/bpp`, `tsc` ≤ 148.
- [ ] **Step 3:** `STRUCTURE.md` (дерево `features/bpp`).
- [ ] **Коммит** — `feat(bpp): экраны «Настройки» и «Оплаты факт» — счета организации, шаблоны, загрузка выписки`.

## Task 6: Долги этапа 2 в зоне A

Отложенные мелкие замечания финального ревью и валидаторов этапа 2 — те, что на стороне A:

- [ ] `access.interface.holders_of` — импорт `depth` на уровень модуля.
- [ ] `export.run_background` — убрать лишний `internal_authorized=True` для scope `generic`; поправить устаревший докстринг `media_files.interface.store_file`.
- [ ] `refdata`: родительская статья — только из той же группы (сервис + форма). Тест — чужая группа → 422.
- [ ] `projects/ProjectFormDialog` — поле «Заказчик — контрагент» (`customer_counterparty_id`, поиск по реестру контрагентов). Тест.
- [ ] `counterparties/BankAccountsPanel.test.tsx` — добавить счёт, неверный IBAN, архив.
- [ ] Реестр: `moneyColumn`/`moneyTotal` на `formatMoney`; `HistoryTab` принимает `fieldLabels` и форматирует деньги; страница и поиск реестра — в URL (`useSearchParams`), возврат со строки не сбрасывает место.
- [ ] Тесты, полный vitest, `tsc`.
- [ ] **Коммит** — `fix(bpp): долги этапа 2 — …` (перечислить).

---

## Сведение (после бэкенда B3.1–B3.2)

- [ ] PR этапа 3 A (волна 1) в `new-module-BPP-merge`, мердж встречной ветки, merge-миграция `bpp` при двух `00NN` (как `0009` этапа 2).
- [ ] Проверить на сведённой ветке:
  - B3.1 прикладывает договор через `file_owner.py` (задача 1);
  - `closing_docs_pending_for_user` и поля `Invoice.paid_bank_amount`/`recon_status` на месте.
- [ ] Если примеры выписок (В-13) уже в `docs` — прогнать их через задачу 3, поправить шаблоны или синонимы.

## Task 7: Метрики счетов — часть 2 (A3.2, волна 2)

- [ ] `metrics.py`:
  - `htqweb_bpp_invoices_awaiting_fd` — очередь ФД;
  - `htqweb_bpp_invoices_to_pay` — очередь БУХ «К оплате»;
  - `htqweb_bpp_invoices_closing_docs_overdue` — «Ждёт закрывающих» дольше 5 дней (Q-C29).

  Панели на `htqweb-bpp.json`. Правило `htqweb-bpp-closing-docs-overdue` в бизнес-канале (`channel=business`) — событие для людей, а не инцидент.
- [ ] Тесты на моделях B (фабрики — из его тестов), сторожа, `check-monitoring-config.sh`.
- [ ] **Коммит** — `feat(bpp): метрики очередей счетов и закрывающих документов (A3.2, часть 2)`.

## Task 8: Раздел сводки «ждут от вас закрывающих документов» (A3.2, D-13)

- [ ] Источник сводки `bpp.closing_docs` — `notifications.interface.register_digest_source(..., tenant=True)` из `BppConfig.ready()` поверх `bpp.interface.closing_docs_pending_for_user` (B3.2). Пункт: «СЧ-… — ждёт закрывающих N дн.», ссылка на счёт на поддомене компании.
- [ ] Тесты (Review Focus 5):
  - автор счёта в «Ждёт закрывающих» получает раздел;
  - автор без таких счетов — нет;
  - `bpp` выключен у компании → сводка остальных уходит.
- [ ] **Коммит** — `feat(bpp): раздел сводки о закрывающих документах (A3.2, D-13)`.

## Task 9: Сквозная проверка этапа

- [ ] Сценарий в тесте:
  - счёт B «Оплачено» → запрос закрывающих → сводка автора с разделом;
  - метрика «Ждёт закрывающих» растёт после 5 дней (подмена времени);
  - загрузка выписки с номером этого счёта в назначении даёт строку «Не сопоставлена» — сверка появится в A4.2.
- [ ] Весь бэкенд без `ci-known-failures.txt` чанками, полный vitest, `tsc`, `check-monitoring-config.sh`.
- [ ] Финальное ревью ветки отдельным ревьюером; важные замечания — исправить, мелкие — в журнал.
- [ ] PR в `new-module-BPP-merge`.

---

## Остаток B на этапе 3 (Руслан) — справочно

| # | Что | На чём стоит |
|---|---|---|
| B-1 | Волна 2 этапа 2: экраны B2.5 (бюджет, заявка, план) на `BppRegistry`/`BppDocumentShell`; выгрузка реестров бюджета, заявок, плана — `?format=xlsx` на ручке реестра (контракт A: та же ручка, `export.respond`, фильтр общий со страницей — образец `views_counterparties.py::counterparty_list`) | этап 2 A |
| B-2 | B3.1 договор — файлы через `services/agreements/file_owner.py` (D-S3-1); контрагент — `services/counterparties/lookup.py` (`assert_usable`, `needs_confirmation`, `record_success`), окно подтверждения — `counterparties/ConfirmCounterpartyDialog` | задача 1 |
| B-3 | B3.2 счёт — файлы через `services/invoices/file_owner.py`; `find_by_number`, `paid_bank_amount`/`recon_status`, `closing_docs_pending_for_user` — handoff A до волны 2 | задача 1 |
| B-4 | B3.3 «задействовано» полностью | B3.2 |
| B-5 | `BppDocumentShell` требует `historyType` — тип журнала = `label_lower` модели (`bpp.agreement`, `bpp.invoice`), а не тип предмета signoff | этап 2 A |
| B-6 | Статусы договора и счёта — добавить словари в `core/statusDictionaries.ts` (коды = `TextChoices` моделей) | этап 2 A |

## Ждёт решения пользователя

- **Письма движка согласования по всем предметам.** `signoff.engine._notify_center` не передаёт `deliver=`, поэтому центр по умолчанию шлёт e-mail и по кадровым документам, заявкам форм и договорам `contracts`, а не только по документам БЗО. Варианты: сузить до `bpp.*` (правка B) или оставить.
- **Вопросы B к Алгазы** из его плана этапа 3: счёт без закрывающих документов, счёт-фактура.

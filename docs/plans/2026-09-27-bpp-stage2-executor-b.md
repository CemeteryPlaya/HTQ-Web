# БЗО, этап 2 — исполнитель B (Руслан, ветка `new-module-BPP-ruslan`)

**Goal:** Цепочка «бюджет проекта → заявка на закупку → план закупок» по ТЗ §06–§08:
- лимиты по статьям с версиями;
- заявка с контролем остатка под блокировкой и маршрутом ТД → ОД;
- план закупок утверждённых позиций;
- расчёт «Задействовано» (CALC-002);
- экраны F-01/L-01, F-02/L-02, L-04 + F-03.

**Spec:** [мастер-план](2026-09-26-bpp-master-plan.md), задачи B2.1–B2.5, решения D-06, D-07, D-08, D-10, D-28, D-29, D-39; ТЗ §06, §07, §08, §13, §15.1–15.2, §17, §19–§21, §23–§24, §26.1; BR-001…004, BR-010…014, BR-020…021; CALC-001…006; AC-001…004; REQ-001…007.

**Статус (27.09):** бэкенд B2.1–B2.4 сделан поверх вмерженной ветки A (её этапы 0 и 1). Ждут:
- файлы заявки, печать PDF и экспорт — A2.2;
- экраны B2.5 — каркас A2.1.

Отступления — в [файле сверки](2026-09-26-bpp-reconciliation-B.md), §7.

## 0. Что нужно от исполнителя A

Задача B стартует, как только в ветке A появится её строка. Интерфейсы берутся буквально из мастер-плана §2.6. Разойдутся — подстраивается B, а расхождение записывается в сверку.

| Нужно | Задача A | Что именно | Кто ждёт |
|---|---|---|---|
| Аппка `bpp` зарегистрирована, подмодули `bpp_budget`/`bpp_requests`, узлы `bpp.*`, каркас `urls.py` с `include` подмодулей | A0.1, A0.2 | `apps/bpp/{apps,urls,access_functions,holding}.py`, `KNOWN_SUBMODULES`, `PREFIX_TO_SERVICE` | всё |
| Ядро | A1.1 | `BppModel` (UUID, `created_*`/`updated_*`, `version`), `next_number`, `audit.record`, `files.attach`/`list_files`, `DomainError` + конверт D-28, `api_view(idempotent=True)`, `check_version`; `bpp` в `TENANT_APPS` | B2.1, B2.2 |
| Справочники | A1.2 | `refdata.interface.article_brief`, `article_groups`, `uom_brief`; валюты (KZT по умолчанию) | B2.1, B2.2 |
| Проекты | A1.3 | `project.interface.project_brief`, `is_member`, `member_project_ids`, `search_projects` | B2.1, B2.2 |
| Роли | A1.4 | роли `bpp-*`, `permissions.allowed_actions(request, obj)`, `permissions.article_groups_for(request)` | B2.1–B2.3 |
| Экспорт и печать | A2.2 | общий экспорт xlsx, печать HTML → PDF | экспорт бюджета и плана, печать заявки |
| Каркас фронта | A2.1 | оболочка `/bpp`, реестр, форма, `allowed_actions` на кнопках, `Idempotency-Key`, формат денег и дат | B2.5 |

Уже сделано у B и используется здесь (этап 1):
- `signoff` — строковый `subject_id` (UUID);
- флаги маршрута `forbid_self_approval`, `reject_comment_min=10`, `lazy_resolution`;
- «Сейчас у» (`current_holders`), `pending_for_user`, массовые решения;
- временные исполнители должностей.

## Global Constraints

- Модели — наследники `BppModel` (UUID-ключ, `version` для E-CON-01). Межаппные ссылки — UUID/строкой, без FK: `project_id`, `article_id`, `uom_id`, пользователи — `*_id` целым.
- Деньги `Decimal(18,2)`, количество `Decimal(15,3)`, округление `ROUND_HALF_UP` до 0,01 (мастер-план §2.5).
- Ручки — в `views_budget.py`/`urls_budget.py` и `views_requests.py`/`urls_requests.py`. Каждая — `api_view(module="bpp", level=…)` с явным уровнем; тонкие права — `allowed_actions` и узлы `bpp.*` (`access.interface.flags_for`).
- Мутации — с `Idempotency-Key` и `version`. Ошибки — `DomainError` с текстом ТЗ §26.1 и правил BR дословно.
- Каждая изменяющая операция пишет `audit.record` (кто, что, было/стало, комментарий).
- Физически удаляются только черновики (BR-080).
- Фронт: строки — `t('bpp.<ключ>', 'Русский текст')`, переводы не добавлять (D-39).
- Тесты — pytest на Postgres `:55432`, один прогон за раз; конкурентные сценарии — два потока с отдельными соединениями.

---

## Task B2.1: Бюджет проекта

**Решения:**
- **D-06.** Один бюджет на проект на весь срок, версии со снимками, лимиты в KZT. Черновик корректировки на остатки не влияет: заявки проверяются по действующей версии (ТЗ §13.1 п.18).
- **D-07.** Утверждение и корректировка — прямое действие ФД (узел `bpp.budgets.approve`), без маршрута `signoff`.

**Модели** (`apps/bpp/models/budget.py`):

| Модель | Поля | Ограничения |
|---|---|---|
| `Budget` | `project_id` (UUID), `number` («БДЖ-<код проекта>»), `currency` (код, KZT), `status` (`draft`/`approved`/`closed`), `active_version` (FK на версию, null), `date_from`/`date_to` ([У], необязательны), `status_comment` | `UNIQUE(project_id)` — BR-001; `UNIQUE(number)`; `date_to ≥ date_from` |
| `BudgetVersion` | `budget` (FK, CASCADE), `version_no`, `status` (`draft`/`active`/`archived`), `comment` (корректировка, ≥10), `approved_at`, `approved_by_id` | `UNIQUE(budget, version_no)`; один `draft` на бюджет (частичный уникальный индекс) |
| `BudgetLine` | `version` (FK, CASCADE), `article_id` (UUID), `limit_amount`, `comment` (≤255) | `UNIQUE(version, article_id)` — BR-002; `CHECK limit_amount ≥ 0` |

Черновик бюджета — это версия 1 в статусе `draft`. Утверждение делает её `active`. Корректировка копирует строки действующей версии в новый `draft` с номером N+1; его утверждение переводит N в `archived`, а N+1 — в `active`.

**Сервисы** (`apps/bpp/services/budget/`):
- `budgets.py`:
  - `create(project_id, currency, lines)` — проект активный и доступный (A1.3); BR-001 — текст «У проекта П-015 уже есть бюджет БДЖ-П-015. Откройте его и выполните корректировку.» со ссылкой;
  - `update_draft(budget_id, version, …)` — строки заменяются целиком, BR-002 «Статья „Металлопрокат“ уже есть в бюджете, строка 4»;
  - `approve` — ≥1 строка, Σ > 0;
  - `start_correction`;
  - `approve_correction(comment)` — BR-004 под блокировкой строк: «Лимит статьи „…“ не может быть меньше задействованной суммы 3 400 000,00 KZT»; удалить строку с задействованным > 0 нельзя;
  - `cancel_correction`;
  - `close` — нет заявок «На согласовании»; неоплаченные счета проверяются с этапа 3;
  - `reopen(comment)`;
  - `delete_draft`.
- `balance.py` — `balance(project_id, article_id, *, exclude_request_id=None) -> {limit, committed, available, as_of}` (контракт §2.6) по ДЕЙСТВУЮЩЕЙ версии; `lock_line(project_id, article_id)` — `SELECT … FOR UPDATE` строки действующей версии для BR-011/034/043.
- `totals.py` — итоги по бюджету и по группам статей («Снабжение» / «Проектное управление») через `refdata.article_groups`.
- `visibility.py` — строки для СН/ПМ: только группы из `article_groups_for(request)` и, для ПМ, только проекты-участия (`member_project_ids`); ФД, ГД, ТД, ОД, АДМ — всё (§06.1).

**Ручки** (`views_budget.py`, префикс `budgets` — подмодуль `bpp_budget`):

| Ручка | Метод | Уровень | Операция ТЗ §23 |
|---|---|---|---|
| `budgets` | GET | read | реестр L-01 (статус, проект; Σ лимит/задействовано/доступно; дата утверждения) |
| `budgets` | POST | write | CreateBudget |
| `budgets/<id>` | GET / PATCH / DELETE | read / write / write | карточка F-01 (действующая версия + черновик корректировки, итоги, `allowed_actions`) / UpdateBudget / удаление черновика |
| `budgets/<id>/approve` | POST | write | ApproveBudget |
| `budgets/<id>/correction`, `…/correction/approve`, `…/correction/cancel` | POST | write | Start/Approve/CancelBudgetCorrection |
| `budgets/<id>/close`, `…/reopen` | POST | write | закрыть / открыть повторно (комментарий) |
| `budgets/<id>/versions`, `…/versions/<n>` | GET | read | вкладка «Версии», снимок |
| `budgets/lines?project_id=&role=` | GET | read | GetBudgetLines — строки группы роли для формы заявки |
| `budgets/balance?project_id=&article_id=&exclude_request_id=` | GET | read | GetBudgetBalance |
| `budgets/<id>/export` | GET | read | xlsx (A2.2) |

Права на узлах: `bpp.budgets` (просмотр/создание/правка/удаление), `bpp.budgets.approve` (edit) — утверждение, корректировка, закрытие, открытие.

**Тесты** (`apps/bpp/tests/budget/`):
- второй бюджет проекта → 422 BR-001 со ссылкой;
- дубль статьи → 422 BR-002 с номером строки;
- утверждение с Σ = 0 → 422;
- лимит ниже задействованного в корректировке → 422 с суммой;
- заявки во время корректировки проверяются по действующей версии;
- снимок версии N доступен после утверждения N+1;
- отмена корректировки удаляет только черновик;
- закрытие при заявке «На согласовании» → 409, повторное открытие — с комментарием;
- СН видит только строки «Снабжения», ПМ — только своих проектов;
- устаревший `version` → 409 E-CON-01;
- повтор с тем же `Idempotency-Key` — один переход и одна запись аудита.

---

## Task B2.2: Заявка на закупку

**Решения:**
- **D-10.** Типизированная модель, маршрут ТД → ОД через `signoff`, шаблон «Заявка на закуп» не используется.
- Флаги маршрута БЗО включены: самосогласование, комментарий ≥ 10, ленивое разрешение.
- `purchase_type` — «ТМЦ» / «Работы и услуги».

**Модели** (`apps/bpp/models/requests.py`):

| Модель | Поля | Ограничения |
|---|---|---|
| `PurchaseRequest` (`BppModel`, `signoff.Approvable`, `SIGNOFF_SUBJECT_TYPE = "bpp.purchase_request"`) | `number` («ЗЗ-ГГГГ-NNNNNN», `next_number` при ПЕРВОМ сохранении), `author_id`, `initiator_role` (`sn`/`pm`), `project_id`, `article_id`, `purchase_type` (`goods`/`works`), `need_date`, `justification` (10–2000), `currency`, `total_amount`, `status` (`draft`/`on_review`/`approved`/`rework`/`rejected`/`cancelled`/`closed`), `status_comment`, `is_migrated` (B6.1) | `UNIQUE(number)` (частичный — номер есть у сохранённой) |
| `PurchaseRequestItem` (`BppModel`) | `request` (FK, CASCADE — только у черновика), `line_no`, `sys_number` («<номер>-NN»), `name` (3–500), `specs` (≤2000), `uom_id`, `qty`, `price`, `amount` (CALC-004), `need_date`, `status` (`open`/`partially_closed`/`closed`/`annulled`), `executor_id` (по умолчанию автор; «Переназначить исполнителя» — B2.3) | `UNIQUE(sys_number)`, `UNIQUE(request, line_no)`; `CHECK qty > 0, price > 0, amount > 0`; ≤ 200 позиций (сервис) |

Видимый статус — `status`; `approval_state` ведёт `signoff` (Q-C08).

**Регистрация в `signoff`** — `apps/bpp/approval_hooks.py` (файл B):

| Колбэк | Что делает |
|---|---|
| `on_started` | → `on_review` |
| `on_approved` | → `approved`; позиции остаются `open` и попадают в план |
| `on_rejected` | → `rejected`, позиции `annulled` |
| `on_rework` | → `rework`, резерв снят (BR-012) |
| `on_cancelled` | отзыв → `draft` |

Кроме колбэков: `describe` (номер, проект, сумма, ссылка), `facts` (сумма, группа статьи, вид закупки), `assert_editable` первой строкой каждой правки. Маршрут не зашит: команда `bpp_setup_routes --company <slug> --td <position_id> --od <position_id>` заводит маршрут «ТД → ОД» с флагами БЗО.

**Сервисы** (`apps/bpp/services/requests/`):
- `requests.py`:
  - `create_draft` — «Роль инициатора»: у пользователя одна роль — подставляется, две — обязательна; бюджет проекта утверждён — BR-003 / E-BUD-02;
  - `update_draft` — только `draft`/`rework`;
  - `submit` — обязательные поля (E-REQ-01), права на проект и статью, затем в ОДНОЙ транзакции `lock_line` → `balance(exclude_request_id)` → сравнение (BR-011, текст E-BUD-01 с суммой превышения) → `signoff.start_process` → `on_review`;
  - `withdraw` — «На согласовании», решений ещё нет → `signoff.cancel_process`;
  - `cancel(comment)` — автор: `draft`/`rework`; ФД (`bpp.requests.cancel_approved`): `approved` без позиций в договорах и счетах; позиции `annulled`;
  - `close_remainder(comment)` — автор или ФД, `approved`; невыбранные остатки позиций → `annulled`/`closed`, статус `closed`;
  - `copy` — новый черновик без файлов и согласований;
  - `delete_draft`.
- `visibility.py`:
  - статьи — только группы из `article_groups_for`; чужая группа при сохранении → 403 E-ACC-01 (AC-002);
  - проекты ПМ — только участия (BR-014);
  - заявки: СН/ПМ видят свои, ТД/ОД/ФД/ГД — все.
- `execution.py` — блок 6 «Исполнение»: по позиции план / в договорах / в счетах / оплачено / остаток (с этапа 3 — договорами и счетами).
- Файлы КП/ТЗ/Спецификация/Прочее — `services/core/files.py` (A1.1): до 20 документов, PDF/DOCX/XLSX/JPG/PNG до 20 МБ; удаление в `draft`/`rework`, дальше — только версии.
- Печать PDF с листом согласования — шаблон печати A2.2 + ход согласования из `signoff`.

**Ручки** (`views_requests.py`, префикс `requests` — подмодуль `bpp_requests`):
- `requests` GET (L-02: статус, проект, статья, автор, период, «Ждёт моего решения» через `signoff.list_awaiting_subject_ids`, колонка «Сейчас у» через `current_holders`) / POST;
- `requests/<id>` GET / PATCH / DELETE;
- `requests/<id>/submit|withdraw|cancel|close-remainder|copy` POST;
- `requests/<id>/execution` GET;
- `requests/<id>/print` GET.

Согласование — ручки `signoff` («Мои согласования» — фильтр инбокса по `bpp.*`, A2.1).

**Тесты** (`apps/bpp/tests/requests/`):
- AC-001 — превышение остатка → 422 E-BUD-01 с суммой, статус «Черновик»;
- AC-002 — СН не может выбрать статью ПМ → 403;
- AC-003 — после ТД статус не меняется, после ОД «Утверждена», позиции в плане;
- AC-004 — две параллельные отправки по 2 000 000 при остатке 3 000 000 в двух потоках: одна проходит, вторая E-BUD-01, задействовано 2 000 000;
- повтор отправки с тем же ключом — один переход, одна запись аудита, одно уведомление;
- отмена и отклонение снимают резерв;
- отзыв после первого решения → 409;
- 201-я позиция → 422;
- номер ЗЗ- выдаётся один раз и не меняется;
- автор не согласует свою заявку (флаг маршрута);
- комментарий 9 символов при возврате → 422.

---

## Task B2.3: План закупок

Не модель, а выборка (§08, BR-020, BR-021). Сервис `apps/bpp/services/requests/plan.py`:
- `plan_items(user, filters, sort, page)`:
  - позиции утверждённых заявок, где `executor_id = user` и роль инициатора совпадает с ролью, в которой пользователь смотрит план;
  - остаток количества > 0 (CALC-005) и остаток суммы (CALC-006) — на этапе 2 договоров и счетов нет, поэтому остаток = план; этап 3 добавляет слагаемые;
  - держатель `bpp.plan.all` (ФД) видит все позиции без действий.
- Фильтры и сортировка — §8.2: проект, статья, наименование, дата потребности (просроченные помечены), вид закупки, «есть договор», номер и дата заявки; пагинация 25/50/100; экспорт — A2.2.
- `validate_selection(item_ids, target)`:
  - одна статья и один проект — BR-021, текст «Для одного документа выберите позиции одного проекта и одной статьи»;
  - остаток > 0;
  - позиции пользователя.

  Ответ — `{ok, project_id, article_id, purchase_type, items}` для мастера F-03.
- Метка «В договоре на согласовании» — поле ответа, заполняется с B3.1.
- `reassign(item_ids, to_user_id)` — АДМ: переносит `executor_id`, запись в аудит.

Ручки:
- `plan` GET;
- `plan/validate` POST;
- `plan/reassign` POST (`module="bpp", level="admin"` + узел `bpp.plan` edit);
- `plan/export` GET.

**Тесты** (`apps/bpp/tests/plan/`):
- позиции разных статей → 422 с текстом;
- позиция с остатком 0 не выбирается;
- ФД видит все позиции и не может их выбрать;
- СН не видит позиций своих заявок в роли ПМ;
- переназначение переносит позиции и пишется в аудит;
- просроченная дата потребности помечена.

---

## Task B2.4: «Задействовано» (CALC-002)

**Решение D-08.** Считается на лету, не хранится. Сумма по позициям заявок на статью проекта в статусах «На согласовании», «Утверждена», «Закрыта»:
- **открытая или частично закрытая позиция** — `max(план; Σ позиций договоров «На согласовании»/«Действует»; Σ строк счетов от «На рассмотрении ФД», кроме «Отменён» и «Не к оплате»)`;
- **закрытая или аннулированная позиция** — `Σ строк счетов`.

На этапе 2 слагаемых договоров и счетов нет: они приходят в B3.3, подотчёт — в B4.1. Функция написана так, чтобы их добавление было одной строкой в списке слагаемых.

`apps/bpp/services/budget/committed.py`:
- `committed_by_article(project_id, article_ids=None, *, exclude_request_id=None) -> {article_id: Decimal}` — один SQL-агрегат (`CASE`/`GREATEST` по позициям) для реестров и `balance()`;
- `committed_reference(project_id, article_id)` — независимый пересчёт по позициям в Python, для сверки и тестов.

**Ночная сверка** — `apps/bpp/tasks.py::committed_check_dispatch` (диспетчер + веер по компаниям, 02:30):
- сравнивает агрегат с эталоном по каждой строке действующих бюджетов;
- расхождение → `fallback("bpp.committed.mismatch", …)` и метрика `htqweb_bpp_committed_mismatch_total{company}`.

Панель и алерт метрики — вместе с дашбордами БЗО A3.2: сторож `test_metrics_are_observed` не пропустит метрику без панели. Поэтому сама метрика заводится в ту задачу, которая первой добавит панель; до этого — только `fallback` и лог.

**Тесты** (`apps/bpp/tests/budget/test_committed.py`):
- формула для открытой, частично закрытой, закрытой и аннулированной позиции;
- черновик и отклонённая заявка не занимают;
- отмена снимает резерв;
- `exclude_request_id` исключает саму заявку;
- агрегат совпадает с эталоном на наборе из 50 случайных заявок;
- ночная сверка находит подложенное расхождение (подмена агрегата в тесте).

---

## Task B2.5: Экраны

`frontend/src/features/bpp/` — поверх каркаса A2.1 (оболочка, реестр, форма, `allowed_actions`, `Idempotency-Key`, формат денег и дат):

| Экран | Файлы | Что |
|---|---|---|
| L-01 / F-01 бюджет | `budget/BudgetList.tsx`, `budget/BudgetForm.tsx`, `budget/BudgetVersions.tsx` | лимиты, пересчёт «Доступно» при вводе (< 0 — красным), итоги по группам, режим корректировки с обязательным комментарием, вкладка «Версии» |
| L-02 / F-02 заявка | `requests/RequestList.tsx`, `requests/RequestForm.tsx`, `requests/ItemsTable.tsx` | роль инициатора, проект → статьи группы → остаток, «Остаток после заявки» на лету, «Отправить» недоступна при превышении с текстом, жёлтая плашка комментария возврата, вставка позиций из Excel, блок «Исполнение», колонка «Сейчас у» |
| L-04 + F-03 план | `plan/PlanList.tsx`, `plan/PlanWizard.tsx` | фильтры §8.2, выбор позиций, кнопки блокируются при разных статьях, мастер ведёт в F-04/F-05 (этап 3) |

**Карточка процесса `signoff`.** Сделано заранее, 27.09. `SIGNOFF_SUBJECT_VIEWS` (`frontend/src/app/signoffSubjectViews.ts`) переведена на строковый id: `SubjectViewProps.id: string`, представления старых доменов с целыми id подключены через `intKeyed`, документы БЗО подключаются через `stringKeyed`. Остаётся зарегистрировать `bpp.purchase_request` → `RequestSubjectView` через `stringKeyed`.

**Тесты (vitest):**
- пересчёт остатка при вводе;
- недоступность «Отправить» при превышении;
- выбор позиций разных статей блокирует кнопки;
- роль инициатора скрыта при одной роли;
- корректировка требует комментарий ≥ 10;
- строковый id в `SIGNOFF_SUBJECT_VIEWS` — есть (`src/app/__tests__/signoffSubjectViews.test.tsx`).

---

## Порядок и коммиты

1. A0.2 + A1.1 в ветке A → `git merge origin/new-module-BPP-sanzhar`. Затем модели и миграция `bpp` (B2.1 + B2.2 одной первой миграцией, если у A её ещё нет), сервисы бюджета, `committed.py`, заявка без файлов и печати.
2. A1.2 + A1.3 + A1.4 → права и видимость, реальные статьи, проекты, роли; тесты AC-001…AC-004.
3. B2.3 план закупок.
4. A2.1 → экраны B2.5; A2.2 → экспорт и печать.

Коммит на задачу (`feat(bpp): …`), документация в той же задаче: `STRUCTURE.md` — раздел `bpp`, `API.md` — ручки, `CLAUDE.md` — абзац модуля. Перед каждым коммитом:
- тесты задачи;
- `apps/bpp`, `apps/signoff`;
- сторожа `test_invariants`, `test_app_isolation`, `test_gate`, `test_metrics_are_observed`.

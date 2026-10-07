# Тендерный модуль — пошаговый план этапов 0–2 (задачи T0.3 … T2.3)

07.10.2026 · ветка `tender` · поверх мастер-плана [2026-10-06-tender-master-plan.md](2026-10-06-tender-master-plan.md) (решения T-01…T-31 действуют). Здесь — то, что мастер-план оставил «к старту этапа»: матрица ролей, контракт `bpp.interface` пакета B-1, модели и API заявки и тендера, раскладка файлов по исполнителям. Умолчания этого плана помечены **[умолч.]** — их можно поменять без переделки архитектуры.

Общие правила для всех задач — CLAUDE.md репозитория: UUID-ключи, деньги `Decimal(18,2)`, количества `Decimal(15,3)`, ошибки — `htqweb.errors.DomainError` (`{detail, code, fields}`), `version` + 409 `E-CON-01` (`apps.tender.services.core.errors.check_version`), журнал — `apps.tender.services.core.audit.record`, «сегодня» — `timezone.localdate()`, ручки — `htqweb.http.api_view(module="tender", level=…)`, оба написания путей (со слешем и без), сосед — только через `apps.<x>.interface`.

---

## 1. Матрица ролей (T0.3)

Узлы `apps/tender/access_functions.py` (по образцу `apps/bpp/access_functions.py`):

| Узел | Название | Признаки |
|---|---|---|
| `tender.requests` | Заявки на закуп | view, create, edit, delete |
| `tender.requests.all` | Все заявки, а не только свои | view — **EXPLICIT_ONLY** |
| `tender.tenders` | Тендеры и участники | view, create, edit, delete |
| `tender.tenders.all` | Все тендеры, а не только свои | view — **EXPLICIT_ONLY** |
| `tender.award.quality` | Проверка качества выбора | edit — **EXPLICIT_ONLY** |
| `tender.award.approve` | Утверждение выбора (ФД) | edit — **EXPLICIT_ONLY** |
| `tender.prospects` | Потенциальные поставщики и контакты | view, create, edit, delete |
| `tender.receipts` | Приёмка и закрывающие | view, create, edit |
| `tender.settings` | Настройки модуля | view, edit |

Роли (миграция `access/0027_tender_roles`, по образцу `access/0014`): **явная строка у каждой роли на каждом узле**, пустая строка = «нет доступа».

| Узел \ роль | `tender-buyer` (СН, ПМ) | `tender-quality` (ТД) | `tender-fd` | `tender-viewer` (БУХ, ОД) | `tender-adm` |
|---|---|---|---|---|---|
| `tender` (модуль) | V C E D | V | V | V | V C E D |
| `tender.requests` | V C E D | — | V | V | V C E D |
| `tender.requests.all` | — | — | V | V | V |
| `tender.tenders` | V C E D | V | V | V | V C E D |
| `tender.tenders.all` | — | V | V | V | V |
| `tender.award.quality` | — | E | — | — | — |
| `tender.award.approve` | — | — | E | — | — |
| `tender.prospects` | V C E | — | V | V | V C E D |
| `tender.receipts` | V C E | — | V | V | V C E |
| `tender.settings` | — | — | V | — | V E |

Гейт ручек: чтение — `level="read"`, запись — `level="write"`. «Свои» (автор) — фильтр в сервисе; `*.all` — по узлу (`access.interface.flags_for`).

`manage.py tender_assign_roles --company <slug> [--dry-run]` (образец `bpp_assign_roles`): «Менеджер по закупкам», «Руководитель проекта» → `tender-buyer`; «Технический директор» → `tender-quality`; «Финансовый директор» → `tender-fd`; «Главный бухгалтер», «Бухгалтер», «Операционный директор» → `tender-viewer`. `tender-adm` — лично.

**Важно:** закупщику для отправки заявки нужны ещё роли БЗО (`bpp-sn`/`bpp-pm`): ЗЗ в БЗО подаётся от его имени, и БЗО проверяет свои права и группы статей (BR-010, T-06, T-20). Роли tender этого не заменяют.

---

## 2. Пакет B-1 — `bpp.interface` для заявки (T1.2, зона B)

Отдельные коммиты с префиксом `bpp(B):`. Схемы Pydantic — `apps/bpp/schemas/tender.py`, **реэкспорт из `apps/bpp/interface.py`** (tender импортирует только `apps.bpp.interface` — сторож изоляции). Все функции: первой строкой `require_service("bpp")`, зовутся в контексте компании, пользователь — `Actor.for_user(actor.user_id, company=<текущая>, is_superuser=actor.is_superuser)`: права и группы статей — его собственные.

**Модель.** `PurchaseRequest.source` (`CharField(16)`, `""`/`"tender"`, `db_default=""`) и `tender_number` (`CharField(32)`, `db_default=""`) — миграция `bpp/0021_request_source` (expand). Админка/реестры: поле только для чтения.

**Схемы** (`apps/bpp/schemas/tender.py`):

```python
class TenderActor(BaseModel):  user_id: int; is_superuser: bool = False
class TenderItemIn(BaseModel): name: str; specs: str = ""; uom_id: str; qty: Decimal; price: Decimal; need_date: date
class TenderPartIn(BaseModel):
    key: str                      # ключ части у tender (UUID TenderRequestPart строкой)
    bpp_request_id: str | None    # None — создать ЗЗ; иначе — пересобрать эту (только draft/rework)
    article_id: str; purchase_type: Literal["goods", "works"]
    items: list[TenderItemIn]     # непустой
class TenderRequestSubmit(BaseModel):
    actor: TenderActor; initiator_role: Literal["sn", "pm"]
    project_id: str; tender_number: str; justification: str; need_date: date
    parts: list[TenderPartIn]
class RequestRef(BaseModel):    key: str; bpp_request_id: str; number: str; status: str; items: list[str]  # id позиций по порядку items
class RequestStatusOut(BaseModel):
    bpp_request_id: str; number: str; status: str; status_comment: str = ""; rework_comment: str = ""
class BudgetFigures(BaseModel): limit: Decimal; committed: Decimal; available: Decimal; currency_code: str
class BudgetArticle(BaseModel): id: str; code: str; name: str; group_code: str; available: Decimal
```

**Функции:**

| Функция | Поведение |
|---|---|
| `submit_request_from_tender(data) -> list[RequestRef]` | Одна транзакция на все части: по части — `create_draft` (новая ЗЗ, `source="tender"`, `tender_number`) или `update_draft` (существующая, только draft/rework), затем `submit` (BR-011 под блокировкой строки бюджета). Любая ошибка — откат всех частей и `DomainError` наружу с `details={"part": key}`. |
| `withdraw_requests_from_tender(ids, *, actor) -> None` | `withdraw` каждой ЗЗ в «На согласовании» (без решений). |
| `cancel_requests_from_tender(ids, *, actor, comment) -> None` | draft/rework → `cancel`; approved → `close_remainder` (автор вправе, резерв снимается); in_approval → 409 `E-STS-01`; rejected/cancelled/closed — пропуск. |
| `release_to_plan(ids, *, actor) -> None` | Снять `source` (позиции видны в Плане у исполнителя-закупщика) — для «тендер не состоялся» (этап 2). Только approved. |
| `request_status(ids) -> dict[str, RequestStatusOut]` | Невозможные/чужие ключи в ответ не попадают. |
| `register_request_listener(fn: Callable[[RequestStatusOut], None]) -> None` | Слушатель зовётся **в транзакции смены статуса** ЗЗ с `source="tender"`: `on_started`, `on_approved`, `on_rejected`, `on_rework`, `on_cancelled`, `cancel`, `close_remainder`. Исключение слушателя откатывает смену статуса (как `project.register_change_listener`). |
| `budget_available(project_id, article_id, *, actor, role) -> BudgetFigures` | Обёртка `budget.balance.balance` **с проверкой доступа** (замечание проверки безопасности 07.10): проект — по правилам роли (`_check_project`, ПМ — только участия, BR-014), статья — из группы роли (BR-010, 403 `E-REQ-04`); нет утверждённого бюджета/строки — `DomainError` штатный (`E-BUD-02`/`E-BUD-07`). |
| `budget_articles(project_id, *, actor, role) -> list[BudgetArticle]` | Статьи утверждённого бюджета проекта ∩ группа статей роли (`ROLE_GROUP`, BR-010), с остатком. |

**Замок T-07** (в сервисах БЗО, для `source="tender"`):
- через API/сервисы БЗО — `update_draft`, `delete_draft`, `submit`, `withdraw`, `cancel`, `close_remainder`, `copy` → 409 `E-STS-02` «Заявка {номер} ведётся в тендерном модуле ({tender_number})». Внутренний флаг (`via_tender=True`) пропускает функции интерфейса выше. Колбэки согласования (решения ТД/ОД в signoff) — работают как обычно;
- `allowed_actions` для такой ЗЗ — только `["print"]`; карточка/реестр отдают `source`, `tender_number`;
- План закупок (`plan/service._base`) скрывает позиции `source="tender"`; `plan.validate_selection` (мастер F-03) отвергает их 409 `E-STS-02` (создать документы из этих позиций сможет только пакет B-2).

Тесты — `apps/bpp/tests/test_tender_bridge.py`: две части → две ЗЗ, обе «На согласовании», резерв в `balance`; ошибка BR-011 во второй части откатывает и первую; решение ТД (отказ/возврат/утверждение) вызывает слушателя с нужным статусом; правка/отмена/копия через сервисы БЗО — 409; позиции не видны в Плане и не выбираются в F-03; `release_to_plan` возвращает их в План; `budget_articles` отдаёт только группу роли; статья чужой группы — 403 `E-REQ-04`. Плюс зелёные `apps/bpp/tests/test_requests*.py`, `test_plan*.py`, сторож изоляции.

---

## 3. Заявка tender (T1.1, T1.3, T1.4)

### 3.1 Модели (`apps/tender/models/request.py`, миграция `tender/0002_requests`)

`TenderRequestStatus`: `draft` Черновик · `in_approval` На согласовании · `approved` Утверждена · `rework` На доработке · `rejected` Отклонена · `in_tender` В тендере · `handed_over` Передана в БЗО · `closed` Закрыта · `cancelled` Отменена.

`TenderRequest(VersionedModel)`: `number` (**`ЗТ-ГГГГ-NNNNNN`** [умолч.], уникален), `author_id`, `initiator_role` (`sn`/`pm` — роль БЗО, в которой подаются ЗЗ), `project_id` (UUID), `article_id` (UUID, null — статья по умолчанию), `purchase_type` (`goods`/`works`, по умолчанию `goods` — вид основных позиций), `need_date`, `delivery_address` (Text), `justification` (Text, ≥10 при отправке, T-05), `needs_delivery` (bool), `delivery_article_id`, `delivery_plan_amount` (Decimal null; > 0 при отправке, если `needs_delivery`, T-04), `needs_works` (bool), `works_scope` (Text), `works_article_id`, `works_plan_amount`, `allow_analogs` (bool, False), `allow_partial` (bool, True) [умолч.], `status`, `status_comment`, `rework_comment`.

`TenderRequestPart(TenderModel)`: `request` FK CASCADE, `kind` (`goods`/`delivery`/`works`), `article_id`, `purchase_type`, `bpp_request_id` (UUID null), `bpp_number`, `bpp_status` (зеркало, пишет слушатель), `excluded_at` (null). Уникальность (`request`, `kind`, `article_id`).

`TenderRequestItem(TenderModel)`: `request` FK CASCADE, `part` FK SET_NULL null (назначается при отправке), `line_no`, `name` (3–500), `specs`, `uom_id`, `qty` > 0, `plan_price` > 0, `need_date`, `article_id` (null = статья заявки), `bpp_request_item_id` (null). Позиции доставки и СМР **не хранятся строками** — строятся при отправке: одна позиция «Доставка до объекта» / «СМР: <объём работ>» qty 1, ед. `refdata.uom_id("service")`, цена = плановая сумма.

`register_history_access("tender.tenderrequest", can_view)`.

### 3.2 Разбиение на части при отправке (T-03)

Основные позиции группируются по `item.article_id or request.article_id` → часть `goods` с `purchase_type = request.purchase_type`; если `needs_delivery` — часть `delivery` (`works`, `delivery_article_id`); если `needs_works` — часть `works` (`works`, `works_article_id`). Части пересобираются при каждой отправке из черновика; на доработке уже утверждённые/идущие части не трогаются — правка позиций утверждённой части → 422 `E-TND-03`.

### 3.3 Статус заявки — свёртка частей (T-08)

Слушатель `bpp.register_request_listener` (регистрация из `TenderConfig.ready()`) обновляет `TenderRequestPart.bpp_status` и пересчитывает статус заявки, **только пока она в draft/in_approval/approved/rework/rejected**: по неисключённым частям — есть `rejected` → `rejected`; иначе есть `rework` → `rework` (+ `rework_comment` последней); иначе есть `draft` → `draft` (отзыв); иначе есть `in_approval` → `in_approval`; иначе все `approved` → `approved`; все `cancelled`/`closed` → `cancelled`. «Исключить часть» (`parts/<id>/exclude`) — только для `rejected`-части: `excluded_at`, её позиции удаляются из заявки, статус пересчитывается. Тендер (этап 2) объявляется, только если заявка `approved`.

### 3.4 API (`apps/tender/urls_requests.py` + `views_requests.py`, схемы — `schemas.py`)

| Метод и путь | Узел / уровень | Назначение |
|---|---|---|
| `GET requests` | `tender.requests` view, read | Реестр: свои; с `tender.requests.all` — все. Фильтры `status`, `project_id`, `q` (номер/наименование) |
| `POST requests` | `tender.requests` create, write | Черновик |
| `GET requests/<id>` | view | Карточка: шапка, позиции, части с `bpp_number`/`bpp_status`, `allowed_actions`, `version` |
| `PATCH requests/<id>` | edit (автор, draft/rework) | Правка с `version` |
| `DELETE requests/<id>` | delete (автор, draft, ни разу не отправлялась) | |
| `POST requests/<id>/submit` | edit | Разбиение на части + `bpp.submit_request_from_tender` |
| `POST requests/<id>/withdraw` | edit | `bpp.withdraw_requests_from_tender` |
| `POST requests/<id>/cancel` | edit | `{comment}` ≥10 — `bpp.cancel_requests_from_tender`, статус `cancelled` |
| `POST requests/<id>/parts/<part_id>/exclude` | edit | §3.3 |
| `GET requests/budget?project_id=&article_id=` | view | `bpp.budget_available` |
| `GET requests/articles?project_id=&role=` | view | `bpp.budget_articles` |
| `GET requests/projects?q=` | view | `project.interface.search_projects` (ПМ — только участия) |

Файлы ТЗ и чертежей — владелец `tender.request` в `apps.files` (`apps/tender/file_owners.py`, миграция `files/0006_tender_file_types`: тип `tender_spec` — PDF/DOCX/XLSX/DWG/JPG/PNG до 20 МБ, до 20 документов); правка — автор в draft/rework.

### 3.5 Фронт (T1.4)

`features/tender/requests/`: реестр (`/tender/requests`), форма (`/tender/requests/new`, `/tender/requests/:id/edit`), карточка (`/tender/requests/:id`) с частями «ЗЗ-… — На согласовании» и ссылкой на ЗЗ в БЗО, подсказкой остатка статьи в форме, кнопками по `allowed_actions`. Тексты — `t('tender.…', 'фолбэк')`, ключи в `public/locales/ru/translation.json`.

---

## 4. Тендер и участники (T2.1, T2.2, T2.3)

### 4.1 Модели (`apps/tender/models/tender.py`, `supplier.py`; миграция `tender/0003_tenders`)

`TenderStatus`: `draft` Черновик · `intake` Приём предложений · `opened` Вскрыт · `on_approval` На утверждении · `awarded` Выбор утверждён · `handed_over` Документы в БЗО · `delivery` Поставка · `closed` Закрыт · `cancelled` Отменён · `failed` Не состоялся · `rework` Возвращён на доработку. Активные — все, кроме `cancelled`/`failed`/`closed`.

`Tender(VersionedModel)`: `number` (`ТН-ГГГГ-NNNNNN`), `request` FK PROTECT, `author_id`, `deadline_at` (DateTime), `currency_code` (желаемая, `KZT`), `delivery_terms`, `opened_at`, `round` (1), `parent_tender` FK null, `quality_reviewer_user_id` (null — ТД по должности, T-11), `cancel_reason`, `status`. Ограничение «одна заявка — один активный тендер» — частичный `UniqueConstraint(request, condition=status in активные)`.

`PaymentScheme(TenderModel)`: `tender` FK CASCADE null (желаемая схема тендера; у предложения — этап 3), `kind` (`prepay` 1 · `advance` 2 · `postpay` 3 · `staged` 4), `postpay_days` (null). `PaymentStage(TenderModel)`: `scheme` FK CASCADE, `order`, `trigger` (`before_shipment`/`on_receipt`/`after_works`/`after_warranty`), `pct` (Decimal(5,2)), `days` (null). Шаблоны — `services/tenders/schemes.py::from_template(kind, *, advance_pct=None, days=None)`: 1 — `before_shipment 100`; 2 — `before_shipment X` + `on_receipt 100−X`; 3 — `on_receipt 100` + `postpay_days`; 4 — в пилоте 422 «после пилота». Сумма `pct` = 100.

`SupplierContact(TenderModel)`: `counterparty_id` (UUID), `email`, `name`, `phone`, `is_primary`, `is_active`. Уникальность (`counterparty_id`, `email`).

`SupplierProspect(VersionedModel)`: `name`, `email`, `reg_number`, `country_code`, `source` (`manual`), `counterparty_id` (null — заполнится после выбора, этап 5), `created_by`.

`Invitation(TenderModel)`: `tender` FK CASCADE, `counterparty_id` (UUID null) **XOR** `prospect` FK PROTECT null (`CheckConstraint`), `email`, `name`, `token_hash` (`CharField(64)`, уникален), `status` (`created`, `sent`, `delivery_error`, `opened`, `submitted`, `declined`, `awarded`, `not_awarded`, `revoked`, `expired`), `sent_at`, `delivery_error`, `first_opened_at`, `revoked_at`, `max_devices` (1; настройка до 2, ТЗ решение 9). Уникальность (`tender`, `email`) среди не отозванных.

`DeviceBinding(TenderModel)`: `invitation` FK CASCADE, `secret_hash`, `user_agent`, `ip`, `bound_at`, `revoked_at` — в этапе 2 только сброс (`reset-device` ставит `revoked_at`), выдаёт этап 3.

### 4.2 Правила

- Тендер создаётся из заявки `approved` (иначе 409 `E-STS-01`), заявка → `in_tender` при публикации; отмена тендера / «Не состоялся» возвращает заявку в `approved` (ТЗ). Второй активный тендер — 409 `E-TND-01`.
- Участник-контрагент — только `status == "active"` по `bpp.counterparty_brief` (иначе 422 `E-TND-02`); email — из выбранного `SupplierContact` или контакта карточки контрагента. Потенциальный — `SupplierProspect` с email.
- **Токен**: `secrets.token_urlsafe(32)`, в БД — SHA-256 hex (`hashlib.sha256`), сырой токен отдаётся **только** в ответе публикации / перевыпуска (поле `link`) — повторно его не получить. Ссылка — `companies.interface.public_url(slug) + "/supplier/" + token` (пустой `public_url` — относительный путь `/supplier/<token>`).
- Публикация (`draft` → `intake`): ≥1 приглашение, `deadline_at` в будущем, есть схема оплаты; всем `created` — выпуск токенов, статус `sent` **без писем** (почта — этап 4; `sent_at` = время публикации). Добавленный после публикации участник получает ссылку сразу.
- До срока: `extend` (новый срок > старого и > сейчас), добавить участника, `revoke`, `reissue` (старый хэш заменён — старая ссылка 404 на этапе 3), `reset-device`, `cancel` с причиной ≥10 (все приглашения → `revoked`).
- Счётчики TND-013: `sent` / `opened` / `submitted` — из статусов приглашений; предложения до вскрытия не отдаются (их модели — этап 3).
- Видимость: автор; с `tender.tenders.all` — все.

### 4.3 API (`urls_tenders.py`/`views_tenders.py`, `urls_suppliers.py`/`views_suppliers.py`)

| Метод и путь | Узел | Назначение |
|---|---|---|
| `GET/POST tenders` | `tender.tenders` view/create | Реестр; создать из `request_id` |
| `GET/PATCH tenders/<id>` | view/edit | Карточка (+ счётчики, приглашения без хэшей) / правка черновика и `quality_reviewer_user_id` |
| `PUT tenders/<id>/payment-scheme` | edit | `{kind, advance_pct?, postpay_days?}` → шаблон |
| `POST tenders/<id>/publish` · `extend` · `cancel` | edit | Жизненный цикл; `publish` отдаёт `links` |
| `GET/POST tenders/<id>/invitations` | view/edit | Участники; `POST` — `{counterparty_id, contact_id?}` или `{prospect_id}`; после публикации отдаёт `link` |
| `POST tenders/<id>/invitations/<inv>/revoke` · `reissue` · `reset-device` | edit | `reissue` отдаёт новый `link` |
| `GET/POST contacts?counterparty_id=` · `PATCH/DELETE contacts/<id>` | `tender.prospects` | Контакты контрагентов |
| `GET/POST prospects` · `GET/PATCH prospects/<id>` | `tender.prospects` | Потенциальные поставщики |
| `GET counterparties?q=` | `tender.tenders` view | `bpp.search_counterparties` |

**Формы ответов** (по ним строится фронт T2.3): карточка тендера — `{id, number, status, request_id, request_number, deadline_at, currency_code, delivery_terms, quality_reviewer_user_id, cancel_reason, round, version, allowed_actions[] (edit/publish/extend/cancel/invite), payment_scheme: {kind, postpay_days, stages:[{order, trigger, pct, days}]} | null, counters: {sent, opened, submitted}, invitations: [...]}`; приглашение — `{id, counterparty_id, prospect_id, name, email, status, sent_at, first_opened_at, revoked_at, max_devices}` (токена и хэша нет никогда); `link` — только в ответах `publish` (`{links: [{invitation_id, link}]}`), `reissue` (`{link}`) и `POST invitations` после публикации; контакт — `{id, counterparty_id, email, name, phone, is_primary, is_active}`; потенциальный поставщик — `{id, name, email, reg_number, country_code, counterparty_id, version}`; `counterparties?q` — карточки `bpp.search_counterparties`. Тела: `extend` — `{deadline_at, version}`, `cancel` — `{reason, version}`, `payment-scheme` — `{kind, advance_pct?, postpay_days?}`.

Дополнение от фронта (T2.3): строка реестра — `{id, number, status, request_id, request_number, deadline_at, counters}`; `PUT payment-scheme` без `version`, `advance_pct` — строкой (`"30.5"`), `postpay_days` — числом; после `publish`/`revoke`/`reset-device` фронт перечитывает карточку; карточка может отдавать `quality_reviewer_name` (иначе фронт показывает «Пользователь № id»).

### 4.4 Фронт (T2.3)

`features/tender/tenders/`: реестр (`/tender/tenders`), «Объявить тендер» с карточки утверждённой заявки, карточка тендера (срок, валюта, схема оплаты, условия, проверяющий), участники (поиск контрагента + контакт; потенциальный поставщик), публикация с диалогом ссылок и кнопками «Скопировать», счётчики «отправлено / открыто / подано», продление, отзыв, перевыпуск, сброс устройства, отмена. Справочник потенциальных поставщиков — `/tender/prospects`.

---

## 5. Раскладка файлов (кто что правит)

| Задача | Файлы |
|---|---|
| T0.3 | `apps/tender/access_functions.py`, `apps/access/migrations/0027_tender_roles.py`, `apps/tender/management/commands/tender_assign_roles.py`, `apps/tender/tests/test_roles.py` |
| T0.4 | `frontend/src/features/tender/**` (каркас), маршруты/меню/`lazyPages`, `vite.config.ts` + `endpoints.proxy.test.ts`, ключи `tender.*` |
| T0.5 | ТЗ (переименование), `STRUCTURE.md`, `API.md`, `CLAUDE.md` |
| T1.1 | `apps/tender/models/request.py`, `migrations/0002_*`, `file_owners.py`, `apps/files/migrations/0006_*`, `urls*.py`/`views_requests.py`/`schemas.py` (CRUD), `services/requests/crud.py`, тесты |
| T1.2 | `apps/bpp/**` (модель, миграция `0021`, сервисы заявок и плана, `interface.py`, `schemas/tender.py`), `apps/bpp/tests/test_tender_bridge.py` |
| T1.3 | `apps/tender/services/requests/{submit,status}.py`, `apps.py` (слушатель), ручки submit/withdraw/cancel/exclude/budget/articles/projects, тесты |
| T1.4 | `frontend/src/features/tender/requests/**` |
| T2.1–T2.2 | `apps/tender/models/{tender,supplier}.py`, `migrations/0003_*`, `services/tenders/**`, `services/suppliers/**`, `urls_tenders.py`/`views_tenders.py`, `urls_suppliers.py`/`views_suppliers.py`, тесты |
| T2.3 | `frontend/src/features/tender/{tenders,prospects}/**` |

Коды ошибок модуля: `E-TND-01` второй активный тендер · `E-TND-02` участник не может быть приглашён · `E-TND-03` правка утверждённой части · `E-TND-04` публикация не готова (нет участников/срока/схемы) · `E-STS-02` ЗЗ ведётся в тендерном модуле (в БЗО).

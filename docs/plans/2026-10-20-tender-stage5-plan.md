# Тендерный модуль — этап 5 (T5.1–T5.7): пошаговый план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** вскрытие и сравнение предложений, выбор поставщиков с утверждением «Проверка качества → ФД», передача выбора в БЗО документами, стадии поставки и приёмка с закрывающими — сквозной сценарий ТЗ этапа 5.

**Architecture:** всё новое в tender — подмодули `services/comparison`, `services/award`, `services/delivery`, модели `award.py` и `delivery.py`, предмет signoff `tender.award`. Стык с БЗО — только `bpp.interface` (пакет B-2, зона B, коммиты `bpp(B):`) и `refdata.interface` (зона A). Фронт — вкладки карточки тендера и общая таблица сравнения в `features/bpp/core`.

**Tech Stack:** Django 5.2.7 / Python 3.14 (корневой `.venv`), pytest на Postgres `:55432`, React + Vite + vitest, Playwright (`--project=chromium`).

**Spec:** [2026-10-20-tender-stage5-spec.md](2026-10-20-tender-stage5-spec.md) — правила §1, модель §2, задачи §3, решения S5-01…S5-20 §6. Над ней — [мастер-план](2026-10-06-tender-master-plan.md) (T-01…T-31, пакет B-2 §3.4).

## Global Constraints

- **Ветка `tender` не пушится до конца модуля**; коммиты — локальные; веток не создавать.
- Соседи — только через `apps.<x>.interface` (сторож `test_app_isolation` сканирует и management-команды); новые ручки — `api_view(module="tender", level="read"|"write")`.
- Деньги — `Decimal`, округление до 0,01 `ROUND_HALF_UP` на строке, затем сумма; на фронте — копейки `BigInt` (`features/bpp/budgets/cents.ts`), никакого `float`.
- Тенантные миграции — expand; на стенде после каждой — `docker exec htqweb-local-backend-web-1 python manage.py migrate_companies`.
- Один прогон pytest за раз; прогон дольше 10 минут — `nohup` в каталоге сессии. Время в тестах — `pinned_clock`.
- Фронт: `npx tsc --noEmit -p tsconfig.app.json` — не больше **148** ошибок; тексты — `t('tender.…', 'фолбэк')` в обоих `translation.json`.
- Коды ошибок этапа: `E-TND-07` до вскрытия (409), `E-TND-10` нет курса (422), `E-TND-11` дефицит бюджета (422), `E-TND-12` нужен комментарий (422), `E-TND-13` приёмка сверх выбранного (422), `E-TND-14` нет реквизитов для карточки контрагента (422).
- Коммиты — по-русски, `feat(tender):`/`fix(tender):`/`bpp(B):`/`docs(tender):`, в конце `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Стенд для ручной проверки: `seed_bpp_demo` → `tender_assign_roles` → `seed_tender_demo --company hi-tech-group` (тендер «к-вскрытию» — пять участников, срок в прошлом).

## Review Focus

1. **Курс на выходной день вскрытия** — поставщик в USD, вскрытие в воскресенье: берётся пятничный курс, `rate_on` в ответе — пятница. Тест — Task 1 и Task 3.
2. **Возврат выбора с утверждения и повторная отправка** — после «Вернуть» ФД выбор снова правится, повторная отправка запускает новый процесс, а не падает на «процесс уже идёт». Тест — Task 6.
3. **Повторное нажатие «Передать в БЗО»** (двойной клик, обрыв сети) — те же документы, ни одного дубля ни в tender, ни в БЗО. Тест — Task 8.
4. **Счёт поставщика заменён альтернативой БЗО** — стадии поставки идут по новому документу, приёмка ставит отметку уже на него. Тест — Task 9.
5. **Отменённая ошибочная приёмка** — количество к получению возвращается, дата приёмки на счёте пересчитывается по оставшимся, стадия откатывается. Тест — Task 9.

---

### Task 1: Курс «не позже даты» и контрагент из потенциального поставщика (T5.4, зона A)

**Files:**
- Modify: `backend/apps/refdata/interface.py`, `backend/apps/refdata/services/lookup.py`
- Modify: `backend/apps/bpp/interface.py`, `backend/apps/bpp/schemas/tender.py`
- Create: `backend/apps/bpp/services/requests/tender_counterparty.py`
- Test: `backend/apps/refdata/tests/test_rate_on_or_before.py`, `backend/apps/bpp/tests/test_tender_counterparty.py`

**Interfaces:**
- Produces:
  - `refdata.interface.exchange_rate_on_or_before(currency: str, on_date: date) -> RateOut | None`, `RateOut` — dataclass `{rate: Decimal, on_date: date}`; KZT → `RateOut(Decimal("1"), on_date)`.
  - `bpp.schemas.tender.ProspectIn(name, country_code, reg_number, is_vat_payer, contact_name, phone, email)`, `CounterpartyRef(id: str, created: bool, status: str)`.
  - `bpp.interface.create_counterparty_from_prospect(data: ProspectIn, *, actor: TenderActor) -> CounterpartyRef`.

- [ ] **Step 1: Тесты курса** — `test_weekend_takes_friday` (курсы на пятницу 17.10 и четверг; запрос на воскресенье 19.10 → курс пятницы, `on_date == date(2026,10,17)`); `test_no_rate_at_all_is_none`; `test_kzt_is_one`.
- [ ] **Step 2: Тесты контрагента** — `test_existing_reg_number_is_linked_not_duplicated` (контрагент `KZ`/БИН есть → `created=False`, тот же `id`, контрагентов не прибавилось); `test_new_prospect_becomes_active_counterparty` (`created=True`, `status="active"`, `verified_override is None`); `test_blocked_counterparty_is_refused` (→ `DomainError` код `E-TND-14`, текст называет причину); `test_empty_reg_number_is_refused` (`E-TND-14`); `test_actor_without_create_right_is_403` (у актора нет `bpp.counterparties` create → `DomainError` статус 403).
- [ ] **Step 3: Прогнать — красные:** `../.venv/Scripts/python.exe -m pytest -q apps/refdata/tests/test_rate_on_or_before.py apps/bpp/tests/test_tender_counterparty.py`.
- [ ] **Step 4: Реализация** — `lookup.rate_on_or_before` (`ExchangeRate.objects.filter(currency_code=…, on_date__lte=…).order_by("-on_date").first()`), обёртка в interface с `require_service("refdata")`; в bpp — поиск по `country_code` + нормализованному `reg_number` (та же нормализация, что у `counterparties.service`), создание — `service.create(data, actor_id=…)`, право — `Actor.for_user(...).can("bpp.counterparties", "create")`; `kind` по правилу спеки (KZ + 12 цифр → `legal`, иначе `nonresident`).
- [ ] **Step 5: Зелёные** — тот же прогон + `apps/refdata` и `apps/bpp/tests/test_counterparties*.py`.
- [ ] **Step 6: Коммиты** — `feat(refdata): курс «не позже даты» для сравнения тендера (T5.4)` и `bpp(B): контрагент из потенциального поставщика тендера (T5.4)`.

---

### Task 2: Вскрытие (T5.1)

**Files:**
- Modify: `backend/apps/tender/models/tender.py`; Create: `backend/apps/tender/migrations/0006_opening.py`
- Create: `backend/apps/tender/services/comparison/__init__.py`, `opening.py`
- Modify: `backend/apps/tender/services/tenders/tenders.py` (`allowed_actions`, `card`), `file_owners.py` (`_offer_can_view`), `urls_tenders.py`, `views_tenders.py`
- Test: `backend/apps/tender/tests/test_opening.py`

**Interfaces:**
- Produces:
  - Поля `Tender`: `rate_date: DateField(null=True)`, `award_comment: TextField(blank=True)`, `status_comment: TextField(blank=True)`; `Tender(signoff.Approvable, VersionedModel)` с `SIGNOFF_SUBJECT_TYPE = "tender.award"` (колонка `approval_state` — та же миграция).
  - `opening.open_tender(ctx: Ctx | None, tender_id) -> Tender`; `opening.is_opened(tender) -> bool` (`opened_at is not None`); `opening.require_opened(tender) -> None` (иначе `DomainError("E-TND-07", …, status=409)`).
  - Ручка `POST tenders/<id>/open` `{version}` → карточка; `allowed_actions` получает `"open"` (статус `intake`, срок прошёл — или досрочно по S5-02).

- [ ] **Step 1: Тесты** (`test_opening.py`, мир — `seed`-подобная фикстура: тендер на приёме, 3 приглашения, 2 отправленных предложения, 1 без версии):
  - `test_open_after_deadline` — `pinned_clock` после срока → `status="opened"`, `opened_at`, `rate_date == localdate`, приглашение без версии → `expired`, журнал `opened`;
  - `test_open_before_deadline_only_when_everyone_answered` — до срока при молчащем участнике → 409 `E-STS-01`; все подали/отказались → вскрыт;
  - `test_open_without_offers_fails_the_tender` — ни одной отправленной версии → `failed`, заявка `approved`;
  - `test_not_author_cannot_open` — 403;
  - `test_portal_is_closed_after_opening` — `PUT supplier/<token>/offer` → 409 `E-TND-05`;
  - `test_offer_files_open_after_opening` — до вскрытия папка `tender.offer` для ФД пуста/404, после — видна автору и ФД;
  - `test_parallel_open_opens_once` (`transaction=True`, два потока) — один `opened`, второй 409.
- [ ] **Step 2: Красные** — `../.venv/Scripts/python.exe -m pytest -q apps/tender/tests/test_opening.py`.
- [ ] **Step 3: Миграция и модель** — `makemigrations tender -n opening`; проверить, что в миграции только `AddField` (expand).
- [ ] **Step 4: Сервис и ручка** — `open_tender` под `select_for_update` тендера; `ctx=None` — системный актор `portal_actor()` (для beat этапа 4); ручка — `api_view(module="tender", level="write")`.
- [ ] **Step 5: Зелёные** — `test_opening.py` + `test_tenders.py` + `test_portal_whitelist.py` + `apps/access/tests/test_gate.py`; `makemigrations --check`.
- [ ] **Step 6: Стенд** — `migrate_companies`; вскрыть «к-вскрытию» из `seed_tender_demo` руками через API — статус `opened`, «Молчун» — `expired`.
- [ ] **Step 7: Коммит** — `feat(tender): вскрытие предложений — по сроку, досрочно, «не состоялся» (T5.1)`.

---

### Task 3: Сравнение (T5.1)

**Files:**
- Create: `backend/apps/tender/services/comparison/money.py`, `table.py`
- Modify: `urls_tenders.py`, `views_tenders.py`
- Test: `backend/apps/tender/tests/test_comparison.py`

**Interfaces:**
- Consumes: `refdata.interface.exchange_rate_on_or_before` (Task 1), `opening.require_opened` (Task 2).
- Produces:
  - `money.gross(amount: Decimal, *, with_vat: bool, vat_rate: Decimal | None) -> Decimal` — по S5-03: с НДС — как есть; без НДС — как есть (цена = к оплате). Функция существует, чтобы правило S5-03 жило в одном месте, если Алгазы решит иначе.
  - `money.to_kzt(amount, rate) -> Decimal` (0,01 `ROUND_HALF_UP`).
  - `table.comparison(ctx, tender_id) -> dict` — форма ответа из спеки §3 T5.1 (`suppliers[]`, `items[]`, `extras[]`, `totals`, `warnings[]`).
  - Ручки `GET tenders/<id>/comparison`; `GET tenders/<id>/offers/<offer_id>/files/<doc_id>` → 302 `files.download_link`.

- [ ] **Step 1: Тесты** (числа — из сценария `seed_tender_demo` «к-вскрытию», курс USD задать в фикстуре `ExchangeRate(USD, пятница, 515.20)`):
  - `test_before_opening_is_409_even_for_fd` — `(409, "E-TND-07")` у ФД и у автора;
  - `test_full_cost_and_common_set` — общий набор = позиции 1–2 (поставщик B не предложил позицию 3); у A `total_common_kzt == 10·238000 + 4·219000 + 0 (доставка в цене) + 1150000`; у B `coverage == {"offered": 2, "total": 3}`, `rate_on == пятница`;
  - `test_usd_line_converted_by_rate` — `amount_kzt` строки B = `price·qty·rate`, округление до 0,01;
  - `test_cheapest_per_item_and_extra` — `cheapest_invitation_id` по `unit_price_kzt`; доставка «в цене» — 0 и `included_in_price`;
  - `test_saving_against_plan` — `saving_common_kzt = plan − total` (знак: удорожание отрицательное);
  - `test_missing_rate_is_null_with_warning` — курса CNY нет → `total_full_kzt is None`, в `warnings` — код `no_rate` с поставщиком;
  - `test_expired_validity_is_warned` — `valid_until` вчера → `valid_expired is True`, предупреждение;
  - `test_withdrawn_and_declined_not_in_table` — отозванное и отказ в `suppliers` нет, `declined` — в `totals.declined` с причиной;
  - `test_offer_file_link_journals_download` — 302 и `FileEvent` `file_downloaded`.
- [ ] **Step 2: Красные.**
- [ ] **Step 3: Реализация** — `money.py`, `table.py`: одна выборка отправленных версий с `lines`, `extras`, `payment_schemes`; курсы — один вызов на валюту.
- [ ] **Step 4: Зелёные** + сторож гейта.
- [ ] **Step 5: Коммит** — `feat(tender): сравнение предложений по полной стоимости в KZT (T5.1)`.

---

### Task 4: Экспорт сравнения и санитайзер формул (T5.1, T-27)

**Files:**
- Create: `backend/htqweb/xlsx_safe.py`, `backend/htqweb/tests/test_xlsx_safe.py`
- Create: `backend/apps/tender/services/comparison/export.py`; Modify: `urls_tenders.py`, `views_tenders.py`
- Modify: `backend/apps/bpp/services/core/export.py` (`_cell`)
- Test: `backend/apps/tender/tests/test_comparison_export.py`, `backend/apps/bpp/tests/test_export_formulas.py`

**Interfaces:**
- Produces: `htqweb.xlsx_safe.safe_cell(sheet, value) -> WriteOnlyCell` — строка с первым символом из `= + - @ 	 ` → ячейка-текст, значение без изменений; прочее — как есть. Ручка `GET tenders/<id>/comparison/export` → `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.

- [ ] **Step 1: Тесты** — `test_safe_cell_neutralises_six_prefixes` (параметризация по `= + - @ \t \r` и строка без префикса); `test_export_has_two_sheets_and_no_formula` (листы «Сравнение», «Поставщики»; ни одна ячейка не `data_type == "f"`; комментарий поставщика `=HYPERLINK(...)` хранится текстом); `test_bpp_export_escapes_plus_and_at` (у реестра БЗО ячейка `+7…` и `@cmd` — текст).
- [ ] **Step 2: Красные.**
- [ ] **Step 3: Реализация** — openpyxl, как `bpp/services/core/export.py`; БЗО `_cell` зовёт `safe_cell`.
- [ ] **Step 4: Зелёные** — + `apps/bpp/tests/test_export*.py`.
- [ ] **Step 5: Коммиты** — `feat(tender): экспорт сравнения в xlsx, общий санитайзер формул (T5.1)` и `bpp(B): экспорт реестров — все префиксы формул (T-27)`.

---

### Task 5: Выбор поставщиков (T5.2)

**Files:**
- Create: `backend/apps/tender/models/award.py`, migration `0007_awards.py`
- Create: `backend/apps/tender/services/award/__init__.py`, `selection.py`
- Modify: `models/__init__.py`, `urls_tenders.py`, `views_tenders.py`, `schemas.py`, `services/tenders/tenders.py` (`allowed_actions` — `"award"`, `"reviewer"`)
- Test: `backend/apps/tender/tests/test_award.py`

**Interfaces:**
- Consumes: `table.comparison` (Task 3).
- Produces:
  - Модель `Award(TenderModel)`: `tender` FK CASCADE, `offer` FK PROTECT, `line` FK `OfferLine` null, `extra` FK `OfferExtra` null (`CheckConstraint` XOR), `part_id` UUID, `qty` Decimal(15,3), `amount` Decimal(18,2), `amount_kzt` Decimal(18,2), `plan_amount_kzt` Decimal(18,2), `is_cheapest` bool, `comment` text; `UniqueConstraint(tender, line)`, `UniqueConstraint(tender, extra)`.
  - `selection.save(ctx, tender_id, data: dict) -> dict` (`data` — `schemas.AwardIn {version: int, comment: str, lines: [{line_id, qty, comment}], extras: [{extra_id, comment}]}`), `selection.view(ctx, tender_id) -> dict` — строки, итоги по поставщикам и частям, `budget_check`, `allowed_actions`.
  - Ручки `GET/PUT tenders/<id>/award`.

- [ ] **Step 1: Тесты:**
  - `test_one_supplier_per_item` — две строки одной позиции → 422 `E-VAL-01` у `lines`;
  - `test_qty_not_above_offered` — 422;
  - `test_extra_only_from_item_winner` — доставка поставщика, не выигравшего ни одной позиции части → 422;
  - `test_included_delivery_selected_automatically` — выбор позиций A → строка доставки A «в цене» с `amount_kzt == 0` в ответе без явного `extras`;
  - `test_not_cheapest_needs_both_comments` (S5-07) — выбор C по позиции 1: без комментариев → `(422, "E-TND-12")`, `details.rows` — позиция 1, `fields` — `comment` и `lines[0].comment`; только общий → 422 (`lines[0].comment`); только строчный → 422 (`comment`); оба ≥ 10 → 200; у самой дешёвой строки комментарий не требуется;
  - `test_award_only_in_opened_or_rework` — в `intake`, `on_approval`, `awarded` → 409;
  - `test_save_replaces_previous_selection` — повторный `PUT` заменяет набор, `version` растёт;
  - `test_reviewer_change_before_process` — `PATCH tenders/<id>` `quality_reviewer_user_id` в `opened` → 200, в `on_approval` → 409.
- [ ] **Step 2: Красные. Step 3:** модель, миграция, сервис. **Step 4:** зелёные + `test_tenders.py`. **Step 5: Коммит** — `feat(tender): выбор поставщиков по позициям, доставке и СМР (T5.2)`.

---

### Task 6: Утверждение `tender.award` (T5.2)

**Files:**
- Create: `backend/apps/tender/approval_hooks.py`, `services/award/submit.py`, `management/commands/tender_configure_route.py`
- Modify: `apps.py` (`ready` → `approval_hooks.register()`), `urls_tenders.py`, `views_tenders.py`
- Test: `backend/apps/tender/tests/test_award_signoff.py`, `test_configure_route.py`

**Interfaces:**
- Consumes: `bpp.interface.budget_available(project_id, article_id, *, actor, role)` (B-1), `signoff.interface.register_subject/start_process/configure_route`, `hr.interface.positions_by_title`, `hr.interface.resolve_position_users`, `access.interface.flags_for`.
- Produces:
  - `submit.submit(ctx, tender_id, *, expected_version: int) -> dict` — проверки курса (`E-TND-10`) и бюджета (`E-TND-11`, `details.deficits=[{article_id, article_code, over, available}]`), затем `start_process(subject_type="tender.award", subject_id=str(tender.id), initiator_id=author)`.
  - `approval_hooks.register()` — `register_subject("tender.award", label="Выбор поставщиков", model=Tender, approvers=_approvers, approver_fields=_approver_fields, on_started, on_approved, on_rejected, on_rework, on_cancelled, describe, summary)`; `_approver_fields() -> [{"key": "quality_reviewer", "label": "Проверяющий качество тендера"}]`.
  - Ручка `POST tenders/<id>/award/submit` `{version}`.
  - Команда `tender_configure_route --company SLUG [--fd ID] [--dry-run]` — этап 1 `approver_kind="subject"`, `approver_key="quality_reviewer"`; этап 2 — должность «Финансовый директор» (своя компания, затем вышестоящая, как `bpp_configure_routes`); флаги `{"reject_comment_min": 10, "forbid_self_approval": True}`; повтор — без изменений.

- [ ] **Step 1: Тесты:**
  - `test_deficit_blocks_submit` — `budget_available` статьи меньше перерасхода → `(422, "E-TND-11")`, в `deficits` — статья и суммы;
  - `test_missing_rate_blocks_submit` — `(422, "E-TND-10")`;
  - `test_td_by_position_gets_the_task` — проверяющий не назначен → задача у держателя должности «Технический директор»;
  - `test_assigned_reviewer_gets_the_task` — назначен пользователь с `tender-quality` → задача у него;
  - `test_fd_approval_awards` — оба решения → `awarded`, приглашения победителей `awarded`, участвовавшие без выбора `not_awarded`;
  - `test_return_goes_to_rework_and_resubmit_starts_new_round` (Review Focus 2) — ФД «На доработку» с комментарием → `rework`, `status_comment`; правка выбора → 200; повторный `submit` → `on_approval`, процесс — новый раунд;
  - `test_author_cannot_approve_own_award` — автор — держатель ТД → его группа уходит эскалации/пропуску по `forbid_self_approval` (поведение движка), сам он решить не может (403);
  - `test_no_route_is_409` — маршрута нет → 409 «Маршрут не настроен»;
  - `test_configure_route_is_idempotent`, `test_configure_route_dry_run_writes_nothing`.
- [ ] **Step 2: Красные. Step 3:** реализация. **Step 4:** зелёные + `apps/signoff` целиком (отдельным процессом) + `test_gate`.
- [ ] **Step 5: Стенд** — `tender_configure_route --company hi-tech-group`; на «к-вскрытию» сохранить выбор и отправить — задача у ТД в «Ждёт меня».
- [ ] **Step 6: Коммит** — `feat(tender): утверждение выбора «Проверка качества → ФД», маршрут tender.award (T5.2)`.

---

### Task 7: Пакет B-2 в БЗО (T5.3 [B], зона Руслана — коммиты `bpp(B):`)

**Files:**
- Modify: `backend/apps/bpp/models/invoices.py`; Create: `backend/apps/bpp/migrations/0022_invoice_receipt.py`
- Create: `backend/apps/bpp/services/requests/tender_documents.py`, `backend/apps/bpp/services/core/doc_listeners.py`
- Modify: `bpp/interface.py`, `bpp/schemas/tender.py`, `bpp/services/invoices/{invoices,read,decisions,payments}.py` и `agreements/agreements.py` (вызов слушателей при смене статуса), `bpp/services/invoices/read.py` (поля приёмки в карточке, пометка «ждёт приёмки» в очереди БУХ)
- Modify (фронт БЗО): `frontend/src/features/bpp/invoices/` — строка «Товар принят …, оригиналы переданы …» в карточке, пометка в очереди
- Test: `backend/apps/bpp/tests/test_tender_documents.py`, vitest карточки счёта

**Interfaces:**
- Produces — ровно спека §3 T5.3: `HandoverLineIn`, `HandoverDocIn`, `TenderHandover`, `DocumentRef`, `DocumentStatusOut`, `ClosingFileIn {media_file_id: str, file_type: Literal["waybill","act","vat_invoice"], name: str}`; функции `create_documents_from_tender`, `documents_status`, `set_acceptance`, `attach_closing_docs`, `register_document_listener`. Поля `Invoice`: `pay_after_receipt`, `postpay_days`, `received_at`, `originals_at`, `originals_to`, `source_tender`.
- Внутри: документы собираются как `services/selection/documents.py::_draft` (B5.1) — `new_invoice`/`new_agreement` + контрагент, валюта, НДС; актор — `Actor.for_user(actor.user_id, company=current_company())`.

- [ ] **Step 1: Тесты** (`test_tender_documents.py`, ЗЗ `source="tender"` в статусе «Утверждена» — фикстура B-1):
  - `test_invoice_for_supplier_below_threshold` — `kind="invoice"`, `prepay` → черновик счёта, `is_advance=True`, автор — закупщик, `source_tender` = номер ТН;
  - `test_advance_is_one_invoice_with_partial_marks` — `advance` → один счёт `is_advance=True`; две частичные отметки БУХ допустимы;
  - `test_postpay_invoice_waits_for_receipt` — `postpay`, `postpay_days=14` → `pay_after_receipt=True`; `set_acceptance(received_at=пятница 06.11.2026)` → `due_date == refdata.add_bank_days(06.11, 14)` (банковские дни, S5-12), карточка отдаёт `received_at`;
  - `test_agreement_above_threshold` — `kind="agreement"` → договор-черновик по ЗЗ;
  - `test_repeat_returns_same_documents` (Review Focus 3) — второй вызов с теми же `key` → те же `doc_id`, документов не прибавилось;
  - `test_lines_must_belong_to_request` / `test_qty_above_remaining` — `DomainError` E-STS / BR-042;
  - `test_closing_docs_only_in_awaiting_docs_and_requested_type` — `attach_closing_docs` при `paid` → 409; при `awaiting_docs` с `docs_required=["waybill"]` и файлом `act` → 409; `waybill` → прикреплён;
  - `test_status_reports_payments_and_replacement` — `documents_status`: `paid_amount` = Σ живых отметок; заменённый альтернативой → `replaced_by`;
  - `test_listener_called_in_status_transaction` — слушатель видит `awaiting_docs` при `request_docs` и `closed` при `accept_docs`.
- [ ] **Step 2: Красные. Step 3:** миграция (expand), сервисы, слушатели. **Step 4:** зелёные + **`apps/bpp` целиком** (отдельным процессом) + vitest `features/bpp/invoices`.
- [ ] **Step 5: Коммиты `bpp(B):`** — модель и миграция; `create_documents_from_tender`/`documents_status`; приёмка и закрывающие; слушатель; карточка счёта на фронте. Руслану — список коммитов на ревью (Q-T09).

---

### Task 8: Передача в БЗО (T5.5)

**Files:**
- Create: `backend/apps/tender/models/delivery.py` (`Handover`, `Receipt`, `ReceiptLine`), migration `0008_delivery.py`
- Create: `backend/apps/tender/services/award/handover.py`
- Modify: `urls_tenders.py`, `views_tenders.py`, `services/tenders/tenders.py` (`allowed_actions` — `"handover"`)
- Test: `backend/apps/tender/tests/test_handover.py`

**Interfaces:**
- Consumes: `bpp.create_counterparty_from_prospect` (Task 1), `bpp.create_documents_from_tender` (Task 7), `bpp.cancel_requests_from_tender` (B-1), `refdata.contract_threshold`.
- Produces: `handover.handover(ctx, tender_id, *, expected_version: int) -> dict` — `{documents: [{invitation_id, part_id, doc_type, doc_id, number}], closed_parts: [part_id]}`; модель `Handover` (уникальность `tender, invitation, part_id`); ручка `POST tenders/<id>/handover` `{version}`.

- [ ] **Step 1: Тесты:**
  - `test_threshold_per_document` (S5-10) — у одного поставщика часть «товар» > `contract_threshold(today)` → договор, его же доставка ≤ порога → счёт; граница ровно = порогу → счёт;
  - `test_supplier_scheme_goes_to_documents` — у поставщика `postpay 15` → в `HandoverDocIn.payment == "postpay"`, `postpay_days == 15`; без своей схемы — схема тендера; схема 3 без дней → 14 (S5-12);
  - `test_prospect_becomes_counterparty` — `prospect.counterparty_id` записан, повтор не создаёт второй карточки;
  - `test_prospect_without_reg_number_is_422` — `E-TND-14`, документов не создано (транзакция);
  - `test_handover_twice_is_idempotent` (Review Focus 3);
  - `test_unawarded_part_is_closed` — доставка «в цене» → её ЗЗ закрыта `cancel_requests_from_tender`, резерв освобождён (`budget_available` вырос);
  - `test_status_handed_over` — тендер и заявка `handed_over`, журнал `handover`.
- [ ] **Step 2–4:** красные → реализация → зелёные (+ `apps/bpp/tests/test_tender_documents.py`).
- [ ] **Step 5: Коммит** — `feat(tender): передача выбора в БЗО — договоры и счета по порогу (T5.5)`.

---

### Task 9: Стадии поставки, приёмка, закрывающие (T5.5)

**Files:**
- Create: `backend/apps/tender/services/delivery/__init__.py`, `stages.py`, `receipts.py`, `closing.py`
- Modify: `file_owners.py` (владелец `tender.receipt`), `apps.py` (`bpp.register_document_listener(closing.on_document)`), `portal/serializers.py` (`_result`), `urls_tenders.py`, `views_tenders.py`
- Create: `backend/apps/files/migrations/0008_tender_receipt_types.py`
- Test: `backend/apps/tender/tests/test_delivery.py`, `test_receipts.py`, `test_portal_result.py`

**Interfaces:**
- Consumes: `bpp.documents_status`, `bpp.set_acceptance`, `bpp.attach_closing_docs`, `bpp.register_document_listener` (Task 7); `files.current_files`.
- Produces:
  - `stages.delivery(ctx, tender_id) -> dict` — `[{invitation_id, name, stage, documents, paid, total, received, scheme}]`, стадии — ключи `awaiting_documents | awaiting_shipment_payment | in_delivery | partially_received | received | awaiting_final_payment | closed | replaced`;
  - `receipts.create(ctx, tender_id, data) -> dict`, `receipts.set_originals(ctx, tender_id, receipt_id, data) -> dict`, `receipts.cancel(ctx, tender_id, receipt_id, *, comment) -> dict`;
  - `closing.on_document(status: DocumentStatusOut) -> None` — прикладывает сканы при `awaiting_docs`, переводит тендер в `closed`;
  - Ручки `GET tenders/<id>/delivery`, `POST tenders/<id>/receipts`, `PATCH …/receipts/<rid>`, `POST …/receipts/<rid>/cancel`.
  - Типы файлов `waybill`, `act`, `vat_invoice` (уже есть у БЗО — переиспользуются), `tender_photo` — новый.

- [ ] **Step 1: Тесты стадий** (`test_delivery.py`, отметки БУХ — через сервис БЗО `payments.mark_paid` в фикстуре БЗО-теста или через interface-обёртку теста):
  - `test_prepay_stages` — до оплаты `awaiting_shipment_payment`, после 100 % — `in_delivery`, после приёмки — `received`, после «Закрыт» счёта — `closed`;
  - `test_advance_30_stages` — оплата 30 % → `in_delivery`; приёмка → `awaiting_final_payment`; доплата → `received`→`closed`;
  - `test_postpay_stages` — после согласования счёта сразу `in_delivery`; приёмка ставит `due_date`;
  - `test_replaced_document_followed` (Review Focus 4) — счёт заменён альтернативой → стадия по новому, `set_acceptance` уходит на новый;
  - `test_tender_closed_when_all_closed` — последний счёт «Закрыт» → тендер и заявка `closed`.
- [ ] **Step 2: Тесты приёмки** (`test_receipts.py`): `test_partial_receipt`; `test_receipt_above_awarded_is_422` (`E-TND-13`); `test_works_accepted_with_act`; `test_cancel_receipt_rolls_back` (Review Focus 5 — количество, дата на счёте, стадия); `test_scans_attached_on_awaiting_docs` (БУХ `request_docs` → накладная из приёмки на счёте, тип не из запроса — не прикреплён); `test_viewer_and_reviewer_do_not_see_closing_scans` (T-17: `tender-viewer` и проверяющий видят фото, не видят `waybill`/`act`/`vat_invoice`).
- [ ] **Step 3: Тест портала** (`test_portal_result.py`): `result` — `awaiting` до `awarded`; победитель — `awarded` с перечнем своих позиций; невыбранный — `not_awarded`; `cancelled`/`failed`; сторож белого списка — без сумм других поставщиков.
- [ ] **Step 4: Красные. Step 5:** реализация. **Step 6:** зелёные + `test_portal_whitelist.py` + `apps/files`.
- [ ] **Step 7: Коммит** — `feat(tender): стадии поставки, приёмка, закрывающие на счёт БЗО (T5.5)`.

---

### Task 10: Фронт — вскрытие, сравнение, выбор (T5.6)

**Files:**
- Create: `frontend/src/features/bpp/core/ComparisonGrid.tsx` (+ `.test.tsx`) — вынесена из `features/bpp/alternatives/AlternativesBlock.tsx` (`ComparisonTable`)
- Modify: `features/bpp/alternatives/AlternativesBlock.tsx` (использует `ComparisonGrid`)
- Create: `features/tender/tenders/{ComparisonTab,AwardTab}.tsx` (+ тесты), `features/tender/tenders/comparison.ts` (типы ответа и разбор)
- Modify: `features/tender/tenders/{api.ts,TenderCardPage.tsx}`, `public/locales/{ru,en}/translation.json`

**Interfaces:**
- Produces: `ComparisonGrid<Row, Column>({ columns, rows, cell, highlight, footer, renderSelect })` — колонки — поставщики/предложения, строки — позиции, `highlight(row, column) -> 'cheapest' | null`; `tendersApi.open/comparison/exportComparison/getAward/saveAward/submitAward`.

- [ ] **Step 1: Тесты** — `ComparisonGrid.test.tsx` (колонки, подсветка, слот выбора); `AlternativesBlock.test.tsx` — прежние тесты зелёные без изменений (рефакторинг поведение не меняет); `ComparisonTab.test.tsx` (вкладки нет до вскрытия; пометки «аналог», «N из M ед.», «срок истёк», «нет курса»; кнопка экспорта); `AwardTab.test.tsx` (выбор поставщика в строке, доставка «в цене» сама, ответ 422 `E-TND-12` → поле комментария с перечнем строк, 422 `E-TND-11` → блок дефицита по статьям, «На утверждение» уходит с `version`).
- [ ] **Step 2: Красные** — `npx vitest run src/features/tender src/features/bpp/core src/features/bpp/alternatives`.
- [ ] **Step 3: Реализация.** **Step 4:** зелёные; eslint; tsc ≤ 148.
- [ ] **Step 5: Коммит** — `feat(tender): сравнение и выбор поставщиков во фронте, общая таблица сравнения (T5.6)`.

---

### Task 11: Фронт — утверждение, передача, поставка, портал (T5.6)

**Files:**
- Create: `features/tender/tenders/{DeliveryTab,ReceiptDialog}.tsx` (+ тесты)
- Modify: `TenderCardPage.tsx` (блок «Ход согласования» — `SubjectProcesses` из `components/signoff`), `features/tender/portal/{types.ts,PortalScreens.tsx,OfferEditor.tsx}` (итог TND-035)

- [ ] **Step 1: Тесты** — `DeliveryTab.test.tsx` (стадии, документы БЗО ссылками, «Отметить получение» доступно с `in_delivery`, «Оригиналы переданы»); `ReceiptDialog.test.tsx` (количество не больше остатка — ошибка у строки; сканы — общая панель файлов владельца `tender.receipt`); портал — `SupplierTender.test.tsx`: `result: 'awarded'` → «Выбрано по позициям: …», `not_awarded` → «Не выбрано».
- [ ] **Step 2–4:** красные → реализация → зелёные; eslint; tsc ≤ 148.
- [ ] **Step 5: Коммит** — `feat(tender): утверждение, передача и поставка во фронте, итог в портале (T5.6)`.

---

### Task 12: Метрики и сквозные сценарии (T5.6)

**Files:**
- Create: `backend/apps/tender/metrics.py`, `infra/logging/grafana-dashboards/htqweb-tender.json`
- Modify: `infra/logging/grafana-provisioning/alerting/rules.yml` (+ `templates.yml`, если нужна подпись)
- Create: `backend/apps/tender/tests/test_metrics.py`, `test_stage5_e2e.py`; `frontend/tests/e2e/41_tender_award.spec.ts`

**Interfaces:**
- Produces: `collect() -> dict` с ключами `tender_tenders` (`values: [((status,), n)]`), `tender_award_approval_stale`, `tender_delivery_overdue`; правило `htqweb-tender-award-stale` (`channel=business`, `noDataState: OK`).

- [ ] **Step 1: Тесты метрик** — `test_collect_counts_by_status`; `test_stale_award_counted_after_three_working_days` (`pinned_clock`); сторож `apps/core/tests/test_metrics_are_observed.py` — зелёный (каждая метрика на дашборде или в правиле).
- [ ] **Step 2: Сквозной pytest** `test_stage5_e2e.py` — сценарий спеки §3 T5.6 от заявки до «Закрыт» (2 поставщика, доставка и СМР, ТД → ФД, договор + счёт, аванс 30 %, приёмка, закрывающие, оплата остатка).
- [ ] **Step 3: Playwright** `41_tender_award.spec.ts` (стенд + `seed_tender_demo`): вскрыть «к-вскрытию», сравнение видно, выбор с комментарием, ТД и ФД утверждают (вход их учётками `demo12345`), передача — документы БЗО ссылками. Запуск — `npx playwright test tests/e2e/41_tender_award.spec.ts --project=chromium`.
- [ ] **Step 4:** `./scripts/check-monitoring-config.sh` — зелёный.
- [ ] **Step 5: Коммит** — `feat(tender): метрики этапа 5 и сквозной сценарий (T5.6)`.

---

### Task 13: Ранбук, документация, регрессия, ревью (T5.7)

- [ ] **Step 1: Ранбук** `docs/deploy/tender-rollout-runbook.md` — по спеке §3 T5.7 (порядок миграций `files/0006–0008`, `access/0026–0027`, `bpp/0021–0022`, `tender/0001–0008`; `tender_assign_roles`, `tender_configure_route`; ClamAV; `service tender --on` только у холдинга; откат). Протокол репетиции на дампе заполняет пользователь.
- [ ] **Step 2: Документация** — API.md (ручки этапа 5, B-2 в разделе `apps.bpp`), STRUCTURE.md (`services/comparison|award|delivery`, модели, `ComparisonGrid`), CLAUDE.md (абзац тендерного модуля — этап 5, коды ошибок, `tender_configure_route`).
- [ ] **Step 3: Регрессия** одним процессом: `apps/tender apps/bpp apps/signoff apps/files apps/refdata apps/access/tests/test_gate.py htqweb/tests` + сторожа CI (`test_invariants`, `test_app_isolation`, `test_periodic_tasks`, `test_platform_today`, `test_metrics*`, `test_digest`, `test_service_gate`); `makemigrations --check`. Полный vitest — без новых падений.
- [ ] **Step 4: `harness-review`** всего этапа (диапазон от коммита спеки `9f58c7fb`), Critical/Major — исправить; `nginx -t` — хвост T3.1, если пользователь разрешил.
- [ ] **Step 5: `Plans.md`** — T5.1–T5.7 `cc:完了 [хэши]`, итог этапа. **Пуш и PR — только по команде пользователя.**

# Тендерный модуль — доводка этапа 3 (T3.6–T3.9): пошаговый план

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** закрыть этап 3 (портал поставщика, T3.1–T3.5): починить фронт портала, доделать проверки и сторожа бэкенда, действия приглашения после срока, затем проверки, документацию и локальные коммиты.

**Architecture:** бэкенд портала уже написан (`apps/tender/services/portal/`, `views_supplier.py`, 315 тестов зелёные). План правит порядок проверок в ручках, сторожа и действия приглашения; фронт портала (`features/tender/portal`) приводится к настоящему контракту ответов.

**Tech Stack:** Django 5.2.7 / Python 3.14 (корневой `.venv`), pytest-django на Postgres `:55432`, React + Vite + vitest, Playwright (`--project=chromium`).

**Spec:** [2026-10-07-tender-stage3-portal-plan.md](2026-10-07-tender-stage3-portal-plan.md) — §1 (сквозные правила) и §4 (доводка, состояние на 20.10, принятые отступления, отклонённое). Над ним — мастер-план [2026-10-06-tender-master-plan.md](2026-10-06-tender-master-plan.md).

## Global Constraints

- **Ветка `tender` не пушится до конца модуля** (решение пользователя 20.10): ни пуша, ни PR. Коммиты — только локальные. Веток не создавать.
- Один прогон pytest за раз (общая тестовая БД); прогон дольше 10 минут — отдельным процессом через `nohup`, не фоновой командой инструмента.
- Интерпретатор: `../.venv/Scripts/python.exe` из `backend/` (Python 3.14, Django 5.2.7).
- Соседи — только через `apps.<x>.interface`; ручки портала — `api_view(..., auth=None)` литералом.
- Ответы портала — белым списком; ключи, запрещённые на любой глубине: `plan_price`, `delivery_plan_amount`, `works_plan_amount`, `budget`, `invitations`, `counters`, `token`, `token_hash`, `secret_hash`, `author_id`, префиксы `quality_reviewer`, `bpp_`.
- Коды ошибок: `E-TND-05` (приём завершён, 409), `E-TND-06` (устройство, 403/409), `E-TND-08`, `E-TND-09`, `E-RATE-01` (429 + `Retry-After` + `details.retry_after`), `E-VAL-01` (422), `E-VAL-02` (415), `E-ACC-01` (403 Origin).
- Фронт: `npx tsc --noEmit -p tsconfig.app.json` — не больше **148** ошибок; тексты — `t('tender.…', 'фолбэк')`, ключи в обоих `translation.json`.
- Сообщения коммитов — по-русски, префикс `feat(tender):`/`fix(tender):`/`docs(tender):`, в конце `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Двойное нажатие «Отправить» на медленной сети** — два `submit` с одним `version`: вторая отправка 409 `E-CON-01`, версия одна. Тест — Task 2, шаг 1.
2. **Срок истёк, пока поставщик заполнял форму** — `PUT offer` 409 `E-TND-05`: форма переходит в «только чтение» с баннером «Приём предложений завершён» и не падает. Тест — Task 1, шаг 1.
3. **429 от самого nginx** (тело — HTML, без `Retry-After`) — клиент не падает на разборе, `retryAfter = null`, экран «Слишком много запросов» без числа. Тест — Task 1, шаг 1.
4. **Одна cookie на двух приглашениях, сброс одного** — привязка к другому приглашению остаётся. Тест — Task 5, шаг 1.
5. **Закупщик открыл карточку после срока** — у приглашения остаётся только «Отозвать», кнопки перевыпуска и сброса нет, сервер на них отвечает 409. Тест — Task 5, шаг 1.

---

### Task 0: Зафиксировать уже написанное

Рабочее дерево смешивает T3.2–T3.5 и правку меню. Сначала — коммиты того, что зелёное, чтобы дифф каждой следующей задачи читался отдельно.

**Files:** всё из `git status`, кроме фронта портала (он уходит с Task 1).

- [ ] **Step 1: Убедиться, что бэкенд зелёный** (из `backend/`, отдельным процессом):
  `../.venv/Scripts/python.exe -m pytest -q apps/tender apps/files/tests/test_remove_document.py apps/users/tests/test_interface_service_account.py htqweb/tests/test_ratelimit_hit.py`
  Ожидается: `315 passed` (прогон 20.10), 0 failed.
- [ ] **Step 2: Коммит бэкенда портала:**
  ```bash
  git add backend/apps/tender backend/apps/files backend/apps/users backend/apps/access/self_service.py backend/htqweb
  git commit -m "feat(tender): портал поставщика — вход по ссылке, предложение, файлы КП (T3.2–T3.4)"
  ```
- [ ] **Step 3: Коммит меню и подсказки формы заявки** (не этап 3):
  ```bash
  git add frontend/src/components/profile/ProfileSidebar.tsx frontend/src/components/profile/__tests__/ProfileSidebar.test.tsx frontend/src/features/tender/requests/RequestFormPage.tsx
  git commit -m "feat(tender): раздел меню «Тендерные закупки», подсказка «проект не найден» в заявке"
  ```
  Ключи `profile.sidebar.sectionTender` и `tender.requests.noProjects*` лежат в `translation.json` вместе с ключами портала, поэтому `translation.json` целиком уходит с Task 1 (`git add -p` недоступен).
- [ ] **Step 4:** `git status` — остались только фронт портала, `translation.json`, `routeDefinitions*`, `lazyPages.ts`, e2e и планы.

---

### Task 1: Фронт портала по настоящему контракту (T3.8)

**Files:**
- Modify: `frontend/src/features/tender/portal/types.ts`, `offerForm.ts`, `client.ts`, `OfferEditor.tsx` (шапка), `testData.ts`
- Test: `frontend/src/features/tender/portal/client.test.ts`, `offerForm.test.ts`, `frontend/src/pages/public/SupplierTender.test.tsx`
- E2e: `frontend/tests/e2e/40_tender_portal.spec.ts`

**Interfaces:**
- Consumes (бэкенд, не меняется): `GET offer` → `extras: [{kind, amount, included_in_price, note}]`; `PUT offer` принимает `extras: {delivery?: {amount, included_in_price, note}, works?: {…}}` (`schemas.PortalOfferIn`, `offers._apply_extras`); пустое предложение — `_EMPTY` (`with_vat`, `currency_code`, `version`, `status`, `id` = `null`, `requisites = {}`); `GET tender` → `customer`, `participation_status`; 429 → заголовок `Retry-After` и `details.retry_after`.
- Produces: `OfferInput.extras: Partial<Record<ExtraKind, Omit<OfferExtra, 'kind'>>>`; `PortalOffer` с `null` у `id`, `version`, `status`, `number`, `currency_code`, `with_vat` и у значений `requisites`; `PortalTender.customer: string`, `PortalTender.participation_status: string`.

- [ ] **Step 1: Дописать тесты Review Focus** (три упавших теста уже есть и верны — их не трогать):
  - `client.test.ts` — `it('429 от nginx: HTML без Retry-After — retryAfter null, без падения')`: `fakeResponse(429, '<html>…</html>')` без заголовков → `toMatchObject({ status: 429, retryAfter: null, code: null })`.
  - `SupplierTender.test.tsx` — `it('срок истёк во время правки: PUT 409 E-TND-05 → только чтение')`: мок `PUT` отвечает 409 `{code: 'E-TND-05'}` → на экране текст «Приём предложений завершён», кнопка «Отправить» отсутствует, поле цены `disabled`.
- [ ] **Step 2: Прогнать — падают ровно новые и три известных:**
  `cd frontend && npx vitest run src/features/tender/portal src/pages/public/SupplierTender.test.tsx`
  Ожидается: FAIL у `Retry-After без заголовка…`, `доставка и СМР…`, `пустое предложение…` и у новых, если поведения ещё нет.
- [ ] **Step 3: `types.ts`** — `OfferInput.extras` и `PortalOffer` — по Interfaces; `PortalTender`: `company_name` → `customer`, добавить `participation_status`. `PortalCard.company_name` не трогать (карточка его и отдаёт).
- [ ] **Step 4: `offerForm.ts`** — `offerInput` собирает `extras` словарём только по запрошенным видам (`needs_delivery` → `delivery`, `needs_works` → `works`), без `kind`; ничего не запрошено — `{}`. `formOf`: `with_vat: offer.with_vat ?? false`, `currency_code: offer.currency_code ?? tender.currency_code ?? 'KZT'`, реквизиты — пустые строки по всем полям `Requisites` поверх `offer.requisites`.
- [ ] **Step 5: `client.ts`** — `retryAfter`: положительное число из заголовка, иначе положительное `envelope.details.retry_after`, иначе `null`.
- [ ] **Step 6: `OfferEditor.tsx`** — шапка формы берёт `tender.customer`.
- [ ] **Step 7: `testData.ts`** — фикстуры `portalTender`/`portalOffer` повторяют ответы `serializers.tender_view` и `offers.offer_view`: `customer`, `participation_status`, `submitted_at`; у `portalOffer` — `extras` списком.
- [ ] **Step 8: Прогнать vitest — зелёный:**
  `npx vitest run src/features/tender src/pages/public src/app/routing`
  Ожидается: 0 failed.
- [ ] **Step 9: Линт и типы:**
  `npx eslint src/features/tender src/pages/public/SupplierTender.tsx src/pages/public/SupplierTender.test.tsx` — 0 ошибок;
  `npx tsc --noEmit -p tsconfig.app.json 2>&1 | grep -c "error TS"` — не больше 148 (до задачи было 150, из них 2 — в `testData.ts`).
- [ ] **Step 10: e2e — проверка cookie стенда:** в `40_tender_portal.spec.ts` к проверке cookie добавить `expect(cookie.secure).toBe(false)` и `expect(cookie.name).toBe('tender_device')` (`TENDER_PORTAL_INSECURE_COOKIE` стенда).
- [ ] **Step 11: Прогнать e2e на стенде:**
  `docker compose -f docker-compose.test-local.yml up -d --build`, затем `./scripts/bpp-e2e-seed.sh`, затем миграции компаний стенда (`docker compose -f docker-compose.test-local.yml exec backend-web python manage.py migrate_companies`, ожидается `tender` на `0005`), затем
  `cd frontend && npx playwright test tests/e2e/40_tender_portal.spec.ts --project=chromium`.
  Ожидается: все сценарии passed, в том числе «второе устройство видит отказ». При `EIO` на bind-mount — `--force-recreate` контейнеров `backend-web` и `frontend`.
- [ ] **Step 12: Коммит:**
  ```bash
  git add frontend/src/features/tender/portal frontend/src/pages/public/SupplierTender.tsx frontend/src/pages/public/SupplierTender.test.tsx frontend/src/app/routing frontend/public/locales frontend/tests/e2e/40_tender_portal.spec.ts
  git commit -m "feat(tender): страница поставщика — вход, предложение, файлы КП (T3.5, T3.8)"
  ```

---

### Task 2: Устройство и Origin до разбора тела (T3.6)

**Files:**
- Modify: `backend/apps/tender/services/portal/access.py`, `backend/apps/tender/views_supplier.py`
- Test: `backend/apps/tender/tests/test_portal_offers.py`, `test_portal_access.py`

**Interfaces:**
- Produces:
  - `access.parse_body(request, schema: type[BaseModel]) -> BaseModel` — `schema.model_validate_json(request.body or b"{}")`; `ValidationError` → `DomainError("E-VAL-01", "Проверьте заполнение полей.", fields=[{"field": ".".join(loc), "message": msg}, …], status=422)` (ошибка в конверте портала, а не голый `{"detail": [...]}` из `api_view`).
  - `access.check_body(request, *, multipart: bool = False) -> None` — `multipart/form-data` допустим только при `multipart=True`.
  - `access.check_write(request, *, multipart: bool = False)` и `access.require_device(request, token, *, multipart: bool = False) -> PortalContext` — пробрасывают флаг.
- Consumes: `schemas.PortalOfferIn`, `PortalSubmitIn`, `PortalVersionIn`, `PortalDeclineIn` (без изменений).

- [ ] **Step 1: Тесты:**
  - `test_portal_offers.py::test_broken_json_from_unbound_device_is_403` — `PUT offer` с телом `b"{oops"`, верным Origin, без cookie → 403 `E-TND-06` (сейчас 422).
  - `test_portal_offers.py::test_broken_json_from_bound_device_is_422_in_envelope` — то же с привязанной cookie → 422, `code == "E-VAL-01"`, `fields` — список.
  - `test_portal_access.py::test_multipart_only_for_upload` — `POST submit` и `POST bind` с `multipart/form-data` → 415 `E-VAL-02`.
  - `test_portal_offers.py::test_double_submit_keeps_one_version` — два `POST submit` с одним `version` → второй 409 `E-CON-01`; `Offer.objects.filter(number__isnull=False).count() == 1` (Review Focus 1).
- [ ] **Step 2: Прогнать — падают первый и третий** (второй может упасть по конверту, четвёртый должен пройти — тогда это сторож на будущее):
  `../.venv/Scripts/python.exe -m pytest -q apps/tender/tests/test_portal_offers.py apps/tender/tests/test_portal_access.py -k "broken_json or multipart_only or double_submit"`
- [ ] **Step 3: `access.py`** — `parse_body`, флаг `multipart` по Interfaces.
- [ ] **Step 4: `views_supplier.py`** — у `portal_offer_put`, `portal_offer_submit`, `portal_offer_withdraw`, `portal_decline` убрать `body=` из `api_view` и параметр `data`; первая строка — `require_device`, вторая — `data = access.parse_body(request, schemas.<…>)`. `portal_offer_files_post` — `require_device(request, token, multipart=True)`.
- [ ] **Step 5: Прогнать все тесты портала — зелёные:**
  `../.venv/Scripts/python.exe -m pytest -q apps/tender/tests/test_portal_access.py apps/tender/tests/test_portal_offers.py apps/tender/tests/test_portal_files.py apps/access/tests/test_gate.py`
- [ ] **Step 6: Коммит** — `fix(tender): портал — устройство и Origin до разбора тела, multipart только у загрузки (T3.6)`.

---

### Task 3: Лимиты в настройках и журнал отказа привязки (T3.6)

**Files:**
- Modify: `backend/htqweb/settings/base.py`, `backend/apps/tender/services/portal/access.py`, `backend/apps/tender/services/portal/binding.py`, `backend/apps/tender/services/portal/files.py`
- Test: `backend/apps/tender/tests/test_portal_access.py`

**Interfaces:**
- Produces: в `base.py` рядом с `TENDER_PORTAL_INSECURE_COOKIE` — `TENDER_PORTAL_TOKEN_LIMIT = 120`, `TENDER_PORTAL_IP_LIMIT = 300`, `TENDER_PORTAL_BIND_LIMIT = 10`, `TENDER_PORTAL_UPLOAD_LIMIT = 30` (из env через `int(os.environ.get(...))`, как соседние настройки файла). `access._setting` читает `settings.<имя>` напрямую, без `getattr`-умолчаний; `portal_files.UPLOADS_PER_HOUR` берётся из `TENDER_PORTAL_UPLOAD_LIMIT`.

- [ ] **Step 1: Тесты:**
  - `test_ip_rate_limit_is_429` — `settings.TENDER_PORTAL_IP_LIMIT = 3`, четыре `GET` карточки с разными токенами с одного `REMOTE_ADDR` → четвёртый 429 `E-RATE-01`, есть `Retry-After`.
  - `test_bind_refused_survives_a_journal_failure` — второе устройство при `max_devices=1`, `log_event` подменён на `raise DatabaseError` для `bind_refused` → ответ 409 `E-TND-06`, не 500.
- [ ] **Step 2: Прогнать — второй падает (500).**
- [ ] **Step 3: Настройки и `_setting`** по Interfaces.
- [ ] **Step 4: `binding.bind`** — запись `bind_refused` в `try/except DatabaseError` → `fallback("tender.portal.bind_refused_journal_failed", None, reason="журнал отказа привязки не записан", exc=exc)`, затем `raise _refused()`.
- [ ] **Step 5: Прогнать тесты портала — зелёные** (команда из Task 2, шаг 5).
- [ ] **Step 6: Коммит** — `fix(tender): лимиты портала в настройках, отказ привязки не теряется при сбое журнала (T3.6)`.

---

### Task 4: Сторож белого списка на всех ручках портала (T3.6)

**Files:**
- Create: `backend/apps/tender/tests/test_portal_whitelist.py`
- Modify: `backend/apps/tender/tests/helpers.py` (общая `portal_forbidden_keys`), `test_portal_access.py`, `test_portal_offers.py` (импорт из helpers вместо своих копий `FORBIDDEN`/`forbidden_keys`)

**Interfaces:**
- Produces: `helpers.portal_forbidden_keys(value, path="") -> list[str]` — рекурсивно, пути запрещённых ключей (набор — Global Constraints).

- [ ] **Step 1: Тест `test_every_portal_route_answers_a_whitelist`:** сценарий — привязанное устройство, черновик с позицией, загруженный файл КП (фикстуры `memory_storage`, `clamd`), затем отправка. Обход — по `apps.tender.urls_supplier.urlpatterns` (маршруты без слэша): для каждого — успешный вызов и вызов с ошибкой (без cookie → 403; чужой `doc_id` → 404; после срока → 409; лимит → 429). У каждого JSON-ответа `portal_forbidden_keys(body) == []`. В конце — `assert covered == {p.pattern._route for p in urlpatterns if not p.pattern._route.endswith("/")}`: новая ручка без сценария валит тест.
- [ ] **Step 2: Прогнать:** `../.venv/Scripts/python.exe -m pytest -q apps/tender/tests/test_portal_whitelist.py`. Ожидается PASS; найден ключ — убрать его из сериализатора, а не из списка.
- [ ] **Step 3: Вынести `FORBIDDEN`/`forbidden_keys` в `helpers.py`**, прогнать три файла тестов портала — зелёные.
- [ ] **Step 4: Коммит** — `test(tender): сторож белого списка на каждой ручке портала, включая ошибки (T3.6)`.

---

### Task 5: Действия приглашения после срока (T3.7)

**Files:**
- Modify: `backend/apps/tender/services/tenders/tenders.py` (`invitation_out`, `card`), `backend/apps/tender/services/tenders/invitations.py` (`list_for`, `add`, `revoke`, `reissue`, `reset_device`)
- Modify: `frontend/src/features/tender/tenders/api.ts` (`Invitation.allowed_actions`), `TenderCardPage.tsx` (`invitationActions`)
- Test: `backend/apps/tender/tests/test_suppliers.py` (там тесты `reissue`/`reset_device` этапа 2), `test_portal_access.py` (сброс при одной cookie на двух приглашениях), `frontend/src/features/tender/tenders/TenderCardPage.test.tsx`

**Interfaces:**
- Produces:
  - `tenders.invitation_actions(ctx: Ctx, tender: Tender, row: Invitation) -> list[str]` — подмножество `["revoke", "reissue", "reset_device"]`. Пусто, если не автор или нет `edit` на `tender.tenders`, или приглашение отозвано / в `CLOSED` (`revoked`, `expired`, `declined`, `awarded`, `not_awarded`). `revoke` — тендер в `INVITABLE` (`draft`, `intake`); `reissue` и `reset_device` — `intake_open(tender)` и статус приглашения не `created`.
  - `tenders.invitation_out(row: Invitation, actions: list[str]) -> dict` — прежний словарь + `"allowed_actions": actions`.
  - `invitations.revoke/reissue/reset_device` первой проверкой после `_own_invitation` вызывают `invitation_actions` и при отсутствии действия отвечают прежней 409 (`tenders.state_error` / `_invitation_state_error`) — кнопка и проверка из одного места.

- [ ] **Step 1: Тесты бэкенда:**
  - `test_after_deadline_only_revoke_is_left` — приём, срок в прошлом (`pinned_clock`) → у приглашения `allowed_actions == ["revoke"]`; `POST reissue` и `POST reset-device` → 409; `POST revoke` → 200.
  - `test_intake_open_gives_all_three` → `["revoke", "reissue", "reset_device"]` (порядок фиксирован).
  - `test_not_author_sees_no_invitation_actions` → `[]`.
  - `test_reset_of_one_invitation_keeps_the_other` — одна cookie на приглашениях A и B (как `test_one_cookie_serves_two_invitations`), сброс A → `GET supplier/<B>/tender` с той же cookie — 200, по A — 403 (Review Focus 4).
- [ ] **Step 2: Прогнать — падают.**
- [ ] **Step 3: Бэкенд** по Interfaces; вызовы `invitation_out(row)` (4 места в `invitations.py`, 1 в `tenders.card`) передают `invitation_actions(ctx, tender, row)`.
- [ ] **Step 4: Тест фронта** `TenderCardPage.test.tsx::'кнопки приглашения — по allowed_actions приглашения'`: карточка с `allowed_actions: []` у тендера и `invitations[0].allowed_actions: ['revoke']` → видна «Отозвать», нет «Перевыпустить ссылку» и «Сбросить устройство» (Review Focus 5).
- [ ] **Step 5: Фронт** — `Invitation.allowed_actions: ('revoke' | 'reissue' | 'reset_device')[]`; `invitationActions(row)` строит кнопки по `row.allowed_actions`, без `allowed.includes('invite')`, `CLOSED_INVITATIONS` и `card.status` (решает сервер).
- [ ] **Step 6: Прогнать:** pytest `apps/tender` (отдельным процессом, ~13 мин) и `npx vitest run src/features/tender` — зелёные; `tsc` ≤ 148.
- [ ] **Step 7: Коммит** — `feat(tender): действия приглашения по сроку приёма — перевыпуск и сброс только на приёме (T3.7)`.

---

### Task 6: Проверки шлюза и документация (T3.9)

**Files:**
- Modify: `API.md`, `STRUCTURE.md`, `CLAUDE.md`, `docs/plans/2026-10-07-tender-stage3-portal-plan.md` (§4.1 — результаты проверок)

- [ ] **Step 1: `nginx -t`** образом прода. Временные самоподписанные сертификаты — в каталоге сессии, не в репозитории:
  ```bash
  D=<scratchpad>/nginx-check && mkdir -p "$D" && openssl req -x509 -nodes -newkey rsa:2048 -days 1 -subj "/CN=test" -keyout "$D/origin.key" -out "$D/origin.pem"
  docker run --rm -v "$PWD/infra/nginx/default.conf:/etc/nginx/conf.d/default.conf:ro" -v "$D:/etc/htq-certs:ro" \
    $(grep -oE 'server [a-z0-9_-]+:[0-9]+' infra/nginx/default.conf | awk '{split($2,a,":"); print "--add-host " a[1] ":127.0.0.1"}' | sort -u) \
    fholzer/nginx-brotli:latest nginx -t
  ```
  Ожидается: `syntax is ok` и `test is successful`. Не нашлось имя в `proxy_pass` вне `upstream` — добавить `--add-host` вручную.
- [ ] **Step 2: Compose:** `docker compose -f docker-compose.yml config -q`, то же для `docker-compose.test-local.yml` и `docker-compose.test-env.yml` — exit 0 у каждого (прод-файлу нужны переменные `:?` — брать из `.env.example`, `.env` не читать).
- [ ] **Step 3: Мониторинг:** `./scripts/check-monitoring-config.sh` — exit 0.
- [ ] **Step 4: Документация:**
  - API.md — раздел «apps.tender»: ручки портала (таблица §2 T3.2/T3.3/T3.4 плана этапа 3 с фактическими кодами: 11-й файл — 409, `.xml` — 415), `GET tenders/<id>/invitations/<inv>/events`, `allowed_actions` у приглашения; убрать «с этапа 3» (строки ~138, ~2096).
  - STRUCTURE.md — `services/portal/` (`access`, `binding`, `offers`, `files`, `serializers`, `actor`), `models/offer.py`, `models/portal.py`, `urls_supplier.py`/`views_supplier.py`, `features/tender/portal`, `pages/public/SupplierTender.tsx`.
  - CLAUDE.md — абзац «Тендерный модуль»: этап 3 сделан; портал — пара «токен + cookie устройства» (`__Secure-tender_device`, на стенде `tender_device`), журнал `PortalEvent` только для вставки, файлы КП только при включённом антивирусе (иначе 503), коды `E-TND-05/06/08/09`, `E-RATE-01`; **ветка `tender` не пушится до конца модуля**.
  - План этапа 3, §4.1 — строка T3.1: результаты шагов 1–3.
- [ ] **Step 5: Коммит** — `docs(tender): этап 3 — портал поставщика в API.md, STRUCTURE.md, CLAUDE.md`.

---

### Task 7: Регрессия, ревью, закрытие (T3.9)

- [ ] **Step 1: Регрессия бэкенда** одним процессом (`nohup`, из `backend/`):
  `../.venv/Scripts/python.exe -m pytest -q apps/tender apps/files apps/users apps/access/tests/test_gate.py apps/core/tests htqweb/tests`
  и `../.venv/Scripts/python.exe manage.py makemigrations --check --dry-run`. Ожидается: 0 failed (кроме строк `backend/ci-known-failures.txt`), «No changes detected».
- [ ] **Step 2: Полный vitest:** `cd frontend && npm test` — падения только известные 9 вне tender (HR-диалоги, `uxContract` в `features/bpp/projects`); eslint по изменённым файлам чист.
- [ ] **Step 3: Ревью** — `harness-review` по диффу `be18fe73..HEAD` (этап 3 целиком). Critical и Major — исправить отдельными коммитами `fix(tender): …` и повторить шаг 1 для затронутых аппок.
- [ ] **Step 4: `Plans.md`:** T3.1–T3.9 — `cc:完了 [<хэши>]`; в итоговую строку этапа — числа прогонов шагов 1–2. Коммит `docs(tender): этап 3 выполнен — Plans.md`.
- [ ] **Step 5:** `git status` — чисто; `git log --oneline be18fe73..HEAD` — коммиты этапа. **Пуша нет.**

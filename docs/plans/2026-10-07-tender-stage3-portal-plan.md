# Тендерный модуль — пошаговый план этапа 3: портал поставщика (T3.1 … T3.5)

07.10.2026 · ветка `tender` · поверх мастер-плана ([T-21…T-27](2026-10-06-tender-master-plan.md)) и плана этапов 0–2 ([2026-10-07-tender-stages-0-2-plan.md](2026-10-07-tender-stages-0-2-plan.md)). Общие правила — те же (CLAUDE.md, `DomainError`, `version`, журнал, `api_view`, только `interface` соседей). Умолчания — **[умолч.]**.

Портал — **анонимный** контур на платформе, рассчитанной на JWT. Доступ даёт только пара «токен ссылки + секрет устройства в cookie». Всё ниже подчинено одному правилу: **поставщик видит только своё приглашение и только то, что ему положено** — ни плановых цен, ни других участников, ни их числа.

---

## 1. Контур и сквозные правила

**Пути.** SPA — `/supplier/<token>` (публичный маршрут без layout). API — `/api/tender/v1/supplier/<token>/…`. Каждая ручка — `@api_view(methods=…, auth=None)` **с литералом `auth=None` в вызове** (сторож `test_gate.py` ищет его по тексту) и запись в `apps/access/self_service.py` → `SELF_SERVICE["tender"]` с причиной `scoped` («доступ по токену ссылки и секрету устройства»).

**Тенант.** Компания — по поддомену (`CompanyContextMiddleware`); хэш токена ищется в схеме этой компании, поэтому токен компании A на поддомене B — 404. Архивная компания — 404 (`archive.anonymous_blocked`, tender в `TENANT_APPS`). Выключенный сервис — 503 (гейт по префиксу).

**Токен → приглашение** (`services/portal/access.py`, T3.2): `sha256(token)` → `Invitation` с `revoked_at IS NULL`. Неизвестный, отозванный, перевыпущенный токен и тендер в `draft` — **одинаковый 404** `E-NOT-FOUND` «Ссылка недействительна» (тело не различает причины). Сравнение — поиск по уникальному индексу хэша; сырой токен нигде не логируется и не попадает в журнал/ответ.

**Устройство** (T-21): POST `bind` выдаёт секрет `secrets.token_urlsafe(32)` в cookie; в БД (`DeviceBinding.secret_hash`) — только SHA-256. Cookie: имя `__Secure-tender_device`, `HttpOnly; Secure; SameSite=Strict; Path=/api/tender/v1/supplier/; Max-Age` = до `deadline_at` + 30 дней. На стенде без HTTPS — настройка `TENDER_PORTAL_INSECURE_COOKIE=True` (только `settings.dev`/`test`): имя `tender_device` без префикса и без `Secure` [умолч.]. Одна cookie на устройство может обслуживать несколько приглашений (секрет один, привязок — по строке `DeviceBinding` на приглашение).

**Проверка «токен + cookie»** — функция `access.require_device(request, token) -> PortalContext(invitation, tender, binding)`: первой строкой каждой ручки, кроме `GET <token>` (промежуточная карточка) и `POST bind`. Нет cookie / не совпала / привязка снята → **403** `E-TND-06` «Ссылка открыта на другом устройстве» с `details={"rebind": "otp"}` (OTP — этап 4; до него — «попросите закупщика сбросить привязку»).

**POST портала**: `Origin` обязателен и должен принадлежать хосту компании (`access.check_origin`): хост из `Origin` = `companies.interface.public_url(slug)` **или** метка поддомена резолвится в текущую компанию (`companies.interface.resolve_host_label`) при корне из `PUBLIC_BASE_URL` или `localhost` (только `DEBUG`) — иначе 403 `E-ACC-01`. Тело — только `application/json` (иначе 415), кроме загрузки файлов (`multipart/form-data`).

**IP** — только `X-Real-IP` (nginx), не `X-Forwarded-For` (T-23). User-Agent — обрезка до 512.

**Лимиты** (T3.1): `htqweb.ratelimit.hit(bucket, key, *, limit, window, fail_closed=False) -> bool` — `True` = в пределах. Портал: 120 запросов/мин на токен, 300/мин на IP; `bind` — 10/час на токен; загрузка файлов — 30/час на приглашение [умолч.]. Превышение — **429** `E-RATE-01` + `Retry-After`. Хранилище недоступно: обычные лимиты — fail-open (`fallback(..., expected=False)`), `fail_closed=True` (OTP, этап 4) — отказ.

**Срок** — время сервера: правка/отправка после `deadline_at` или при статусе тендера ≠ `intake` → **409** `E-TND-05` «Приём предложений завершён». Проверка — под `select_for_update` тендера в той же транзакции, что запись.

**Журнал портала** `PortalEvent` (append-only триггером БД, как `AuditLog`): `invitation`, `kind` (`bound`, `bind_refused`, `offer_saved`, `offer_submitted`, `offer_withdrawn`, `declined`, `file_uploaded`, `file_removed`, `device_reset`), `ip`, `user_agent`, `meta` (JSON, без токенов и секретов), `created_at`. Закупщик видит журнал своего приглашения: `GET tenders/<id>/invitations/<inv>/events` (узел `tender.tenders` view, свои/`all`).

**Ответы — белым списком.** Сериализаторы портала собирают словари явно (никакого `model_to_dict`/`__dict__`). Сторож-тест обходит ответы всех ручек портала и рекурсивно проверяет отсутствие ключей `plan_price`, `delivery_plan_amount`, `works_plan_amount`, `budget`, `invitations`, `counters`, `token`, `token_hash`, `secret_hash`, `author_id`, `quality_reviewer*`, `bpp_*`.

---

## 2. Задачи

### T3.1 — лимитер и nginx (исполнитель A)

- `htqweb/ratelimit.py`: публичный `hit(bucket, key, *, limit, window, fail_closed=False) -> bool` поверх `_incr` (ключ `ratelimit:<bucket>:<sha256(key)[:32]>`), `retry_after(bucket, key, window) -> int`; блокировка входа не меняется. Тесты — `htqweb/tests/test_ratelimit_hit.py`: в пределах/сверх лимита, окно, `None` от кэша → fail-open и fail-closed, ключ не хранит сырой токен.
- `infra/nginx/default.conf`: зона `limit_req_zone $binary_remote_addr zone=tender_portal:10m rate=60r/m`; `location ^~ /api/tender/v1/supplier/` (выше общей `/api/`): `limit_req zone=tender_portal burst=30 nodelay`, `limit_req_status 429`, `client_max_body_size 21M`, `add_header X-Frame-Options DENY always`, `add_header Referrer-Policy no-referrer always`, `proxy_set_header X-Real-IP $remote_addr`, отдельный `access_log` с форматом, где путь маскирован (`map $uri $tender_portal_uri` → `/api/tender/v1/supplier/***/…`). То же для SPA-пути: `location ^~ /supplier/` — отдаёт SPA, лог маскирован, `X-Frame-Options DENY`, `Referrer-Policy no-referrer`.
- Проверка конфига: `docker run --rm -v <conf>:/etc/nginx/conf.d/default.conf:ro --add-host backend:127.0.0.1 … nginx:<версия образа прода> nginx -t` (имена апстримов — через `--add-host`); результат — в отчёт.

### T3.2 — вход по ссылке, привязка устройства, журнал (исполнитель A)

Модели (`models/portal.py`, миграция **`0005_portal_events`** — после `0004_offers` исполнителя B): `PortalEvent` + триггер. `DeviceBinding` уже есть (`0003`).

Сервис `services/portal/access.py`: `resolve`, `require_device`, `check_origin`, `client_ip`, `record_event`, установка/снятие cookie (`set_device_cookie(response, secret, expires)`). Сервис `services/portal/binding.py::bind(invitation, request) -> (binding, secret|None)`: `select_for_update` приглашения; если cookie этого устройства уже привязана — вернуть её; иначе если активных привязок < `max_devices` — новая привязка; иначе 409 `E-TND-06` «Ссылка уже открыта на другом устройстве». Первая привязка: `first_opened_at`, статус `sent`/`delivery_error` → `opened`. Тендер не `intake` — привязка всё равно возможна (поставщик смотрит итог, TND-035), правка — нет.

Ручки (`urls_supplier.py`/`views_supplier.py`):

| Метод и путь | Назначение |
|---|---|
| `GET supplier/<token>` | Промежуточная карточка (**ничего не пишет**): `{company_name, tender_number, deadline_at, intake_open, bound}` — `bound` = эта cookie привязана к приглашению |
| `POST supplier/<token>/bind` | Привязать устройство, `Set-Cookie`, событие `bound`/`bind_refused`, лимит 10/ч |
| `GET supplier/<token>/tender` | Карточка тендера для поставщика (после привязки): заказчик, номер, срок, валюта, желаемая схема оплаты, условия поставки, адрес, позиции `{id, line_no, name, specs, uom{code, short_name}, qty, need_date}` (**без плановых цен**), признаки `needs_delivery`, `needs_works`, `works_scope`, `allow_analogs`, `allow_partial`, файлы ТЗ `{id, name, size}`, `intake_open`, `result` (`awaiting` / позже — итог этапа 5) |
| `GET supplier/<token>/files/<doc_id>` | Ссылка на файл ТЗ: 302 на `files.interface.download_link(..., actor_id=None, ip, ua)` — только документы владельца `tender.request` этой заявки |
| `GET tenders/<id>/invitations/<inv>/events` (внутренний, JWT) | Журнал портала приглашения для закупщика |

Тесты (`test_portal_access.py`): GET не создаёт привязку и не ставит cookie; `bind` → cookie с атрибутами (имя, `HttpOnly`, `SameSite=Strict`, `Path`, `Max-Age`); второе устройство → 409; повтор с той же cookie → та же привязка; два параллельных `bind` (`transaction=True`, потоки) → одна привязка; без cookie `tender` → 403; отозванный/перевыпущенный/неизвестный токен → одинаковый 404; токен другой компании (`two_company_schemas`) → 404; архив → 404; сервис выключен → 503; POST с чужим `Origin` → 403, без `Origin` → 403, `text/plain` → 415; поддельный `X-Forwarded-For` не попадает в журнал; лимит `bind` → 429; сторож белого списка ключей; `reset-device` (этап 2) делает старую cookie недействительной.

### T3.3 — предложение (исполнитель B)

Модели (`models/offer.py`, миграция **`0004_offers`**; `PaymentScheme.offer` FK null — в той же миграции):

- `OfferStatus`: `draft` · `submitted` · `replaced` · `withdrawn`.
- `Offer(VersionedModel)`: `invitation` FK, `number` (версия: 1, 2, … — номер отправки; у черновика `null`), `status`, `submitted_at`, `currency_code`, `with_vat` (bool), `vat_rate` (Decimal(5,2) null), `delivery_cost`, `delivery_included` (bool), `works_cost`, `works_note`, `valid_until` (date), `extra_terms`, `requisites` (JSON: `name, country_code, reg_number, is_vat_payer, contact_name, phone, email`), `pd_consent_at`, `declined_reason`. Одна строка `draft` на приглашение (частичный уникальный индекс), отправленные версии — отдельными строками.
- `OfferLine(TenderModel)`: `offer` FK CASCADE, `item` FK `TenderRequestItem` PROTECT, `participates` (bool), `price` (Decimal(18,2) null), `qty` (Decimal(15,3) null, ≤ запрошенного), `delivery_date` (date null), `is_analog` (bool), `analog_note`, `comment`; уникальность (`offer`, `item`).
- `OfferExtra(TenderModel)`: `offer` FK CASCADE, `kind` (`delivery`/`works`), `amount` (Decimal null), `included_in_price` (bool), `note` — по строке на вид, если тендер его запросил.
- Предложенная схема оплаты — `PaymentScheme(offer=…)` по тем же шаблонам 1–3 (`services/tenders/schemes.py`).

Сервис `services/portal/offers.py`:
- `get_draft(invitation)` — черновик или новый черновик-копия последней отправленной версии; реквизиты известного контрагента (`bpp.counterparty_brief`) — **только чтение** (подставляются, правка отвергается), у потенциального — правка.
- `save_draft(ctx, data)` — `version`/409, проверки строк: позиция из этой заявки; `qty ≤ item.qty`; цена > 0 у участвующей; аналог только при `allow_analogs` (иначе 422 `E-TND-09`); частичное предложение только при `allow_partial`; доставка/СМР — только если запрошены.
- `submit(ctx)` — под `select_for_update` тендера: срок/статус (409 `E-TND-05`), согласие на ПДн (`pd_consent: true` в теле первой отправки → `pd_consent_at`; без него 422 `E-TND-08`), хотя бы одна участвующая позиция, `valid_until ≥ сегодня`; прежняя `submitted` → `replaced`, черновик → `submitted` с `number = n+1`; приглашение → `submitted`; событие.
- `withdraw(ctx)` — отправленная → `withdrawn`, приглашение → `opened`; `decline(ctx, reason≥10)` — приглашение → `declined`, черновик удаляется.

Ручки:

| Метод и путь | Назначение |
|---|---|
| `GET/PUT supplier/<token>/offer` | Черновик (или последняя отправленная, если правка закрыта) + история версий `{number, status, submitted_at}` / сохранить черновик `{version, …}` |
| `POST supplier/<token>/offer/submit` · `withdraw` | `{version, pd_consent?}` / `{version}` |
| `POST supplier/<token>/decline` | `{reason}` |

Ручки — по контракту `access.require_device` исполнителя A (до его готовности — писать и тестировать сервис, вьюхи — после). Тесты (`test_portal_offers.py`): правка после срока → 409 (фикстура `pinned_clock`); без согласия → 422; аналог при запрете → 422; qty больше запрошенного → 422; известный контрагент не меняет реквизиты; повторная отправка → версия 2, первая `replaced`; отзыв; отказ; позиция чужой заявки → 422; сторож белого списка для ответов предложения.

### T3.4 — файлы КП (исполнитель B, после T3.3)

- `users.interface.ensure_service_account(username, *, first_name, last_name) -> int` — неактивная учётка без пароля (`set_unusable_password`), идемпотентно (`get_or_create` по `username`); тест в `apps/users/tests`. Автор файлов поставщика — `tender-portal` («Поставщик (портал)», Q-T10 умолчание); id приглашения — в `PortalEvent.meta`.
- `files.interface.remove_document(owner_type, owner_id, document_id, *, actor_id, ip=None, user_agent=None)` — удаление документа из кода по правилам подсистемы (физически — у ни разу не отправленного владельца, иначе `deleted_at`), событие `FileEvent`; тест в `apps/files/tests`.
- Владелец `tender.offer` (`file_owners.py`, `register_owner(..., tenant=True, model=Offer)`), тип **`tender_offer`** (миграция `files/0007_tender_offer_type`: PDF/DOCX/XLSX/JPG/PNG, 20 МБ, до 10 документов; без xml и исполняемых). Колбэки панели `/api/files/v1` для внутренних пользователей: видеть файлы КП — **только после вскрытия** (этап 5; сейчас — никто, кроме суперпользователя), менять — никто (только портал).
- Ручки портала: `GET supplier/<token>/offer/files`, `POST …/offer/files` (multipart, поле `file`), `DELETE …/offer/files/<doc_id>` — файлы черновика своего приглашения. **Загрузка только при включённом антивирусе** (`htqweb.antivirus.enabled()`; иначе 503 `E-SYS-01` «Загрузка файлов временно недоступна»), лимит 30/ч, срок/статус как у правки. Файлы привязаны к черновику; при отправке переносятся на отправленную версию (владелец — `Offer` отправки) [умолч.: файлы — у приглашения через «текущее предложение»; исполнитель выбирает проще и описывает].
- Тесты (`test_portal_files.py`): без сканера — 503; поддельный clamd с угрозой — 422 `E-FIL-08` (образец `apps/core/tests/test_antivirus.py`); 11-й файл и `.xml` — 422; файл чужого приглашения — 404; после срока — 409.

### T3.5 — страница поставщика (исполнитель C)

`frontend/src/pages/public/SupplierTender.tsx` (+ компоненты в `features/tender/portal/`), маршрут `/supplier/:token` в `publicRoutes` (`routeDefinitions.ts`), без layout, **мобильная вёрстка** (одна колонка, крупные поля). Поток: промежуточная карточка (`GET`) → «Открыть предложение» (`POST bind`) → форма: позиции (участвую / цена за ед. / кол-во ≤ запрошенного / срок поставки / комментарий / аналог с описанием, если разрешено), доставка («включена в цену» или сумма), СМР (сумма + состав работ), НДС, валюта, срок действия, схема оплаты (1–3), доп. условия, файлы КП, реквизиты (известный контрагент — только чтение), чекбокс согласия на ПДн перед первой отправкой; «Сохранить черновик», «Отправить», «Отозвать», «Отказаться с причиной»; после срока — только чтение и итог «Ожидается решение». Ошибки: 403 `E-TND-06` → экран «Ссылка открыта на другом устройстве — обратитесь к закупщику»; 404 → «Ссылка недействительна»; 409 `E-TND-05` → «Приём предложений завершён»; 429 → «Слишком много запросов, повторите через N с». Тексты — `t('tender.portal.…', 'фолбэк')`. Запросы портала — **без** JWT-интерсептора (`credentials: 'include'` для cookie) — отдельный клиент. Vitest на моках; Playwright (`frontend/tests/e2e/40_tender_portal.spec.ts`): два `browser.newContext()` — второе устройство видит отказ; на стенде проверить, что cookie ставится на `http://group.localhost:3000` (настройка небезопасной cookie стенда).

---

## 3. Раскладка файлов

| Задача | Файлы |
|---|---|
| T3.1 | `htqweb/ratelimit.py`, `htqweb/tests/test_ratelimit_hit.py`, `infra/nginx/default.conf` |
| T3.2 | `apps/tender/models/portal.py`, `migrations/0005_portal_events.py`, `services/portal/{__init__,access,binding,serializers}.py`, `urls_supplier.py`/`views_supplier.py`, ручка событий в `urls_tenders.py`/`views_tenders.py`, `apps/access/self_service.py` (записи `scoped`), `htqweb/settings/{base,dev,test}.py` (`TENDER_PORTAL_*`), `tests/test_portal_access.py` |
| T3.3 | `apps/tender/models/offer.py`, `models/tender.py` (`PaymentScheme.offer`), `migrations/0004_offers.py`, `services/portal/offers.py`, ручки предложения в `urls_supplier.py`/`views_supplier.py` (после A), `tests/test_portal_offers.py` |
| T3.4 | `apps/users/interface.py` (+тест), `apps/files/interface.py` (+тест), `apps/files/migrations/0007_tender_offer_type.py`, `apps/tender/file_owners.py`, `services/portal/files.py`, ручки файлов, `tests/test_portal_files.py` |
| T3.5 | `frontend/src/pages/public/SupplierTender.tsx`, `frontend/src/features/tender/portal/**`, `routeDefinitions.ts`, `lazyPages.ts`, переводы, `frontend/tests/e2e/40_tender_portal.spec.ts` |

Общие файлы (`models/__init__.py`, `urls_supplier.py`, `views_supplier.py`) — правка точечно, с перечитыванием перед записью; `urls_supplier.py`/`views_supplier.py` создаёт A, B добавляет свои ручки после него.

Коды ошибок этапа: `E-TND-05` приём завершён · `E-TND-06` устройство не привязано / ссылка открыта на другом устройстве · `E-TND-08` нет согласия на ПДн · `E-TND-09` аналог или частичное предложение не разрешены · `E-RATE-01` лимит запросов (429).

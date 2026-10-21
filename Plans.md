# HTQWeb — Plans.md

作成日: 2026-10-02 · Реестр задач для `claude-code-harness` (`/harness-work <N>`, `/harness-sync`).
Продуктовый контракт (spec) — [docs/plans/2026-10-02-bpp-stage7-executor-a.md](docs/plans/2026-10-02-bpp-stage7-executor-a.md) (решения D-S7-1…8, Review Focus, Global Constraints). Порядок: spec > Plans.md.

Phase 8 — spec: [docs/plans/2026-10-03-bpp-stage8-tails-executor-a.md](docs/plans/2026-10-03-bpp-stage8-tails-executor-a.md) (решения D-S8-1…4, Review Focus, Global Constraints).

Spec delta (Phase 8):
- path: docs/plans/2026-10-03-bpp-stage8-tails-executor-a.md (корневого `spec.md` нет; контракт — план этапа)
- change: D-S8-1 срок антивируса на всю проверку; D-S8-2 счётчики блокировки раздельные (решение пользователя 03.10); D-S8-3 видимость поиска договоров по `can_view` без запроса на строку; D-S8-4 `ext_1c_ref` только в нижнем регистре (`CheckConstraint`)
- why: хвосты итогового ревью этапа 7; две проверки плана (subagent) учтены

Spec delta (Phase 7):
- path: docs/plans/2026-10-02-bpp-stage7-executor-a.md (в репозитории нет корневого `spec.md`; продуктовые контракты модуля — мастер-план и план этапа)
- change: решения пользователя 02.10 (D-S7-1…8) и правки пяти проверок плана
- why: задачи ниже опираются на эти правила; при расхождении действует план этапа

---

## Phase 7: БЗО, этап 7 — исполнитель A (ветка `new-module-BPP-sanzhar`)

| Task | 内容 | DoD | Depends | Status |
|------|------|-----|---------|--------|
| 7.1 | `[lane:gate]` `[tdd:required]` `[feature:security]` Производственный календарь → `refdata` (A7.1 ч.1, D-S7-1): модель, расчёты в `refdata.interface`, чтение — самообслуживание, правка — узел `refdata.production_calendar` (ОД/HR холдинга), команда `refdata_import_production_days`, `rewrite` старых путей в nginx, `tasks` считает дни через `refdata` | «Золотые даты» совпадают; 5 тестов прав (ОД/HR холдинга 200, ОД дочерней 403, `refdata:admin` без узла 403, `tasks:write` 403, сотрудник читает 200); импорт идемпотентен, конфликт — отчёт; `makemigrations --check` чист; сторожа и `apps/tasks`, `apps/refdata` зелёные; vitest/tsc ≤148/eslint | - | cc:完了 [1a4af4b] |
| 7.2 | `[lane:gate]` `[tdd:required]` Банковские дни (D-S7-7): `kz_holidays` помнит исходный день переноса; `refdata.interface.is_bank_day/add_bank_days/bank_days_before`; срок оплаты и `bank_wait_days` (зона B — отдельный коммит) | 24.03.2026 банковский, 25.03.2026 нет; дашборд и `total` реестра совпадают на закреплённой дате; «застрявшие» и «ждут закрывающих» — Пн–Пт без изменений; `apps/bpp`, `apps/core` зелёные | 7.1 | cc:完了 [35e9b9a] |
| 7.3 | `[lane:gate]` `[tdd:required]` `[feature:security]` Блокировка входа (A7.2, D-S7-3): `htqweb/ratelimit.py`, единый ответ для неизвестного/неактивного/неверного, `auth_unlock`, сброс при смене пароля, fail-open с `fallback`, `limit_req_status 429` только у токена, порог `0` по умолчанию в compose, метрика и алерт, `LoginForm` 429 | Тесты из плана (6-я попытка 429, одинаковые ответы, `Admin`≠`admin`, окно 15 мин, `None` от кэша, порог 0) зелёные; `apps/users`, `htqweb` зелёные; `check-monitoring-config.sh` зелёный; vitest/eslint/tsc | - | cc:完了 [8abb835] |
| 7.4 | `[lane:gate]` `[tdd:required]` `[feature:security]` Заготовки 1С (A7.3, D-S7-5): `secrets/` в `.gitignore`/`.dockerignore` первым коммитом; `env_file` `secrets/onec.env` (`required: false`); клиент OData (https, без редиректов, экранирование `$filter`); upsert контрагентов и «Проектов»; частичный `UniqueConstraint` `ext_1c_ref`; `onec_check` | Тесты из плана (идемпотентность, конфликт, невалидный БИН, дубль GUID, пароль не в логах/`repr`) зелёные; `docker compose -f <каждый> config` без файла секретов — ок; `makemigrations --check` чист | - | cc:完了 [8aac4cb] |
| 7.5 | `[lane:gate]` `[tdd:required]` ClamAV — эксплуатация (A7.4, D-S7-6): порт/таймаут в compose, healthcheck, метрика вердиктов, PING в инфраструктуре, `check-monitoring-config` с профилем, ранбук включения, живой тест | Юнит-тесты метрики и PING зелёные; ручной прогон на `test-local --profile antivirus`: `healthy`, EICAR → 422 `E-FIL-08` — вывод в отчёте; `check-monitoring-config.sh` зелёный | - | cc:完了 [3f66e91] |
| 7.6 | `[lane:gate]` `[tdd:required]` Хвосты этапа 6: привлечение → договор модуля (M-5, с проверкой контрагента/статуса/прав); имена в карточке «Проекта» из `users`; `seed_purchase_request_template --company`; `--revoke-pending` печатает документы без процесса; переводы `contracts.frozen.*`; докстринг | Тесты по каждому пункту зелёные; зона B — отдельными коммитами | - | cc:完了 [7ea8887, 9bbe8ed] |
| 7.7 | `[lane:gate]` `[tdd:required]` `[feature:security]` A8.1 (D-S7-8): `bpp_group_directors` (`serves_subsidiaries` + членства в дочерних), `bpp/holding.py` + читатели, `GET bpp/v1/holding/summary` под узлом `bpp.holding` (ФД, ГД) и гейтом холдинга, раздел на «Сводке группы» | Команда идемпотентна, `--dry-run` не пишет; суммы сводки = реестрам компаний; дочерний поддомен — отказ; без узла 403; сторожа холдинга зелёные; `makemigrations --check` чист; vitest/eslint/tsc | 7.1 | cc:完了 [80aac55] |
| 7.8 | `[lane:release]` `[tdd:skip:verification-and-review]` Прогон и PR: полный бэкенд по аппкам, фронт, стенд (импорт календаря, `bpp_group_directors`, e2e + spec блокировки), ранбук выкатки, итоговое ревью (`harness-review`), PR в `new-module-BPP-merge` | Все аппки зелёные, `ci-known-failures.txt` не вырос; ранбук дополнен; Critical/Important ревью исправлены; PR создан, CI зелёный; мерж — по команде пользователя | 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7 | cc:完了 [44bc2c2] |

Отложено (решения 02.10): события календаря отдельной аппкой (A7.1 ч.2), лимит 300 запросов/мин (D-S7-4), отзыв refresh при смене пароля — см. раздел «Отложено» плана этапа.

## Phase 8: БЗО, этап 8 — хвосты итогового ревью этапа 7 (исполнитель A, ветка `new-module-BPP-sanzhar`)

| Task | 内容 | DoD | Depends | Status |
|------|------|-----|---------|--------|
| 8.1 | `[lane:gate]` `[tdd:required]` Срок проверки антивирусом — на всю проверку (D-S8-1): остаток считается раз и проверяется до `settimeout`, ответ без `\0` — `ScanUnavailable`, fail-closed | Красные тесты («капающий» clamd: `< T + 1 с` вместо ~3·T; арифметика срока без `ValueError`; ответ без `\0`) зелёные и с red-log; `htqweb/tests`, `apps/core/tests/test_antivirus*`, `apps/media_files`, `apps/files` зелёные; ранбук и `.env.example` — «на всю проверку» | - | cc:完了 [f286fec] |
| 8.2 | `[lane:fast]` `[tdd:skip:decision-no-code]` Блокировка входа — счётчики остаются раздельными (D-S8-2, решение пользователя 03.10) | В плане этапа 7 («Отложено») и в ранбуке выкатки (шаг включения блокировки) записано решение с датой; изменений кода нет | - | cc:完了 [211c257] |
| 8.3 | `[lane:gate]` `[tdd:required]` `[feature:security]` Поиск договоров для привлечения без N+1 (D-S8-3, зона B): `signoff.interface.participant_subject_ids`, `neighbour.search`/`visible_brief` по правилу `can_view` | Число запросов при 3 и 30 договорах у СН равно (`CaptureQueriesContext`); эквивалентность с `can_view` (ФД, СН, ПМ, участник с ролью, автор; без роли — пусто); выключенный `signoff` не ломает поиск ФД; `apps/bpp/tests` (договоры), `apps/tasks/tests/test_engagement_bpp_agreement.py`, `apps/signoff`, сторож изоляции зелёные | - | cc:完了 [d233872] |
| 8.4 | `[lane:gate]` `[tdd:required]` `ext_1c_ref` только в нижнем регистре (D-S8-4): `CheckConstraint` + миграции `bpp/0020`, `project/0003` (дубли без регистра — стоп, приведение к нижнему), поиск 1С — точное сравнение | Запись верхнего регистра мимо сервиса — `IntegrityError` `ck_*_ext_1c_lower`; django-admin — ошибка формы; тест миграции (дубли — стоп, иначе приведено, откат проходит); `makemigrations --check` чисто; `apps/bpp/tests/counterparties`, `test_onec_migration.py`, `apps/project`, `htqweb/tests` зелёные; ранбук — шаг 4 | - | cc:完了 [99c9d63] |
| 8.5 | `[lane:release]` `[tdd:skip:verification-and-review]` Прогон, стенд (`migrate_companies`), итоговое ревью `harness-review`, PR в `new-module-BPP-merge` | Затронутые аппки зелёные, `ci-known-failures.txt` не вырос; стенд мигрирован; Critical/Major ревью исправлены; PR создан, CI зелёный; мерж — по команде пользователя | 8.1, 8.2, 8.3, 8.4 | cc:完了 [PR #47, 83aa114] |

## Phase 9: итоги сверки 04.10 — пробелы A без решения (ветка `new-module-BPP-sanzhar`)

Spec: раздел «Дополнение 04.10» плана [этапа 8](docs/plans/2026-10-03-bpp-stage8-tails-executor-a.md). `team_validation_mode: not_required_lightweight` (документы, тесты, одна функция чтения).

| Task | 内容 | DoD | Depends | Status |
|------|------|-----|---------|--------|
| 9.1 | `[lane:fast]` `[tdd:skip:docs-only]` Мастер-план и CLAUDE.md ↔ код и решения этапов | В мастер-плане нет `DocumentFile` как действующего решения, §2.6 совпадает с сигнатурами кода, A7.1/§7 — с D-S7-2/D-S5-1, у задач A/B — статусы этапов; CLAUDE.md без `calendar`-аппки, `landing_url` верный | 9.4 | cc:完了 [1b9b8c9] |
| 9.2 | `[lane:gate]` `[tdd:required]` Нагрузка выписки 1С 5 000 строк ≤ 60 с (A4.1, Q-C26) | Тест разбора и автосверки 5 000 строк укладывается в 60 с на Python 3.14 локально (время в отчёте); `apps/bpp/tests/bank` зелёные | - | cc:完了 [41d3f06] |
| 9.3 | `[lane:gate]` `[tdd:required]` Правила Grafana БЗО срабатывают на подложенных данных (A3.2) | `promtool test rules` по выражениям бизнес-правил БЗО с подложенными рядами: правило срабатывает выше порога и молчит ниже; шаг в `check-monitoring-config.sh`, скрипт зелёный | - | cc:完了 [501c5f8] |
| 9.4 | `[lane:gate]` `[tdd:required]` `companies.interface.ancestor_slugs` для B8.1 | Предки от родителя вверх, архивные включены, цикл не вешает; `access.inheritance.ancestors_of` через неё; `apps/companies`, `apps/access`, сторож изоляции зелёные | - | cc:完了 [0547b58] |
| 9.5 | `[lane:release]` `[tdd:skip:verification-and-review]` Прогон затронутых аппок, ревью, push | Затронутые аппки зелёные; ревью без Critical/Major; запушено (в PR #47, пока он открыт) | 9.1, 9.2, 9.3, 9.4 | cc:完了 [PR #47] |

## Phase 10: навигация модуля — блок «Подтверждения» и экран маршрутов (решение пользователя 05.10)

Spec: ответ Q-A06 (25.09, «новый раздел — всё в одном месте») и решение 05.10: в левом сайдбаре отдельный блок «Подтверждения» — все страницы модуля (по тем же правилам видимости, что меню `/bpp`), «Мои согласования» (общая очередь `/signoff`: в ней и документы модуля, и кадровые, и запросы) и «Архив договоров»; из группы «Работа» убрать «Договоры» и «Согласования», «Запросы» остаются. Экран маршрутов: без технических кодов типов (`approvals.request`), типы сгруппированы по разделам. `team_validation_mode: not_required_lightweight` (фронт-навигация, подпись типа).

| Task | 内容 | DoD | Depends | Status |
|------|------|-----|---------|--------|
| 10.1 | `[lane:gate]` `[tdd:required]` Блок «Подтверждения» в `ProfileSidebar`: пункты модуля из реестра `features/bpp/modules.ts` (та же видимость, что `BppLayout`), «Мои согласования» → `/signoff`, «Архив договоров» → `/contracts` (при доступе к «Договорам»); «Договоры»/«Согласования» убраны из «Работы»; поиск по сайдбару находит пункты блока; шапка (`navItems.ts`) — без дублей «Договоры»/«Согласования», если они уже в блоке | vitest: блок виден, пункты по правам (без `bpp:read` — только «Мои согласования» и архив), «Работа» без «Договоров»/«Согласований», активный пункт подсвечен; eslint чисто; tsc ≤ 148 | - | cc:完了 [2bbda170] |
| 10.2 | `[lane:gate]` `[tdd:required]` Экран маршрутов `RouteListPanel`: без строки технического кода; типы по разделам — «Закупки и оплаты» (`bpp.*`), «Кадры» (`hr.*`), «Запросы» (`approvals.*`), «Архив договоров» (`contracts.*`, последним); подпись `approvals.request` — «Запрос» | vitest на группировку и отсутствие кода; backend-тесты `apps/approvals`, `apps/signoff` зелёные | - | cc:完了 [5affc613] |

Итог 05.10: шапка (`navItems.ts`) не менялась — сайдбар есть только на `/myprofile` и `/settings`, а шапка на всех страницах, поэтому «Договоры», «Согласования» и «Закупки и оплаты» в «Ещё» остаются: дублем это не является. До заморозки «Договоров» старый раздел в блоке подписан «Прежние договоры» (рядом с «Договорами» модуля), после — «Архив договоров». Подпись типа `approvals.request` — «Запрос»: она видна и в сообщениях об ошибках, внутренний термин «конструктор форм» туда не нужен.

## Phase T: тендерный модуль `tender` (ветка `tender`, с 06.10)

Spec: [docs/plans/2026-10-06-tender-master-plan.md](docs/plans/2026-10-06-tender-master-plan.md) — реестр решений T-01…T-31 поверх ТЗ (`docs/tz/TZ-tender-procurement-v1.0.md`); порядок: мастер-план > ТЗ > Plans.md. Пошаговый план с кодом пишется к старту каждого этапа; ниже — задачи уровня мастер-плана. `team_validation_mode: subagent` (Product / Architecture / Security / QA / Skeptic, 06.10). `formatter_baseline: configured` (eslint, tsc `app.json` ≤148, сторожа pytest). **[B]** — зона Руслана (Q-T09).

Spec delta (Phase T):
- path: docs/plans/2026-10-06-tender-master-plan.md (корневого `spec.md` нет; контракт — мастер-план)
- change: вариант A подтверждён, полный объём ТЗ в пилоте, АП разрешены, OTP — с почтой (ответы 06.10); исправлены 22 расхождения ТЗ с кодом (§2.2): путь cookie, D-13 вручную, схема 2 одним счётом, BR-040 вместо BR-094, своя копия нумерации/журнала, outbox вместо `apps.mail`, автор файлов портала, курс «не позже даты», плановые суммы доставки/СМР, группы статей, проверяющий через `ApproverKind.SUBJECT`
- why: пять проверок ТЗ против кода `sanzhar` @ 0d5eebd3

| Task | 内容 | DoD | Depends | Status |
|------|------|-----|---------|--------|
| T0.1 | `[lane:gate]` `[tdd:required]` Каркас `apps.tender`: `INSTALLED_APPS`, `KNOWN_SERVICES` (+ зеркало `ACCESS_MODULES` фронта), `PREFIX_TO_SERVICE`, `TRANSLATED_APPS`/`SELF_SERVICE`, `urls.py`, `interface.py`; `platform-admin` получает модуль (`access/0026`). `TENANT_APPS`, `holding.py`, `admin.py` — в T0.2 с первой миграцией (тенантная аппка без таблиц роняет `test_tenancy_status`) | Тест каркаса: 404 при включённом, 503 при выключенном сервисе и `CompanyModule`; `test_app_isolation`, `test_invariants`, `test_gate`, `test_me`, `test_bootstrap`, `test_depth`, `test_module_service`, `test_holding_views`, `test_tenancy_status` зелёные | - | cc:完了 [2188fe24] |
| T0.2 | `[lane:gate]` `[tdd:required]` `services/core` tender: копия нумерации `ТН-ГГГГ-NNNNNN` и журнала с триггером append-only, `DomainError` (T-10); первая миграция + `TENANT_APPS`, `holding.py` (`HOLDING_MODELS = ()`), `admin.py` с `ServiceGatedAdminMixin` | Номера без дыр под гонкой; `UPDATE`/`DELETE` журнала — ошибка БД; `makemigrations --check` чист; `test_tenancy_status`, `test_holding_views`, `test_invariants` (админка), `migrate_companies` на стенде | T0.1 | cc:完了 [7f3722c6] |
| T0.3 | `[lane:gate]` `[tdd:required]` `[feature:security]` Узлы `tender.*` и роли `tender-buyer/quality/fd/viewer/adm` (`access/0027`, явные строки, `*.all` в `EXPLICIT_ONLY`), `tender_assign_roles` | Тест «роль × узел» по каждой паре; `*.all` без явной строки — нет доступа; `test_bootstrap`, `test_depth` зелёные; команда идемпотентна, `--dry-run` не пишет | T0.1 | cc:完了 [6998d87b] |
| T0.4 | `[lane:gate]` `[tdd:required]` Фронт: раздел `/tender`, реестр `features/tender/modules.ts`, гейт `tender:read`, `vite.config.ts`, ключи `tender.*` | `modules.test.ts`, `routeDefinitions.test.ts`, `translationKeys.test.ts`, `endpoints.proxy.test.ts` зелёные; eslint чисто; tsc ≤148 | T0.1 | cc:完了 [98ef31d9] (реестр с заглушкой «Обзор»: пустой раздел вёл бы в «Нет доступа») |
| T0.5 | `[lane:fast]` `[tdd:skip:docs-only]` ТЗ перенести в `docs/tz/TZ-tender-procurement-v1.0.md`; `STRUCTURE.md`, `CLAUDE.md`, `API.md` — раздел tender | Ссылки мастер-плана и CLAUDE.md на ТЗ открываются; три файла описывают аппку | T0.1 | cc:完了 [46e8eaba + docs] |
| T1.1 | `[lane:gate]` `[tdd:required]` Модели заявки (`TenderRequest`, `TenderRequestPart`, `TenderRequestItem`), CRUD черновика, файлы ТЗ/чертежей (`files/0006`) | Черновик правит только автор; после отправки — 409; ПМ видит только свои проекты; `makemigrations --check` чист | T0.2, T0.3 | cc:完了 [ddca6248] |
| T1.2 | `[lane:gate]` `[tdd:required]` **[B]** Пакет B-1: `PurchaseRequest.source`/`tender_number` (`bpp/0021`), замок правки/отмены/ручных документов для `source="tender"`, фильтр Плана, `submit_request_from_tender`, `request_status`, `register_request_listener`, `cancel_request_from_tender`, `release_to_plan`, `budget_available`, `budget_articles` (BR-010), схемы Pydantic | ЗЗ `source="tender"`: правка/отмена через API БЗО — 409, ручной документ на её позицию — 409, в Плане не видна; `apps/bpp` зелёный; `migrate_companies` на стенде | T0.1 | cc:完了 [213b0f55] |
| T1.3 | `[lane:gate]` `[tdd:required]` Сервис заявки: части по (статья × вид), группы статей, подсказка остатка, отправка, свёртка статусов (T-08), «исключить часть», отмена | Две статьи + доставка + СМР → 4 ЗЗ; отказ ТД виден в tender в той же транзакции; резерв уменьшает `budget_available`; чужая группа статьи — 422 | T1.1, T1.2 | cc:完了 [ddca6248] |
| T1.4 | `[lane:gate]` `[tdd:required]` Фронт заявки: реестр, форма (позиции, признаки, статьи, плановые суммы, обоснование), карточка с частями и статусами ЗЗ | vitest формы и карточки; eslint чисто; tsc ≤148 | T1.3, T0.4 | cc:完了 [5dc8092e] |
| T2.1 | `[lane:gate]` `[tdd:required]` `Tender`, `PaymentScheme`/`PaymentStage` (шаблоны 1–3, модель для 4), черновик → продление → отмена с причиной | Второй активный тендер — 409; тендер по неутверждённой заявке — 409 | T1.3 | cc:完了 [ddca6248] |
| T2.2 | `[lane:gate]` `[tdd:required]` `[feature:security]` `SupplierContact`, `SupplierProspect`, приглашения (токен SHA-256), отзыв, перевыпуск, сброс устройства, публикация без писем («Скопировать ссылку») | Заблокированный контрагент — 422; сырого токена в БД нет; перевыпуск — старый токен 404 | T2.1 | cc:完了 [ddca6248] |
| T2.3 | `[lane:gate]` `[tdd:required]` Фронт тендера: карточка, участники, ссылки, счётчики «отправлено/открыто/подано» | vitest; до вскрытия предложения не отображаются; eslint/tsc | T2.2, T1.4 | cc:完了 [5dc8092e] |
| T3.1 | `[lane:gate]` `[tdd:required]` `[feature:security]` `htqweb/ratelimit.hit(...)` + nginx `location ^~ /api/tender/v1/supplier/` (лимит, маскировка токена в логе, 21M, `X-Frame-Options: DENY`, `Referrer-Policy`) | Юнит-тесты лимитера (fail-open/closed); `check-monitoring-config.sh` зелёный; `docker compose -f <каждый> config` | T0.1 | blocked [50e490fc] (отложено пользователем 20.10: не выполнен только `nginx -t` — нужен ок на самоподписанные `*.pem`/`*.key`; compose config и `check-monitoring-config.sh` — зелёные) |
| T3.2 | `[lane:gate]` `[tdd:required]` `[feature:security]` Вход по ссылке: GET-карточка, POST `bind` → cookie `__Secure-tender_device` (`Path=/api/tender/v1/supplier/`), «токен + cookie» на каждой ручке, `max_devices`, `PortalEvent` (IP из `X-Real-IP`), Origin/JSON | GET не привязывает; второе устройство — отказ; параллельные `bind` → одна привязка; чужой Origin — 4xx; архив — 404; сервис выключен — 503; `X-Forwarded-For` не в журнале | T2.2, T3.1 | cc:完了 [e8a97163, 159f5311, 17281f7e, 1cd8f7fb] |
| T3.3 | `[lane:gate]` `[tdd:required]` `[feature:security]` Предложение: позиции, аналоги, `OfferExtra` (доставка/СМР), НДС, валюта, срок, схема оплаты, реквизиты, согласие ПДн, версии, отзыв, отказ; правка после срока — 409 под блокировкой тендера | Сторож: рекурсивно нет `plan_price`/других участников; после срока — 409 (`pinned_clock`); версии с историей | T3.2 | cc:完了 [e8a97163, 1cd8f7fb] |
| T3.4 | `[lane:gate]` `[tdd:required]` `[feature:security]` Файлы КП: владелец `tender.offer`, технический пользователь (`users`), загрузка только при включённом сканере, 20 МБ/10 файлов/без xml | Без сканера — 503; поддельный clamd с угрозой — 422 `E-FIL-08`; 11-й файл — 409, `.xml` — 415 (коды подсистемы файлов, план §4.1); чужой файл — 404 | T3.3 | cc:完了 [e8a97163, 1cd8f7fb] |
| T3.5 | `[lane:gate]` `[tdd:required]` Фронт портала `SupplierTender.tsx` (мобильный, без layout, итог после срока) | vitest; Playwright: два `newContext` — второе устройство видит отказ; `Secure`-cookie на `*.localhost` проверена | T3.3, T3.4 | cc:完了 [52c5b100, 01c54fcb] |
| T3.6 | `[lane:gate]` `[tdd:required]` `[feature:security]` Доводка портала (план этапа 3 §4.2): устройство и Origin до разбора тела; сторож белого списка на всех ручках и телах ошибок; multipart только у загрузки; тест лимита IP и `TENDER_PORTAL_*_LIMIT` в `base.py`; `bind_refused` через `fallback` | Битый JSON без cookie — 403; multipart на `submit` — 415; лимит IP — 429; сторож обходит каждый маршрут `urls_supplier.py`; тесты портала зелёные | T3.2–T3.4 | cc:完了 [159f5311, 17281f7e, a9ba21d3] |
| T3.7 | `[lane:gate]` `[tdd:required]` `[feature:security]` Хвосты 0–2: `allowed_actions` у приглашения (одна функция для кнопок и проверки сервера); перевыпуск и сброс устройства — только пока идёт приём; фронт карточки тендера | После срока у приглашения только `revoke`; сброс и перевыпуск после срока — 409; сброс A не снимает привязку той же cookie к B; vitest карточки | T3.2 | cc:完了 [6524398c] |
| T3.8 | `[lane:gate]` `[tdd:required]` Фронт портала: `extras` словарём в `PUT offer`, `retryAfter` из `details.retry_after`, пустое предложение без `null`, `customer` в шапке, `testData.ts` по настоящим ответам | vitest tender/portal зелёный; eslint чисто; tsc ≤148; Playwright `40_tender_portal` (chromium) зелёный на `test-local` | T3.5 | cc:完了 [52c5b100, 01c54fcb] |
| T3.9 | `[lane:release]` `[tdd:skip:verification-and-review]` Закрытие этапа 3 локально: `nginx -t`, `docker compose -f <каждый> config`, `check-monitoring-config.sh`; API.md/STRUCTURE.md/CLAUDE.md; регрессия (tender, files, users, `test_gate`, сторожа core, `htqweb/tests`, `makemigrations --check`); `harness-review`; локальные коммиты по задачам — **без пуша** | Все проверки зелёные с выводом в отчёте; Critical/Major исправлены; T3.1–T3.9 `cc:完了` с хэшами; `git status` чист | T3.6, T3.7, T3.8 | blocked [85ad0136, 1a9a5eb6, 1cd8f7fb, 01c54fcb] (документация, ревью — APPROVE после исправлений, регрессия 2259 passed, `makemigrations --check` чист; ждёт `nginx -t` из T3.1) |
| T4.1 | `[lane:gate]` `[tdd:required]` Outbox `OutboundEmail` + Celery, шаблоны писем (приглашение, продление, напоминание, отмена, итог), статус доставки, mailpit в `test-local` | `mail.outbox` с приглашением; повтор не дублирует; ошибка SMTP — `delivery_error`; `test_invariants`, `test_periodic_tasks` зелёные | T2.2 | cc:TODO |
| T4.2 | `[lane:gate]` `[tdd:required]` `[feature:security]` OTP-перепривязка (хэш HMAC, 10 мин, 5 попыток, 3 отправки/ч + IP, fail-closed) | 6-я попытка — 429; верный код после 5 неудач — отказ; повтор кода — отказ; старое устройство — отказ; Playwright с кодом из mailpit | T4.1, T3.2 | cc:TODO |
| T4.3 | `[lane:gate]` `[tdd:required]` Beat: закрытие приёма по сроку, напоминания, чистка OTP; `notify` внутренним и источник сводки | `test_periodic_tasks` зелёный; закрытие по сроку на `pinned_clock`; уведомления в колокольчике | T4.1 | cc:TODO |
| T4.4 | `[lane:release]` `[tdd:skip:ops-dns-mailbox]` Ящик `tender@htq.group`, SPF/DKIM/DMARC, ранбук почты | Ручной протокол: письмо во «Входящих» Gmail, Mail.ru, Yandex | T4.1 | cc:TODO |
| T5.1 | `[lane:gate]` `[tdd:required]` Вскрытие и сравнение (полная стоимость в KZT с НДС, курс «не позже даты», покрытие, экономия), экспорт xlsx с санитайзером (+ `bpp/services/core/export.py`) | `comparison` до вскрытия — 409; частичное предложение — по общему набору; формулы нейтрализованы | T3.3, T5.4 | cc:完了 [00de210c, d6aac409, e2ae9d7e] |
| T5.2 | `[lane:gate]` `[tdd:required]` Выбор по позициям и `OfferExtra`, комментарий не самой низкой цены, проверка остатка (T-13), signoff `tender.award` (SUBJECT → ФД), возврат, письма итога | Без комментария — 422; дефицит — 422; ТД по должности и заменённый проверяющий получают задачу; `apps/signoff` зелёный | T5.1 | cc:完了 [64499f0e, f1fca498] (письма итога поставщикам — этап 4) |
| T5.3 | `[lane:gate]` `[tdd:required]` **[B]** Пакет B-2: `create_documents_from_tender`, `documents_status`, `set_acceptance`, `attach_closing_docs` (D-13), схема 3 (`pay_after_receipt`, срок от приёмки) | > 1000 МРП на поставщика — договоры; повтор не дублирует; автор — закупщик; закрывающие вне `awaiting_docs`/незапрошенного типа — отказ; `apps/bpp` зелёный | T1.2 | cc:完了 [8ebd33fe, 50f9ce97, 6628c7ee, 76beaf4f, b2d22989] |
| T5.4 | `[lane:gate]` `[tdd:required]` Зона A: `create_counterparty_from_prospect`, `refdata.exchange_rate_on_or_before` | Страна + рег. номер — привязка без дубля; курс в выходной — последний рабочий; `apps/bpp/tests/counterparties`, `apps/refdata` зелёные | T0.1 | cc:完了 [90f402e2, 75911a06] |
| T5.5 | `[lane:gate]` `[tdd:required]` Передача и поставка: `handover`, стадии по схемам 1–3, приёмка (частичная, сканы, «оригиналы переданы»), автоприкладывание по запросу БУХ, «Закрыт» | Стадии на трёх схемах; приёмка ставит срок схемы 3; «Закрыт» — всё получено и счета закрыты | T5.2, T5.3 | cc:完了 [b5211748, 5a91acf3, 7559f5bb] |
| T5.6 | `[lane:gate]` `[tdd:required]` Метрики `htqweb_tender_*` + дашборд/правило; сквозной pytest и Playwright по сценарию ТЗ | `test_metrics_are_observed` зелёный; сквозные сценарии зелёные | T5.5, T4.3 | cc:完了 [697cfb0d, 4fd59e3f, 96bf130d, 5a91acf3] (без частей этапа 4: T4.3 не начат) |
| T5.7 | `[lane:release]` `[tdd:skip:verification-and-review]` Ранбук выкатки, прогон затронутых аппок + сторожей backend-full, `harness-review`, PR `tender` → `sanzhar` | Аппки зелёные, `ci-known-failures.txt` не вырос; Critical/Major исправлены; PR создан, CI зелёный; мерж — по команде пользователя | T5.6, T4.4 | cc:done [1c01c31a, 5a91acf3, b82802ce] (ранбук, документация, ревью; PR #58 `tender` → `sanzhar` смержен 21.10 — `b82802ce`; регрессия — `218b62dc`; этап 4 — T4.1–T4.4 — отдельно, зависимость от T4.4 снята решением о мерже) |
| T6.1 | `[lane:gate]` `[tdd:required]` После пилота: открытый тендер, переторжка и тендер на остаток, вопросы-ответы, отгрузка от поставщика, схема 4, этап ГД и `tender-gd`, bounce, рейтинг, английский, удаление по сроку | Пошаговый план этапа 6 утверждён до начала | T5.7 | cc:TODO |

Итог 07.10 (T0.3–T2.3, автономный прогон): общий прогон бэкенда — 1880 passed (tender, мост БЗО, заявки и план БЗО, сторожа прав, тенантности и файлов), фронт — 172 passed, eslint чисто, tsc 148. Замечания проверки безопасности закрыты по ходу: `budget_available` в правах пользователя, `release_to_plan` — только автор ЗЗ или ФД, файлы ЗЗ из tender заперты.

Итог 20.10 (этап 3, доводка T3.6–T3.9 — план [2026-10-20-tender-stage3-tails-plan.md](docs/plans/2026-10-20-tender-stage3-tails-plan.md)): регрессия бэкенда — 2259 passed (`apps/tender`, `apps/files`, `apps/users`, `test_gate`, `htqweb/tests`, сторожа `core`), `makemigrations --check` чист; vitest tender/public/routing — зелёный (полный vitest — только известные падения вне tender: HR-диалоги, `uxContract` у `features/bpp/projects`, три нестабильных под нагрузкой файла БЗО, поодиночке зелёные), tsc 148, eslint чисто; e2e `40_tender_portal` (chromium, test-local) — 2 passed. `harness-review`: 2 major (токен в логах, сироты в S3) и 6 minor исправлены, повторное ревью — APPROVE. Хвосты этапов 0–2 по `allowed_actions` приглашения и окну сброса устройства закрыты (T3.7); DWG в `tender_spec` — отложен до этапа 5.

Спека этапа 5 (20.10): [docs/plans/2026-10-20-tender-stage5-spec.md](docs/plans/2026-10-20-tender-stage5-spec.md), пошаговый план — [docs/plans/2026-10-20-tender-stage5-plan.md](docs/plans/2026-10-20-tender-stage5-plan.md) (13 задач, демо-данные — `seed_tender_demo`) — порядок T5.4 → T5.1 → T5.2 → T5.3 [B] → T5.5 → T5.6 → T5.7, решения S5-01…S5-20, вопросы Алгазы до T5.2/T5.5.

Итог 20.10 (этап 5, T5.1–T5.7 по [плану](docs/plans/2026-10-20-tender-stage5-plan.md)): вскрытие и сравнение, выбор с комментариями, утверждение «Проверка качества → ФД», передача в БЗО (пакет B-2 у Руслана — коммиты `bpp(B):`), поставка, приёмка, закрывающие, «Закрыть остаток», метрики/дашборд/правило, фронт всех вкладок и итог в портале, ранбук. Проверки: сквозной pytest `test_stage5_e2e` на настоящем БЗО, Playwright `41_tender_award` + `40_tender_portal` — 3 passed (chromium, test-local), `check-monitoring-config.sh` зелёный, `makemigrations --check` чист, tsc 148, eslint чисто, vitest tender/bpp — зелёный (полный — только известные падения вне модуля). `harness-review`: 6 major исправлены (документ из замены альтернативой, постоплата «просрочена» до приёмки, «Закрыть остаток», e2e, ранбук, 409 на вкладке выбора и float в приёмке), повторное ревью — 2 major исправлены (плановая дата при повторной приёмке, закрытие тендера при открытом остатке). Регрессия на финальном коде (`apps/tender apps/bpp apps/signoff apps/files apps/refdata`, `test_gate`, `htqweb/tests`, сторожа CI) — 3150 passed, 2 skipped, 1 failed: `signoff/test_cross_company.py::test_acting_holder_of_holding_position_gets_the_task` — тест берёт `date.today()` машины, а движок `timezone.localdate()` в UTC, поэтому он падает между полуночью и 05:00 местного времени (прогон кончился в 01:00); signoff в этапе не менялся, днём тест проходит. Хвосты: `nginx -t` (T3.1), этап 4 (почта, OTP, автозакрытие приёма).

Хвосты этапов 0–2 (несрочные, в план этапа 3 или 5):
- DWG в `tender_spec` — файловая подсистема и scope `file_object` формат не знают (`files/services/documents.py` + `media_files`).
- Действия на уровне приглашения (`allowed_actions` у приглашения): после срока кнопки отзыва/перевыпуска/сброса пропадают вместе с `invite` (этап 3); окно `reset-device` (сейчас draft…rework) сузить до приёма (этап 3).
- Смена проверяющего качества после публикации — не выведена в `allowed_actions` (этап 5, T5.2).
- Ручка «мои роли инициатора» в tender — форма берёт роли из `bpp/v1/me` (нужен `bpp:read`).
- Контакты контрагента требуют `tender.prospects` view — автору тендера без него доступна только почта карточки.
- Признак `delete` у `tender.prospects` объявлен, ручки удаления потенциального поставщика нет.
- `FOREIGN_EXPLICIT` в `access/0027` не включает `bpp.*.all`/`bpp.holding` — догнать, если у них появится сторож «строка у каждой системной роли».
- Полный vitest: 9 падений вне tender (HR-диалоги, `uxContract` в `features/bpp/projects`) — были до ветки.

Каждый этап (T0…T5) закрывается `harness-review` и локальными коммитами; **ветка `tender` не пушится до конца модуля** (решение пользователя 20.10) — пуш и PR в `sanzhar` только после T5.7 по команде; открытые вопросы Q-T01…Q-T15 — §6 мастер-плана (до ответа — умолчания).

## Phase K: канбан-доски модуля «Задачи», этап 1 — видимость и права (ветка `sanzhar`, с 21.10)

Spec: [docs/plans/2026-10-21-kanban-stage1-spec.md](docs/plans/2026-10-21-kanban-stage1-spec.md) (S1-01…S1-14) поверх [мастер-плана](docs/plans/2026-10-21-kanban-boards-master-plan.md) (K-01…K-33, ответы заказчика 21.10); порядок: мастер-план > спека > Plans.md. Пошаговый план — [docs/plans/2026-10-21-kanban-stage1-plan.md](docs/plans/2026-10-21-kanban-stage1-plan.md) (Task 1…8 = K1.1…K1.8).

Spec delta (Phase K, этап 1):
- path: docs/plans/2026-10-21-kanban-stage1-spec.md (корневого `spec.md` нет; контракт — мастер-план и спека этапа)
- change: видимость задачи по поддереву отдела (и в календаре, Ганте, связях, подзадачах — закрытие существующих утечек) (`Task.department_id` и `TaskDepartmentLink`), права главы отдела (`Department.manager`) на задачи поддерева, узел `tasks.departments.all` (ОД, ГД), `project.board` у ГД и `EXPLICIT_ONLY`, перенос в отдел со связью `origin`, «Взять в работу», `scope=mine|department`, флаги `can`; `elevated` — без изменений
- why: решения заказчика 21.10 (мастер-план §1, §12); сверка с кодом `sanzhar` @ 218b62dc; три проверки плана (subagent: архитектура, безопасность, тестируемость) — 54 находки, приняты в спеке S1-15…S1-27

| Task | 内容 | DoD | Depends | Status |
|------|------|-----|---------|--------|
| K1.1 | `[lane:gate]` `[tdd:required]` `hr.interface`: `department_subtree_ids`, `managed_department_ids`, `department_manager_user_ids` (план Task 1) | `apps/hr/tests/test_interface_departments.py` зелёный: поддерево по «.» (`it` не захватывает `itops`, `a_b` — `aXb.c`), неактивные подотделы входят, глава двух отделов, уволенный/удалённый глава — пусто, обе функции глав на одном фильтре, `hr` выключен — `ServiceDisabled`, `_like`-индекс `path` есть | - | cc:完了 [65876648] |
| K1.2 | `[lane:gate]` `[tdd:required]` Узлы `tasks.departments.all` (`view`, `EXPLICIT_ONLY`), `project.board` в `EXPLICIT_ONLY` и у ГД; миграция `access/0028`; матрица ролей БЗО (план Task 2) | `apps/access/tests/test_tasks_board_nodes.py` (вкл. `unseed`→`seed`) и обновлённый `test_bpp_roles.py` зелёные: строки у каждой системной роли кроме `platform-admin`, `view` — ровно ОД и ГД / ТД, ОД, ГД, ПМ, АДМ; кастомная роль с модулем без строки узла не получает; `makemigrations --check --dry-run` чист | - | cc:完了 [4f577a96] |
| K1.3 | `[lane:gate]` `[tdd:skip:mechanical-refactor-covered-by-existing-suite]` `load_for_action`/`require_*` получают `request` вместо `token` (40 вызовов, план Task 3) | Полный `apps/tasks` — те же id упавших (`-rf`), что в базе до замены; 40 вызовов на месте, `request.token` в них нет; `test_gate.py` зелёный | - | cc:TODO |
| K1.4 | `[lane:gate]` `[tdd:required]` `[feature:security]` `TaskDepartmentLink.kind` (`tasks/0027`), `TaskScope` (кэш на запросе), новая `visibility_q`, права главы (в т.ч. делегаты), доски и роудмапы по поддереву, видимость в календаре, Ганте, связях и подзадачах карточки (план Task 4) | `test_migration_0027.py`, `test_board_visibility.py`, `test_head_rights.py`, `test_leaks_closed.py`, новые тесты `test_board_scope.py` зелёные (Review Focus 1–3, 5; вкл. настоящую роль `bpp-gd`); полный `apps/tasks` без новых упавших; `test_app_isolation` зелёный; на стенде `migrate_companies` прошёл | K1.1, K1.2, K1.3 | cc:TODO |
| K1.5 | `[lane:gate]` `[tdd:required]` `[feature:security]` Правила отдела при создании и правке (порядок проверок, только управляемые поддеревья у главы, перекладка `department_ids`), `reporter_id` (создание и `PATCH`), начальный статус, видимый `parent_id`, `department_ids` ответа без `origin`, журнал отдела (план Task 5) | `test_department_rules.py` зелёный (обходы переноса закрыты — Review Focus 4); `test_create_task_stores_multi_department_set` переписан; полный `apps/tasks` без новых упавших | K1.4 | cc:TODO |
| K1.6 | `[lane:gate]` `[tdd:required]` `[feature:security]` Перенос `tasks/<id>/transfer`, «Взять в работу» `tasks/<id>/claim` (только свой отдел, с блокировкой), `?scope=mine\|department`, `can` в карточке и `can.claim` в списке, схемы и `contracts.json` (план Task 6) | `test_transfer.py`, `test_claim.py`, `test_list_scope.py`, `test_detail_can.py`, `test_contract_parity.py` зелёные (Review Focus 3–5); `test_gate.py` зелёный; новых запросов в списке нет | K1.5 | cc:TODO |
| K1.7 | `[lane:gate]` `[tdd:required]` Фронт: `EmployeeTasks` на `scope`, «Взять в работу» → `claim`, `TransferDialog` на `/tasks/:id`, i18n (план Task 7) | vitest `EmployeeTasks.test.tsx`, `TransferDialog.test.tsx`, `translationKeys.test.ts` зелёные; `npm run lint` чисто; `tsc -p tsconfig.app.json` — не больше базы на старте | K1.6 | cc:TODO |
| K1.8 | `[lane:release]` `[tdd:skip:verification-and-review]` `API.md`, `STRUCTURE.md` §4.2, `CLAUDE.md`; регрессия; ручная проверка на стенде; `harness-review` (план Task 8) | Регрессия бэкенда по списку плана — зелёная или только `ci-known-failures.txt`; фронт зелёный; на стенде пройдены 4 сценария Task 8 шага 4; Critical/Major ревью исправлены; пуш и PR — по команде пользователя | K1.7 | cc:TODO |

## 事前確認

- 事項: external-send — `git push origin new-module-BPP-sanzhar`
  理由: коммиты задач 7.1–7.8 публикуются в ветку исполнителя (как на этапах 4–6)
  scope: Phase 7 / Task 7.1–7.8
- 事項: external-send — GitHub REST API: создание PR в `new-module-BPP-merge` и чтение статуса CI/PR (токен из `git credential fill`, не печатается)
  理由: DoD задачи 7.8; мерж PR — только по отдельной команде пользователя
  scope: Phase 7 / Task 7.8
- 事項: external-send — `docker pull clamav/clamav:1.4` и загрузка баз freshclam на тестовом стенде
  理由: ручная проверка `healthy` и EICAR в DoD задачи 7.5
  scope: Phase 7 / Task 7.5
- 事項: destructive — тестовая БД `test_htqweb` (pytest создаёт и удаляет) и миграции/команды на БД стенда `docker-compose.test-local.yml` (`migrate_companies`, `refdata_import_production_days`, `bpp_group_directors`, `auth_unlock`), перезапуск сервисов стенда
  理由: прогоны тестов и проверка на стенде в DoD задач 7.1–7.8; прод и `test-env` не затрагиваются
  scope: Phase 7 / Task 7.1–7.8
- secret-read: не требуется — `.env`, `secrets/**` агенты не читают; `onec_check` и тесты 1С — без настоящих доступов.
- 事項: external-send — `git push origin new-module-BPP-sanzhar`
  理由: коммиты задач 8.1–8.5 публикуются в ветку исполнителя
  scope: Phase 8 / Task 8.1–8.5
- 事項: external-send — GitHub REST API: чтение открытых PR и статуса CI, создание PR в `new-module-BPP-merge` (токен из `git credential fill`, не печатается)
  理由: DoD задачи 8.5; мерж — только по отдельной команде пользователя
  scope: Phase 8 / Task 8.5
- 事項: destructive — тестовые БД `test_htqweb*` (pytest создаёт и удаляет) и `migrate_companies` на БД стенда `docker-compose.test-local.yml`
  理由: прогоны тестов и проверка миграций `bpp/0020`, `project/0003` на стенде
  scope: Phase 8 / Task 8.1, 8.3, 8.4, 8.5
- secret-read (Phase 8): не требуется — `.env`, `secrets/**` не читаются.
- 事項: external-send — `git push origin tender`
  理由: коммиты задач фазы T публикуются в ветку модуля
  scope: Phase T / Task T0.1–T6.1
- 事項: external-send — GitHub REST API: создание PR `tender` → `sanzhar` и чтение статуса CI (токен из `git credential fill`, не печатается)
  理由: закрытие каждого этапа (T0…T5); мерж — только по команде пользователя
  scope: Phase T / Task T0.5, T1.4, T2.3, T3.5, T4.4, T5.7
- 事項: external-send — `docker pull axllent/mailpit` (и `clamav/clamav:1.4` для проверки сканера) на тестовом стенде
  理由: Playwright-сценарий OTP (T4.2) и проверка загрузок портала (T3.4)
  scope: Phase T / Task T3.4, T4.1, T4.2
- 事項: destructive — тестовые БД `test_htqweb*` (pytest создаёт и удаляет) и `migrate_companies`/команды tender на БД стенда `docker-compose.test-local.yml`
  理由: прогоны тестов и проверка миграций `tender/*`, `bpp/0021`, `access/0026`–`0027`, `files/0006`
  scope: Phase T / все задачи с кодом
- secret-read (Phase T): не требуется — `.env`, `secrets/**` не читаются; DNS и ящик `tender@` (T4.4) настраивает эксплуатация, агенты доступов не получают.
- 事項: destructive — тестовые БД `test_htqweb*` (pytest создаёт и удаляет), `migrate_shared`/`migrate_companies` и сиды (`seed_hr_demo`, `seed_tasks_demo`, `bpp_assign_roles`) на БД стенда `docker-compose.test-local.yml`
  理由: прогоны тестов и проверка миграций `access/0028`, `tasks/0027` на стенде (DoD K1.2, K1.5, K1.8)
  scope: Phase K / Task K1.1–K1.8
- external-send (Phase K): не требуется — пуш и PR в задачи не входят, только по отдельной команде пользователя.
- secret-read (Phase K): не требуется — `.env`, `secrets/**` не читаются.

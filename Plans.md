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

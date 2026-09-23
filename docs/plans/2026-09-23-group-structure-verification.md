# Итоговая сверка структурного рефакторинга группы компаний

**Дата:** 2026-09-23 (сверка выполнена 2026-09-24)
**Ветка:** `sanzhar`
**Задача:** 6 блока J ([план](2026-09-23-block-j-docs.md)); требования — roadmap
[§1](2026-09-14-group-structure-roadmap.md#1-что-утвердило-руководство),
[§5](2026-09-14-group-structure-roadmap.md#5-блоки-работ-моя-зона).

## 1. Итог одной фразой

**Структурный рефакторинг (блоки A–I.2) выполнен с оговорками.** Каждое из
пятнадцати проверяемых требований руководства реализовано в коде и держится
тестом или демо-стендом; расхождения, оставшиеся открытыми, — это ранее
известные и явно задокументированные границы (передача второму разработчику,
вопросы руководству, сознательно отложенное — §6 ниже), плюс четыре новых
находки этой сверки (документ и код — небольшие неточности, не дефекты
рефакторинга) и одна независимая находка о состоянии рабочего дерева
(TIME_ZONE), которая на код рефакторинга не влияет, но объясняет 4 из 12
упавших тестов полного прогона.

## 2. Требования → реализация → доказательство → статус

Метод проверки — по коду и тестам (Review Focus блока J), не по тексту
roadmap: для каждой строки ниже проверен файл реализации и прогнан (или
прочитан) тест.

| № | Требование (источник) | Реализация (файл) | Доказательство (тест/команда) | Статус |
|---|---|---|---|---|
| 1 | Холдинг и три ДО с видами (`kind`) и деревом владения (`parent`) — §1, §4, §5.A | `backend/apps/companies/models.py`: `CompanyKind` (строки 40–54: `HOLDING`, `CONSTRUCTION`, `IT`, `SERVICE`), `Company.parent`/`subdomain`/`status` (77–109) | `apps/companies/tests/*` (236 прошли, см. §4); стенд (§5): `hi-tech-group/None/holding`, `hi-tech-qazaqstan/hi-tech-group/construction`, `hi-tech-systems/hi-tech-group/it`, `kazakhstan-engineering-group/hi-tech-group/service` — все `active` | ✅ |
| 2 | ОСУ — системная должность над ГД холдинга — §1, §5.F | `backend/apps/hr/services/participant_service.py::ensure_participant` (стр. 124+), `backend/apps/hr/interface.py::participant_position` (465+), `apps/hr/management/group_structures.py:163` | `apps/hr/tests/test_participant_service.py`, `test_interface_participant.py`, `test_group_structures.py::test_participant_is_the_only_system_post_and_sits_on_top`; стенд: `osu=True` только у `hi-tech-group` | ✅ |
| 3 | Три дирекции холдинга (финансы/ПТО/операционная) — §1, §5.D | `apps/hr/management/group_structures.py:150-158` (`Unit("fin"/"pto"/"ops", …, "directorate")`), `apps/hr/models.py:36` (`UnitType.DIRECTORATE`) | `test_group_structures.py::test_holding_directorates_are_directorates`; стенд: `directorates=3` у `hi-tech-group`, `0` у трёх ДО (по структуре документа дирекции только в холдинге) | ✅ |
| 4 | Уровни N-1…N-4, в холдинге N-3 пропущен — §1, §5.D | `apps/hr/migrations/0024_seed_level_thresholds.py` (`LEVELS`, диапазоны весов 0-99/100-299/300-599/600-1999); веса должностей холдинга в `group_structures.py:163-187` заполняют 0, 10, 110–187, 610–680 — диапазон 300-599 (N-3) не занят ни одной должностью холдинга | `test_group_structures.py::test_levels_match_the_migration_seed`, `test_levels_used_by_each_structure`; прямая проверка весов (см. выше) — N-3 действительно пуст у холдинга; стенд: `levelthresholds=4` в каждой из 4 схем | ✅ |
| 5 | У ДО руководитель — «Директор», не «Генеральный директор» — §1, §5.D | `group_structures.py`: `Post("Директор", "upr", 10, 10, "lead", is_manager=True)` во всех трёх структурах ДО (строки 259, 279, 299) | `test_group_structures.py::test_subsidiary_heads_are_directors_not_general_directors` | ✅ |
| 6 | Штатные единицы («1 шт. ед.») — §1, §5.D/H | `apps.hr.models.StaffingPosition`; добавлена в `apps/hr/holding.py::HOLDING_MODELS` (блок H, «штат против факта») | `apps/hr/tests/test_staffing_api.py`, `apps/hr/tests/test_holding_summary.py` | ✅ |
| 7 | Пунктирные горизонтальные связи менеджеров дирекций — §1, §5.D | `ReportingRelation.functional` (модель `hr`), сеется в `group_structures.py` (`managers={...}`) | `test_group_structures.py::test_functional_links_are_exactly_the_dashed_lines` | ✅ |
| 8 | Внешняя иерархия (правило 4) — §1, §5.B | `hr.Position.is_manager`/`external_hierarchy` (`apps/hr/models.py:131-147`), `apps/access/services/hierarchy.py::_is_external_manager`/`subordinate_companies` (50-75) | `apps/access/tests/test_hierarchy.py` (10 тестов), `test_hierarchy_integration.py` (3), `apps/hr/tests/test_position_external_hierarchy.py` | ✅ (оговорка сохраняется по §4: отметка «руководящая» — вручную, автобэкфилла по оргструктуре нет — задокументировано, не дефект) |
| 9 | Права холдинга в ДО, `serves_subsidiaries` — §1, §5.C | `hr.Position.serves_subsidiaries` (`apps/hr/models.py:152`), `apps/access/services/inheritance.py` (`ancestors_of`, `inherit`, `inherited_role_scopes`) | `apps/access/tests/test_inheritance.py` — 10 тестов (наследование вниз, архивный предок, цикл в дереве, объединение с личными правами и др.) | ✅ (членство остаётся отдельным явным фактом — задокументировано в §4, не дефект) |
| 10 | Десять кадровых предметов согласования HR-FRM-004 строк 1–10 с фактами — §1, §5.G | `apps/hr/approval_hooks.py`: `SUBJECT_MODELS`/`SUBJECT_SPECS` (580–594, ровно 10 записей), регистрация из `HrConfig.ready()` | `apps/hr/tests/test_approval_subjects.py` — 23 теста, включая `test_every_matrix_row_has_its_subject_and_facts`, `test_every_subject_declares_fields_the_engine_accepts`, `test_only_the_personnel_order_has_an_automatic_effect` | ✅ |
| 11 | Замещение ключевых должностей (HR-FRM-006) — §1, §5.E | `hr.Substitution` (`position`, `substitute_position`, `kind`, `basis`, `valid_from/to`), `apps/hr/services/substitution_service.py`, `apps.hr.interface.substitutes_for` (430+, ровно три ключа) | `test_substitution_model.py` (6), `test_substitution_service.py` (11), `test_substitutions_api.py`, `test_interface_substitutes.py`, `test_group_structures.py::test_substitution_matrix_matches_the_document` | ✅ (строка «Системный администратор → внутригрупповой ИТ-подрядчик» не сеется намеренно — задокументировано) |
| 12 | Реестр/API/экраны компаний — §5.A | `apps/companies/{urls,views,schemas}.py`, `services/lifecycle.py`, `module_service.py`, `membership_service.py`; фронт `CompanySwitcher.tsx`, `pages/CompanyPicker.tsx`, `pages/Companies*` | `apps/companies/tests/*` — 236 тестов прошли (§4); файлы фронта подтверждены (`ls`) | ✅ |
| 13 | Сводки холдинга (`hr`, `tasks`) — §5.H | `apps/hr/holding_models.py`, `apps/tasks/holding_models.py` (managed=False, читают `holding.*` через `use_holding()`), `holding_service.py` в обоих доменах, ручки `GET hr/v1/holding/headcount`, `GET tasks/v1/holding/projects` | `apps/hr/tests/test_holding_api.py`, `test_holding_summary.py`; `apps/tasks/tests/*holding*` (в составе 717 тестов `apps/tasks`, §4) | ✅ (финансы `contracts` и согласования `signoff` — плитки-заглушки до читателей второго разработчика, задокументировано, не в этой зоне) |
| 14 | Единая модель прав (`apps.access`, блок I/I.2) — §5.I, §5.I.2 | `api_view(module=, level=)` на каждой ручке `hr/users/companies/access/tasks`; `apps/access/self_service.py` (реестр исключений с причиной `self`\|`open`\|`scoped`); `apps/access/services/resolve.py`; `apps/access/legacy_roles.py::KEY_TO_NODE` | `apps/access/tests/test_gate.py` — 19 тестов (перевёрнутый сторож, `_OUT_OF_SCOPE_APPS = {signoff, contracts}`); `test_hr_level_roles_exact.py` | ✅ (contracts/signoff вне зоны блока I — сами в `_OUT_OF_SCOPE_APPS`, зона другого разработчика, §6) |
| 15 | Поддомены компаний — §5.I.2 | `Company.subdomain`, `apps/companies/interface.py::resolve_host_label` (89–109, псевдоним → слаг без псевдонима, один канонический хост); `CompanyPicker.tsx`, `sessionRestore.ts`, `CompanySwitcher.tsx` | `apps/companies/tests/test_subdomain.py` (в составе 236 тестов `apps/companies`, §4) | ✅ |

Требования без реализации или без теста в проверяемом наборе не найдены —
все 15 строк минимума брифа подтверждены кодом и тестом. Оговорки у строк
8, 9, 11, 13, 14 — это границы, уже названные в roadmap §4/§6/§9, а не
пропуски этой сверки.

## 3. Блоки A–I.2: план → статус → коммиты

Полные списки коммитов каждого блока — в его собственном плане (ссылки
ниже); здесь — представительные коммиты, найденные `git log --oneline` по
файлам и ключевым словам блока, достаточные, чтобы подтвердить, что блок
действительно состоялся в истории, а не только в roadmap. Все восемь
статусов «(выполнено)» в roadmap §5 подтверждены проверкой по коду в §2.

| Блок | План | Статус (roadmap §5) | Представительные коммиты |
|---|---|---|---|
| A. Реестр компаний | [2026-09-14-block-a-company-registry.md](2026-09-14-block-a-company-registry.md) | выполнено | `d6246ff` реестр компаний группы, `e401d91` HTTP-API реестра, `44a00ad` архив/восстановление по HTTP, `0010486` `tenancy_status`, `41ed84d` виды компаний по утверждённой структуре |
| B. Внешняя иерархия | [2026-09-15-block-b-external-hierarchy.md](2026-09-15-block-b-external-hierarchy.md) | выполнено | `a8d1c72` должность знает, руководящая ли она |
| C. Права холдинга в ДО | [2026-09-15-block-c-holding-authority.md](2026-09-15-block-c-holding-authority.md) | выполнено | `8cc2ed9` признак «обслуживает дочерние компании», `ec37cac` видимость внешних держателей прав, `5946a7f` метрика разрыва «признак без членства» |
| D. Уровни, дирекции, демо | (часть roadmap, без отдельного плана) | выполнено | `120e5d5` «Дирекция» — вид подразделения, `e53253a` новая схема рождается с уровнями N-1…N-4, `2a2bc95` матрица замещения — модель, `830c2e3` блок D закрыт |
| E. Замещение (HR-FRM-006) | (часть roadmap D/E) | выполнено | `2a2bc95` модель `Substitution`, `b6c2da0` контракт `substitutes_for` |
| F. ОСУ / «Участник» | (часть roadmap) | выполнено | `563ee07` контракт `participant_position`, `53f850b` команда `hr_participant` |
| G. HR-субъекты согласования | (часть roadmap) | выполнено | `e4bcf2c` штатное расписание согласуется, `ced1556` кадровый приказ и `PersonnelHistory`, `1f4abdb` премия/взыскание, `f8e5e0c` отпуск/командировка, `713ff09` график отпусков |
| H. Сводки холдинга | (часть roadmap) | выполнено | `e475074` сводка по людям и штату, `ec31c79` сводка по работам, `c6b78a9` закрытие обхода сторожа через `_base_manager` |
| I. Единая модель прав | [2026-09-17-block-i-single-rbac.md](2026-09-17-block-i-single-rbac.md) (roadmap: `1f69716..9600982`) | выполнено | `82e88ee` companies под перевёрнутым сторожем, `af776ed` ручки под гейтом модуля, `f544bfb` сторож требует гейт у переведённых аппок, `afd07a2` документы блока I |
| I.2. Хвосты блока I и поддомены | [2026-09-22-block-i2-spec.md](2026-09-22-block-i2-spec.md), [2026-09-22-block-i2.md](2026-09-22-block-i2.md) (roadmap: `f2d5077..2c747dc`, 25 коммитов) | выполнено | `d27837c` поле `subdomain`, `f75c0ad` псевдоним в реестре/API/команде, `80ea6c4` членство из админки выдаёт базовую роль, `87d66a0` сессия переезжает на поддомен без второго входа |
| J. Документы | [2026-09-23-block-j-docs.md](2026-09-23-block-j-docs.md) | выполнено (задачи 1–5 закоммичены `9094596`…`a444667`; задача 6 — этот документ) | `8dd5c18` план блока J, `9094596`/`bbd444a` roadmap, `3b593bd`/`80bbccb` design.md, `1f69716`… |

Оговорка честности: для блоков B, C, D, E, F, G, H в roadmap нет явного
диапазона хэшей (в отличие от I и I.2) — коммиты выше найдены точечно по
`git log --oneline --grep`/`-- <файл>` и подтверждают, что блок состоялся, а
не служат исчерпывающим списком; исчерпывающий список — в плане блока по
ссылке слева, где он есть.

## 4. Прогоны — числа дословно

⚠️ **Прогон идёт по рабочему дереву с чужой незакоммиченной правкой**
`backend/htqweb/settings/base.py` (`TIME_ZONE = "UTC"` → `"Asia/Almaty"`) — она
не часть рефакторинга структуры группы, её не трогали и не откатывали (по
прямому указанию задачи). Как показано ниже, ровно эта правка объясняет 4 из
12 упавших тестов полного прогона — они НЕ входят в `backend/ci-known-failures.txt`
и НЕ являются дефектом рефакторинга.

### 4.1 Backend — pytest (форграунд, по частям; одна сессия за раз)

Полный прогон делился на части по аппкам (инструкция брифа) — единой команды
`pytest -q` на весь backend не выполнялось; сумма времени частей — **55.6
минуты**, что соответствует заявленным в CLAUDE.md «~55 минут» полного прогона.

| Часть | Команда | Результат (дословно) |
|---|---|---|
| `apps/access` | `pytest -q apps/access` | `370 passed in 441.56s (0:07:21)` |
| `apps/companies` | `pytest -q apps/companies` | `236 passed in 736.63s (0:12:16)` (ушёл в фон по таймауту инструмента 600 с, дождался завершения, параллельно ничего не запускал) |
| `apps/hr` (1/3, 20 файлов a–i) | `pytest -q apps/hr/tests/test_admin_position.py … test_identity_decide.py` | `2 failed, 428 passed in 380.85s (0:06:20)` |
| `apps/hr` (2/3, 20 файлов i–o) | `pytest -q apps/hr/tests/test_identity_fields.py … test_org_employee_relations_api.py` | `329 passed in 271.33s (0:04:31)` |
| `apps/hr` (3/3, 19 файлов p–v) | `pytest -q apps/hr/tests/test_participant_service.py … test_vacation_schedule.py` | `421 passed in 231.90s (0:03:51)` |
| `apps/tasks` | `pytest -q apps/tasks` | `3 failed, 714 passed in 432.52s (0:07:12)` |
| `apps/contracts apps/signoff` | `pytest -q apps/contracts apps/signoff` | `6 failed, 435 passed, 1 skipped in 30.21s` |
| `apps/users apps/core apps/cms apps/media_files` | `pytest -q …` | `1745 passed in 451.84s (0:07:31)` |
| `apps/mail apps/messenger apps/approvals apps/conference` | `pytest -q …` | `1 failed, 1006 passed in 316.76s (0:05:16)` |
| `htqweb` | `pytest -q htqweb` | `68 passed in 40.35s` |

**Итого:** 5765 тестов (370+236+428+329+421+714+435+1745+1006+68=5752 прошли
+ 12 упали + 1 пропущен = 5765), 12 упали, 1 пропущен.

**8 падений — ровно те, что в `backend/ci-known-failures.txt` (поимённо, все
найдены):**
- `apps/signoff/tests/test_engine.py::test_quorum_any_closes_the_stage_on_the_first_approval`
- `apps/signoff/tests/test_processes_api.py::test_quorum_any_clears_the_inbox_of_the_other_approver`
- `apps/signoff/tests/test_branching.py::test_inactive_approver_in_an_unrelated_branch_does_not_block`
- `apps/signoff/tests/test_processes_api.py::test_a_skipped_approver_cannot_reopen_a_finished_process`
- `apps/signoff/tests/test_processes_api.py::test_returning_a_running_process_for_rework_is_409`
- `apps/contracts/tests/test_accountable_funds_requests_api.py::test_approved_advance_reports_are_computed_and_close_the_request`
- `apps/hr/tests/test_employees_api.py::test_create_employee_with_card_t2_writes_card`
- `apps/hr/tests/test_employees_api.py::test_update_employee_with_card_t2_applies_both`

**4 падения ДОПОЛНИТЕЛЬНО к списку — проверены и объяснены правкой TIME_ZONE,
не дефект рефакторинга:**
- `apps/tasks/tests/test_interface_conference.py::test_user_events_include_invitations_and_own`
- `apps/tasks/tests/test_interface_conference.py::test_admin_sees_every_conference_of_the_day`
- `apps/tasks/tests/test_interface_conference.py::test_events_of_other_days_are_out_of_range`
- `apps/approvals/tests/test_stats_api.py::test_heatmap_returns_per_day_rows`

Механизм (проверен чтением кода): все четыре теста строят границы суток через
`timezone.localdate()` (или сохраняют `date` через него — `apps/approvals/
services/stats_rollup.py:46`: `day = timezone.localdate(instance.finalized_at)`),
а сравнивают/фильтруют с UTC-моментами или с `timezone.now().date()`
(`apps/approvals/views.py:734`) — датой, взятой из UTC-значения БЕЗ перевода в
локальный пояс. Пока `TIME_ZONE = "UTC"`, `localdate()` и `.date()` от
`timezone.now()` совпадают всегда. С `TIME_ZONE = "Asia/Almaty"` (UTC+6) они
расходятся на несколько часов в сутки (когда UTC-время ≥ 18:00, алматинская
дата уже следующий день) — ровно в это время суток и шёл прогон (в логе
упавшего теста видно `finalized_at`/`end_at` с `21:23:54 UTC`), поэтому окно
дня, посчитанное по алматинской дате, не включает событие/факт, записанный
по UTC-дате. Ни один из четырёх тестов не упоминается в `ci-known-failures.txt`
и ни один не относится к коду блоков A–I.2 (`apps.tasks` и `apps.approvals` —
интерфейс конференций и статистика согласований формы, не структура группы).
С `TIME_ZONE = "UTC"` (состояние до чужой правки) все четыре, по прочитанному
коду, обязаны проходить — отдельно не перепроверялось откатом правки
(инструкция задачи запрещает трогать этот файл).

### 4.2 Frontend

```
cd frontend && npx vitest run src
```
`Test Files  2 failed | 86 passed (88)`
`Tests  8 failed | 786 passed (794)`
Упавшие — ровно ожидаемые 8: `CardT2SectionDialog` ×4
(`заполняет «Финансы» у сотрудника БЕЗ карточки`, `нормализует запятую в сумме
к точке`, `не отправляет запрос при нечисловой сумме…`, `закрывается после
успешного сохранения`) и `EmployeeFormDialog — секции Т-2` ×4 (`делает поля
read-only при view без edit`, `не отправляет запрос при нечисловом окладе`,
`создание уходит одним POST с вложенным card_t2`, `403 "Missing permission:
hr.card.<section>.edit" разворачивает секцию…`).

```
npx tsc --noEmit -p tsconfig.app.json 2>&1 | grep -c "error TS"
```
`148` — ровно ожидаемое число (roadmap §9.1, P1).

### 4.3 `makemigrations --check --dry-run`

С окружением dev-БД (`DJANGO_SETTINGS_MODULE=htqweb.settings.dev`,
`DB_HOST=localhost DB_PORT=55432 DB_NAME=htqweb DB_USER=htqweb
DB_PASSWORD=change-me JWT_SECRET=dev`):

```
System check identified some issues:
WARNINGS:
mail.EmailAccount.mailbox: (fields.W342) Setting unique=True on a ForeignKey has the same effect as using a OneToOneField.
mail.EmailAccount.oauth_token: (fields.W342) Setting unique=True on a ForeignKey has the same effect as using a OneToOneField.
No changes detected
```
«No changes detected» — модели и миграции совпадают, включая миграции блоков
A–I.2. Два предупреждения `W342` — про `apps.mail`, вне зоны рефакторинга
структуры группы, не влияют на «No changes detected».

## 5. Стенд (dev-БД `:55432`, только чтение) — что увидено

Контейнер `htqweb-local-db-1` уже был поднят и здоров (`docker compose -f
docker-compose.test-local.yml ps db` → `Up …, healthy`) — поднимать заново не
понадобилось. Ниже — только чтение через `manage.py shell`/`use_company`,
записей не производилось.

**Реестр компаний** (`Company.objects.order_by('slug')`):

| slug | subdomain | kind | parent | status |
|---|---|---|---|---|
| `hi-tech-group` | `group` | `holding` | — | `active` |
| `hi-tech-qazaqstan` | `htq` | `construction` | `hi-tech-group` | `active` |
| `hi-tech-systems` | `hts` | `it` | `hi-tech-group` | `active` |
| `kazakhstan-engineering-group` | `keg` | `service` | `hi-tech-group` | `active` |

Ровно холдинг + три ДО, вид и дерево владения совпадают с оргструктурой
roadmap §1 (строительная/IT/сервисная), псевдонимы соответствуют
`htq`/`hts`/`keg`/`group` из блока I.2.

**По каждой компании** (`use_company(slug)`, только чтение):

| slug | дирекций (`UnitType.DIRECTORATE`) | «Участник (ОСУ)» (`is_system`) | `LevelThreshold` строк |
|---|---|---|---|
| `hi-tech-group` | 3 | есть | 4 |
| `hi-tech-qazaqstan` | 0 | нет | 4 |
| `hi-tech-systems` | 0 | нет | 4 |
| `kazakhstan-engineering-group` | 0 | нет | 4 |

Три дирекции и ОСУ — только у холдинга, как в оргструктуре документа; пороги
N-1…N-4 засеяны во всех четырёх схемах (сид блока D — миграция `hr/0024`).

**Права** (`apps.access` — НЕ тенантная аппка, `TENANT_APPS = (hr, tasks,
contracts, signoff)`, поэтому `PositionRole`/`RoleAssignment`/`Role` живут в
`public` одной таблицей на всю платформу, а не по схемам компаний — при
чтении через `use_company()` число не меняется от компании к компании, это
ожидаемо, не баг сверки):

- `PositionRole.objects.count()` → **25**
- `RoleAssignment.objects.count()` → **24**
- `Role.objects.count()` → **7**

Числа **дословно совпадают** с числами репетиции блока I, §3 roadmap («25
`PositionRole`, 24 `RoleAssignment`») — то есть стенд, на котором проверялся
блок I.2, и стенд, на котором сейчас снят слепок, — одно и то же состояние
(демо на 4 компании / 25 должностей / 24 членства из отчёта задачи 11 блока I).

Сравнение с оргструктурой roadmap §1 — совпадает по всем проверенным пунктам:
вид и дерево владения компаний, три дирекции строго в холдинге, ОСУ строго в
холдинге, пороги уровней в каждой схеме.

## 6. Что не выполнено — и чьё это

### 6.1 Зона второго разработчика (roadmap §6) — не проверяется по существу

`apps/contracts/**`, `apps/signoff/**`, `frontend/src/pages/{contracts,signoff}/**`
— чужая зона (Global Constraints блока J), проверено только косвенно: 435
тестов прошли, 6 упали ровно по списку известных падений (§4.1). Открытые
пункты по roadmap §6, не проверявшиеся здесь по существу: гейт
`api_view(module="contracts"/"signoff", level=…)` (сейчас обе аппки — в
`_OUT_OF_SCOPE_APPS` сторожа `test_gate.py`, подтверждено чтением файла, §2
строка 14); переход `contracts` с `hr.interface.user_has_permission` на узлы
`contracts.*` (§6.6); строки матрицы 11–15 (финансовые); читатели
`holding.contracts_*`/`holding.signoff_*`.

### 6.2 Вопросы руководству (roadmap §8) — без изменений

Пять вопросов остаются открытыми, ответы не проверяются кодом (это вопросы к
исходным документам, не к платформе): наименование УК (Hi-Tech Management vs
Hi-Tech Group LTD), канонический справочник должностей (три расхождения
названий), незаполненная оргструктура HTQ (N-4, «Менеджеры —», «Всего —»),
инициатор п.6 матрицы полномочий, HR ДО (вариант C-1). Плюс отдельно —
переименование «Системного администратора» и просьба о нескольких уровнях
администраторов сайта (roadmap §8, отдельные абзацы).

### 6.3 Сознательно оставленное (roadmap §9) — подтверждено, без изменений

Архив «только чтение» не выполнен (архив = 404 на весь трафик компании,
подтверждено чтением `htqweb/middleware/company_context.py`, соответствует
`multi-company-tenancy-followups.md` п.4); банкротство с переносом
активов/людей/договоров; автоматический бэкфилл внешней иерархии по
оргструктуре; границы I.2 (§9.1–9.2, включая P1 базу tsc=148 — подтверждено
в §4.2).

### 6.4 Новые расхождения, найденные этой сверкой

Пять расхождений, переданных этой задаче для перепроверки. Каждое
перепроверено самостоятельно; оценка важности — моя.

**1. Бизнес-метрики tenant-аппок не экспортируются — подтверждено, важность высокая.**
`backend/apps/core/metrics.py::_metric_modules()` (строки 103–110) пропускает
`metrics.py` всех четырёх tenant-аппок (`hr`, `tasks`, `contracts`, `signoff`)
через `if config.label in tenant_apps: … continue` с `logger.info("… пропущена
до подпроекта 3")`. Подтверждено число: `_BLOCKED_ON_TENANT_FANOUT`
(`apps/core/tests/test_metrics_are_observed.py:113-132`) перечисляет ровно
**16** метрик (`contracts_accountable_funds_outstanding`, `…_agreements`,
`…_awaiting_accounting`, `…_awaiting_accounting_amount`,
`…_budget_lines_overspent`, `contracts_signoff_desync`, `daily_reports_today`,
`hr_active_without_account`, `hr_employees`, `hr_terminated_still_active`,
`projects_active`, `signoff_pending_stale`, `signoff_processes`,
`signoff_routes_without_approvers`, `tasks`, `tasks_overdue`), и ещё 2 из
`_CONDITIONAL` относятся к tenant-аппкам (`daily_report_staleness_days` —
`tasks`, `signoff_oldest_pending_seconds` — `signoff`; два других элемента
`_CONDITIONAL` — `mail`/`messenger`, не тенантные, не в счёт). Подтверждено
число правил алертинга: ровно **6** правил в `infra/logging/grafana-provisioning/
alerting/rules.yml` читают эти метрики и стоят с `noDataState: OK` — `htqweb-
contracts-signoff-desync`, `htqweb-contracts-budget-lines-overspent` (обе на
метрики `contracts_*`), одно на `hr_terminated_still_active`, одно на
`signoff_routes_without_approvers`, `htqweb-contracts-awaiting-accounting`,
`htqweb-signoff-pending-stale` — все шесть никогда не сработают, оставаясь
«зелёными» вечно. `htqweb-business-metrics-stale` (`absent(htqweb_service_enabled)`)
и `test_metrics_are_observed.py` этого действительно не ловят — они проверяют
«метрика посчитана → она на дашборде», а не «метрика ДОЛЖНА считаться». Пункт
без хозяина: `docs/multi-company-tenancy-followups.md` п.3 подтверждает
(«Пункт ждёт хозяина»), docstring `apps/core/metrics.py:~30` и
текст `logger.info` («до подпроекта 3») — устаревшая, но пока верная
формулировка (подпроект 3 закрыт для `CompanyModule`, но НЕ для веера сбора
метрик — это явно названо в `followups.md` п.3, тоже перепроверено, см. ниже).
**Важность высокая**: это тихий отказ алертинга по деньгам и просроченным
задачам, а не просто пустой дашборд.

**2. `backend/apps/tasks/views.py` — докстринг `is_elevated` vs гейт `tasks:admin` — подтверждено частично, важность низкая.**
Прочитан весь докстринг `_deny_unless_holding` (строки 2313–2330) и
`holding_projects` (2347–2380). Гейт на ручке `holding_projects` — реально
`@api_view(methods=("GET",), module="tasks", level="admin")` (строка 2347), и
собственный докстринг `holding_projects` (2352–2364) ПРАВИЛЬНО называет
`module="tasks", level="admin"` и объясняет, почему `is_elevated` недостаточен.
Упоминание `is_elevated` на строке 2316 — внутри докстринга СОСЕДНЕЙ функции
`_deny_unless_holding` (гейта по виду компании, не по уровню модуля) и
используется как **гипотетический контрпример** («обычная проверка домена
… знает только флаги вызывающего»), а не как описание фактического гейта
ручки. Формально расхождение есть — при чтении ИЗОЛИРОВАННО от
`holding_projects` абзац можно принять за описание текущего гейта; в
контексте файла (два докстринга рядом, второй явно всё объясняет) путаницы
на практике не возникает. **Важность низкая** — это не искажающая
документация, а неудачно расположенный контрпример; правка не требуется
срочно, разве что для ясности при будущем рефакторинге этого файла.

**3. `docker-compose.yml:~374` — комментарий про `RUN_MIGRATIONS=1` устарел — подтверждено, важность средняя.**
Строка 374 (`# migrate + идемпотентный сид админа (admin/admin12345) — ТОЛЬКО
backend-web (RUN_MIGRATIONS=1)`) противоречит объявлению 12 строк ниже (386):
`RUN_BOOTSTRAP: ${RUN_BOOTSTRAP:-1}` с комментарием «collectstatic + бакеты
хранилища + сид админа … НЕ зависят от флага выше» (то есть не от
`RUN_MIGRATIONS`). Подтверждено `backend/docker-entrypoint.sh`: сид админа
идёт под `if [ "${RUN_BOOTSTRAP}" = "1" ]` (строка 51), а не под
`RUN_MIGRATIONS` (строка 36 — там только `migrate`). Комментарий строки 374 —
рудимент до разделения флагов, реальному коду не соответствует. **Важность
средняя**: чисто документирующий комментарий внутри кода, не влияет на
поведение, но вводит в заблуждение при выкатке (сид админа продолжит идти и
при `RUN_MIGRATIONS=0`, если `RUN_BOOTSTRAP` не выставлен отдельно, — читатель
комментария строки 374 этого не заподозрит).

**4. Roadmap §9.2 — сошлись, без изменений.** Список «сознательно оставлено»
блока I.2 (сторож гейтов, сторож колонки `permissions`, псевдоним компании без
ограничения БД и др.) перепроверен построчно при чтении §9 (см. §6.3 выше) —
расхождений с кодом не найдено, копировать не стал (roadmap уже содержит их).

**5. Мелкие неточности документов — три из пяти подтверждены, одна уже устранена, одна не оценивалась отдельно.**

- `docs/multi-company-tenancy-design.md:~8-10, ~140` («архивация — по плану
  подпроекта 1» вместо «доработка подпроекта 1, 29.08») — **при повторной
  проверке текста НЕ ПОДТВЕРЖДЕНО**: обе указанные строки уже содержат точную
  дату (`«создание, архив и восстановление компании есть (company_create/
  company_archive/company_restore — подпроект 1, 28–29.08.2026»)`, строка 143;
  шапка на строке 7 — «Состояние на 23.09.2026» с явными ссылками на планы и
  даты). Похоже, это было устранено более ранним раундом правок задачи 2
  блока J (коммиты `3b593bd`, `80bbccb` — «дизайн мультикомпанейности —
  состояние после блоков A–I.2», «раунд правок 1»), которые эта сверка не
  переиграла заново, а прочитала уже готовый результат. Отмечаю как
  **закрыто**, не переоткрываю.
- `docs/plans/2026-08-29-stage2-access-and-roles-spec.md:~873` («остаток гейта
  назван только contracts/signoff») — **подтверждено**: строка 873
  по-прежнему говорит «`contracts`/`signoff` — без гейта, их навешивает
  второй разработчик», а сторож `apps/access/tests/test_gate.py`
  (докстринг `test_gate_is_not_hung_on_apps_without_a_translation_plan`)
  прямо перечисляет ещё **7** аппок без запланированного гейта:
  `approvals`, `cms`, `conference`, `core`, `mail`, `media_files`,
  `messenger`. Текст спеки создаёт впечатление, что после contracts/signoff
  гейт — вопрос времени только для этих двух; на деле непокрытых доменов
  девять. **Важность средняя** — вводит в заблуждение о размере оставшейся
  работы по гейту, но не искажает статус самого блока I (который гейтует
  ровно пять названных аппок, как и заявлено).
- `docs/multi-company-tenancy-followups.md:~95-107` (последствия п.3 не
  названы) — **подтверждено**: раздел объясняет механизм (`_metric_modules()`
  пропускает `TENANT_APPS`, `logger.info` вместо `fallback`) и то, что
  «метрика домена … просто не считается», но НЕ называет конкретное
  следствие — что 6 правил алертинга (см. находку №1 выше) при этом стоят с
  `noDataState: OK` и никогда не сработают. Это более серьёзное
  последствие, чем «метрика не считается» — молчание алертов, а не пустая
  панель. **Важность средняя-высокая** — сам факт назван, но не назван его
  вес.
- `…:~132-133` (ссылка на roadmap §10 про подпроект 4 неточна) —
  **подтверждено**: `followups.md` строка 132 пишет «подпроект 4 не выполнен
  (roadmap §10)», но roadmap §10 («Итог рефакторинга») не формулирует это
  утверждение явно — там сказано лишь «сознательно оставлено — архив
  компании «только чтение» …» со ссылкой на §9, а не на §10 как источник
  утверждения «подпроект 4 не выполнен». Точнее было бы сослаться на
  `multi-company-tenancy-design.md` §4 (таблица подпроектов, статус
  подпроекта 4 — «частично») — там это сказано прямо. **Важность низкая** —
  ссылка ведёт в правильный документ (roadmap), просто не на тот раздел,
  который формулирует именно это утверждение.
- `…:~198-200` (`Header.tsx` — рендер, вызов `switchCompany` —
  `CompanySwitcher.tsx:~33`) — **подтверждено**: `frontend/src/components/
  Header.tsx:264,298` только рендерит `<CompanySwitcher enabled={isLoggedIn} />`;
  сам вызов `switchCompany(target)` — внутри `frontend/src/components/
  companies/CompanySwitcher.tsx:33` (`if (target) switchCompany(target);`).
  `followups.md` п.6 приписывает вызов файлу и строкам, где на деле только
  рендер компонента. **Важность низкая** — путь к функции всё равно
  выводим (компонент назван верно), но точная строка вызова указана неверно.

### 6.5 Ветка `sanzhar` разошлась с `origin/sanzhar` — условие выкатки

`git rev-list --left-right --count sanzhar...origin/sanzhar` → **`187` / `9`**
(187 коммитов только в локальной `sanzhar`, 9 — только в `origin/sanzhar`).
Девять — это в точности то, что называет roadmap §9.3: слияния `main` в
удалённой ветке (PR #29, #30, 10–14.09.2026: парсер cashflow в `contracts`,
правки аватаров в кадрах). **Перед пушем эти 9 коммитов необходимо влить** —
без слияния пуш локальной ветки создаст конфликт или молча похоронит эти
изменения второго разработчика, если пушить force (запрещено политикой
репозитория без явного запроса пользователя). Это условие выкатки, не
дефект рефакторинга.

### 6.6 Чужая незакоммиченная правка в рабочем дереве — не дефект рефакторинга

`backend/htqweb/settings/base.py` (`TIME_ZONE = "UTC"` → `"Asia/Almaty"`) и
`.gitignore` (добавлены игноры для `.zed/`, `.github/copilot-instructions.md`,
`.cursor/mcp.json`, `.codebase-memory/`) — не часть этого рефакторинга, не
тронуты и не застейджены. Как показано в §4.1, TIME_ZONE напрямую объясняет 4
дополнительных падения полного прогона (смешение `timezone.localdate()` и
UTC-момента в `apps.tasks`/`apps.approvals` — доменах вне блоков A–I.2). Эта
правка должна разрешиться отдельно от блока J (её коммитить или откатывать —
решение пользователя, не этой задачи).

## 7. Что НЕ проверялось

- **Браузер** — ни один экран (`CompanyPicker`, `CompanySwitcher`,
  `PositionSubstitutions`, `ExternalHierarchy`, экран «Сводка группы») не
  открывался в браузере/Playwright; проверка — только по коду компонентов и
  их unit/vitest-тестам.
- **nginx / нарезка поддоменов на живом хосте** — `infra/nginx/default.conf`
  прочитан (существование регулярки поддомена, отсечение `www`/IP), но ни
  один реальный HTTP-запрос через nginx с реальным поддоменом не выполнялся;
  чеклист `docs/deploy/subdomains-runbook.md` не прогонялся.
  ⚠️ Обновление TLS-сертификата (`SAN` под `*.htq.group`), Cloudflare (режим
  SSL «Full (strict)», DNS `*`) — не проверялись вовсе, это внешняя
  инфраструктура вне репозитория.
- **Прод/боевые данные** — `tenancy_bootstrap`, `migrate_companies`,
  `access_backfill_positions`/`access_backfill_basic` на боевой БД не
  запускались и не проверялись; вся проверка стенда (§5) — только dev-БД
  `:55432`, только чтение.
- **Конференция (SFU/WebTransport)** — `apps.conference`, запись, история,
  подписанные ссылки на запись не проверялись по существу этой сверкой (её
  тесты прошли в составе группы `apps/mail apps/messenger apps/approvals
  apps/conference`, §4.1, но функциональность вне зоны структуры группы).
- **Grafana/Prometheus живьём** — существование правил и дашбордов
  подтверждено чтением файлов и тестом `test_metrics_are_observed.py`; сам
  Grafana не поднимался, `./scripts/check-monitoring-config.sh` не
  запускался.
- **contracts/signoff по существу** — см. §6.1: подтверждено только
  прохождение тестов (за вычетом известных 6 падений) и наличие/отсутствие
  гейта; функциональная корректность финансовых расчётов, маршрутов
  согласования и экранов — зона второго разработчика, не проверялась.
- **Полный список исторических коммитов по блокам B–H** — §3 даёт
  представительные коммиты, не исчерпывающий список (см. оговорку в конце §3).

---

**Проверка ссылок** — общей командой из «Карты файлов» плана блока J
(`docs/plans/2026-09-23-block-j-docs.md`), применённой к этому документу и к
roadmap. Первая попытка держать саму команду проверки внутри черновика этого
документа дала ложное срабатывание: команда ищет запрещённый путь к
служебному каталогу подстрокой прямо в тексте, а её же исходный код (внутри
неё самой) эту подстроку неизбежно содержит — команда находила сама себя.
Тот же эффект даёт прогон той же команды по самому плану блока J
(`2026-09-23-block-j-docs.md`), где команда тоже приведена целиком, — там она
находит несколько срабатываний в собственном тексте, а не в реальных
ссылках документа. Убрав литеральный код команды из этого документа
(оставлена только ссылка на неё в «Карте файлов»), прогон обеих проверок —
на файлы и на запрещённый путь — дал чистый результат на обоих документах.
Битых ссылок на файлы и разделы не найдено. Итог — **ссылки: ok**.

Ссылка из roadmap §10 на этот документ (`[2026-09-23-group-structure-
verification.md](2026-09-23-group-structure-verification.md)`) теперь
разрешается — файл существует. Пояснение рядом со ссылкой в roadmap
(«документ появится в ходе блока J; на момент этой правки ссылка ещё не
разрешается — ожидаемо») стало неточным ПОСЛЕ появления этого файла, но
`roadmap.md` не входит в файлы задачи 6 (только создание этого документа) —
правка предложения оставлена задаче, которая правит roadmap, или отдельным
мелким коммитом по решению пользователя; здесь фиксирую как факт, не
исправляю сама.

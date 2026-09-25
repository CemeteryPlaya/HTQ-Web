# Структура группы компаний — дорожная карта доводки

**Дата:** 2026-09-14
**Ветка:** `sanzhar`
**Статус на 23.09.2026:** блоки A–I, I.2 выполнены; J —
[план](2026-09-23-block-j-docs.md), итог — [§10](#10-итог-рефакторинга-23092026); выкатка —
§7 и [чеклист поддоменов](../deploy/subdomains-runbook.md).
**Основание:** документы руководства от 10.09.2026 — «Обновлённый проект
оргструктуры Группы» (комментарии К. Садыева) и «HR-FRM-004…006: Матрица
полномочий, RACI, Матрица замещения».
**Опирается на:** [multi-company-tenancy-design.md](../multi-company-tenancy-design.md)
(подпроект 1, выполнен), [stage2-spec](2026-08-29-stage2-access-and-roles-spec.md)
(стадия 2, выполнена), [followups](../multi-company-tenancy-followups.md).

Документ фиксирует **что ещё не сходится** между построенной платформой и
утверждённой структурой группы, **кто что делает** (два разработчика) и **в
каком порядке** это выкатывается, не ломая работающие модули.

---

## 1. Что утвердило руководство

**Оргструктура (стр. 1–5).** Головная компания ТОО «Hi-Tech Group LTD» —
владение долями и стратегический контроль. Над ГД группы — Общее собрание
участников (ОСУ). Три дирекции головной компании: по финансам и экономике,
проектно-техническая, по операционной деятельности. Три дочерних общества
(ДО), все напрямую под холдингом: ТОО «HI-TECH QAZAQSTAN» (строительная),
ТОО «HI-TECH SYSTEMS» (IT), ТОО «KAZAKHSTAN ENGINEERING GROUP» (сервисная).
Уровни N-1…N-4 (в холдинге N-3 пропущен). У ДО руководитель — «Директор», не
«Генеральный директор» (правка Садыева). Штатные единицы («1 шт. ед.»).
Пунктирные горизонтальные связи между менеджерами дирекций.

**Матрицы (HR-FRM-004…006).** Полномочия по 15 решениям с ролями
И/С/У для колонок ОСУ, ГД УК, CFO, Технический директор, Операционный
директор, Руководитель блока; RACI по 14 процессам, включая пару УК ↔ ДО;
замещение шести ключевых должностей (основной/резервный, порядок оформления).

⚠️ Документы **внутренне расходятся** — см. §8, вопросы руководству.

## 2. Зоны ответственности

| Зона | Кто | Что входит |
|---|---|---|
| **Моя** | автор ветки | `apps/{companies,access,hr,users,core,tasks,…}`, `htqweb/*`, инфра, фронт (кроме экранов contracts/signoff), `docs/**` |
| **Другой разработчик** | contracts/signoff | `apps/contracts/**`, `apps/signoff/**`, `frontend/src/pages/{contracts,signoff}`, `src/api/{contracts,signoff}.ts` |

Правило то же, что в стадии 2: **файловые множества не пересекаются**. Стык —
только через `apps.<x>.interface` и настоящий документ (§6). Находку в чужой
зоне не чиню, а формулирую как требование в §6.

## 3. Режим перехода: одна компания «Hi-Tech Qazaqstan»

На время доводки (блоки A–I) модули **contracts** и **signoff** обязаны
работать штатно — на них идут боевые проверки обновлений в продакшене.
Поэтому:

1. **В реестре одна действующая компания** — slug `hi-tech-qazaqstan`, имя
   «Hi-Tech Qazaqstan». Все текущие боевые данные `hr_*`, `tasks_*`,
   `contracts_*`, `signoff_*` принадлежат ей (после `tenancy_bootstrap` — в
   схеме `co_hi_tech_qazaqstan`; до него — в `public`, и это тоже штатно:
   `CompanyContextMiddleware` без заголовка оставляет `search_path=public`).
2. **Остальные три компании (холдинг, HTS, KEG) на бою НЕ заводятся**, пока
   не закрыты блоки B–D: пустая схема без уровней и без внешней иерархии
   ничего не даёт, а `rebuild_holding_views` при каждом заведении — лишний
   риск. Заведение — отдельный шаг выкатки (§7, шаг 5).
3. **Ни один блок не переносит, не переименовывает и не удаляет таблицы
   tenant-аппок.** Изменения схем `hr` — только expand-миграциями
   (`is_manager`, `external_hierarchy`, `LevelThreshold`-сид, `Substitution`);
   contract-фаза — не раньше, чем другой разработчик подтвердит, что
   signoff/contracts не читают удаляемое.
4. **Единственную действующую компанию нельзя архивировать** — без
   действующей компании платформе негде писать: `contracts`/`signoff` живут
   только в схемах компаний. Гейт ставится в блоке A (`LastActiveCompany` →
   409) и действует и для API, и для CLI.
5. **Перед и после каждой боевой выкатки** снимается слепок
   `manage.py tenancy_status` (блок A, задача 1): где лежат таблицы
   tenant-аппок, сколько строк в `contracts_*`/`signoff_*`, какие строки в
   реестре. Расхождение слепков — стоп-сигнал.
6. Slug `hi-tech-qazaqstan` не переименовывается никогда (он — имя схемы и
   значение claim `company`; поддомен после блока I.2 — псевдоним `htq`,
   `companies/0006_seed_company_subdomains.py`); `kind` у неё выставляется правкой через API блока A, когда
   появится холдинг.

## 4. Что построено и где расходится (сводка)

| Тема | Есть | Расхождение |
|---|---|---|
| Реестр компаний, схемы, `search_path`, claim `company` | ✅ реестр (подпроект 1), HTTP-API и экраны (блок A), короткие адреса `htq/hts/keg/group`, экран выбора компании на голом домене (блок I.2) | архив «только чтение» — **закрыт** ([спека](2026-09-25-archive-read-only-spec.md), [план](2026-09-25-archive-read-only.md)); банкротство с преемником — нет |
| Поддомены компаний | ✅ `Company.subdomain`, `companies.interface.resolve_host_label`, `CompanyPicker` | выкатка — одним окном с блоком I, чеклист |
| Уровни N-1…N-4 | ✅ `LevelThreshold` + `UnitType.DIRECTORATE` | пороги сеются при заведении схемы компании (миграция `hr/0024`); на боевой БД no-op |
| Внешняя иерархия (правило 4) | ✅ | поля `is_manager`/`external_hierarchy` есть, `subordinate_companies` считается по ним; отметку «руководящая» ставит кадровик вручную в карточке должности — автоматического бэкфилла по оргструктуре нет |
| Права холдинга в ДО (блок C) | ✅ `serves_subsidiaries` + `apps/access/services/inheritance.py`, `inherited_from` в `/me` | членство (`CompanyMembership`) в ДО остаётся отдельным явным шагом — без него признак не даёт ничего (`company_grant --serving`, разрыв виден на дашборде); данные по внешней иерархии по-прежнему не режутся, только наследуются права (см. строку выше) |
| Роли «функция × глубина» | ✅ **единственная** модель прав (блок I): гейт `api_view(module=, level=)` на каждой ручке одиннадцати аппок — пяти блока I (`hr/users/companies/access/tasks`) и шести блока L (`media_files` → модуль `media`, `conference/messenger/mail/cms/approvals`) — под перевёрнутым сторожем (`apps/access/tests/test_gate.py`), кроме реестра самообслуживания (`apps/access/self_service.py`; платформенные операции `companies` — только суперпользователь, в реестре как `scoped`); проверки тоньше уровня — по узлу (`apps/hr/rbac.py`); уровни `junior…lead` перенесены в системные роли `hr-*` (`access/0005`, `0008`), перенос данных — `access_backfill_positions`/`access_backfill_basic` | `contracts`/`signoff` пока без гейта — вешают владельцы (§6.2/6.3); `Position.permissions` — мёртвая колонка, жива только ради `hr.interface.user_has_permission` для `contracts` (§6.6); гейты требуют контекста компании → выкатка только вместе с поддоменами (§7) |
| Сводки холдинга | ✅ читаются — экран «Сводка группы» (`/holding`), ручки `hr` и `tasks` | финансы (`contracts`) и согласования (`signoff`) остаются плитками-заглушками до читателей второго разработчика |
| Матрица полномочий | ✅ десять кадровых предметов согласования (`hr.*`) с фактами для условий, блок G | финансовые строки 11–15 — зона contracts; относительные согласующие («руководитель блока», ОСУ) и кросс-компанейские этапы — зона signoff (§6.2), у меня для них готовы `participant_position()`, `manager_position_of`, `substitutes_for` |
| Замещение | ✅ `hr.Substitution` + `substitutes_for` | расхождение названия должностей в HR-FRM-006 и оргструктуре (§8.2); строка «Системный администратор → внутригрупповой ИТ-подрядчик» не выражается должностью |
| ОСУ / Участник | ✅ системная должность `Участник (ОСУ)` над ГД, `hr_participant`, `hr.participant_position()` | «N-0» реализован положением в дереве, не порогом (решение 1 плана F) |
| Демо-данные | ✅ `seed_group_demo` | `group_structures.py` (4 утверждённые структуры), `seed_group_demo` заводит холдинг и ДО, сеет структуры и учётки; с блока I `seed_hr_demo --company` раскладывает `Post.hr_level` в роли должностей (`access.interface.ensure_position_role`) — `Position.permissions` сид больше не пишет |

## 5. Блоки работ (моя зона)

Порядок — по зависимостям; A и D можно вести параллельно.

### A. Реестр компаний — из CLI в платформу (выполнено)
План: [2026-09-14-block-a-company-registry.md](2026-09-14-block-a-company-registry.md).
- `apps/companies/{urls,views,schemas}.py`, сервисы `lifecycle.py`,
  `module_service.py`, дополнение `membership_service.py`;
- `GET companies/v1/me` (мои компании) → фронт: `CompanySwitcher` в шапке
  на `switchCompany`; страница `/companies` — дерево группы, карточка,
  правка/архив/восстановление, модули, участники. **Создание компании
  остаётся за CLI** (`company_create`): миграции схемы ~1 мин не помещаются
  в `gunicorn --timeout 60`, а убитый посреди DDL воркер оставил бы
  «осиротевшую строку реестра»;
- `CompanyKind`: `+construction`, `+it` (expand; `regional` остаётся до
  contract-фазы);
- `manage.py tenancy_status` — слепок раскладки таблиц (§3, п.5);
- гейт `LastActiveCompany`;
- docs: `design.md §1/§5`, `API.md`, `STRUCTURE.md`, `CLAUDE.md`.

### B. Внешняя иерархия — снять заглушку (выполнено)
Ход работ и разбивка на задачи: [2026-09-15-block-b-external-hierarchy.md](2026-09-15-block-b-external-hierarchy.md).
`hr.Position.is_manager`/`external_hierarchy` появились (expand-миграция
`hr/0021`), `get_employee_brief` отдаёт оба ключа аддитивно →
`apps/access/services/hierarchy.py::_is_external_manager` заработал на
реальных данных без правок самого `apps.access`; поля редактируются в
`HRPositions.tsx`; `ExternalHierarchy.tsx` показывает дерево компаний (API
блока A) вместо списка слагов. Отметку «руководящая» по-прежнему ставит
кадровик вручную (см. §4) — фильтрацию данных по иерархии блок не делает
(см. [stage2-spec](2026-08-29-stage2-access-and-roles-spec.md) §7).

### C. Права холдинга в подчинённых компаниях (выполнено)
План и разбивка на задачи: [2026-09-15-block-c-holding-authority.md](2026-09-15-block-c-holding-authority.md).
Холдинг по документам — сервисный центр (финансы, кадры, закупки, ИТ для
всех ДО; у ДО нет ни бухгалтера, ни кадровика). Кросс-компанейский доступ у
8 из 12 должностей холдинга — норма, не исключение (спека §1.2 отражает
решение заказчика, см. правку ниже). Принят **вариант C-1**: роли должности
«домашней» компании действуют во всех компаниях ниже по дереву владения —
но по ОТДЕЛЬНОМУ признаку, не по `is_manager`/`external_hierarchy` блока B
(«начальник людей» и «работает на всю группу» — разные вопросы; в холдинге
обслуживают ДО именно 8 менеджеров, ни один из них сотрудниками ДО не
руководит).

- `hr.Position.serves_subsidiaries` (expand-миграция `hr/0022`) — признак на
  должности, отдельный от блока B; доходит до `apps.access` аддитивно через
  `hr.interface.get_employee_brief`. Карточка должности его правит, показывает
  предпросмотр (какие роли и в какие компании поедут) и предупреждает, что
  членство — отдельный, ещё не сделанный шаг; диалог ролей должности
  предупреждает, что добавленная роль тоже уедет в ДО.
- `apps/access/services/resolve.py::Resolution`/`resolve_for` — расчёт ролей
  на запрос стал одним вызовом вместо 35 (`/me` раньше пересчитывал их на
  каждый из 32 узлов-страниц); без этого шва наследование умножило бы 35 ещё
  и на переключения схемы.
- `apps/access/services/inheritance.py` — обход ВВЕРХ по `Company.parent`:
  действующий предок с обслуживающей должностью отдаёт её роли с областью
  `company`; предки не взаимоисключающи — роли всех обслуживающих предков
  складываются с собственными правами человека; архивный предок ничего не
  даёт, но обход идёт дальше вверх; цикл в дереве не вешает разрешение;
  недоступный `hr` у предка — пустое наследование через `fallback(expected=True)`,
  а не молчание.
- `/me` называет источник в `inherited_from` (отсортированный список слагов
  компаний-предков, а не одна строка — ровно потому, что предки не
  взаимоисключающи); `usePermissions().inheritedFrom`; `ExternalHierarchy.tsx`
  выводит поясняющую строку.
- `Company.show_external_holders` (миграция `companies/0004`) +
  `GET companies/<slug>/external-holders` — видимость держателей прав из
  компаний-предков управляется платформенным администратором (не ДО), по
  умолчанию включена; выдаёт ровно четыре поля (ФИО, домашняя компания,
  должность, модули с уровнями).
- **Членство осталось отдельным явным фактом** (решение заказчика 3) —
  признак сам по себе ничего не даёт, пока держателю не заведено
  `CompanyMembership` в ДО. Три вещи не дают об этом забыть:
  `company_grant --serving` (разово по всем держателям обслуживающих
  должностей предков), напоминание о разрыве, которое печатает
  `company_create` при заведении новой ДО, и метрика
  `htqweb_access_serving_holders_without_membership` с панелью на
  `htqweb-domains`.
- **Чего блок не делает** (см. план, §«Что блок C не делает»): не режет
  данные по внешней иерархии (только отображение, как и раньше), не заводит
  членство автоматически, не даёт ДО отказаться от самого доступа (только от
  его видимости).

### D. Уровни, дирекции, демо-данные (выполнено)
План: [2026-09-15-block-d-levels-directorates-demo.md](2026-09-15-block-d-levels-directorates-demo.md).

**Что сделано:**
- `hr/0023_alter_department_unit_type` (choices для `UnitType.DIRECTORATE`);
- `hr/0024_seed_level_thresholds` — сид `LevelThreshold` N-1…N-4 при `migrate_companies`, только в пустую таблицу схемы компании (на боевой БД no-op);
- `apps/hr/management/group_structures.py` — четыре утверждённые оргструктуры с документа 10.09.2026;
- `seed_hr_demo [--company SLUG]` — сеет структуру по виду компании; без флага — HTQ в контекстную схему;
- `seed_group_demo [--skip-tasks]` — единственный локальный способ увидеть группу: заводит холдинг, три ДО, сеет структуры, учётки, членства сотрудникам своих компаний. Членства обслуживающим должностям холдинга (блок C) появляются только после назначения ролей этим должностям — на свежем стенде их ноль, и команда об этом печатает. Наполняет задачи HTQ.

**Структуры по видам компаний:**
- **Холдинг** (hi-tech-group): 12 должностей — 3 дирекции по 3–4 шт. ед., остальное — штаб (финансы, кадры, закупки, ИТ);
- **HI-TECH QAZAQSTAN** (строительная): 4 должности — директор, РП, начальник участка, инженер ОТ и ТБ;
- **HI-TECH SYSTEMS** (IT): 4 должности — аналогичная подстановка;
- **KEG** (сервисная): 4 должности — то же.

Пунктирные связи как `ReportingRelation.functional`. Пустой блок на N-4 HTQ (вопрос руководству §8.3) не сеется.

### E. Замещение (HR-FRM-006) — (выполнено)
План: [2026-09-16-block-e-substitution.md](2026-09-16-block-e-substitution.md).

**Что сделано:**
- `hr.Substitution(position, substitute_position, kind=primary|reserve, basis, valid_from, valid_to, note)` (expand-миграция `hr/0025`) + сервис `substitution_service.py` (пересечения, валидация, история);
- `apps.hr.interface.substitutes_for(position_id, on_date) -> list[{position_id, kind, basis}]` — контракт для signoff (§6.1), закреплён тестом на точный набор ключей;
- HTTP: `GET/POST positions/{id}/substitutions`, `PATCH/DELETE substitutions/{id}` (чтение — JWT, запись — админ);
- `PositionSubstitutions.tsx` на карточке должности; матрица документа в демо-стенде холдинга (10 строк). Строка «Системный администратор → внутригрупповой ИТ-подрядчик» не сеется: замещающий — внешний подрядчик, а не должность, и команда печатает об этом предупреждение.

### F. ОСУ / «Участник» — (выполнено)
План: [2026-09-16-block-f-participant.md](2026-09-16-block-f-participant.md).

**Что сделано:**
- `hr.Position` системная должность «Участник (ОСУ)» (`is_system=True`, вес 0, подразделение `osu`) над генеральным директором холдинга;
- `apps.hr.services.participant_service.ensure_participant()` — заведение идемпотентно, заводит/проверяет статус, отказывает, если вес 0 занят;
- `apps.hr.interface.participant_position() -> {id, title, is_active} | None` — способ для соседей узнать id без хардкода названия;
- `manage.py hr_participant --company SLUG` — боевой путь (через API `is_system` не ставится); `seed_hr_demo` сеет ОСУ + связь с ГД.

Маршруты signoff ссылаются на ОСУ обычным `position_id`, движку ничего нового для этого случая не нужно.

### G. HR-субъекты согласования (строки 1–10 матрицы) — моя половина (выполнено)
План: [2026-09-16-block-g-hr-approval-subjects.md](2026-09-16-block-g-hr-approval-subjects.md).
Десять моделей в `hr` наследуют `signoff.Approvable` с
`SIGNOFF_SUBJECT_TYPE = "hr.<…>"`, регистрируются одной таблицей из
`HrConfig.ready()` (`apps/hr/approval_hooks.py`), отправляются одной ручкой
`POST /api/hr/v1/approvals/{subject_type}/{id}/submit` через
`apps.signoff.interface`. Движок не тронут: в чужой зоне изменена ровно одна
строка — `"registered_subjects"` в `__all__` его `interface.py`.

Десять типов по строкам матрицы: `hr.org_change` (1), `hr.staffing_position`
(2), `hr.policy` (3), `hr.job_description` (4), `hr.personnel_order` (5, 6,
7), `hr.bonus` (8), `hr.reprimand` (9), `hr.vacation_schedule` +
`hr.leave_request` + `hr.business_trip` (10 — заказчик развёл строку на три
предмета 16.09.2026). Ключи фактов каждого — §6.4.

Чего в блоке НЕТ намеренно: экранов заведения заявок; настройки самих
маршрутов (данные второго разработчика); применения утверждённой заявки к
дереву оргструктуры и проставления отсутствий в календаре после отпуска —
и то и другое остаётся ручной работой кадровика. Единственный
автоматический эффект утверждения во всём блоке — кадровый приказ пишет
`PersonnelHistory`; это закреплено тестом
`test_only_the_personnel_order_has_an_automatic_effect`.

### H. Сводки холдинга — читатели для `hr` и `tasks` (выполнено)
План: [2026-09-17-block-h-holding-readers.md](2026-09-17-block-h-holding-readers.md).

**Что сделано:**
- `managed=False`-модели `apps/hr/holding_models.py` (`HoldingEmployee`,
  `HoldingDepartment`, `HoldingPosition`, `HoldingStaffingPosition`) и
  `apps/tasks/holding_models.py` (`HoldingProject`, `HoldingSite`,
  `HoldingTask`, `HoldingDailyReport`) читают представления
  `holding.hr_*`/`holding.tasks_*` через свой менеджер: без
  `htqweb.tenancy.db.use_holding()` он поднимает `HoldingContextRequired` —
  `db_table` СОВПАДАЕТ с таблицей компании (иначе и быть не может,
  представление называется по таблице), и без сторожа вызов вне контекста
  тихо вернул бы данные одной компании за групповые;
- сводки — `apps/hr/services/holding_service.py::headcount_by_company()` и
  `apps/tasks/services/holding_service.py::projects_by_company()`, обе
  поднимают `HoldingViewsUnavailable`, когда представлений нет
  (`migrate_companies` временно их сносит и пересобирает);
- ручки `GET /api/hr/v1/holding/headcount` и `GET /api/tasks/v1/holding/projects`:
  503 на `HoldingViewsUnavailable`; доступ — обычная проверка своего домена
  (HR-доступ / `is_elevated` на момент блока H; с блока I — гейт модуля, см.
  CLAUDE.md «Сводное чтение холдинга») ПЛЮС отдельный гейт по виду компании — только
  поддомен компании вида «холдинг» (`apps.companies.interface.is_holding`,
  новый предикат), платформенный администратор проходит всегда, с любого
  другого поддомена — 403;
- экран «Сводка группы» (`/holding`) сводит обе ручки в таблицу по компаниям
  с итогами; бюджеты (`contracts`) и согласования (`signoff`) — пока плитки-
  заглушки с подписью «данные подключит второй разработчик»;
- `StaffingPosition` добавлен в `hr/holding.py::HOLDING_MODELS` («штат
  против факта» — иначе численность не с чем сравнивать) — появилось НОВОЕ
  представление `holding.hr_staffingposition`, поэтому выкатка блока требует
  отдельного `migrate_companies`. Миграции `hr/0036`, `hr/0037`, `tasks/0020`
  — все аддитивные (`CreateModel`/`AlterModelOptions` с `managed=False`),
  DDL не выполняют;
- побочная находка блока: `tenancy_bootstrap` и `tenancy_status` считали
  таблицы тенантных аппок по всем моделям, не пропуская `managed=False`, —
  новые читатели давали дубли, и второй проход боевого переноса
  (`ALTER TABLE … SET SCHEMA`) падал бы на них. Обе команды теперь пропускают
  `managed=False`; сторожа в их тестах проверяют и отсутствие дублей, и
  присутствие настоящих таблиц.

### I. Свернуть параллельный RBAC (спека §1.6) — (выполнено)
План блока — `docs/plans/2026-09-17-block-i-single-rbac.md` (коммиты
`1f69716`…`9600982`). Сделано:
- `api_view(module=, level=)` стоит на КАЖДОЙ ручке пяти аппок `hr/users/
  companies/access/tasks` (перевёрнутый сторож; `level=` всегда явный);
  исключения перечислены поимённо в реестре самообслуживания
  `apps/access/self_service.py` с причиной из закрытого списка `self` (ручка
  отдаёт строго данные вызывающего) | `open` (общий справочник, у которого
  не было и нет ни одной проверки — сужать не наше решение) | `scoped`
  (защищена своей, не ролевой проверкой — «свой отдел», «я согласующий»;
  платформенные операции `companies` — архив, восстановление, отзыв
  членства — только суперпользователь, в реестре как `scoped`);
  сторож `apps/access/tests/test_gate.py` требует гейт у всего, чего нет в
  реестре, и причину у всего, что в нём есть. Разрушающие ручки кадров,
  бывшие открытыми (закрытие вакансии, удаление отклика/записи времени/
  документа), — под `hr:admin` (сознательное исключение №3).
- Угадывание уровня по названию должности (`apps/hr/access.py::
  resolve_hr_access`) заменено ролями должности: четыре системные роли
  `hr-junior/middle/senior/lead` (`access/0005`, запреты на под-узлах —
  `0008`) собраны из старых пресетов `apps/hr/permissions.py` таблицей
  `apps/hr/legacy_roles.py::KEY_TO_NODE`; равенство «роль ⇔ старый пресет
  по каждому ключу» держит `apps/access/tests/test_hr_level_roles_exact.py`.
  Область «свой отдел»/«вся компания» — не признак узла, а
  `PositionRole.scope_kind` (junior/middle → `department`, senior/lead →
  `company`). Внутри ручки права считает `apps/hr/rbac.py::NodeAccess` по
  узлу реестра (нужно, потому что `hr-senior` агрегируется в `admin`
  модуля так же, как `hr-lead`, — уровень модуля не отличает их, узел
  `hr.employees` с признаком `delete` отличает).
- Перенос данных: `manage.py access_backfill_positions [--dry-run]`
  (уровень берётся тем же порядком, что видел живой запрос: явный
  `Position.permissions["hr_level"]`, иначе эвристика `classify_hr_level`
  по держателю; конфликты и расхождения держателей печатаются, не решаются)
  и `manage.py access_backfill_basic` (`employee-basic` каждому
  действующему участнику компании). Оба идемпотентны. Порядок выкатки — §7.
  Должность с явным списком ключей (`Position.permissions["permissions"]`
  заменял пресет уровня) получает именную роль `hr-custom-<slug>-<id>`;
  карточка держателя ищется и по почте (как искал старый резолвер);
  новому участнику `employee-basic` выдаётся при создании членства.
  **Сознательное исключение №4** (блок I.2): должность, чей явный список
  состоит только из ключей `contracts.*`, кадровой роли не получает —
  старая модель пускала держателя в кадровые ручки по одному уровню
  (`HRAccess.has_access` — «уровень ИЛИ ключи»), хотя ни одного кадрового
  ключа список не давал. Сводка переноса печатает такие должности строкой
  «явный список без кадровых ключей» — её читают вместе с конфликтами и
  расхождениями; `contracts` свои ключи читает из колонки сам (§6.6).
- Фронт читает права ТОЛЬКО из `/api/access/v1/me` (`usePermissions`);
  `useHRLevel` ужат до тонкой обёртки для четырёх экранов `pages/contracts/*`
  (сторож `hooks/__tests__/useHRLevelImporters.test.ts`), навигация
  кадрового раздела — одна таблица `app/navigation/hrNavAccess.ts`.
- `apps/hr/access.py` остался ТОЛЬКО как эвристика переноса
  (`classify_hr_level` для `hr.interface.list_positions_hr_levels`); сторож
  `apps/hr/tests/test_single_rbac_guards.py` не пускает других читателей.
  Уходит вместе с командой переноса после выкатки на все компании.
- **`Position.permissions` — мёртвая колонка.** Кадровый домен её не
  читает; сид её не пишет; жива она ради одного читателя —
  `hr.interface.user_has_permission`, которым `apps/contracts` проверяет
  три ключа `contracts.*` (§6.6), и API должностей продолжает её принимать
  только ради него. Удалять — вместе с `user_has_permission`, `apps/hr/
  permissions.py::CONTRACTS_*`, `DEFERRED_KEYS` в `legacy_roles.py` и
  `useHRLevel.ts`, ПОСЛЕ того как `contracts` объявит свои узлы и перейдёт
  на `access.interface.flags_for`/`can` (§6.6); отдельной contract-миграцией
  через `migrate_companies` (столбец в `hr_position` — тенантная таблица).
- Экран «Уровни доступа» (`pages/hr/HRAccessLevels.tsx`, `/admin/access-levels`)
  считал уровни копией снятой эвристики — удалён в блоке I.2 (решение
  заказчика 22.09.2026).
- Хвосты блока I закрыты блоком I.2 (`docs/plans/2026-09-22-block-i2-spec.md`,
  часть 2): именная роль принадлежит своей компании (`Role.company_slug`,
  `access/0009`–`0010`), `hr_level` не задаётся ни формой, ни API должностей,
  членство из django-admin выдаёт базовую роль, кнопки удаления кадровых
  экранов — по `hr:admin`, сторож гейтов видит метод класса-вьюхи без
  декоратора, роли считаются один раз на запрос. При отзыве членства
  назначения ролей остаются и без членства инертны (решение заказчика) —
  кроме уже выданного access-токена: он живёт до `JWT_ACCESS_TTL_MIN`
  (60 мин), так было и до блока.

### I.2 Хвосты блока I и поддомены — (выполнено)
Спека и план: [2026-09-22-block-i2-spec.md](2026-09-22-block-i2-spec.md),
[2026-09-22-block-i2.md](2026-09-22-block-i2.md) (коммиты `f2d5077..2c747dc`,
25 штук).
Сделано: хвосты блока I (роль ⇔ своя компания, снятие `hr_level` из формы и
API должностей, базовая роль из django-admin, сторож гейтов на метод класса)
и переход компаний на поддомены — `Company.subdomain`, псевдонимы
`htq/hts/keg/group`, `companies.interface.resolve_host_label`,
`CompanyPicker` на голом домене, восстановление сессии по refresh-cookie.
Решения по ходу и отложенное — [§9](#9-блок-i2--решения-по-ходу-исполнения-и-отложенное).

### J. Документы (выполнено — план [2026-09-23-block-j-docs.md](2026-09-23-block-j-docs.md))
[multi-company-tenancy-design.md](../multi-company-tenancy-design.md),
[stage2-spec](2026-08-29-stage2-access-and-roles-spec.md) §1.6/§7,
[multi-company-tenancy-stage2-design.md](../multi-company-tenancy-stage2-design.md),
[multi-company-tenancy-followups.md](../multi-company-tenancy-followups.md),
[STRUCTURE.md](../../STRUCTURE.md), [CLAUDE.md](../../CLAUDE.md),
[API.md](../../API.md), [backend/README.md](../../backend/README.md) — под
новый состав группы и блоки A–I.2; итоговая сверка — документ задачи 6:
[2026-09-23-group-structure-verification.md](2026-09-23-group-structure-verification.md).

## 6. Передача другому разработчику (contracts / signoff)

### 6.1 Контракты, которые предоставляю я (только `apps.<x>.interface`)

| Функция | Статус | Зачем им |
|---|---|---|
| `hr.get_positions_brief(ids)`, `hr.resolve_position_users(ids)` | есть; действуют в контексте текущей компании | без изменений |
| `hr.get_employee_brief(user_id)` → `+is_manager`, `+external_hierarchy` | блок B | меняет `access.subordinate_companies` |
| `hr.manager_position_of(position_id) -> int \| None` | новое (B) | «Руководитель блока» = руководитель дирекции инициатора |
| `hr.participant_position() -> {id, title, is_active} \| None` | есть, блок F | утверждающий ОСУ в маршрутах согласования (HR-FRM-004 п. 7, 11, 14) |
| `hr.substitutes_for(position_id, on_date) -> list[{position_id, kind: primary\|reserve, basis}]` | есть, блок E | подмена согласующего |
| `companies.get_company(slug)`, `companies.active_company_slugs()` | есть | кросс-компанейские этапы |
| `access.subordinate_companies(user, company)` | есть (пусто до B) | право ГД/CFO холдинга согласовывать в ДО |
| `access.permission_level(token, module, company)` | есть | их `api_view(module="contracts"/"signoff")` |
| `htqweb.tenancy.db.use_company(slug)` | есть | войти в схему ДО и резолвить её должности |

### 6.2 Требования к signoff (их работа)
- `ApproverKind`: `manager_of_initiator` (через `hr.manager_position_of`); ОСУ — обычная должность по `hr.participant_position()`, отдельного вида согласующего не нужно.
- Кросс-компанейский согласующий: `ApprovalRouteStageRole.company_slug`,
  резолв через `use_company`, проверка права в той компании через
  `access.permission_level`.
- Замещение при формировании `ApprovalTask` (по `hr.substitutes_for`) и
  переназначение открытых задач.
- ✅ с моей стороны: субъекты `hr.*` зарегистрированы, факты объявлены,
  список закреплён тестом и лежит в §6.4 — сумма премии (`hr.bonus.amount`),
  срок отпуска (`hr.leave_request.days`, включительные границы), категория
  должности (`position_level`, `is_manager`). Осталась ваша половина:
  условия маршрутов по этим ключам.
- Экспортировать из `signoff.interface` проверку фактов (обёртку над
  `conditions.normalize_facts` или хотя бы кортеж допустимых типов):
  сейчас предметная аппка не может спросить у движка, переварит ли он её
  факты, и вынуждена повторять список типов у себя
  (`test_every_subject_gives_the_engine_only_values_it_can_normalize`) —
  ошибка вылезает на живом маршруте, в вашем коде, а не в тесте владельца
  предмета.
- Навесить `api_view(module="signoff", level=…)` на свои ручки — гейт готов,
  `access_functions.py` у них уже объявлен.

### 6.3 Требования к contracts (их работа)
- Читатели `holding.contracts_budget/agreement/invoice/counterparty`
  (`managed=False`) и экран консолидированной финотчётности холдинга.
- Маршруты для строк 11–15 матрицы (бюджет группы, хоздоговоры, платежи,
  крупные сделки, списание) с лимитами и участниками
  ОСУ → ГД УК → CFO → Руководитель блока.
- Навесить `api_view(module="contracts", level=…)`.
- Перейти с `hr.interface.user_has_permission` на узлы `contracts.*` — см.
  §6.6 (блок I).

### 6.4 Данные, которые уезжают вместе с этим
- slug'и и названия компаний: `hi-tech-group` (холдинг), `hi-tech-qazaqstan`,
  `hi-tech-systems`, `keg` (предложение; утверждается вместе с §8);
- канонический справочник должностей (после ответа на §8 п.2) — маршруты
  ключуются на `position_id`;
- матрица HR-FRM-004, строки 11–15, с лимитами;
- **список `hr.*` subject-типов и ключей их фактов** (блок G выполнен).
  Набор закреплён тестом `test_every_matrix_row_has_its_subject_and_facts`
  (`backend/apps/hr/tests/test_approval_subjects.py`): переименование ключа
  ломает уже настроенное условие в маршруте, поэтому менять таблицу в
  одиночку нельзя — только согласованной правкой с обеих сторон.

| Строка HR-FRM-004 | `subject_type` | `label` | Ключи фактов |
|---|---|---|---|
| 1 | `hr.org_change` | Заявка на изменение оргструктуры | `kind`, `department_id`, `effective_date`, `headcount_delta` |
| 2 | `hr.staffing_position` | Штатная единица | `department_id`, `position_id`, `position_level`, `headcount`, `salary`, `payroll` |
| 3 | `hr.policy` | Локальный нормативный акт | `kind`, `version`, `effective_from` |
| 4 | `hr.job_description` | Должностная инструкция | `position_id`, `position_level`, `department_id`, `version`, `effective_from` |
| 5, 6, 7 | `hr.personnel_order` | Кадровый приказ | `kind`, `position_id`, `position_level`, `is_manager`, `target_company_slug`, `salary`, `effective_date` |
| 8 | `hr.bonus` | Премия | `employee_id`, `department_id`, `position_level`, `amount`, `period`, `kind` |
| 9 | `hr.reprimand` | Дисциплинарное взыскание | `employee_id`, `department_id`, `position_level`, `severity`, `event_date` |
| 10а | `hr.vacation_schedule` | График отпусков | `year`, `lines_count`, `employees_count`, `total_days` |
| 10б | `hr.leave_request` | Заявление на отпуск | `employee_id`, `department_id`, `kind`, `days`, `date_from`, `date_to` |
| 10в | `hr.business_trip` | Командировка | `employee_id`, `department_id`, `destination`, `country`, `days`, `estimated_cost`, `date_from`, `date_to` |

  Что важно знать про сами значения: `position_level` — номер уровня с
  должности (`hr.Position.level`, N-1 самый высокий: чем меньше число, тем
  выше), `is_manager` — булево с должности, а не догадка по названию;
  `days` у отпуска и командировки считается включительно (с 1-го по 1-е —
  один день) и НЕ хранится полем; `target_company_slug` — slug компании
  назначения, заполняется у приказа строки 7 и приезжает `None` у остальных
  (модель его не требует — это крючок для кросс-компанейского этапа, а не
  обязательное поле); `payroll` штатной строки — оклад × число
  единиц, именно по нему ветвится примечание «ФОТ — в пределах бюджета».
  Даты уезжают как `date` (у приказа и взыскания — уже ISO-строкой, разницы
  после нормализации нет), суммы как `Decimal` — движок нормализует и то и
  другое сам (`conditions.normalize_facts`). Типы полей в объявлениях —
  из `conditions.FIELD_TYPES` (`choice`, `number`, `string`, `bool`), и все
  десять объявлений прогоняются через сам движок тестом
  `test_every_subject_declares_fields_the_engine_accepts`.

  ⚠️ В компании БЕЗ активных подразделений объявление полей семи предметов
  (у них `department_id` — `choice`) движок отвергает целиком: `choice` без
  вариантов. Симптомов два: редактор маршрутов покажет предмет без условий,
  а сохранение ЛЮБОГО условия этапа для такого предмета — даже не
  упоминающего подразделение, вроде «оклад больше 5 млн» — вернёт 409
  (`route_service` зовёт тот же `fields_for`). Самолечится данными: без
  подразделения не завести ни должность, ни сотрудника, то есть и предмета
  согласования не возникнет; но при настройке маршрутов на пустой компании
  выглядит как сломанный редактор
  (`test_without_departments_the_route_editor_sees_no_conditions`). Ловушка
  не кадровая: у `contracts` та же форма с пустым справочником стран.

### 6.5 Что им нужно знать про режим перехода (§3)
- Одна компания; их данные лежат в её схеме (или в `public` до bootstrap);
  переносов не будет.
- Их тесты, использующие фикстуры `company_schema`/`two_company_schemas`,
  не меняются.
- `tenancy_status` — общий инструмент проверки «ничего не потеряно» до и
  после выкатки; результат прикладывается к релизу.

### 6.6 Блок I «Единая модель прав» — что переезжает к вам

Параллельная кадровая модель снята (§5.I); у вас остаётся три пункта в
`contracts` и один во фронте, у `signoff` — ничего сверх §6.2.

(а) **`contracts`, бэкенд.** `hr.interface.user_has_permission(user_id,
permission)` — ЕДИНСТВЕННЫЙ оставшийся читатель `Position.permissions`, и
живёт он до вашего перехода. Семь вызовов в `apps/contracts/services/*`
(`accountable_funds_request_service`, `advance_payment_service`,
`completion_act_service`, `contract_payment_service`, три в
`work_queue_service`) проверяют три ключа: `contracts.accountable_funds_
request.mark_paid`, `contracts.advance_payment.record_payment`,
`contracts.contract_payment.record_payment`. Что сделать: объявить под них
узлы в своём реестре функций (`apps/contracts/access_functions.py` — узел
`contracts.payments` уже есть, решение о раскладке за вами: блок I узлов
чужой аппки не выдумывал намеренно, см. `legacy_roles.DEFERRED_KEYS`) и
проверять `access.interface.flags_for(user, node, company)` (или свою
обёртку `can`) вместо `user_has_permission`. После этого
`user_has_permission`, ключи `CONTRACTS_*` в `apps/hr/permissions.py` и
сама колонка удаляются вместе (§5.I).

(б) **`contracts`, фронт.** Четыре экрана `src/pages/contracts/*`
(`AccountableFundsRequestDetail`, `AdvancePaymentDetail`,
`CompletionActDetail`, `ContractPaymentDetail`) читают
`useHRLevel().hasPerm(<ключ contracts.*>)`. ⚠️ С задачи 8 блока I `hasPerm`
для этих ключей **всегда `false`** — узла под них нет, а `hasPerm` считает
по узлам `/access/v1/me` через `KEY_TO_NODE`; кнопки «отметить оплату»
у бухгалтера на фронте сейчас скрыты (сервер их всё ещё пускает по
`user_has_permission`). Перейти на `usePermissions().can(<ваш узел>,
'edit')` — после чего `hooks/useHRLevel.ts` удаляется целиком (сторож
`hooks/__tests__/useHRLevelImporters.test.ts` это допускает: он разрешает
импорт только из `pages/contracts/*`).

(в) **`signoff`** — ничего: гейт `api_view(module="signoff", level=…)`
вешаете сами (§6.2), `access_functions.py` у вас объявлен, реестр
самообслуживания (`apps/access/self_service.py::TRANSLATED_APPS`) вашу
аппку не проверяет, пока вы её туда не впишете.

## 7. Порядок выкатки

1. **A** (реестр, переключатель, `tenancy_status`, гейт последней компании)
   — безопасно при одной компании; слепок до/после.
2. **D** + **B** — expand-миграции `hr/0021`–`0024` через `migrate_companies` на HTQ (миграции `hr/0023`–`0024` no-op по данным: choices без DDL; пороги уже есть); слепок до/после; contracts/signoff не затронуты.
3. **C** — решение и реализация в `access`; **E**, **F** — модели и интерфейс; (`hr/0025_substitution` — expand, НОВАЯ таблица, через `migrate_companies`; на бою матрица заполняется руками с карточки должности, демо-сид на бой не идёт);
   передать §6.1 другому разработчику. Параллельно у него — §6.2/6.3.
4. **G** — HR-субъекты (моя половина) после их `ApproverKind`. Девять
   expand-миграций `hr/0027`–`0035` через `migrate_companies`: `0027` —
   колонка `approval_state` на `hr_staffingposition`, `0028`–`0033` — десять
   НОВЫХ таблиц: девять предметов (`hr_personnelorder`, `hr_bonus`,
   `hr_reprimand`, `hr_leaverequest`, `hr_businesstrip`,
   `hr_vacationschedule`, `hr_policy`, `hr_jobdescription`,
   `hr_orgchangerequest`) плюс строка графика (`hr_vacationscheduleline`);
   `0034` расширяет `PersonnelHistory.order_number` с 64 до 255 (туда пишет
   утверждённый приказ своё основание — varchar→varchar правкой каталога,
   без переписывания таблицы), `0035` добавляет истории nullable-связь
   `source_order` с приказом (одна запись истории на приказ, единственность
   на уровне БД; старые строки остаются с NULL). Данные не переносятся, откат — снос таблиц;
   слепок `tenancy_status` до/после. Маршруты на бою пусты: до их настройки
   ручка отправки отвечает 409 «маршрут не настроен», и это ожидаемо.
5. **Заведение остальных компаний** (`company_create` холдинг → HTS → KEG,
   `--parent hi-tech-group`, у каждой — короткий адрес: `--subdomain group`
   холдингу, `--subdomain hts`, `--subdomain keg`; миграция
   `companies/0006` проставляет псевдонимы только уже существующим
   компаниям, а заведённые после неё без флага остаются на адресе по слагу;
   HTQ получает `parent` и `kind=construction`
   через PATCH из A); `manage.py hr_participant --company hi-tech-group`
   — завести ОСУ в холдинге; затем кадровик соединяет ОСУ с ГД в дереве.
   `company_grant` персоналу холдинга; сид уровней отработает сам. Только
   теперь появляется второй поддомен.
6. **H** (выполнено) — сводки: новое представление `holding.hr_staffingposition`
   (`StaffingPosition` добавлен в сводимые модели `hr`) требует `migrate_companies`
   отдельным шагом выкатки — порядок «мигрировать все компании → пересобрать
   вьюхи» обеспечивает сама команда; миграции `hr/0036`, `hr/0037`, `tasks/0020`.
   **I** + **I.2** (выполнено в коде) — снятие параллельного RBAC и
   перевод компаний на поддомены. ⚠️ **Гейты уже в коде, и они требуют
   контекста компании**: без `X-HTQ-Company` (голый домен)
   `permission_level` отвечает `none` любому, кроме суперпользователя, —
   на голом домене 403 получат все. Поэтому гейты и поддомены неразделимы:
   без поддоменов гейты закрывают всё, без гейтов поддомены ничего не
   защищают. Выкатываются ОДНИМ образом в ОДНО окно, перенос прав —
   строго ДО того, как код с гейтами попадёт под трафик. Порядок (спека
   блока I.2, §8); команды, проверочные запросы и признаки отката — в
   чеклисте [`docs/deploy/subdomains-runbook.md`](../deploy/subdomains-runbook.md):
   0. **Заранее, без кода** (чеклист, шаги 1–4, и предпроверка
      слагов-коллизий): DNS `*` с проксированием, SAN origin-сертификата
      (`htq.group` и `*.htq.group`), режим SSL «Full (strict)»,
      `SFU_ALLOWED_ORIGINS`. Голый домен при этом работает как сегодня.
   **Одно окно выкатки, трафик закрыт:**
   1. новый образ (блоки I + I.2); `manage.py migrate_shared` при старте
      контейнера — роли `hr-*` (`access/0005`), `scope_kind`
      (`0006`–`0007`), запреты на под-узлах (`0008`), роль компании
      `Role.company_slug` (`0009`–`0010`), `Company.subdomain` и псевдонимы
      `htq`/`hts`/`keg`/`group` (`companies/0005`–`0006`);
   2. `manage.py migrate_companies` — схемы компаний (по данным no-op);
   3. `manage.py access_backfill_positions --dry-run` — по всем компаниям;
      **прочитать сводку**: конфликты (должность уже несёт другую роль
      `hr-*`), расхождения по держателям и строки «явный список без
      кадровых ключей» (исключение №4, §5.I) команда не решает — их
      разбирает кадровик до следующего шага;
   4. `manage.py access_backfill_positions` — реальный перенос;
      повторный прогон обязан показать «создано сейчас 0»; должности с явным
      списком ключей (`Position.permissions["permissions"]`, заменявшим
      пресет уровня) переносятся именными ролями `hr-custom-<slug>-<id>`
      (с `company_slug=<slug>`) — после переноса их просмотреть (строки
      «явный список ключей» сводки);
   5. `manage.py access_backfill_basic` — `employee-basic` каждому
      действующему участнику; число выданных = число членств. Только для
      уже существующих членств: новому участнику базовая роль выдаётся при
      создании членства (`membership_service.grant_membership` →
      `access.interface.ensure_basic_role` — `company_grant`, экран
      участников, django-admin, `tenancy_bootstrap --grant-all`);
   6. `tenancy_status --json --exact` до и после (без `--exact` — оценки
      планировщика, на свежей базе нули);
   7. проверка поддоменов (чеклист, шаг 8): канонический хост компании
      отвечает, адрес по слагу у компании с псевдонимом — 404, вход на
      голом домене ведёт на выбор компании/редирект, конференция проходит
      проверку Origin;
   8. и только теперь — открыть трафик. Пользователи приходят на
      `htq.group`, входят и попадают на свою компанию
      (`/companies/choose`).
   Репетиция на стенде (dev-БД, 4 компании, 25 должностей, 24 членства) —
   отчёт задачи 11 блока I, §3: 25 `PositionRole`, 24 `RoleAssignment`, оба
   переноса идемпотентны, живая проверка под `hr-middle`/`hr-junior`
   показала список сотрудников, суженный до отдела держателя (4 из 13).
7. **J** — документы закрываются вместе с каждым блоком, финальная сверка.

## 8. Вопросы руководству (расхождения в самих документах)

1. HR-FRM-004…006 выписаны на ТОО «Hi-Tech Management», оргструктура — на
   «Hi-Tech Group LTD». Какое юрлицо — УК? От этого зависит имя и slug холдинга.
2. Должности расходятся: «Менеджер по кадрам / HR-специалист», «Менеджер ПТО
   и КК / Специалист ПТО», «Экономист-аналитик / Экономист», «Кадровый
   бухгалтер / Бухгалтер». Нужен один справочник — `Position.title` одна строка.
   Одна пара из четырёх снята решением заказчика 16.09.2026: «Кадровый
   бухгалтер» в оргструктуре читается как «Бухгалтер» и совпадает с
   HR-FRM-006. Остаются открытыми «Менеджер по кадрам / HR-специалист»,
   «Менеджер ПТО и КК / Специалист ПТО», «Экономист-аналитик / Экономист».
3. Оргструктура HTQ не заполнена: пустой блок на N-4, «Менеджеры — », «Всего — ».
   Курсив у «Начальник участка» — правка или нет?
4. Матрица полномочий п.6 («Приём и увольнение руководителей блоков»): нет
   инициатора (И). Кто?
5. HR ДО (RACI 12–13) — в оргструктурах ДО кадровика нет. Значит функцию
   выполняет холдинг, и это подтверждает вариант C-1 (роли должности холдинга
   действуют в ДО). Согласовать.

**Должность «Системный администратор» переименована** в «Специалист
технической поддержки» решением заказчика 16.09.2026. Причина не в
расхождении документов: словом «системный администратор» платформа называет
администраторов САЙТА — это роль доступа, а не кадровая должность, и
совпадение имён привело бы к тому, что кадровик, заводя должность, счёл бы,
что выдаёт права администратора. В оргструктуре документа должность
названа «Системный администратор»; это осознанное расхождение с ним.

**Уровни администраторов сайта.** Заказчик просит расширить состав
администраторов и завести старшего администратора — несколько уровней
административного доступа вместо одного флага `is_elevated`. Место — блок I,
где и так пересматривается гейт `api_view(module=…)`.

## 9. Блок I.2 — решения по ходу исполнения и отложенное

Блок I.2 (спека `docs/plans/2026-09-22-block-i2-spec.md`, план
`docs/plans/2026-09-22-block-i2.md`, коммиты `f2d5077..2c747dc`, 25 штук) —
хвосты блока I и переход компаний на поддомены. Выполнен субагентами с ревью
каждой задачи и финальным ревью ветки. Здесь записано то, что решалось по ходу
без участия заказчика, и то, что сознательно оставлено: журнал исполнения
в git не хранится и удалён по закрытии блока.

### 9.1 Решения, принятые по ходу (что будет, если решение неверно)

- **P1. База `tsc`** — не константа 150, а число, записанное последней
  задачей: удаление экрана «Уровни доступа» законно унесло две его ошибки,
  база стала 148. Цена ошибки — одна неверная сверка числа, видна в отчёте.
- **P2. Имена из кода, а не из плана.** Где план помечал имя «сверь по коду»,
  исполнитель брал фактическое и называл его: выдача роли пользователю —
  `set_user_assignments` (не `assign_role`), фикстура `hr_admin_auth`, ключ
  ответа share-ссылки `url`. Смысл тестов не менялся.
- **P3 / P3'. Трейлер коммитов** дважды менялся вслед за сменой модели
  сессии; сделанные коммиты не переписывались. На код не влияет.
- **P4. pytest только в форграунде.** Один исполнитель запустил две фоновые
  сессии на общей тестовой базе — процессы остановлены, фоновые прогоны
  запрещены каждому следующему. Иначе — ложно-красные прогоны.
- **P5. Переводы фронта** лежат в `frontend/public/locales/{ru,en}/translation.json`
  (план указывал несуществующий путь).
- **P6. Бэкенд и фронт — одним окном.** После миграции псевдонимов адрес по
  слагу компании с псевдонимом отвечает 404, а старый фронт строил адрес по
  слагу. Частичная выкатка — 404 на переключении компаний.
- **P7. `PUBLIC_BASE_URL` — голый домен со схемой, без `www`**: корень адреса
  компании и доверенный origin CSRF берутся из хоста целиком; при `www`
  получится `acme.www.htq.group`.
- **Q1. Соседние чтения роли** (`roles/<id>/permissions`, `roles/<id>/holders`)
  на чужую именную роль отвечают 404 — спека требовала сузить «каталог и
  соседние чтения»; до блока они отдавали ФИО, отдел и должность держателей
  из другой компании. Общие роли и суперпользователя не касается.
- **Q2. Проверка «чужая роль» — в модели** (`PositionRole.clean()`,
  `RoleAssignment.clean()`), поэтому её проходит и django-admin, а не только
  сервис. `clean()` срабатывает через `full_clean`/форму, не на `save()` — сид
  и перенос прав не задеты.
- **Q3. Копия роли наследует компанию источника** — иначе копия именной роли
  стала бы общей и раскрыла название должности всей группе.
- **R1. Правка должности с ключом `permissions` заменяет словарь целиком** и
  стирает старый `hr_level` — намеренно: после переноса прав колонка для
  модели прав мертва, а перенос идёт до трафика. Закреплено тестом; ключи
  `contracts.*` сохраняются.
- **R2. Админка должности отбрасывает `hr_level`** при сохранении, ключи
  `permissions` остаются правимыми (readonly сузил бы правку ключей contracts).
- **R3. Метка исключения в стороже колонки** — «рулинг R2 блока I.2», а не
  «L»: буква L уже означает поиск кадровой карточки по почте.
- **R4.** Снятый маршрут `/admin/access-levels` убран и из e2e-теста
  (`frontend/tests/e2e/18_hr_ui.spec.ts`).
- **R5, S2.** Исполнители менялись между моделями по лимитам; продолжение
  всегда шло по уже сделанной работе, без переделки.
- **S1. Финальная волна — один исполнитель**; стендовая приёмка (миграции на
  dev-БД, резолв псевдонимов, запрос с токеном через `htq`) — контроллером.

### 9.2 Сознательно оставлено (не ошибки, а известные границы)

- **Сторож гейтов** (`backend/apps/access/tests/test_gate.py`) обходится только
  умышленно: база вьюхи под псевдонимом импорта (`ApiView as _Base`) или из
  соседнего модуля; `**{"level": "none"}` на вызове фабрики или
  `level = "none"` в её теле; функция-ручка в `hr`/`users`/`tasks` совсем без
  `@api_view` (отличить от помощника можно только сверкой с `urls.py`). При
  разнесённом `@method_decorator(\n api_view(...))` сообщение называет не ту
  функцию, но сторож краснеет. — три обхода **закрыты** блоком K
  ([план](2026-09-24-post-refactoring-leftovers.md), задача 7, `b557f99`);
  неточное имя в сообщении при разнесённом декораторе осталось (не обход:
  сторож всё равно краснеет).
- **Сторож колонки `Position.permissions`** (`apps/hr/tests/test_single_rbac_guards.py`):
  исключения ключуются по (файл, имя функции), не по классу — `save_model`
  в другом `ModelAdmin` файла `apps/hr/admin.py` проскочит. Исправление
  требует переписать разбор `_enclosing_function`; та же гранулярность у
  исключений A/B/C/K блока I.
- **Псевдоним компании.** Запрет «псевдоним = слаг другой компании» держится
  в приложении (`Company.clean()`), ограничения в БД нет — гонка двух
  одновременных сохранений теоретически возможна. Миграция `companies/0006`
  ставит псевдонимы через `.update()` мимо `clean()` — закрыто предпроверкой в
  чеклисте выкатки. Зарезервированные метки (`api`, `admin`, …) запрещены
  только для псевдонима, слаг `api` по-прежнему допустим (было до блока).
- **Миграция `access/0010`** определяет компанию именной роли по коду
  `hr-custom-<slug>-<id>`, не сверяя со списком компаний: роль из редактора с
  кодом такого вида привязалась бы к несуществующей компании.
- **Базовая роль.** Если `employee-basic` не засеяна, создание членства падает
  `UnknownRole` без обёртки — одинаково во всех путях (API, админка,
  `company_grant`, `tenancy_bootstrap`). — для API (503 `access_not_seeded`)
  и `company_grant` (`CommandError`) **закрыто** блоком K
  ([план](2026-09-24-post-refactoring-leftovers.md), задача 4, `6e71eff`);
  django-admin, `tenancy_bootstrap` и `seed_group_demo` остаются «громкими»
  намеренно — трейсбек оператору, bootstrap откатывается целиком.
- **Переводы.** 94 вызова `t('access.…')` на экранах прав не имеют записей в
  файлах переводов — показывается запасной текст (было до блока). — **закрыто**
  блоком K ([план](2026-09-24-post-refactoring-leftovers.md), задача 6, `6aa4fe5`).
- **Производительность.** Гейт дважды зовёт `require_service("access")` (кэш
  5 с); неизвестная метка хоста стоит два запроса вместо одного (только в
  разработке — в проде заголовок ставит nginx по регулярке). Тесты
  `provision_company` в `apps/companies/tests/test_subdomain.py` гоняют полное
  заведение схемы — медленно.
- **`CLAUDE.md`** в разделе про мультикомпанейность упоминает
  несуществующий `.env.production` — **закрыто** блоком J (`a472478`); в
  `docs/multi-company-tenancy-design.md:345` то же упоминание оставалось,
  исправлено той же волной финального ревью блока J.
- **Два пояса: `TIME_ZONE` (UTC) и `PLATFORM_TIME_ZONE` конференций
  (Asia/Almaty).** «Сегодня» в `hr`/`tasks`/`approvals` и в метриках —
  `timezone.localdate()`, то есть день в `TIME_ZONE` (в проде `"UTC"`); сторож
  `apps/core/tests/test_platform_today.py`. Конференции (обзор, история
  встреч) считают границу суток в `PLATFORM_TIME_ZONE`
  (`apps/conference/services/platform_time.py`). С 00:00 до 05:00 по Алматы
  (19:00–24:00 UTC) эти два «сегодня» расходятся на день: доска ежедневных
  отчётов и «отчёты за сегодня» показывают вчерашний день, а обзор
  конференций — уже новый. Блок K поведение не менял — он только свёл все
  чтения и записи «сегодня» вне конференций к одной точке (задача 3,
  `675ddaf`). Свести пояса — отдельное решение заказчика: смена `TIME_ZONE`
  сдвигает каждую дату платформы (см. комментарий у `PLATFORM_TIME_ZONE` в
  `backend/htqweb/settings/base.py`).

### 9.3 Вне блока, но касается выкатки

- Ветка `sanzhar` разошлась с `origin/sanzhar`: в удалённой — 9 коммитов
  слияний `main` (PR #29, #30, 10–14.09.2026: парсер cashflow в `contracts`,
  правки аватаров в кадрах). Перед пушем их нужно влить.
- Share-ссылки кадров, выданные до выкатки, ведут на голый домен и после неё
  не откроются (404) — выдать заново.

## 10. Итог рефакторинга (23.09.2026)

Построено: реестр и схемы Postgres на компанию (подпроект 1), HTTP-API и
экраны реестра (блок A), короткие адреса и поддомены (блок I.2); внешняя иерархия и права холдинга
в ДО (блоки B, C); уровни N-1…N-4, три дирекции холдинга, демо-структуры
четырёх компаний (блок D); замещение ключевых должностей и системная
должность «Участник (ОСУ)» (блоки E, F); десять кадровых предметов
согласования HR-FRM-004 строк 1–10 с фактами для маршрутов (блок G); сводки
холдинга по `hr`/`tasks` (блок H); единая модель прав `apps.access` вместо
параллельной кадровой (блок I) и её хвосты вместе с переходом на поддомены
(блок I.2).

Передано второму разработчику (`contracts`/`signoff`) — контракты
`apps.<x>.interface`, гейт `api_view(module=…)`, узлы вместо
`user_has_permission`, строки матрицы 11–15, читатели `holding.contracts_*` —
подробно в [§6](#6-передача-другому-разработчику-contracts--signoff).

Ждёт решения руководства — пять открытых вопросов о расхождениях в
исходных документах (наименование УК, канонический справочник должностей,
незаполненная оргструктура HTQ, инициатор п.6 матрицы, HR ДО) —
[§8](#8-вопросы-руководству-расхождения-в-самих-документах).

Сознательно оставлено — банкротство с переносом активов, автоматический
бэкфилл внешней иерархии по оргструктуре и прочие границы блока I.2 —
[§9](#9-блок-i2--решения-по-ходу-исполнения-и-отложенное).

Бизнес-метрики tenant-аппок — закрыто блоком K
([план](2026-09-24-post-refactoring-leftovers.md)): веер по компаниям с
меткой `company`.

Остальные хвосты сверки («сегодня» по одному поясу (`TIME_ZONE`), `UnknownRole`, два давних
падения кадров, переводы экранов прав, обходы сторожа гейтов, устаревшие
комментарии) — закрыты блоком K. Гейт на шесть аппок платформы — блок L
([спека](2026-09-24-block-l-gate-remaining-apps-spec.md),
[план](2026-09-24-block-l-gate-remaining-apps.md)); `core` не модуль прав.
Архив «только чтение» — закрыт ([спека](2026-09-25-archive-read-only-spec.md), [план](2026-09-25-archive-read-only.md)).

Итоговая сверка требований руководства по коду и тестам — задача 6 блока J:
[2026-09-23-group-structure-verification.md](2026-09-23-group-structure-verification.md) —
итог: выполнен с оговорками.

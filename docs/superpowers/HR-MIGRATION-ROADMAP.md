# HR-микросервис — дорожная карта и регламент работ (handoff)

> **Назначение.** Единый файл для продолжения работ по рефакторингу/развитию HR-микросервиса в любой новой сессии. Здесь: что уже сделано, КАК мы это делаем (методология), повторяемые структуры/паттерны кода, что осталось (Фазы 2–4) с подходом к каждой фиче, инварианты и техдолг.
>
> **Как продолжить в новой сессии:** скажи «продолжай <код-фичи> по дорожной карте» (напр. «продолжай B2»). Все спеки — в `docs/superpowers/specs/`, планы — в `docs/superpowers/plans/`. Этот каталог в `.gitignore` (локальный).

- **Ветка работ:** `sanzhar` (личная рабочая; `main` — основа/бэкап). Операции с ветками не делаем — только коммиты по ходу.
- **Последний коммит на момент записи:** `6bc463e` (поверх серии фич-коммитов B0–B4).
- **Alembic head (hr):** `021_merge_staffing_keys`. Цепочка линейна `001 → … → 021`.
- **Permission keys (`ALL_KEYS`):** 27. Каталог `_PERMISSION_CATALOG` — 27 элементов (совпадает).

---

## 1. Что уже сделано (Фаза 0, 1.0, Фаза 1)

| Этап | Суть | Ключевые артефакты |
|---|---|---|
| **Phase 0** | Слияние идентичности 3→2: user-service — единственный владелец ФИО/email/phone/avatar; `Employee` — read-only реплика (синк из `user.upserted`); удалены страница «Профили» и hr-прокси «Аккаунты»; убраны мёртвые поля формы | `services/hr/app/workers/user_identity_sync.py`, `services/hr/app/scripts/backfill_identity.py`; фронт `api/accounts.ts`, `HRAccounts.tsx` |
| **Phase 1.0** | Enforcement-слой прав: **ключи — источник правды**, `hr_level` — пресет; `HRAccess.has()` + `require_permission()`; бэкфилл пресетов в позиции | `services/hr/app/auth/permissions.py`, `hr_access.py`, `services/permission_backfill.py`; миграции 014 |
| **B1** | Карточка Т-2: SQL `hr_employee_card` (financial/personal/certs) + Mongo группы (education/experience/relatives); пер-секционный RBAC `hr.card.*` | `models/employee_card.py`, `services/employee_card_t2_service.py`, `services/employee_groups_service.py`, `api/v1/employee_card.py`; миграции 015–016 |
| **B3a** | Произв. календарь: настраиваемые недельные шаблоны + нац. оверрайды + пер-сотрудничья привязка (default при отсутствии); `CalendarService` | `models/calendar.py`, `services/calendar_service.py`, `api/v1/calendar.py`; миграции 017–018; фронт `HRProductionCalendar.tsx` |
| **B3b** | Циклические смены: `hr_shift_patterns` (+ `holidays_off`), привязка смены (anchor), ручной пер-сотрудничий оверрайд дня; новая резолюция `employee_day_info` | расширения `models/calendar.py`, `calendar_service.py`, `api/v1/calendar.py`; миграция 019 |
| **B4** | Штатное расписание: независимые строки `hr_staffing_positions` (headcount+оклад); occupancy (budgeted/filled/vacant по группе position+отдел), ФОТ-rollup; ключи `hr.staffing.*` | `models/staffing.py`, `services/staffing_service.py`, `api/v1/staffing.py`; миграции 020–021; фронт `HRStaffing.tsx` |

**Аудиты (зафиксированы в начале):** gap-audit vs 1С/идеалы и code-audit HR — резюме в самых ранних спеках. Вердикт по Rust: **не переписывать** (CRUD-сервис, не горячий путь; завязан на общий Python-стек).

---

## 2. Методология (как мы работаем — повторять для каждой фичи)

Для каждой фичи строго по циклу **superpowers**:

1. **brainstorming** → задать 1–3 решающих вопроса (через AskUserQuestion), предложить варианты, согласовать дизайн.
2. **Спека** → `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`. Self-review (плейсхолдеры/консистентность/скоуп/неоднозначность). Гейт ревью пользователем.
3. **writing-plans** → `docs/superpowers/plans/YYYY-MM-DD-<feature>.md`. Bite-sized задачи, TDD, **полный код в каждом шаге** (без плейсхолдеров), частые коммиты. Self-review (покрытие спека, согласованность типов).
4. **Исполнение — Subagent-Driven** (`superpowers:subagent-driven-development`): на каждую задачу — свежий субагент. Для экономии токенов **субагент читает свою секцию плана** (`Read ONLY "## Task N"`) и исполняет verbatim. После — ревью (spec-compliance, при риске + code-quality), фиксы в той же итерации.
5. **Финальное ревью** всей фичи (отдельный субагент) → APPROVED/CHANGES. Минорные фиксы — инлайн самим контроллером.
6. Ветку не закрываем (вариант «оставить как есть»).

**Экономия токенов:** объединять тесно связанные мелкие задачи в один dispatch (напр. «ключи + модель+миграция»); субагенты читают план с диска вместо вставки 250 строк в промпт.

---

## 3. Повторяемые структуры/паттерны кода (HR feature blueprint)

Почти каждая HR-фича собирается из одних и тех же кирпичей. **Используй это как чек-лист.**

### 3.1 Права (если фиче нужен свой доступ)
- **Ключи:** добавить константы в `services/hr/app/auth/permissions.py` → в `ALL_KEYS` → в нужные пресеты `_JUNIOR/_MIDDLE/_SENIOR/_LEAD` (наследование: `_MIDDLE=_JUNIOR|{…}` и т.д.).
- **Каталог:** добавить `PermissionCatalogItem(key=…, label=…, group=…)` в `_PERMISSION_CATALOG` (`services/hr/app/api/v1/positions.py`). `level_presets` строится из `LEVEL_PRESETS` автоматически.
- **Merge-миграция:** новая ревизия, вызывающая `merge_missing_preset_keys(session)` (`services/hr/app/services/permission_backfill.py`) — домерживает новые preset-ключи в существующие позиции, не трогая кастомные. Образец: `016`, `018`, `021`.
- **Enforcement:** в роутере `require_permission("hr.x.y")` как зависимость; для пер-сотрудничьих эндпоинтов — резолв `HRAccess` + проверка `can_see_department` + `access.has(key)`.
- **Тест прав:** `tests/integration/test_<feature>_permissions.py` — ключи в `ALL_KEYS`, правильные уровни.

### 3.2 Модель + миграция
- Модель в `services/hr/app/models/<name>.py`, наследует `BaseModel` (даёт `id`, `created_at`, `updated_at`). Таблицы с префиксом `hr_`. FK `ondelete="CASCADE"` где уместно.
- Зарегистрировать в `services/hr/app/models/__init__.py` (import + `__all__`).
- Миграция `alembic/versions/NNN_<name>.py`: `revision="NNN_<name>"`, `down_revision="<текущий head>"`. **Сверять head:** `python -m alembic heads`. Сиды — через `op.bulk_insert`. Цепочка строго линейна.

### 3.3 Схемы + сервис
- Схемы `services/hr/app/schemas/<name>.py` (Pydantic v2). **Денежные/числовые — строками** (`_money`/`str(Decimal)`), даты — ISO. Валидаторы (`field_validator`) для enum-полей.
- Сервис `services/hr/app/services/<name>_service.py` — вся бизнес-логика; роуты только парсят и вызывают. Ошибки — `HTTPException` (404/409/422). Транзакции: delete+upsert в одном `commit` (для взаимоисключений и т.п.).

### 3.4 Эндпоинты
- Роутер `services/hr/app/api/v1/<name>.py`, `prefix="/<name>"`. **Литеральные сегменты ДО `/{id}`** (иначе FastAPI парсит как int → 422).
- Подключить в `services/hr/app/main.py` (`include_router(..., prefix=API_PREFIX)`); пер-сотрудничьи роутеры — после `employees_router`.

### 3.5 Frontend
- API-клиент в `frontend/src/api/hr.ts` (база `HR`-префикс, axios `api`).
- Страница `frontend/src/pages/hr/HR<Name>.tsx`; гейтинг через `useHRLevel().hasPerm('hr.x.y')` (поддерживает wildcard `*` для админа).
- Роут в `frontend/src/app/routing/lazyPages.ts` + **оба** блока `routeDefinitions.ts` (`requiresAuth` и `requiresRole:'hr'`).
- Навигация — `frontend/src/components/hr/HRLayout.tsx` (`{to, icon, labelKey, levels}`).
- i18n — `frontend/public/locales/{ru,en}/translation.json` (kz НЕТ). Прогон `node check-i18n.mjs` (есть pre-existing false-positives на import-пути lazyPages — игнорировать).

### 3.6 Тесты (окружение)
- pytest-asyncio; Postgres через **testcontainers** (поднимается автоматически). Таблицы строятся из `Base.metadata` (сиды миграций в тестах НЕ выполняются — тесты сами создают нужные строки).
- **Запуск (PowerShell, из `services/hr`):** `$env:PYTHONPATH="$PWD;$PWD\..\..\libs"; $env:JWT_SECRET="change-me"; python -m pytest tests/integration/<file> -v`.
- Хелпер админ-токена: `from tests.conftest import admin_headers` (даёт HRAccess wildcard `{"*"}`).
- Фронт: `cd frontend && npx tsc --noEmit`.

---

## 4. Инварианты и «ловушки» (не нарушать)

- **Идентичность** (ФИО/email/phone/avatar) — владелец user-service; в HR это read-only реплика. Не редактировать в HR для привязанных сотрудников.
- **Ключи прав — источник правды**; `hr_level` — только пресет. Новые ключи раскатывать merge-миграцией, иначе у существующих позиций их не будет.
- **Alembic линеен, один head.** Перед новой миграцией — `python -m alembic heads`; `down_revision` = текущий head.
- **PgBouncer/§7 STRUCTURE.md:** схема `public` + префиксы; `alembic/env.py` владеет своей транзакцией; `statement_cache_size=0`.
- **Numeric на проводе — строкой**; `filled`/счётчики — int.
- **Резолюция календаря (employee_day_info):** ручной пер-сотрудничий оверрайд → смена (с `holidays_off`) → нац.оверрайд → недельный шаблон сотрудника/default → hard-fallback Пн–Пт/8ч. Смена и недельный шаблон **взаимоисключающи**.
- **Occupancy/ФОТ:** занятость и итоги — только по парам (position, department), присутствующим в штатном расписании (не глобальный счёт сотрудников).
- **Mongo опционален:** при пустом `mongo_uri` группы Т-2 деградируют до пустых списков (без 500).

---

## 5. Оставшаяся дорожная карта

### Фаза 2 — Движения (следующая)
| Код | Фича | Подход (предварительно — уточнить в brainstorming) |
|---|---|---|
| **B2** | Отпуска/больничные/отсутствия | Модель типов отсутствий + заявок + остатков дней; расчёт дней через `CalendarService.employee_working_days_between` (B3); **согласование — через сервис `requests`** (S2S), не свой движок. Ключи `hr.leave.*`. Витрина ESS — частично (или в C3). |
| **B5** | Приказы (HR orders) | Реестр приказов с нумерацией/шаблонами; связь с событиями (найм/перевод/увольнение, отпуск). Возможно генерация документа (PDF) + хранение (media/Mongo). Ключи `hr.orders.*`. |
| **B6** | Сроки документов/сертификатов + напоминания | Поля сроков уже частично в Т-2 (`sro_*`, `safety_*`); добавить контроль истечения + worker-напоминания (`app/workers/scheduler.py` APScheduler) → уведомления. Ключи `hr.docexpiry.*` или под `hr.documents.*`. |
| **B7** | Орг-изменения с эффективной датой (+ долг #4) | Эффективные даты для переводов/штатных изменений; `EmployeeTransfer.effective_date` сейчас игнорируется — починить. Возможна общая модель «future-dated change». Затрагивает employees/staffing/calendar. |

### Фаза 3 — Процессы (интеграция, не дублирование)
- **C1** Онбординг/оффбординг чек-листы → hr-триггер в `task`/`requests`.
- **C2** e-Подпись документов (договоры/приказы) → провайдер + hr-документы.
- **C3** Самообслуживание (ESS): сотрудник видит свою карточку/календарь/заявки.

### Фаза 4 — Развитие (стратегическое)
- **D1** Аттестации / Performance / KPI / OKR.
- **D2** Обучение и развитие (LMS-лайт).
- **D3** Расчётный листок / интеграция с расчётом ЗП (вероятно внешняя интеграция).

> **Принцип границ:** чат/задачи/согласования/почта живут в `messenger`/`task`/`requests`/`email` — HR туда не дублирует, а интегрируется (S2S/Redis). HR — кадровый контур (≈ 1С:ЗУП).

---

## 6. Технический долг (залогирован, вне текущего скоупа)

- **0c — S2S/RBAC user↔hr:** HR переподписывает JWT общим секретом для admin-API user-service (3 копии минтинга, из них 1 удалена в Phase 0). Нужен настоящий service-token-контракт. Латентный баг: классифицированный `lead`-HR без платформенного admin не пройдёт admin-гейт user-service.
- **#2** — эвристика `classify_hr_level` по подстроке: теперь только сидер уровня для новых позиций, не рантайм-гейт. Полное удаление — позже.
- **create_user_option** (employees.py) роняет `username`/`patronymic` из ответа (`HRUserOption` их не объявляет) — pre-existing, чинить отдельно.
- **Staffing PUT** — full-replace (не PATCH): частичное обновление зануляет неприсланные поля. При необходимости добавить PATCH.
- **Frontend v1-заглушки:** редакторы (Т-2 формы, слот-редактор смен, формы создания штатных строк, грид-календарь) — только просмотр/минимум; дозакрыть при необходимости.
- **Deprecation:** `HTTP_422_UNPROCESSABLE_ENTITY` → `..._CONTENT` (косметика).
- **avatar/identity sync loop** — по инстансу (дубль работы при горизонтальном масштабе HR).

---

## 7. Быстрый старт следующей сессии

1. Прочитать этот файл + последний релевантный спек/план в `docs/superpowers/`.
2. Выбрать фичу (по умолчанию — **B2**).
3. brainstorming → спека → план → subagent-driven (см. §2), используя blueprint §3 и инварианты §4.
4. Перед миграцией — `alembic heads`; после фичи — финальное ревью + обновить этот файл (§1 статус, §5 вычеркнуть сделанное).

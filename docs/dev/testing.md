# Тесты

Чем проверяется платформа и почему запуск иногда не работает.

---

## 1. Бэкенд: pytest-django против настоящего Postgres

**SQLite не используется.** Тесты идут в реальный Postgres, потому что схема
опирается на его возможности (`ltree`, проверочные ограничения, серверные
значения по умолчанию).

```bash
docker compose -f docker-compose.test-local.yml up -d db   # ТОЛЬКО база
cd backend
./.venv/Scripts/python.exe -m pytest -q                    # вся сюита
./.venv/Scripts/python.exe -m pytest apps/hr/tests/test_x.py::test_name
```

`DJANGO_SETTINGS_MODULE` и `JWT_SECRET` заданы в `backend/pytest.ini` и
`backend/htqweb/settings/test.py` — руками ничего экспортировать не нужно.

Порядок величин: около **3900 тестов, ~13 минут**.

### ⚠️ Интерпретатор — `backend/.venv`, не корневой

Виртуальных окружения два, и в корневом **нет `pytest-django`**. Запуск им даёт
лавину ошибок:

```
django.core.exceptions.ImproperlyConfigured: Requested setting INSTALLED_APPS
```

Выглядит как поломка импортов по всему проекту. На деле — не тот питон.
Признак в выводе: `PytestConfigWarning: Unknown config option: DJANGO_SETTINGS_MODULE`.

Правильный путь: `backend/.venv/Scripts/python.exe`.

### Почему отдельный порт

`pytest-django` создаёт и удаляет базу через `CREATE DATABASE` /
`DROP DATABASE`. Через transaction-пул PgBouncer это не проходит. Плюс порт
`:5432` на хосте обычно занят нативным Windows-Postgres.

`max_connections` у тестовой базы поднят до 300: длинная сюита с тестами
`transaction=True` под дефолтной сотней упирается в лимит к концу прогона.

### Две засады с портом

Обе выглядят как «pytest завис»:

1. **`docker restart` контейнера БД** — пересоздаёт его **без публикации
   порта**. Поднимайте только через compose.
2. **Порт забрал WinNAT** — после перезапуска Windows резервирует куски
   динамического диапазона. Симптом при старте контейнера:
   `bind: An attempt was made to access a socket in a way forbidden by its access permissions`.

Проверка резерваций и обход:

```powershell
netsh interface ipv4 show excludedportrange protocol=tcp
$env:DB_HOST_PORT='15432'
docker compose -f docker-compose.test-local.yml up -d db
$env:TEST_DB_PORT='15432'
```

Диагностика: `docker port <контейнер-БД>` должен показать проброс на хост.
Если видно только `5432/tcp` — порт не опубликован.

Подробнее — [03-data-layer.md](03-data-layer.md), раздел 6.

---

## 2. Мета-тесты: сторожа архитектуры

Живут в `backend/apps/core/tests/` и падают в CI, а не на код-ревью.

| Тест | Что стережёт |
|---|---|
| `test_app_isolation.py` | Домен не импортирует чужие `models`/`services`; нет междоменных FK |
| `test_invariants.py` | Каждая Celery-задача начинается с `require_service` |

`test_invariants.py` проверяет **разбором AST**, а не поиском по строке:
обмануть его комментарием не выйдет. Смысл — выключенный домен не должен
продолжать фоновую работу только потому, что закрыт его HTTP-вход.

Прочие сторожа там же: `test_api_view.py`, `test_service_gate.py`,
`test_admin_gate.py`, `test_validation_envelope.py`.

---

## 3. Фронтенд

```bash
cd frontend
npx tsc --noEmit -p tsconfig.json      # типы
npm test                               # vitest
npx vitest run <файл> -t "<имя>"       # точечно
npm run lint
```

Связка `tsc --noEmit` + `npm test` — самый быстрый способ убедиться, что
правка ничего не сломала.

### i18n в тестах — настоящий

`frontend/src/test/setup.ts` поднимает i18next **с реальными русскими
ресурсами**, а не с пустыми.

Следствие: тест, ищущий элемент по подписи, найдёт **перевод из файла**, а не
запасной текст из кода. Расходятся — тест падает, и это его работа: он ловит
регресс «ключ есть, перевод не тот».

### Полифиллы под Radix

`setup.ts` подкладывает то, чего нет в jsdom: `ResizeObserver`,
`IntersectionObserver`, `matchMedia`, Pointer Capture, `scrollIntoView`. Без
них компонентные тесты не проходят дальше первого открытия выпадающего списка.

### Сторож маршрутов

`frontend/src/app/routing/routeDefinitions.test.ts` роняет сборку при
дубликате пути в `protectedRoutes`. Дубликат молча снимает защиту с маршрута —
так уже терялись `requiresRole` у `/admin/*` и `/hr/*`.

---

## 4. E2E

```bash
cd frontend
npm run test:e2e
```

⚠️ Chromium в окружении **не установлен**. Запускайте с
`{ channel: 'msedge' }` — Edge есть на Windows-хосте.

---

## 5. Известные падения

Их стоит знать, чтобы не искать несуществующую регрессию.

**`test_board_defaults_to_today`**
(`backend/apps/tasks/tests/test_daily_reports_api.py`)
падает **ночью**. Тест пишет отчёт на `dt.date.today()` — локальную дату
машины, а эндпоинт при `TIME_ZONE = "UTC"` берёт `timezone.localdate()`, то
есть дату по UTC. В Алматы (UTC+5) с полуночи до пяти утра это разные даты, и
доска возвращается пустой. Днём проходит. Дефект теста, не кода.

**Тесты Т-2 на полях сертификатов.** Миграция
`backend/apps/hr/migrations/0016_remove_employeecard_certs.py` удалила секцию
«Сертификаты/СРО», а тесты и фронт её ещё ждут. Разбор —
[domains/hr.md](domains/hr.md), раздел 8.

**Ошибки ограничений в логах Postgres при прогоне `mail`.** Строки вида
`ck_email_accounts_type` — **нормально**: это тесты, проверяющие, что
ограничения срабатывают.

---

## 6. Порядок при отладке

1. Тесты вообще не запускаются → интерпретатор (`backend/.venv`).
2. Запускаются и виснут → порт тестовой БД.
3. Падает много и одинаково → мета-тест поймал нарушение инварианта, читайте
   его сообщение.
4. Падает один и странно → сверьтесь с разделом 5, вдруг известное.

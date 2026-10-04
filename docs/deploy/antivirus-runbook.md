# Антивирус загрузок (ClamAV) — включение и эксплуатация

Модуль БЗО, этап 7 A (A7.4, D-31, D-S7-6). По умолчанию антивирус **выключен**
(`ANTIVIRUS_CLAMD_HOST` пуст): файлы принимаются без проверки. Включение на
бою — отдельным решением и отдельным окном, по этому ранбуку; в выкатку модуля
оно не входит.

Что проверяется при включённом сканере: документы подсистемы `apps.files`
(scope `file_object`), сканы договорного контура и любой неизвестный scope
(`generic`), PDF шагов согласования (`signoff_doc`). Аватарки, чат, новости,
HR-документы и вложения задач — нет (`ScopePolicy.antivirus`).

Поведение: угроза — **422 `E-FIL-08`** (+ событие `file_rejected` в журнале
файла); сканер включён, но молчит — **503 `E-SYS-01`** (файл без проверки не
принимается, fail-closed; это не настраивается).

## 1. Предусловия

- Память: сервис `clamav` держит в памяти ~1,5 ГБ сигнатур; лимит контейнера в
  compose — 3 ГБ (при перезагрузке баз clamd на время держит две копии). На
  хосте должно быть свободно не меньше 3 ГБ.
- Сеть: контейнеру нужен выход к `database.clamav.net` (https). Первая закачка —
  ~300 МБ.
- Порт clamd `:3310` наружу не публикуется — только внутри сети стека.

## 2. Включение

1. В боевой `.env`:

   ```
   ANTIVIRUS_CLAMD_HOST=clamav
   # необязательно (значения по умолчанию):
   # ANTIVIRUS_CLAMD_PORT=3310
   # ANTIVIRUS_TIMEOUT=30      # таймаут на всю проверку файла (подключение, передача, ответ),
   #                           # а не на операцию сокета; меньше `proxy_read_timeout` загрузок
   #                           # в nginx (45s) и gunicorn 60
   # CLAMAV_DATABASE_MIRROR=   # только при 403 — см. §4
   ```

2. Поднять сервис профилем и перечитать backend (`backend-web`, `backend-asgi`,
   `backend-worker` — переменная нужна всем, кто принимает файлы):

   ```bash
   docker compose --profile antivirus up -d clamav
   docker compose up -d backend-web backend-asgi backend-worker
   ```

   Профиль `antivirus` надо указывать при **каждом** `up`, иначе сервис
   `clamav` не стартует (и, будучи в списке, останется остановленным).

## 3. Первый старт — загрузки получают 503

Пока `freshclam` качает базы (минуты, до ~10), clamd не отвечает. В это время
**загрузка документов отвечает 503** «проверка на вирусы сейчас недоступна» —
так задумано. Включать вне часов пиковой нагрузки; дождаться `healthy`:

```bash
docker inspect --format '{{.State.Health.Status}}' $(docker compose ps -q clamav)
# starting → healthy
```

`starting` допустим до 10 минут (`start_period: 600s`); после — `unhealthy`
значит, что базы не скачались: смотреть `docker compose logs clamav`.
Базы лежат в томе `clamav_db` — перезапуск контейнера их не перекачивает.

## 4. База не качается: 403 от `database.clamav.net`

CDN ClamAV отдаёт базы не во все страны. Признак — в логах freshclam
`403` / `Forbidden`. Лечение — зеркало: в `.env`

```
CLAMAV_DATABASE_MIRROR=<хост зеркала>
```

(значение — имя хоста зеркала, как у штатного `database.clamav.net`; оно уходит в `DatabaseMirror` freshclam), затем
`docker compose --profile antivirus up -d clamav`. Сверить, что именно
попало в конфиг freshclam:

```bash
docker compose exec clamav grep -E '^(DatabaseMirror|PrivateMirror)' /etc/clamav/freshclam.conf
```

Образ дописывает значение переменной строкой `DatabaseMirror` к уже
имеющимся; будет ли freshclam после 403 переходить к следующему зеркалу, здесь
не проверено — смотрите логи после перезапуска. Если база не качается и с
зеркалом, у freshclam для своего (частного) источника есть отдельная
директива `PrivateMirror` — её можно подложить конфигом (в образе такой
переменной нет). Пустое значение `CLAMAV_DATABASE_MIRROR` не ставить —
используется умолчание.

## 5. Проверка

1. `docker inspect --format '{{.State.Health.Status}}' $(docker compose ps -q clamav)` →
   `healthy`.
2. Админ-панель инфраструктуры (`/admin`) — ресурс «ClamAV» зелёный (PING →
   `PONG`; при пустом `ANTIVIRUS_CLAMD_HOST` ресурса нет).
3. **EICAR через панель файлов.** Создать текстовый файл `eicar.txt` с одной
   строкой — стандартной тестовой строкой EICAR (ищется на eicar.org; в репозитории
   её намеренно нет целиком) — и загрузить его документом заявки/договора.
   Ожидание: **422 `E-FIL-08`**, «антивирус обнаружил угрозу». Чистый PDF —
   принимается. (Расширение `.txt` — чтобы тип файла не отсёк загрузку раньше
   проверки; если тип документа текст не допускает — использовать любой
   допустимый тип, сигнатура ищется по содержимому.)
4. Метрика `htqweb_antivirus_scans_total{verdict}` (панель «Антивирус
   загрузок» дашборда **HTQWeb Business**): после п.3 растёт `infected`, после
   чистой загрузки — `clean`.
5. Живой тест против настоящего clamd — **на стенде** (`test-local`), не в
   боевом `backend-web`: тест прогоняет EICAR через конвейер и увеличит боевую
   метрику `verdict="infected"` (дальше — ложный всплеск на панели):

   ```bash
   docker compose -f docker-compose.test-local.yml --profile antivirus up -d --no-deps clamav
   docker compose -f docker-compose.test-local.yml exec -e ANTIVIRUS_E2E_HOST=clamav \
     backend-web python -m pytest -q -p no:cacheprovider apps/core/tests/test_antivirus_live.py
   ```

## 6. Наблюдаемость

- Алерт **«Антивирус недоступен»** (`htqweb-antivirus-unavailable`): рост
  `verdict="unavailable"` за 10 минут — загрузки отклоняются 503. Причины по
  частоте: контейнер ещё качает базы (§3), контейнер упал/`unhealthy`, упёрлась
  память, вышел таймаут на всю проверку файла (`ANTIVIRUS_TIMEOUT`).
- Серия `unavailable` появляется только у включённого сканера и только при
  попытках загрузки: ночью без загрузок алерт молчит и при мёртвом clamd —
  ориентируйтесь на `healthy` и панель инфраструктуры.

## 7. Откат

Убрать `ANTIVIRUS_CLAMD_HOST` (пусто) и перечитать backend — проверка
выключена сразу, файлы принимаются без неё. Сам контейнер можно остановить:
`docker compose stop clamav` (том с базами остаётся).

# Чеклист выкатки: перевод компаний на поддомены

Источник: `docs/plans/2026-09-22-block-i2-spec.md` §S5, §8. Блок I.2
переводит вход с голого домена `htq.group` на короткие поддомены
(`htq.htq.group`, `hts.htq.group`, `keg.htq.group`, `group.htq.group`).

**Гейты и поддомены неразделимы.** Блок I поставил гейты
`api_view(module=, level=)`, которым нужен контекст компании. На голом
домене контекста нет — `permission_level` отвечает `none` всем, кроме
суперпользователя, то есть без поддоменов гейты блока I закрывают
платформу целиком. И наоборот: без гейтов поддомены ничего не защищают —
это просто разные адреса тех же открытых ручек. Выкатывать одно без
другого нет смысла: код блоков I + I.2 и перевод на поддомены — **один
образ, одно окно**.

Шаги 1–4 — подготовка, без кода, можно сделать заранее (голый домен
продолжает работать как сегодня). Шаги 5–8 — внутри окна выкатки
(трафик закрыт).

## Предпроверка до окна: слаги-коллизии

Миграция `backend/apps/companies/migrations/0006_seed_company_subdomains.py`
проставляет псевдонимы `htq`, `hts`, `keg`, `group` компаниям со слагами
`hi-tech-qazaqstan`, `hi-tech-systems`, `kazakhstan-engineering-group`,
`hi-tech-group` через `.update()` — **мимо** валидации `Company.clean()`
(`backend/apps/companies/models.py`), которая в обычном порядке запрещает
компании чужой слаг, совпадающий с чужим псевдонимом.

Резолв метки хоста (`apps/companies/interface.py::resolve_host_label`)
сначала ищет совпадение по `subdomain`, и только потом — по `slug` (и то
только если у найденной компании `subdomain` пусто). Если на бою ДО этой
миграции уже существует компания со слагом `htq`, `hts`, `keg` или
`group` (отличная от той, что получает этот псевдоним по списку выше), то
после миграции она станет недостижимой: её адрес по слагу заберёт
компания-владелец псевдонима, а резолв её саму не найдёт ни по слагу
(есть более приоритетная компания с таким `subdomain`), ни по псевдониму
(у неё его нет).

Проверка — до окна, на боевой БД:

```bash
cd backend
../.venv/Scripts/python.exe manage.py shell -c "
from apps.companies.models import Company
bad = Company.objects.filter(slug__in=['htq', 'hts', 'keg', 'group'])
for c in bad:
    print(c.slug, c.name, c.subdomain)
"
```

Если команда ничего не напечатала — коллизий нет, можно продолжать.

Если напечатала строку — **остановиться**. Компания со слагом из списка
не является той компанией, что должна получить этот псевдоним (сверить
по `SUBDOMAINS` в миграции 0006: `hi-tech-qazaqstan → htq`,
`hi-tech-systems → hts`, `kazakhstan-engineering-group → keg`,
`hi-tech-group → group`). Псевдоним у неё нужно сменить (или явно
назначить ей другой слаг) ДО выкатки — `PATCH /api/companies/v1/<slug>`
платформенным администратором либо `manage.py shell`. Миграция 0006
идемпотентна и трогает только пустой `subdomain`, поэтому её саму
менять не нужно — правится только конфликтующая компания.

## Шаги 1–4: подготовка (заранее, без кода)

### 1. Cloudflare DNS

Добавить запись `*` (wildcard) — A-запись на `77.243.80.208` либо CNAME
на `htq.group` — с **включённым проксированием** (оранжевое облако).
Universal SSL Cloudflare покрывает `*.htq.group` одного уровня, чего
достаточно: псевдонимы `htq`, `hts`, `keg`, `group` — тоже одного уровня
(`<метка>.htq.group`).

### 2. Origin-сертификат на сервере

Путь на сервере и в nginx — `/etc/htq-certs/origin.pem` /
`/etc/htq-certs/origin.key` (`infra/nginx/default.conf`, смонтирован в
`docker-compose.yml` томом `/etc/htq-certs:/etc/htq-certs:ro`).

Проверить SAN сертификата:

```bash
openssl x509 -in /etc/htq-certs/origin.pem -noout -ext subjectAltName
```

В выводе обязаны быть оба: `htq.group` и `*.htq.group`. Если нет —
перевыпустить в панели Cloudflare (SSL/TLS → Origin Server → Create
Certificate, hostnames `htq.group` и `*.htq.group`) и заменить оба файла
на сервере.

### 3. Режим SSL/TLS в Cloudflare

Выставить «Full (strict)» (не «Flexible» и не «Full») — иначе Cloudflare
не проверяет origin-сертификат сервера при обращении к нему.

### 4. `.env`

```
SFU_ALLOWED_ORIGINS=https://htq.group,https://*.htq.group
```

Значение уходит в SFU как `SIGNALING_ALLOWED_ORIGINS`
(`docker-compose.yml`, три места:
`backend-web`/`backend-asgi` не читают эту переменную, читает контейнер
`sfu`), парсится `sfu/src/config.ts::parseAllowedOriginPatterns` —
шаблон с одним `*` поддерживается (тот же механизм, что уже используют
дефолтные `https://*.instatunnel.my`).

`PUBLIC_BASE_URL` — **не менять**, должен уже быть `https://htq.group`
(голый домен, **со схемой**, **без `www`**). Это важно: корень адреса
компании (`apps/companies/interface.py::public_url`) и список доверенных
CSRF-origin'ов (`backend/htqweb/settings/base.py::_trusted_origins`) оба
берут его через `urlsplit(...).netloc` и подставляют `<метка>.<netloc>`.
Если тут окажется `https://www.htq.group`, ссылки компаний будут вида
`https://htq.www.htq.group` — рабочий поддомен `www.htq.group` для этого
не заведён. Без схемы (`htq.group` без `https://`) `urlsplit` не
распознаёт хост, и `public_url`/`_trusted_origins` откажутся от значения
целиком.

## Шаги 5–8: окно выкатки (трафик закрыт)

### 5. Выкатить код блоков I + I.2

Новый образ `backend-web`/`backend-asgi`/`backend-worker` со всеми
миграциями. При старте контейнера (`RUN_MIGRATIONS` в
`docker-compose.yml` по умолчанию `1` — `${RUN_MIGRATIONS:-1}`, ни
`.env`/`.env.example`/`.env.production` его не переопределяют, поэтому
убедиться явно, что флаг включён) `docker-entrypoint.sh` сам вызывает
`manage.py migrate_shared` — общие аппки: роли `hr-*`
(`access/0005`–`0008`), поле `Role.company_slug`, поле
`Company.subdomain` и миграция данных, проставляющая псевдонимы
(`companies/0005`–`0006`).

`migrate_shared`, а не голый `migrate` — тенантные аппки (`hr`, `tasks`,
`contracts`, `signoff`) им не трогаются, их доводит следующий шаг.

### 6. `migrate_companies`

```bash
cd backend
../.venv/Scripts/python.exe manage.py migrate_companies
```

Доводит схемы `co_<slug>` каждой действующей компании: миграции
тенантных аппок, участвующие в этом блоке (данные — no-op, схема уже
готова shared-миграциями). Пересобирает сводки холдинга.

### 7. Перенос прав блока I

```bash
cd backend
../.venv/Scripts/python.exe manage.py access_backfill_positions --dry-run
# прочитать сводку: конфликты (должность уже несёт другую роль hr-*)
# и расхождения по держателям — разбирает кадровик до следующей команды
../.venv/Scripts/python.exe manage.py access_backfill_positions
# повторный прогон обязан показать «создано сейчас 0»
../.venv/Scripts/python.exe manage.py access_backfill_basic
../.venv/Scripts/python.exe manage.py tenancy_status --json --exact  # слепок после
```

Порядок обязательный — без ролей `hr-*` и `employee-basic` у держателей
после включения гейтов у них не будет прав ни на что.

### 8. Проверка перед открытием трафика

```bash
curl -sI https://htq.htq.group/ | head -1
# 200

curl -s -o /dev/null -w '%{http_code}\n' https://htq.htq.group/api/companies/v1/me
# 401, не 404 — на каноническом хосте компании (псевдоним "htq") middleware
# резолвит контекст и пропускает запрос дальше; MyCompaniesView стоит под
# api_view(auth="jwt") и без токена отвечает 401.

curl -s -o /dev/null -w '%{http_code}\n' https://hi-tech-qazaqstan.htq.group/api/companies/v1/me
# 404 — у компании с этим слагом есть псевдоним ("htq"), поэтому
# resolve_host_label по слагу её больше не находит (условие
# subdomain__isnull=True не выполняется); CompanyContextMiddleware
# отвечает 404 ДО того, как запрос доходит до проверки токена
# (backend/htqweb/middleware/company_context.py, стоит в MIDDLEWARE
# раньше AuthenticationMiddleware и раньше диспетчера api_view).
```

Дополнительно (руками, не curl):

- вход на `https://htq.group/login` → после входа при нескольких
  компаниях — экран выбора компании (`/companies/choose`), при одной —
  немедленный редирект на её хост;
- переключение компаний через `CompanySwitcher` уводит на
  `<псевдоним>.htq.group`;
- конференция на `https://htq.htq.group` — сигналинг проходит проверку
  Origin (шаг 4).

Если что-то из проверки не сошлось — трафик **не открывать**, откатить
образ и разбирать причину: 404 вместо 401 на `htq.htq.group` значит,
что метка `htq` не резолвится (проверить, что миграция 0006 применилась
и `Company.subdomain` заполнен); 200 вместо 404 на слаге с псевдонимом
значит, что резолв слага не учитывает `subdomain__isnull=True` (регресс
в коде задачи 4).

### Открыть трафик

Только после того, как шаг 8 прошёл полностью. Пользователи приходят на
`htq.group`, входят и штатно попадают на свою компанию.

## Разработка

На локальном стенде (`docker-compose.test-local.yml`, Vite HMR
`localhost:3000`) отдельного DNS не нужно — Vite слушает `0.0.0.0` с
`allowedHosts: true`, а браузеры сами резолвят `*.localhost` в
`127.0.0.1`. Войти можно двумя способами:

- на голом `http://localhost:3000/login` — после входа откроется экран
  выбора компании и уведёт на `http://<метка>.localhost:3000/...`;
- сразу на `http://<метка-или-слаг>.localhost:3000/login` — у компаний
  на свежем стенде псевдонимов нет, поэтому метка совпадает со слагом.

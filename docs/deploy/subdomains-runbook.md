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

## Предпроверка до окна: членство администраторов

На голом домене любой защищённый маршрут уводит на экран выбора компании,
а экран без членства говорит «нет доступа» и предлагает только выход. До
блока I.2 платформенный администратор открывал `/admin/companies` и прочее
прямо на голом домене; после выкатки суперпользователь без членства
заперт — останется только django-admin. Проверка — до окна, на боевой БД:

```bash
cd backend
../.venv/Scripts/python.exe manage.py shell -c "
from django.contrib.auth import get_user_model
from apps.companies.models import CompanyMembership
members = set(CompanyMembership.objects.values_list('user_id', flat=True))
for u in get_user_model().objects.filter(is_superuser=True) | get_user_model().objects.filter(is_staff=True):
    if u.id not in members:
        print(u.id, u.username)
"
```

Пусто — у каждого администратора есть членство хотя бы в одной компании.
Иначе выдать до окна: `manage.py company_grant --company <slug> --user <username>`
(идемпотентна).

Если напечатала строку — **остановиться**. Компания со слагом из списка
не является той компанией, что должна получить этот псевдоним (сверить
по `SUBDOMAINS` в миграции 0006: `hi-tech-qazaqstan → htq`,
`hi-tech-systems → hts`, `kazakhstan-engineering-group → keg`,
`hi-tech-group → group`). Псевдоним у неё нужно сменить (или явно
назначить ей другой слаг) ДО выкатки — `PATCH /api/companies/v1/companies/<slug>`
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
`.env`, ни `.env.example` его не переопределяют, поэтому
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

Псевдонимы — у всех четырёх компаний после `migrate_shared` (и у тех, что
заведены позже `companies/0006` через `company_create --subdomain`):

```bash
cd backend
../.venv/Scripts/python.exe manage.py shell -c "
from apps.companies.models import Company
for c in Company.objects.order_by('slug'):
    print(c.slug, c.subdomain)
"
# ожидается: hi-tech-group group, hi-tech-qazaqstan htq,
# hi-tech-systems hts, kazakhstan-engineering-group keg — ни одного None
```

Пустой `subdomain` у компании из этого списка — компания осталась на адресе
по слагу; проставить `PATCH /api/companies/v1/companies/<slug>`
(`{"subdomain": "<метка>"}`) до открытия трафика.

Дополнительно (руками, не curl):

- вход на `https://htq.group/login` → после входа при нескольких
  компаниях — экран выбора компании (`/companies/choose`), при одной —
  немедленный редирект на её хост;
- на поддомене вы уже вошли: второго входа нет, открывается та страница,
  куда вы шли (refresh-cookie родительского домена меняется на access-токен
  до редиректа на `/login`);
- у каждого администратора есть членство хотя бы в одной компании (см.
  предпроверку выше);
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

**Share-ссылки, выданные до выкатки, перестанут открываться.** Фронт строил
их из адреса страницы, то есть на голом домене `htq.group`, а там нет
контекста компании: публичная страница ответит 404 «ссылка
недействительна». Предупредить тех, кто рассылал ссылки на оргструктуру и
карточки сотрудников, — выдать их заново уже с поддомена компании.

## Разработка

На локальном стенде (`docker-compose.test-local.yml`, Vite HMR
`localhost:3000`) отдельного DNS не нужно — Vite слушает `0.0.0.0` с
`allowedHosts: true`, а браузеры сами резолвят `*.localhost` в
`127.0.0.1`. Войти можно двумя способами:

- на голом `http://localhost:3000/login` — после входа откроется экран
  выбора компании и уведёт на `http://<метка>.localhost:3000/...`;
- сразу на `http://<метка-или-слаг>.localhost:3000/login` — у компаний
  на свежем стенде псевдонимов нет, поэтому метка совпадает со слагом.

## Блок L: гейт на шесть аппок платформы

Источник: [`docs/plans/2026-09-24-block-l-gate-remaining-apps-spec.md`](../plans/2026-09-24-block-l-gate-remaining-apps-spec.md)
§11. Блок L переводит `media_files` (модуль `media`), `conference`,
`messenger`, `mail`, `cms` и `approvals` под гейт `api_view(module=,
level=)`, снимая `admin=True`.

**Не раньше поддоменов: гейт считает уровень только в контексте компании**
— то же условие, что у гейтов блока I выше: без `X-HTQ-Company`
`permission_level` отвечает `none` всем, кроме суперпользователя.

**Образ с гейтом не пускать под трафик до шага 3**: гейт действует с
первого запроса, а роль `services-admin` администраторам выдаёт только
шаг 3 — в промежутке `/admin/chats`, `/admin/mailboxes`, `/manage/*`,
`/requests/projects` ответят им 403.

1. `manage.py migrate_shared` — применяет `access/0011`, `access/0012`
   (`access` — общая аппка, `migrate_companies` не нужен).

   1а. Сразу после — три проверки на боевой БД (только чтение):

   ```bash
   cd backend
   ../.venv/Scripts/python.exe manage.py shell -c "
   from django.db.models import Q
   from apps.access.models import RoleAssignment, RolePermission
   from apps.companies.models import CompanyMembership
   # (а) членства без employee-basic: такой сотрудник после выкатки теряет
   #     мессенджер, файлы, заявки, историю встреч (личная почта остаётся —
   #     её ручки самообслуживание). Лечение — access_backfill_basic.
   basic = set(RoleAssignment.objects.filter(role__code='employee-basic')
               .values_list('company_slug', 'user_id'))
   missing = [(m.company.slug, m.user_id) for m in CompanyMembership.objects
              .filter(company__status='active').select_related('company')
              if (m.company.slug, m.user_id) not in basic]
   print('(а) членств без employee-basic:', len(missing), missing[:50])
   # (б) роли из редактора с узлами шести модулей: заведённые ДО блока L,
   #     они начинают действовать в момент выкатки (могут открыть кому-то
   #     cms:write или admin модуля). Просмотреть каждую строку.
   q = Q()
   for m in ('media', 'conference', 'messenger', 'mail', 'cms', 'approvals'):
       q |= Q(node=m) | Q(node__startswith=m + '.')
   for r in (RolePermission.objects.filter(q)
             .exclude(role__code__in=('employee-basic', 'services-admin'))
             .select_related('role').order_by('role__code', 'node')):
       flags = ''.join(f for f, on in (('V', r.can_view), ('C', r.can_create),
                                      ('E', r.can_edit), ('D', r.can_delete)) if on)
       print('(б)', r.role.code, r.role.company_slug or '-', r.node, flags)
   # (в) employee-basic, правленная на бою в редакторе: 0011 только ДОБАВЛЯЕТ
   #     строки (get_or_create) и уже существующую строку с меньшими
   #     признаками не поднимет. Каждое расхождение — поправить в редакторе.
   want = {'media.files': 'VC', 'messenger.rooms': 'VCE',
           'conference.history': 'V', 'conference.transcripts': 'V',
           'approvals.projects': 'V', 'approvals.templates': 'V',
           'approvals.reference': 'V'}
   have = {r.node: ''.join(f for f, on in (('V', r.can_view), ('C', r.can_create),
                                           ('E', r.can_edit), ('D', r.can_delete)) if on)
           for r in RolePermission.objects.filter(role__code='employee-basic', node__in=want)}
   for node, flags in want.items():
       if have.get(node) != flags:
           print('(в) employee-basic', node, 'на бою:', have.get(node), 'ожидалось:', flags)
   "
   ```

   Пустые (б) и (в) и ноль в (а) — можно дальше. Иначе: (а) —
   `manage.py access_backfill_basic`; (б) — решить по каждой роли до
   открытия трафика; (в) — выровнять строку роли в редакторе ролей.
2. `manage.py access_backfill_services_admin --dry-run` — прочитать
   сводку: сколько администраторов, в каких компаниях, кто без членства.
3. `manage.py access_backfill_services_admin`.
4. Открыть трафик. Проверить: сотрудник — мессенджер, почта, заявки,
   файлы; администратор — `/admin/chats`, `/admin/mailboxes`,
   `/manage/news`, `/requests/projects`.

Откат — предыдущий образ; строки `employee-basic` и роль `services-admin`
безвредны для старого кода (он их не спрашивает).

После выкатки: `services-admin` открывает экраны, но внутренние проверки
`is_elevated` в сервисах остались (спека §10) — новому администратору
сервисов, пока они не перенесены на узлы, нужен и `is_staff`, иначе часть
действий внутри экрана (правка проекта заявок, глобальные шаблоны, чужие
встречи в истории) ответит 403.

## Архив компании — только чтение

Спека — [2026-09-25-archive-read-only-spec.md](../plans/2026-09-25-archive-read-only-spec.md).
Миграций БД нет; порядок относительно поддоменов не важен — без заголовка
компании режим не включается.

1. `manage.py tenancy_status` — слепок до.
2. `manage.py migrate_companies` — доведёт схемы архивных компаний, отставшие
   со дня их архивации (до этой выкатки их не мигрировал никто). Архивных
   компаний нет — шаг ничего не меняет, но остаётся в чеклисте.
3. Проверка на стенде: заархивировать одну из компаний `seed_group_demo`
   (`manage.py company_archive --company <slug>`), затем:
   - суперпользователь открывает её поддомен — баннер «Компания в архиве —
     только чтение», списки читаются; кнопки, скрытые по уровню, исчезли,
     оставшиеся (без проверки прав) дают 403 и тост «Нельзя изменить:
     компания в архиве…» — это ожидаемо; аватары, документы и вложения
     открываются (анонимные ручки общих аппок на архиве не закрыты);
   - за nginx заголовок компании берётся из хоста, а не из `-H`
     (`proxy_set_header X-HTQ-Company $company` в `infra/nginx/default.conf`),
     поэтому проверка — по хосту поддомена:
     `curl -X POST https://<метка>.<корень>/api/hr/v1/departments/ -H 'Authorization: Bearer <токен суперпользователя>'`
     → 403 `{"code": "company_archived"}`;
   - участник этой компании: вход на её поддомене — 403 (токен архива ему не
     выдаётся); с токеном, выданным до архивации, — 404 «Компания не найдена»
     на чтение;
   - `manage.py company_restore --company <slug>` — запись снова проходит.
   Статус компании кэширован на 5 с, поэтому каждую проверку после
   `company_archive`/`company_restore` делать не раньше чем через 5 с.
4. `manage.py tenancy_status` — слепок после; расхождение — стоп-сигнал.

## Банкротство компании

Спека — [2026-09-26-company-bankruptcy-spec.md](../plans/2026-09-26-company-bankruptcy-spec.md).
Миграций БД нет (поле `Company.successor` было в модели с подпроекта 1).
Операция — только суперпользователь; то же делает кнопка «Банкротство…» в
реестре компаний (с предпросмотром).

1. `manage.py tenancy_status` — слепок до.
2. `manage.py company_bankrupt --company X --successor Y --dry-run` — прочитать
   сводку: сколько участников X с действующей учёткой, сколько из них
   **получат доступ** к Y и сколько уже там состоят. Ничего не меняет.
3. `manage.py company_bankrupt --company X --successor Y` — участники X
   получают членство в Y (с базовой ролью `employee-basic`), `X.successor = Y`,
   X уходит в архив «только чтение», сводки холдинга пересобираются. Повтор
   той же пары безопасен — довыдаст недостающие членства; другой преемник у
   уже закрытой X — отказ. Если упала пересборка сводок (`holding_stale`),
   членства и архив уже сохранены — сводки доводит `manage.py migrate_companies`.
4. `manage.py tenancy_status` — слепок после; расхождение — стоп-сигнал.
5. Кадровику преемника — завести карточки перенесённым людям: переносится
   **только членство**, карточки `hr`, техника и договоры остаются в архиве X,
   и до кадровика у людей в Y только то, что даёт `employee-basic`.

Откат: `manage.py company_restore --company X` возвращает X из архива и
снимает преемника; выданные в Y членства не отзываются — лишние снимаются
экраном участников Y руками.

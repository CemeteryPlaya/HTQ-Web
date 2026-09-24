# Блок L — гейт модуля на шесть оставшихся аппок (спека)

**Дата:** 2026-09-24
**Ветка:** `sanzhar`
**Основание:** [сверка рефакторинга](2026-09-23-group-structure-verification.md) §6.1/§6.4 п. 5
(«ещё 7 аппок без гейта»), [план блока K](2026-09-24-post-refactoring-leftovers.md) раздел
«Не входит», [roadmap](2026-09-14-group-structure-roadmap.md) §4 строка «Роли».
**Прецедент:** [блок I](2026-09-17-block-i-single-rbac.md) — тот же приём для
`hr/users/companies/access/tasks`.

## 1. Цель и критерий успеха

Доступ к ручкам `approvals`, `cms`, `conference`, `mail`, `media_files` (модуль
`media`) и `messenger` задаётся ролями `apps.access`, а не флагами токена и не
зашит в код. После блока его можно выдать и снять в редакторе ролей, как в
`hr`/`tasks`: забрать у должности мессенджер, дать контент-менеджеру новости,
не делая его администратором платформы.

Критерий успеха:
1. **Ни один сотрудник не теряет доступа, который у него есть сегодня** (решение
   заказчика 24.09 «перенести как есть»). Сужать доступ потом — правкой ролей в
   редакторе, без кода.
2. Каждая ручка шести аппок либо под `api_view(module=…, level=…)`, либо в
   реестре самообслуживания с причиной, либо `auth=None`; сторож
   `apps/access/tests/test_gate.py` требует это так же, как для пяти
   переведённых аппок.
3. Флаг `admin=True` в шести аппках снят; администраторы, которые пользуются
   этими экранами сегодня по `is_staff`, получают роль при переносе.
4. Закрыта найденная дыра в приглашениях конференции (§7).

## 2. Что есть сегодня

Ручка — один вызов `api_view(...)` (единица сторожа `test_gate.py`); функции-
диспетчеры из `urls.py` без своего `api_view` ручками не считаются.

| Аппка (модуль) | Ручек | `admin=True` | `auth=None` | Строго свои данные |
|---|---|---|---|---|
| `media_files` (`media`) | 6 | 1 | 3 | 0 |
| `conference` | 12 | 0 | 7 | 0 |
| `messenger` | 26 | 3 | 2 | 3 |
| `mail` | 42 (+3 вебхука `auth=None`) | 20 | 1 | 20 |
| `cms` | 39 | 25 | 9 | 0 |
| `approvals` | 46 (+SSE `stream` вне `api_view`) | 7 | 0 | 0 |

- `admin=True` пускает по `token.is_elevated` = `is_admin or is_staff or
  is_superuser` (`htqweb/authn/payload.py`), без единой роли.
- Остальные ручки сотрудников — `auth="jwt"`; большинство несёт свою
  не-ролевую проверку (участник комнаты, `conference.services.access.may_view`,
  назначенный согласующий, владелец файла). Совсем без проверок кроме входа —
  чтение проектов/шаблонов/справочников/заявок `approvals`, поиск и присутствие
  в `messenger`, приглашения в конференцию `cms`.
- Узлы реестра всех шести модулей уже объявлены (`apps/<app>/access_functions.py`);
  `employee-basic` (`access/0004`) заранее несёт часть из них.
- `core` — не модуль прав: его нет в `apps.core.models.KNOWN_SERVICES`, гейт
  `module="core"` невозможен. Его ручки инфраструктуры остаются под
  `admin=True`, `/health` и `/metrics` — без `api_view` намеренно. **`core` вне
  блока.**

## 3. Решения заказчика (24.09.2026)

1. **Перенести как есть** — роли фиксируют сегодняшний доступ.
2. **`admin=True` заменяется ролью**: ручка встаёт под `module=…, level=…`,
   флаг снимается.
3. **Текущим `is_staff`/`is_admin` роль выдаётся при переносе** командой, а не
   руками после выкатки.
4. **WebSocket мессенджера и SSE `approvals/stream` — вне блока** (§10).
5. **Вариант В**: ручки со строго своими данными — в реестр самообслуживания с
   причиной `self`; все остальные ручки сотрудников — под гейт, их собственная
   проверка остаётся поверх. Та же конвенция, что у кадров в блоке I.

## 4. Правила классификации

- **R-none.** `auth=None` — не трогать, в реестр не вносить (сторож такие блоки
  пропускает, запись в реестре для них валит `unknown_exempt`).
- **R-self.** Ручка работает строго с данными вызывающего — выборка по
  `request.token.user_id` без параметра на чужой объект, либо параметр
  пересекается с фильтром `user_id=` (доказывается строкой сервиса). →
  `SELF_SERVICE[<аппка>][<имя>] = "self"`.
- **R-read / R-write.** Любая другая ручка сотрудника → `level="read"`
  (чтение) или `level="write"` (запись), собственная проверка остаётся.
  Узлы-действия (`messenger.chats`, `conference.join`, `approvals.decisions`)
  по реестру несут только `view`, поэтому ручки «пользуюсь» над ними —
  `read`, даже если это POST (отправить сообщение, согласовать заявку).
- **R-admin.** Бывшая `admin=True` → `level="admin"`, КРОМЕ экранов, для
  которых фронт уже требует меньший уровень
  (`frontend/src/app/routing/routeDefinitions.ts`, `requires`): там уровень =
  требованию фронта. Сегодня это одно место — `/manage/home|news|contacts` →
  `cms:write`.

**Инвариант L1 — базовая роль ниже любой бывшей админской ручки.** Уровень
модуля — агрегат признаков по всему поддереву модуля (`depth.legacy_level`:
`delete` где угодно → `admin`, `create|edit` → `write`, `view` → `read`).
Поэтому:
- `employee-basic` не несёт `delete` ни на одном узле шести модулей;
- уровень `employee-basic` в каждом модуле строго ниже уровня любой ручки,
  бывшей `admin=True` (для `cms` — ниже `write`, то есть `read`);
- удаление сотрудником своего (своё сообщение, выход из комнаты, отзыв своей
  заявки или решения) — `write` или `read`, не `admin`;
- ручка сотрудника, которой по смыслу нужна запись, но в модуле, где `write`
  занят бывшими админскими ручками (`cms`), встаёт под `read`, а защищает её
  собственная проверка (§7).

Итоговые уровни `employee-basic` закрепляются тестом ровно такими:

| Модуль | Уровень `employee-basic` | Почему |
|---|---|---|
| `media` | `write` | загрузка файлов и подписанные ссылки сегодня у всех; админская ручка одна — `admin` |
| `conference` | `read` | у сотрудника только чтение своих встреч |
| `messenger` | `write` | создание комнат и управление составом своих групп сегодня у всех; модерация — `admin` |
| `mail` | `read` | личная почта — самообслуживание; ящики — `admin` |
| `cms` | `read` | контент (`write`) — только редакторам |
| `approvals` | `write` | подача и правка своих заявок; проекты, справочники — `admin` |

## 5. Роли

### 5.1 `employee-basic` — расширение (миграция `access/0011`)

Литералами (как `access/0004`, не читая реестр), только добавление строк
`RolePermission`, существующие не трогать:

| Узел | Признаки | Зачем |
|---|---|---|
| `media.files` | `view`, `create` | `upload_file`, `issue_signed_url` |
| `messenger.rooms` | `view`, `create`, `edit` | создание/правка/роспуск своих комнат, состав группы, правка и удаление своего сообщения |
| `conference.history` | `view` | история своих встреч |
| `conference.transcripts` | `view` | протокол своих встреч |
| `approvals.projects` | `view` | чтение проектов (сегодня всем) |
| `approvals.templates` | `view` | чтение шаблонов при подаче заявки |
| `approvals.reference` | `view` | опции справочников в форме заявки |

`cms` — без изменений (`cms.news: view` → `read`). `mail` — без изменений.
Держатели роли получают строки сразу (права считаются от роли) — отдельного
переноса для сотрудников не нужно. Миграция идемпотентна (`get_or_create`),
обратная — удаляет ровно эти строки.

### 5.2 `services-admin` — новая системная роль (миграция `access/0012`)

«Администратор сервисов»: `is_system=True`, `company_slug` пуст (общая).
Все узлы шести модулей со всеми применимыми признаками (литералами, по
`access_functions.py` на момент миграции):
`media.files`, `media.avatars` — `view,create,delete`; `conference.join` —
`view`; `conference.history`, `conference.recordings`, `conference.transcripts`
— `view,delete`; `conference.invites` — `view,create,delete`; `messenger.chats` —
`view`; `messenger.rooms` — `view,create,edit,delete`; `messenger.moderation` —
`view,delete`; `mail.messages` — `view`; `mail.mailboxes` — `view,create,edit,delete`;
`mail.server` — `view,edit`; `cms.news`, `cms.home_sections`,
`cms.contact_requests`, `cms.conference` — `view,create,edit,delete`;
`approvals.requests`, `approvals.templates`, `approvals.projects`,
`approvals.reference`, `approvals.stats` — `view,create,edit,delete`;
`approvals.decisions` — `view`. Агрегат — `admin` по всем шести модулям.

### 5.3 Перенос администраторов — `manage.py access_backfill_services_admin`

- Кому: пользователи `is_staff=True` и `is_superuser=False`, активные
  (`is_superuser` проходит гейт сам и роли не получает).
- Где: в каждой компании, где у пользователя есть `CompanyMembership`
  (`apps.companies.interface.user_company_slugs`); без членства — пропуск со
  строкой в сводке (токена на поддомен у такого пользователя всё равно нет).
- Что: `RoleAssignment(role=services-admin, scope_kind=COMPANY)` —
  `get_or_create`, идемпотентно; `--dry-run` печатает сводку «пользователь →
  компании», ничего не пишет; `--company SLUG` сужает.
- Дальше новые администраторы сервисов получают роль в редакторе. **`is_staff`
  сам по себе больше не открывает экраны шести аппок** — как в блоке I для
  кадров.
- Внутренние проверки `is_elevated` в сервисах (§10) остаются: снимать их —
  не задача блока.

## 6. Поручковое решение

Номера строк — на `4b4acbb`; план сверяет их заново. Имя — как его строит
`_qualified_name` сторожа.

### 6.1 `media_files` — модуль `media` (⚠️ не `media_files`: `module="media_files"` молча дал бы `none` всем)
- `write`: `upload_file` (своя проверка скоупов `authorize_scope_write` остаётся), `issue_signed_url` (`_can_access_private` остаётся).
- `admin`: `list_files` (было `admin=True`; узел `media.files`, признак `delete` — единственный администраторский признак модуля).
- `auth=None`: `download_file`, `download_variant`, `serve_raw_key`.

### 6.2 `conference`
- `read`: `overview`, `sessions`, `session_detail`, `session_events`, `session_transcript` (`may_view` остаётся; отказ по-прежнему 404).
- `auth=None`: `session_recording`, `session_poster`, пять `internal_*`.

### 6.3 `messenger`
- `read`: `_list_rooms`, `_get_room`, `users_presence`, `send_message`, `list_messages`, `mark_message_read`, `publish_typing`, `upload_attachment`, `get_user_keys`, `search_users`.
- `write`: `_create_room`, `_update_room`, `_delete_room`, `add_participants`, `_remove_participant`, `_set_participant_role`, `_edit_message`, `_delete_message` (проверки участника/админа группы/автора остаются).
- `admin`: `admin_list_rooms`, `admin_list_room_messages`, `admin_trigger_history_archive` (было `admin=True`; фронт `/admin/chats` уже требует `messenger:admin`).
- `self`: `unread_count`, `upload_keys`, `me`.
- `auth=None`: `serve_attachment`, `serve_attachment_thumb`.

### 6.4 `mail`
- `self` (20): `accounts_collection`, `account_set_default`, `account_sync`, `account_signature`, `account_detail`, `corporate_connect_info`, `_corporate_connect`, `_corporate_disconnect`, `_imap_connect`, `imap_account_password`, `oauth_status`, `oauth_accounts`, `oauth_connect`, `oauth_disconnect`, `list_emails`, `unread_counts`, `get_email`, `send_email`, `mark_as_read`, `save_draft` — сервис фильтрует по `request.token.user_id` («пользователь видит и правит ТОЛЬКО свои строки», докстринг `apps/mail/views.py`); план подтверждает каждую строкой сервиса.
- `read`: `_imap_connect_hint` (не читает данных пользователя).
- `admin` (20, было `admin=True`; фронт `/admin/mailboxes` требует `mail:admin`): `_list_mailboxes`, `_create_mailbox`, `_get_mailbox`, `_update_mailbox`, `_delete_mailbox`, `reset_mailbox_password`, `archive_mailbox`, `restore_mailbox`, `mailbox_status`, `mailbox_lookup`, `_get_mail_settings`, `_put_mail_settings`, `test_mail_connection`, `mailbox_coverage`, `_reconcile_report`, `_reconcile_apply`, `_list_aliases`, `_create_alias`, `delete_alias`, `set_forwarding`.
- `auth=None`: `oauth_callback`, три вебхука `apps/mail/webhooks.py`.

### 6.5 `cms`
- `write` (было `admin=True`; фронт `/manage/*` требует `cms:write`): обращения — `_list_contact_requests`, `contact_request_stats`, `_get_contact_request`, `_update_contact_request`, `_delete_contact_request`, `reply_contact_request`; новости и таксономия — `_create_news`, `_update_news`, `_delete_news`, `translate_news`, `_create_category`, `_update_category`, `_delete_category`, `_create_tag`, `_update_tag`, `_delete_tag`; главная — `_list_home_sections_admin`, `_create_home_section`, `_delete_home_section`, `_update_home_section`, `home_sections_reorder`, `home_items_collection`, `home_items_reorder`, `_update_home_item`, `_delete_home_item`.
- `read`: приглашения — `_create_conference_invite`, `_list_conference_invites`, `conference_invite_revoke`, `conference_invite_send` (инвариант L1: `write` в `cms` занят контентом; защищает их проверка §7).
- `open` (реестр самообслуживания, без гейта): `conference_config` — финальное ревью I-1, см. §9.3 (в исходной редакции спеки стоял в `read`).
- `auth=None`: `_create_contact_request`, `_list_news`, `news_by_slug`, `_get_news`, `_list_categories`, `_list_tags`, `home_sections_public`, `conference_invite_public`, `conference_invite_guest_token`.

### 6.6 `approvals`
- `read`: заявки — `_list_instances`, `_get_instance`; решения — `approve`, `reject`, `request_changes`, `recall`, `batch_approve` (проверка назначенного согласующего в `request_runtime.act` остаётся); проекты — `_list_projects`, `_get_project`, `_list_members`; шаблоны — `_list_templates`, `_get_template`, `get_version`; статистика — `stats_overview`, `stats_by_project`, `stats_by_template`, `stats_by_actor`, `stats_heatmap`; справочники — `list_sources`, `my_data_tables`, `get_source`, `list_rows`, `reference_options`.
- `write`: `_create_instance`, `_update_instance`, `submit_instance`, `resubmit_instance`, `cancel`; `_update_project`, `_add_member`, `remove_member` (`ensure_can_manage_project` остаётся); `_create_template`, `_update_template`, `_delete_template`, `deactivate_template`, `activate_template`, `publish_version`, `preview_template` (`ensure_can_manage_template` остаётся); `set_data_table_access` (`can_manage_data_table` остаётся).
- `admin` (было `admin=True`; фронт `/requests/projects|reference` требует `approvals:admin`): `_create_project`, `_delete_project`, `create_source`, `update_source`, `delete_source`, `add_row`, `delete_row`.
- `stream` (SSE) — вне блока.

## 7. Приглашения в конференцию — проверка организатора

Сегодня `_list_conference_invites` по `?room_id=` отдаёт чужие ссылки вместе
с токеном входа, а `conference_invite_revoke`/`conference_invite_send`
действуют над чужим приглашением — у всех четырёх ручек нет проверки кроме
входа. Новая проверка — в сервисе `apps/cms/services/conference_invite_service.py`
(не во вьюхе), по образцу `conference.services.access.may_view`:

`may_manage_invites(token, room_id, invite=None) -> bool` — истина, если:
1. вызывающий — организатор встречи: `apps.tasks.interface.get_conference_event_for_room(room_id)` вернул событие и его `creator_id == token.user_id`; или
2. операция над существующим приглашением, и вызывающий — его автор (`ConferenceInvite.created_by_id`); или
3. уровень `cms` у вызывающего — `admin` (`apps.access.interface.permission_level`), суперпользователь проходит сам.

Применение: `_list_conference_invites` — только приглашения, которыми
вызывающий вправе управлять (фильтр, а не 403: список организатора — его
ссылки и ссылки его встречи); `conference_invite_revoke`,
`conference_invite_send` — 404 на чужое (как `may_view`: не выдавать факт
существования). `_create_conference_invite` — **как сегодня, любой сотрудник**
(см. §12, вопрос 2). Межаппный вызов `tasks.interface` — разрешён сторожем
изоляции; при выключенном `tasks` (`ServiceDisabled`) условие 1 ложно, 2 и 3
работают.

## 8. Сторожа и тесты

1. `apps/access/self_service.py`: `TRANSLATED_APPS` += `media_files`,
   `conference`, `messenger`, `mail`, `cms`, `approvals` — каждая аппка
   добавляется в том же коммите, где разобраны все её ручки; `SELF_SERVICE`
   получает записи §6 с причиной `self`.
2. `test_gate.py`: `test_gate_is_not_hung_on_apps_without_a_translation_plan`
   после блока покрывает только `core` (и `_OUT_OF_SCOPE_APPS`
   `contracts`/`signoff`). Новый сторож: литерал `module=` в
   `apps/<аппка>/**` переведённой аппки равен имени её модуля —
   `app_label`, либо `htqweb.middleware.service_gate.APP_LABEL_TO_SERVICE`
   (`media_files` → `media`); ловит `module="media_files"`.
3. `apps/access/tests/test_employee_basic_levels.py`: уровни
   `employee-basic` по шести модулям равны таблице §4 ровно (числа выписаны в
   тесте руками, не вычислены тем же кодом); `employee-basic` не несёт `delete`
   ни в одном из шести модулей; уровень `services-admin` — `admin` во всех
   шести.
4. Поведение, по одному на аппку (держатель только `employee-basic`, с
   заголовком компании): 200 на типовую ручку сотрудника (например
   `messenger._list_rooms`, `approvals._list_templates`, `media.upload_file`,
   `conference.sessions`, `cms.conference_config`, `mail._imap_connect_hint`) и
   403 на бывшую админскую (`admin_list_rooms`, `_create_project`,
   `list_files`, `_create_news`, `_list_mailboxes`). Держатель
   `services-admin` — 200 на ту же админскую.
5. `is_staff` без роли — 403 на бывшую админскую ручку (закрепляет решение 2).
6. Приглашения §7: чужой сотрудник — 404 на `revoke`/`send` и пустой список;
   организатор события и автор ссылки — 200; держатель `cms:admin` — 200.
7. `access_backfill_services_admin`: идемпотентность, `--dry-run` ничего не
   пишет, суперпользователь и неактивный пропущены, пользователь без членства —
   в сводке.
8. Существующие тесты шести аппок: их запросы обязаны нести заголовок
   компании и роль (как `apps/tasks/tests/helpers.py::auth`); помощники
   тестов каждой аппки дополняются в её коммите.

## 9. Фронт

1. Экраны, которые показываются по `is_staff`/`is_admin` вместо уровня
   модуля, переводятся на `usePermissions().atLeast(...)` с тем же уровнем, что
   у сервера (§6): по разведке — `frontend/src/features/requests/RequestsLayout.tsx`,
   `NewRequestPage.tsx` (`approvals`); план проверяет все шесть модулей
   `grep`-ом по `is_staff|isAdmin|is_admin`.
2. Меню «Мессенджер» и «Почта» (`navItems.ts` `requires: 'always'`,
   `ProfileSidebar.tsx`) — показывать по `atLeast('messenger'|'mail', 'read')`:
   после блока доступ к ним снимается ролью, и пункт без доступа вёл бы на 403.
3. Голый домен (`/login`, `/join/<token>`, `/companies/choose`, лендинг `/`)
   ручек под новым гейтом не зовёт, кроме бейджа `messenger.unread_count` —
   он в `self` (§6.3). ⚠️ Исходная формулировка («изменений не нужно») была
   неверной (финальное ревью, I-1): `/join/<token>` уводит сотрудника в
   `/room/<id>` **того же** голого домена (ссылка строится от
   `PUBLIC_BASE_URL`, маршрут комнаты публичный — в нём бывает гость), а
   комната звала `cms.conference_config`, `conference.overview`,
   `conference.sessions` и ручки приглашений — без компании гейт дал 403,
   звонок стартовал без TURN/WebTransport. Закрыто так: `conference_config`
   снят с гейта и записан в `SELF_SERVICE["cms"]` с причиной `open`
   (рантайм-конфиг без данных пользователя, до блока — без проверок кроме
   входа); `ConferencePage.tsx` на голом домене (`companyFromHost(host) ===
   null`) не запрашивает сводку и историю встреч и не показывает кнопку
   «Пригласить по ссылке». Увод сотрудника на хост компании отвергнут:
   `/room` — публичный маршрут, `RequireAuth` с обменом refresh-cookie на
   нём не работает, и сотрудник на новом поддомене попал бы на `/login`.
   Сторожа: `cms/tests/test_gate_roles.py::
   test_employee_on_bare_domain_reads_conference_config`,
   `pages/__tests__/ConferencePageCompanyContext.test.tsx`.
4. Проверки фронта: `tsc` не хуже базы, `vitest` не больше известных падений,
   `lint` не больше 376 проблем.

## 10. Вне блока — записать

- **WebSocket мессенджера** (`ws/messenger/socket.io`) — без гейта модуля и
  без контекста компании (`company_context.py` докстринг); проверяет участие в
  комнате. Решение контекста компании для WS — отдельная задача с фронтом.
- **SSE `approvals/stream`** — вне `api_view`, отдаёт только свои события.
- **Внутренние `is_elevated` в сервисах** (`conference.services.access`,
  `approvals.services.permissions/request_runtime/instance_service/template_data_table`,
  `media_files` scope policy и `_can_access_private`) — остаются; `is_staff`
  по-прежнему расширяет видимость ВНУТРИ ручки, в которую его пустил гейт.
- **Правило скоупов загрузки `media`** (решение Д1: `hr_doc`/`hr_department`/
  `task_attachment` — только elevated) — остаётся.
- **Глобальные объекты в `public`**: новости, почтовые ящики, шаблоны заявок
  общие для группы, а уровень модуля считается в компании запроса. Роль в
  любой компании даёт право править их для всех компаний. Следствие того, что
  эти аппки не тенантные; менять — отдельное решение.
- **`core`**: не модуль прав, ручки инфраструктуры — `admin=True`.
- Интерфейсы `apps.<x>.interface` шести аппок гейтом не затрагиваются (вызовы
  Python, не HTTP).

## 11. Выкатка

Гейт считает уровень только в контексте компании — блок выкатывается не
раньше поддоменов (блок I.2, `docs/deploy/subdomains-runbook.md`). Одно окно:

1. `manage.py migrate_shared` — применяет `access/0011`, `access/0012`
   (`access` — общая аппка, `migrate_companies` не нужен).
2. `manage.py access_backfill_services_admin --dry-run` — прочитать сводку:
   сколько администраторов, в каких компаниях, кто без членства.
3. `manage.py access_backfill_services_admin`.
4. Открыть трафик. Проверить: сотрудник — мессенджер, почта, заявки, файлы;
   администратор — `/admin/chats`, `/admin/mailboxes`, `/manage/news`,
   `/requests/projects`.

Откат — предыдущий образ; строки `employee-basic` и роль `services-admin`
безвредны для старого кода (он их не спрашивает).

## 12. Риски и вопросы к ревью спеки

**Риски.**
- Сотрудник без `CompanyMembership` в компании поддомена и так не получает
  токена; но сотрудник с членством без базовой роли (выдана до блока I и снята
  руками) потеряет мессенджер и почту — так задумано моделью, сводка
  `--dry-run` их не ищет. Проверка на бою: число членств без `employee-basic`.
- Бывшие `admin=True` ручки `cms` опускаются до `write`: удаление новостей,
  обращений и блоков главной получает тот же порог, что их правка.

**Нужно подтверждение заказчика** (в спеке — рекомендованный вариант):
1. **Удаление контента `cms` под `write`** (как требует фронт для `/manage/*`),
   а не отдельный порог `admin` для кнопки «удалить». Рекомендую `write`.
2. **Кто создаёт приглашение в конференцию.** Сегодня — любой сотрудник, в
   любую комнату. Спека оставляет как есть («перенести как есть») и закрывает
   только чтение/отзыв/рассылку чужих. Альтернатива — создавать может только
   организатор события (для комнаты без календарного события — любой). Рекомендую
   оставить как есть и записать.
3. **`media.list_files`** на признаке `delete` узла `media.files` (другого
   администраторского признака в модуле нет), без нового узла. Рекомендую так.

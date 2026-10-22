# Канбан-доски модуля «Задачи» (аппка `tasks`) — мастер-план

21.10.2026 · ветка `sanzhar` @ `b82802ce` · код не пишется, только план

**Задача.** Задача остаётся одной сущностью (`tasks.Task`); доски — представления над задачами, а не копии. Появляются три вида досок — личная, отдела, проекта — с карточками и визуальным языком Trello на токенах темы shadcn, модальной карточкой поверх доски, чек-листами, порядком карточек и переносом задач между отделами.

**Как получен.** Описание заказчика (решения §1, строки «Заказчик») проверено против кода `sanzhar` @ `b82802ce`: бэкенд `apps/tasks`, `apps/hr`, `apps/access`, `apps/project`, фронт `frontend/src`. Где описание расходится с кодом — §2.2, с решением. Где прямого решения нет, план идёт по варианту «умолчание» до ответа на вопрос из §12. Ответы заказчика 21.10 на Q-K01, Q-K04, Q-K05, Q-K07 и дополнение «личная доска в профиле» внесены — строки «Ответ 21.10».

**Порядок работы — как у БЗО и тендера.** Пошаговый план с кодом пишется к старту каждого этапа (`docs/plans/2026-10-2x-kanban-stage<N>-plan.md`), задачи этапа — в корневой `Plans.md` (фаза K, `/harness-work`), закрытие — `harness-review`. `STRUCTURE.md` (§4.2), `API.md` («apps.tasks»), `CLAUDE.md` обновляются в той же задаче, что и код. Новых веток не создаём (CLAUDE.md): ветку даёт пользователь.

Ссылки на код — от корня репозитория; `tasks/…` = `backend/apps/tasks/…`, `hr/…` = `backend/apps/hr/…`, `access/…` = `backend/apps/access/…`, `fe/…` = `frontend/src/…`.

---

## 1. Реестр решений

«Заказчик» — утверждённое решение из постановки 21.10; «умолчание» — прямого ответа нет, план идёт по нему до ответа на вопрос из §12; «код» — вывод из сверки §2.

| № | Решение | Источник |
|---|---|---|
| K-01 | Задача — одна сущность. Доска — запрос над задачами: личная (`personal`), отдела (`department:<hr id>`), проекта (`project:<tasks.Project id>`). Отдельной модели «доска» нет | Заказчик |
| K-02 | Колонки — 7 статусов `Status` (`tasks/models.py:49-56`), переходы — существующий FSM `TRANSITIONS` (`tasks/models.py:92-103`). Свои колонки на доске не заводим | Заказчик; код |
| K-03 | **Личная доска** = задачи, где пользователь primary/collaborator-исполнитель, автор (`reporter_id`), руководитель (`supervisor_id`), делегат или наблюдатель — то есть все задачи, к которым он причастен (`Q_part`). Ручка строится только от `token.user_id`, параметра «чей» нет ни в URL, ни в теле, ни в query — чужую личную доску **как доску** не открыть никому, включая директоров, `is_elevated` и суперпользователя (сами задачи администратор видит в реестре, K-17) | Заказчик; Ответ 21.10 (Q-K03: делегаты и наблюдатели входят) |
| K-04 | **Доска отдела** = все задачи поддерева отдела по `Department.path`, включая взятые в работу. Отдел задачи — `Task.department_id` **или** строка `TaskDepartmentLink`. Сотрудник видит доску своего отдела и доски его подотделов, но не доску родителя | Заказчик |
| K-05 | Отдел сотрудника — `hr.Employee.department` (как сейчас `hydration.employee_department_id`, `tasks/services/hydration.py:138-151`), не `Position.department` | код |
| K-06 | **Глава отдела** = `hr.Department.manager` (сотрудник с `user_id`). Глава видит доски поддерева каждого отдела, которым руководит, даже если сам числится в другом отделе, и по задачам этого поддерева **правит, переставляет и переносит**, не будучи их участником: для `can_edit`/`can_progress` он равен руководителю задачи (полная правка, включая удаление задачи — оно и сейчас входит в полную правку) | Заказчик; Ответ 21.10 (Q-K08); «даже если» — умолчание |
| K-07 | **Перенос в чужой отдел** — только глава отдела (и `is_elevated`): при создании и действием «Отправить в отдел». Рядовой сотрудник ставит отдел только из своего поддерева или оставляет пустым, иначе 403 `task_department_forbidden` — на создании и на `PATCH` (`department_id`, `department_ids`) | Заказчик |
| K-08 | При переносе отдел-отправитель сохраняется строкой `TaskDepartmentLink(kind="origin")` — отправитель видит ход работ; у получателя задача появляется **без исполнителя**: `assignee_id` и строки `TaskAssignee` снимаются, статус незавершённой задачи становится `todo` (системный переход, пишется в журнал); `done`/`cancelled` не переносятся (409). Переносит глава отдела, в поддереве которого задача сейчас | Заказчик; Ответ 21.10 (Q-K04 — по умолчанию) |
| K-09 | **Замещения глав нет.** Права главы даёт только `Department.manager`; когда главы нет на месте, задачи переносит администратор задач (`is_elevated`), у которого эти права всегда есть. Ни `hr.Substitution`, ни `hr.ActingAssignment` в правилах досок не участвуют | Ответ 21.10 (Q-K05) |
| K-10 | **ОД (`bpp-od`) и ГД (`bpp-gd`)** видят все доски проектов и все доски отделов со всеми задачами внутри; личные доски — нет; задача без проекта и без отдела видна только её участникам. Права директоров на задачи — только чтение и комментарии | Заказчик |
| K-11 | ГД получает `view` на `project.board` (миграция `access/0028`, правка матрицы ролей БЗО) | Заказчик |
| K-12 | Новый узел `tasks.departments.all` «Доски всех отделов» — только `view`, `EXPLICIT_ONLY`; явные строки у **каждой** системной роли, кроме `platform-admin`: `view` у `bpp-od`, `bpp-gd`, пустые у остальных (приём `access/0024`, `0025`) | Заказчик |
| K-13 | Правило видимости живёт в `task_service` (`visibility_q`/`scope_for` → объект `TaskScope`), а не в ручках досок: всё, что показывает доска, открывает и `load_for_action` | Заказчик |
| K-14 | Расширение видимости через `project.board` действует для **всех** держателей узла: ТД и АДМ (у них `project.all`) — все задачи всех связанных досок, ПМ — все задачи досок своих проектов | Ответ 21.10 (Q-K01) |
| K-15 | `project.board` становится `EXPLICIT_ONLY` с явными пустыми строками у не-`bpp` системных ролей: раз узел теперь открывает задачи, он не должен доставаться по наследству от уровня модуля `project` (сейчас так его получает `platform-admin`, `access/0013`) | Ответ 21.10 (Q-K02 — по умолчанию) |
| K-16 | Комментарий — по видимости, как сейчас (`tasks/views.py:650-659`): директора и наблюдатели комментируют. Отметка «наблюдать» — тоже по видимости (`tasks/views.py:602-610`) | Ответ 21.10 (Q-K06 — оставить) |
| K-17 | `is_elevated` («администратор задач»: `is_admin`/`is_staff`/`is_superuser`, `htqweb/authn/payload.py:39-47`) видит **все** задачи, включая чужие личные, — как сейчас (`scope_for` → `"all"`, `task_service.py:150-154`): в реестре задач и по прямой ссылке. Чужую личную доску как доску он не открывает (K-03), но скрывать от него задачи незачем | Ответ 21.10 (Q-K07) |
| K-18 | «Взять в работу» — отдельное действие `POST tasks/<id>/claim`: сотрудник, видящий задачу через доску отдела, ставит себя primary-исполнителем неразобранной задачи `backlog`/`todo` и переводит её в `in_progress`. Сейчас кнопка «Принять» на фронте шлёт `PATCH {assignee_id, status}` и получает 403 у всех, кроме участников (§2.2, п.7) | код; умолчание |
| K-19 | Карточка открывается модальным окном поверх доски, адрес `?card=<id>`; «назад» и Esc закрывают окно; прямой заход открывает доску с карточкой. Страница `/tasks/:id` остаётся | Заказчик |
| K-20 | Чек-листы — новые модели `TaskChecklist`, `TaskChecklistItem`; отметить/добавить/переименовать/удалить пункт — `require_soft_edit`; удалить чек-лист — `require_full_edit`; каждое действие — строка `TaskActivity`. `progress_percent` чек-листы не меняют; флага «прогресс по чек-листам» в первой версии нет | Заказчик; удаление пункта и флаг — умолчание (Q-K09, Q-K10) |
| K-21 | Порядок карточек — таблица `BoardCardRank(board_kind, board_id, task, rank)`, rank — строка дробной индексации (lexorank-подобная, base-62), сортировка в коллации `"C"`. В `Task` позиция не хранится. Перемещение — одна запись `INSERT … ON CONFLICT DO UPDATE`; ранг считает **сервер** по соседям | Заказчик; формат — умолчание |
| K-22 | Метки остаются общими на компанию (`Label.name` уникально, `tasks/models.py:138-152`), а не на доску, как в Trello | умолчание (Q-K11) |
| K-23 | Визуальный язык Trello — на токенах темы (новые CSS-переменные `--board-*` в `fe/index.css` для `:root` и `.dark`), без логотипов, названия и иллюстраций Trello; все строки — i18n (`ru` и `en`) | Заказчик |
| K-24 | Ошибки новых и изменённых ручек — `{"detail", "code"}` (так уже отвечает гейт сервисов `service_disabled`); прежние ответы `{"detail"}` не меняются | умолчание |
| K-25 | Автор задачи (`reporter_id`) с клиента принимается только от `is_elevated`; остальным — всегда `token.user_id`. Иначе любой положил бы задачу на чужую личную доску под чужим авторством | код (§2.2, п.8) |
| K-26 | `done`/`cancelled` на доске — карточки, завершённые не раньше 30 дней назад (`?done_days=30`, 0 — все); колонки «Готово» и «Отменено» можно свернуть | умолчание (Q-K12) |
| K-27 | **Личная доска в профиле.** На `/myprofile` — блок «Мои задачи»: новые задачи (назначенные пользователю кем-то другим и ещё не открытые им), затем ближайшие по сроку из «К выполнению» / «В работе» / «На проверке» и счётчики по колонкам. Клик по задаче — переход на страницу досок с открытой карточкой: `/tasks/board?card=<id>`; закрыв окно, пользователь остаётся на своей доске и переключателем переходит на доску отдела. Кнопка «Открыть мою доску» — `/tasks/board` | Ответ 21.10 (дополнение) |
| K-28 | **«Новая» задача** — строка `TaskAssignee` с `seen_at IS NULL`, то есть только назначение исполнителем (руководитель задачи и перенос на доску отдела «новой» не делают; главе о переносе приходит уведомление). `seen_at` ставится, когда исполнитель открывает карточку (окно или `/tasks/:id`), и сразу при назначении самим собой (создание, «Взять в работу»). Колокольчик (`apps.notifications`) этим не управляется и сам признак не даёт: уведомление читается отдельно от задачи. Новые задачи отмечены и на личной доске (точка на карточке, фильтр «Новые») | Ответ 21.10 (Q-K18 — по умолчанию) |
| K-29 | **Уведомления о задаче получают только её участники** — исполнители (primary и collaborator), руководитель, автор, делегаты и наблюдатели («Наблюдать» — способ самому стать причастным). Кто просто видит доску (коллеги по отделу, ОД, ГД, держатели «Доски задач проекта»), уведомлений не получает: на общей доске он видит ход работ и при необходимости напоминает коллегам о статусе сам. Подписки «на всю доску» нет | Ответ 21.10 (Q-K19) |
| K-30 | **Выключатель уведомлений по доске.** Каждый может выключить и снова включить уведомления **по каждой доске отдела или проекта отдельно** — это касается только задач этой доски, где он участник (для держателей узлов — задачи досок других отделов, где их сделали руководителем, наблюдателем и т.п.). Выключение доски отдела действует на её поддерево. По умолчанию всё включено. Личную доску выключить нельзя. Адресные события — «вас назначили исполнителем / руководителем», запрос доступа и решение по нему — приходят всегда. События: добавлен исполнитель, сменился основной исполнитель (в т.ч. «взята в работу»), смена статуса, новый комментарий, перенос в другой отдел. Канал — колокольчик (`deliver=False`, как остальные уведомления задач), сразу; автору события не шлётся; одно событие — одно уведомление человеку | Ответ 21.10 (Q-K19: + «добавлен исполнитель»); выключатель — по дополнению 21.10 |
| K-31 | **Запрос доступа к задаче.** Кто видит задачу, но не причастен к ней, может оставить комментарий (K-16) и **запросить доступ**: «на исполнение» (стать исполнителем) или «на владение» (стать владельцем задачи). **Решающие зависят от вида запроса.** «На владение» решают только **владелец задачи** (руководитель, `supervisor_id`) и **глава отдела** задачи (`Department.manager` отдела, в поддереве которого её основной отдел); подтверждая, решающий выбирает: **с заменой** (запросивший становится руководителем, прежний руководитель с задачи снимается) или **делегатом** (запросивший добавляется делегатом с полной правкой, руководитель остаётся; число делегатов не ограничено — так и в модели, `TaskDelegate`). «На исполнение» решают все остальные причастные — руководитель, делегаты, автор, исполнители — и глава отдела; подтверждение — **только заменой**: запросивший становится основным исполнителем, прежний основной исполнитель с задачи снимается (соисполнители остаются), если исполнителя не было — просто становится основным. Уведомление о запросе получают все решающие этого вида, решает любой из них; первое решение закрывает запрос, остальные решить его уже не могут (409). Нет ни одного решающего (нет руководителя и задача без отдела; у задачи нет участников) — решает администратор задач (`is_elevated`). Решение и его автор — в журнале задачи и уведомлением запросившему | Ответ 21.10 (Q-K20, Q-K21, Q-K23, Q-K25) |
| K-32 | **Запросы и история — на странице «Задачи».** Рядом с досками — панель «Запросы»: «Ждут моего решения» (запросы к задачам, где я решающий), «Мои запросы» (со статусом) и — **главе отдела, которому принадлежит доска,** — «История отдела»: все запросы на исполнение и владение и все передачи владения (смена руководителя задачи — решением по запросу или вручную) по задачам доски этого отдела с поддеревом, со статусом решения, кем и когда решено. Счётчик ожидающих — на кнопке панели; те же события приходят и в колокольчик | Ответ 21.10 (Q-K21) |
| K-33 | **Канал уведомлений — только колокольчик** (`deliver=False`). После этого обновления будет Telegram-бот для сотрудников: поэтому все уведомления задач идут через одну точку `task_notify` с устойчивыми кодами событий, а признак доставки — одна константа, которую бот переключит без правки каждого места | Ответ 21.10 (Q-K22) |

---

## 2. Сверка текущего состояния

### 2.1 Что подтверждено

| Утверждение постановки | Код | Итог |
|---|---|---|
| «Доска» = `tasks.Project`, 1:1 с «Проектом» БЗО через `project_ref` | `tasks/models.py:622-698` (`project_ref` `:677`, `uq_task_project_ref` `:693`), синхронизация — `tasks/services/project_link.py` (`MIRRORED` `:41-47`, слушатель `:90-106`), миграции `0022`–`0024` | Да |
| 7 фиксированных статусов, FSM `TRANSITIONS` | `tasks/models.py:49-56`, `:92-103`; `Task.apply_transition` `:1070-1091` (вход в терминальный — `completed_at`, `done` — прогресс 100) | Да |
| Порядка карточек нет, `order_by("-created_at")` | `tasks/services/task_service.py:247`; поля позиции и `Meta.ordering` нет | Да |
| Пагинация по 6 на колонку | `fe/components/tasks/KanbanBoard.tsx:80` (`CARDS_PER_PAGE = 6`), страницы `:446-470` | Да |
| Клик ведёт на `/tasks/:id` через `TaskDetailRouter` | `fe/app/routing/routeDefinitions.ts:106`; `fe/components/tasks/TaskDetailRouter.tsx:14` (`HRTaskDetail` / `EmployeeTaskDetail`) | Да |
| Поповеры быстрой правки на карточке | `KanbanBoard.tsx`: приоритет `:266-289`, прогресс `:298-324`, метки `:327-359`, руководитель `:366-387`, исполнители `:391-431` | Да |
| `TaskComment`, `TaskAttachment` есть | `tasks/models.py:1487-1519`, ручки `tasks/views.py:645-733` | Да |
| `TaskActivity` пишется по `TRACKED_FIELDS` и отдаётся в detail | `tasks/services/task_service.py:62-68`, `_log` `:371-378`; `task_response.build_detail` `:246-252` | Да, но см. 2.2 п.2 |
| Чек-листов нет | в `apps/tasks` нет ни одного `checklist` | Да |
| `_employee_visibility_q` — участник + неразобранные backlog/todo своего отдела | `tasks/services/task_service.py:117-124` | В целом да, уточнения — 2.2 п.1 |
| `board_scope.py`: `project.board` открывает список досок, задачи внутри — «по своим правилам» | `tasks/services/board_scope.py:23-46`; потребители — `project_service._visible` `:40-54`, `roadmap_service._visible` `:39-54`; тест `tasks/tests/test_board_scope.py:49-55` | Да: ОД видит доску почти пустой |
| `create_task` принимает любой `department_id` | `tasks/services/task_service.py:394-398`, комментарий `:437-441`; то же у `department_ids` и `update_task` `:556-561` | Да |
| `Department.path` — строка «it.dev.backend», не ltree; `Department.manager → Employee` | `hr/models.py:84` (`unique=True`), `:88-94` (`related_name="managed_department"`) | Да |
| В `hr.interface` есть `org_ancestors`, нет поддерева и «отделов руководителя» | `hr/interface.py:471-492`; поддерево — только внутри сервисов (`department_service.get_children` `:179-181`) | Да |
| Фронт: React 18 + Vite + TS, TanStack Query, `@hello-pangea/dnd`, shadcn/ui, i18n с тестом ключей | `frontend/package.json:24,53`; `fe/lib/i18n/__tests__/translationKeys.test.ts` | Да |

### 2.2 Расхождения и находки — с решением

1. **Видимость шире, чем «участник + неразобранные отдела».** «Участник» — это и автор, и руководитель, и делегаты, и **наблюдатели** (`_participant_q`, `task_service.py:85-94`); `is_elevated` видит всё (`scope_for`, `:150-154`); ветка отдела смотрит только `Task.department_id`, а `TaskDepartmentLink` не учитывает; при выключенном `hr` ветка отдела пропадает (`hydration.py:138-151`). **Решение:** `_participant_q` сохраняется как есть; ветка отдела переписывается на поддерево и учёт связей (§5.2); поведение при выключенном `hr` — сужение (fail-closed), как сейчас.
2. **Лента активности на фронте выводится**, но только в `HRTaskDetail` (`fe/pages/hr/HRTaskDetail.tsx:491-521`); в `EmployeeTaskDetail` её нет. В detail-ответе `activities` идут без сортировки (prefetch), а `/activity` — по `-created_at` (`task_content_service.py:103-104`). **Решение:** единая лента `GET tasks/<id>/feed` с явной сортировкой (§6.4); в карточке выводится всем, кто видит задачу.
3. **«Доска проекта» в интерфейсе — не канбан.** `/manage/projects` (`fe/pages/hr/HRProjects.tsx`, 1172 строки) показывает задачи вкладкой-списком ссылок (`TasksTab` `:458-501`); `KanbanBoard` используется только в `HRTasks` (`:348`) и `EmployeeTasks` (`:265, :282`). **Решение:** канбан проекта — новая доска `/tasks/board/project/<id>`; во вкладке «Задачи» `HRProjects` — кнопка «Открыть доску».
4. **Обе вкладки `EmployeeTasks` фильтруют на клиенте первые 50 задач.** `EmployeeTasks.tsx:54-60` зовёт `fetchTasks()` без параметров (лимит по умолчанию 50, `tasks/views.py:422`) и отбирает «Мои задачи» и «Задачи отдела» у себя (`:87-106`). С расширением видимости в этапе 1 задачи отдела вытеснят из первых 50 и свои задачи. **Решение:** в этапе 1 — параметр `?scope=mine|department` списка (сервер режет сам, спека этапа 1 S1-04), в этапе 6 страница уходит.
5. **`TaskDepartmentLink` — это «весь набор отделов задачи»**, и `PATCH department_ids` заменяет его целиком (`task_service.py:556-561`). Строка отправителя стёрлась бы первым же таким `PATCH`. **Решение:** поле `kind` (`member` | `origin`), набор `department_ids` заменяет только `member` (§3.1).
6. **У `Department` нет поля `parent`**: иерархия — только строка `path`; правка `path` через API не переписывает пути потомков (`department_service.py:211-218`); существующий обход поддерева в `org_service.py:885` сравнивает `startswith` без точки («it.dev» поймал бы «it.devops»). **Решение:** новые функции считают поддерево строго `path = P OR path LIKE 'P.%'`; правка `path` — риск §11 п.4.
7. **«Принять» свободную задачу сейчас не работает у рядового сотрудника.** Фронт шлёт `updateTask(id, {assignee, status})` (`EmployeeTasks.tsx:63-78`) → `PATCH {assignee_id, status}`; любое поле кроме статуса и прогресса требует полной правки (`tasks/views.py:509-513`), которой у не-участника нет → 403. **Решение:** действие `claim` (K-18).
8. **`create_task` берёт `reporter_id` и начальный `status` с клиента** (`task_service.py:420`, `schemas.py:828-830`), без FSM. **Решение:** K-25; начальный статус на создании ограничить `backlog`/`todo` (у `is_elevated` — любой, как сейчас).
9. **«Администратор задач» — не роль, а `is_elevated`** (`is_admin`/`is_staff`/`is_superuser`). Уровень модуля `tasks:admin` используется только гейтами (`api_view(admin=True)`). **Решение:** в таблице прав §5.3 «администратор задач» = `is_elevated`; уровень модуля на видимость не влияет.
10. **`project.board` наследуется от уровня модуля `project`** (узел не `EXPLICIT_ONLY`, `project/access_functions.py:13,24`); явные строки — только у восьми `bpp-*` (`access/0020`); `platform-admin` получает узел по наследству (`access/0013`). Пока узел открывал только список досок, это было терпимо. **Решение:** K-15.
11. **Матрица ролей БЗО утверждена Алгазы** (`docs/plans/2026-09-27-bpp-roles-matrix.md`), у ГД в строке `project.board` — пусто. **Решение:** K-11 — решение заказчика; в матрицу — строка «21.10: ГД — V» с источником; тест `access/tests/test_bpp_roles.py:96-102` (`test_board_link_is_for_td_od_pm_and_adm`) правится вместе с миграцией.
12. **Общего сторожа «у каждой системной роли есть строка на каждом `EXPLICIT_ONLY`-узле» нет** — только точечные тесты (`test_bpp_roles.py:30`, `test_project_structure_nodes.py:18`, `tender/tests/test_roles.py:142`), и общий сразу упал бы: у узлов `bpp.*.all` (`access/0014`, `0017`, `0021`) строки есть только у восьми `bpp-*`. Для `EXPLICIT_ONLY`-узла отсутствие строки и так значит «нет доступа», поэтому пустые строки там — ясность в редакторе ролей, а не защита. **Решение:** точечный сторож на два узла этапа 1 (спека этапа 1 S1-08); общий — отдельной задачей вместе с миграцией пустых строк для старых узлов, если заказчику нужна единообразная картина в редакторе ролей.
13. **Ошибки в нынешнем `KanbanBoard`** (уходят вместе с ним в этапе 6, но до того чинить не стоит): правки инвалидируют только `['hr-tasks']`, а `EmployeeTasks` читает `['employee-tasks', tab]` (`:118`); неудачный бросок оставляет карточку в чужой колонке (`HRTasks.tsx:132`, `EmployeeTasks.tsx:83`); чип проекта ведёт на несуществующий `/roadmap` (`:244`); приоритет печатается сырым значением (`:273, :284`); бросок не сверяется с FSM.
14. **Переключателя тёмной темы на фронте нет:** `next-themes` в зависимостях, `ThemeToggle.tsx` есть, но `ThemeProvider` не смонтирован и `ThemeToggle` нигде не импортирован. Токены `.dark` в `fe/index.css:65-106` есть. **Решение:** доска делается на токенах и проверяется классом `.dark` (тест/Storybook-снимок); включение переключателя — вне этого плана (Q-K14).
15. **`Project.color` — на доске задач** (`tasks.Project.color`, `tasks/models.py:649`, по умолчанию `#3b82f6`), у «Проекта» БЗО (`apps/project`) цвета нет. Это и нужно: фон доски проекта — `tasks.Project.color`.
16. **`department_id` не входит в `TRACKED_FIELDS`** — смена отдела сейчас в журнал не пишется. **Решение:** добавить (этап 1), перенос пишет и отдельное событие `transfer`.
17. **`/tasks/stats` считает по другому правилу** (`_report_visibility_q`, `task_service.py:127-133`). **Решение:** вне объёма; не трогаем (Q-K15).

---

## 3. Модель данных

Все модели — в `apps/tasks`, то есть в схемах `co_<slug>` (тенантная аппка). FK — только внутри `tasks`; отдел и пользователь — голые числа, как везде в аппке (`Р2`). `Task`, `Project`, `TaskDepartmentLink` не получают разрушающих изменений — только expand.

### 3.1 `TaskDepartmentLink.kind` — `tasks/0027_department_link_kind`

```
TaskDepartmentLink
  + kind CharField(10, choices=member|origin, default="member", db_default="member", db_index=True)
  uq_task_department_link (task, department_id) — остаётся
```
- `member` — отдел-участник (как сейчас; основной отдел тоже лежит здесь, `create_task` `:442-445`).
- `origin` — отдел-отправитель после переноса. Пара `(task, department_id)` уникальна, поэтому возврат задачи в отдел-отправитель превращает его `origin` в `member`, а не добавляет вторую строку.
- `PATCH department_ids` заменяет только строки `member` (`update_task`); `origin` снимает лишь «Отправить в отдел» обратно или удаление задачи.
- `db_default` — чтобы старый код (откат, отставшая компания) вставлял строки без поля.

### 3.2 Порядок карточек — `tasks/0028_board_card_rank`

```
BoardCardRank
  board_kind  CharField(12, choices=personal|department|project)
  board_id    IntegerField          # user_id | hr department id | tasks.Project.id
  task        FK Task, CASCADE, related_name="board_ranks"
  rank        CharField(64, db_collation="C")
  updated_at  DateTimeField(auto_now)
  uq_board_card_rank (board_kind, board_id, task)
  ix_board_card_order (board_kind, board_id, rank)
```
- Статус в таблице не хранится: колонка = `Task.status`. Ранг задаёт порядок внутри колонки; при переходе в другую колонку ранг пересчитывается по соседям в целевой.
- Карточки без строки сортируются после ранжированных, по `-created_at` (как сейчас) — **бэкфилла нет**, строки появляются при первом перемещении или быстром добавлении.
- Ранг считает `services/board_rank.py` (чистые функции, дробная индексация base-62: `between(a, b)`). Длина растёт при многократной вставке в одно место; ранг длиннее 48 символов — перебалансировка колонки одной транзакцией под `pg_advisory_xact_lock(hash(board))` (равномерные ранги), без участия клиента.
- Строки задачи, ушедшей с доски (перенос в другой отдел), не мешают — выборка доски соединяет с видимыми задачами; после переноса строки старой доски отдела удаляются в той же транзакции.
- `board_id` личной доски = `user_id` — строки никогда не отдаются никому, кроме владельца (ручка строится от токена).

### 3.3 Признак «новая задача» — `tasks/0029_assignee_seen_at`

```
TaskAssignee
  + seen_at DateTimeField(null=True, blank=True)
  + ix_task_assignee_unseen (user_id) WHERE seen_at IS NULL     # частичный индекс
```
- Миграция ставит `seen_at = assigned_at` всем существующим строкам (одним `UPDATE` в схеме компании): иначе после выкатки у каждого все старые задачи стали бы «новыми».
- Код: `replace_assignees`, `_sync_primary_assignee`, `create_task` пишут `seen_at = now()` строке самого актёра и `NULL` строкам, назначенным другим; повторное назначение уже видевшего задачу человека сбрасывает `seen_at` в `NULL` (это снова новость); перенос (K-08) строки удаляет — признак уходит вместе с ними.
- `POST tasks/<id>/seen` — ставит `seen_at` строке вызывающего, если она есть (иначе ничего, 204); идемпотентно, в журнал не пишется. Зовётся окном карточки и страницей `/tasks/:id` при открытии.
- `TaskAssignee` в сводках холдинга нет.

### 3.4 Выключатель уведомлений по доске — `tasks/0031_board_notification_mute`

```
BoardNotificationMute
  board_kind  CharField(12, choices=department|project)
  board_id    IntegerField          # hr department id | tasks.Project.id
  user_id     IntegerField(db_index=True)
  created_at  DateTimeField(auto_now_add)
  uq_board_notification_mute (board_kind, board_id, user_id)
```
- Строка есть — уведомления по задачам доски выключены; нет — включены (K-30). Включение — удаление строки.
- Рассылка — `services/task_notify.py::notify_participants(task, event, actor_id, *, direct_to=())`, единая точка вместо разрозненных `_notify` (`task_service.py:356-368`):
  1. получатели = участники задачи (`assignee_id`, `TaskAssignee`, `supervisor_id`, `reporter_id`, `TaskDelegate`, `TaskWatcher`) − автор события;
  2. минус те, у кого выключена хотя бы одна доска задачи: доски отделов — предки (по `path`, `hr.interface.org_ancestors`) и сами отделы задачи (`department_id`, связи `member`/`origin`), доска проекта — `project_id`; одна выборка `BoardNotificationMute` по `user_id IN (…)`;
  3. адресаты `direct_to` (назначенный исполнитель, новый руководитель) получают уведомление в любом случае;
  4. `notifications.interface.notify(recipients=…, event="tasks.task", deliver=DELIVER, target_type="task", target_id=…, dedupe_window_seconds=60)` — один вызов на событие, в `transaction.on_commit` (откат правки — ни одного уведомления), без Celery: получателей единицы, как у нынешнего `_notify`. `DELIVER = False` — константа модуля (K-33); код события (`status`, `assignee_added`, `assignee_changed`, `comment`, `transfer`, `access_requested`, `access_decided`) — в тексте уведомления и в `url`, чтобы будущий бот различал их без разбора заголовка.
- Поведение меняется сознательно: сейчас смену статуса узнаёт только основной исполнитель (`task_service.py:528-530`), после — все участники (K-29).
- Ссылка уведомления — `/tasks/board?card=<task id>` (личная доска с открытой карточкой: задача участника на ней всегда есть).

### 3.5 Запросы доступа — `tasks/0032_task_access_request`

```
TaskAccessRequest
  task          FK Task, CASCADE, related_name="access_requests"
  requester_id  IntegerField(db_index=True)
  kind          CharField(10, choices=execute|own)
  comment       TextField(blank)
  status        CharField(10, choices=pending|approved|rejected|cancelled, default pending)
  approve_mode  CharField(10, choices=replace|delegate, null)   # как подтверждено: «владение» — выбор решающего, «исполнение» — всегда replace
  replaced_user_id IntegerField(null)                          # кого сняли при замене — для истории отдела
  decided_by_id IntegerField(null)
  decided_at    DateTimeField(null)
  decision_comment TextField(blank)
  created_at, updated_at
  uq_task_access_request_pending (task, requester_id, kind) WHERE status='pending'
```
- Сервис `services/access_requests.py`: `request_access` (задача видна, запросивший ещё не в этой роли — иначе 409 `task_access_already`; второй ожидающий того же вида — 409 `task_access_pending`), `decide` (одобрение и роль — в одной транзакции под `select_for_update` **запроса и задачи**: первый решивший меняет статус, второй видит уже не `pending` и получает 409 `task_access_decided`; роль занята, пока запрос ждал, — одобрение всё равно добавляет по правилу K-31), `cancel` (только сам запросивший, пока `pending`).
- Кто решает — `deciders(task, kind)` (K-31), без самого запросившего:
  - `own` — руководитель задачи + глава отдела (держатель `Department.manager` отдела, чьё поддерево содержит основной отдел задачи; один запрос `hr.interface` — отделы-предки основного отдела и их главы);
  - `execute` — руководитель, делегаты, автор, исполнители (`assignee_id` и `TaskAssignee`) + тот же глава отдела;
  - пусто — `is_elevated`.
  Набор считается на момент решения: человек, снятый с задачи, пока запрос ждал, решить его уже не может.
- Подтверждение: `own` — тело `{mode: "replace"|"delegate"}` обязательно (422 без него); `replace` — `supervisor_id = запросивший`, прежний руководитель снимается (его делегирования остаются: они выданы задаче, а не ему лично), если запросивший был делегатом — делегирование снимается; `delegate` — строка `TaskDelegate`. `execute` — `mode` не принимается (422 при `delegate`): запросивший становится primary, строка прежнего primary в `TaskAssignee` удаляется, `assignee_id` обновляется (`_sync_primary_assignee`), соисполнители не трогаются; `seen_at` запросившего — `now()` (он сам просил).
- Журнал: `access_requested`, `access_approved`, `access_rejected`, `access_cancelled` (значение — вид запроса и id пользователя) + обычные записи роли (`assignee_id`, `supervisor_id`, делегаты).
- Уведомления — адресные (`direct_to`, всегда доходят, выключатель доски их не гасит): запрос — всем решающим его вида, решение — запросившему, остальным решающим («решено: …», чтобы у них запрос не висел) и снятому при замене («вас заменил …»).
- **История отдела** (K-32) — `services/access_requests.py::department_history(department_id, …)`: запросы (`TaskAccessRequest`) и передачи владения (`TaskActivity` с `field_name="supervisor_id"`) по задачам `Q_dept(subtree(department_id))`, одной лентой по времени, с фильтрами вид / статус / период. Отдельной таблицы «передач» нет: смена руководителя уже пишется в журнал (`set_supervisor`, `task_service.py:638-652`).

### 3.6 Чек-листы — `tasks/0030_checklists`

```
TaskChecklist
  task          FK Task, CASCADE, related_name="checklists"
  title         CharField(200)
  position      CharField(64, db_collation="C")      # тот же board_rank.between
  created_by_id IntegerField(null)
  created_at, updated_at
  ix (task, position)

TaskChecklistItem
  checklist     FK TaskChecklist, CASCADE, related_name="items"
  text          CharField(500)
  is_done       BooleanField(default=False, db_default=False)
  done_by_id    IntegerField(null)
  done_at       DateTimeField(null)
  position      CharField(64, db_collation="C")
  created_by_id IntegerField(null)
  created_at, updated_at
  ck_checklist_item_done: (is_done AND done_at IS NOT NULL) OR (NOT is_done AND done_at IS NULL AND done_by_id IS NULL)
  ix (checklist, position)
```
- Лимиты (сервис): до 20 чек-листов на задачу, до 200 пунктов в чек-листе (422 `checklist_limit`).
- Удаление задачи мягкое (`is_deleted`) — чек-листы остаются вместе с ней.

### 3.7 Журнал (`TaskActivity`) — без миграции

`field_name` (50 символов) получает новые коды, значения — строки, как сейчас:

| `field_name` | `old_value` → `new_value` |
|---|---|
| `department_id` (новое в `TRACKED_FIELDS`) | id → id |
| `transfer` | id отдела-отправителя → id отдела-получателя |
| `claim` | — → user_id |
| `checklist_added` / `checklist_renamed` / `checklist_deleted` | — / старое → новое название |
| `checklist_item_added` / `_renamed` / `_deleted` | — / старый → новый текст |
| `checklist_item_checked` / `checklist_item_unchecked` | — → текст пункта |

Перестановка карточки без смены статуса в журнал **не пишется** (шум); смена статуса — как сейчас, `status`.

### 3.8 Порядок миграций и влияние на схемы и сводки

| Шаг | Миграция | Где | Зависимости |
|---|---|---|---|
| Этап 1 | `access/0028_tasks_board_nodes` (данные: узел `tasks.departments.all`, `bpp-gd` → `view` на `project.board`, пустые строки `project.board` у не-`bpp` системных ролей) | `public`, `migrate_shared` | `access/0027_tender_roles` |
| Этап 1 | `tasks/0027_department_link_kind` (expand) | `co_<slug>`, `migrate_companies` | `tasks/0026` |
| Этап 2 | `tasks/0028_board_card_rank` (новая таблица) | `co_<slug>` | `tasks/0027` |
| Этап 2 | `tasks/0029_assignee_seen_at` (expand + заполнение `seen_at = assigned_at`) | `co_<slug>` | `tasks/0028` |
| Этап 3 | `tasks/0030_checklists` (две таблицы) | `co_<slug>` | `tasks/0029` |
| Этап 3 | `tasks/0031_board_notification_mute` (новая таблица) | `co_<slug>` | `tasks/0030` |
| Этап 3 | `tasks/0032_task_access_request` (новая таблица) | `co_<slug>` | `tasks/0031` |

- **Сводки холдинга не задеты.** `HOLDING_MODELS = ("Project", "Site", "Task", "DailyReport", "ProjectStaffReport")` (`tasks/holding.py:13`); новые таблицы туда не входят, у `Task` и `Project` столбцы не меняются. `TaskDepartmentLink` и `TaskAssignee` в сводках нет.
- **Номера миграций — по порядку слияния, а не по этапам**: этапы 2 и 3 идут параллельно, и если этап 3 сольётся раньше, номера `0028`–`0031` перераспределятся; зависимость каждой — от последней слитой (`makemigrations` после ребейза), без двух миграций с одним номером.
- Уведомления пишутся в `apps.notifications` (`public`) через `notifications.interface` — новых таблиц в `public` нет; событие прежнее, `tasks.task`. `migrate_companies` всё равно сносит и пересобирает представления — штатно.
- Все миграции `tasks` — expand: разные компании могут стоять на разных версиях; код этапа N читает таблицы этапа N только в ручках этого этапа.
- Метрик в `tasks/metrics.py` не добавляем (иначе их обязан видеть дашборд — `test_metrics_are_observed`). Если понадобятся (например, «задачи, ожидающие исполнителя после переноса»), — отдельной задачей вместе с панелью.

---

## 4. Изменения `hr.interface`

Единственная правка `hr` — две функции только для чтения. Первая строка каждой — `require_service("hr")`, как у соседей (`hr/interface.py`).

```python
def department_subtree_ids(department_ids: list[int]) -> dict[int, list[int]]:
    """Для каждого отдела — он сам и все потомки по Department.path
    (path = P OR path LIKE 'P.%'), включая неактивные: задачи закрытого
    подотдела остаются на доске родителя. Неизвестный id — ключа нет."""

def managed_department_ids(user_id: int) -> list[int]:
    """Отделы, которыми руководит пользователь: Department.manager → Employee
    с этим user_id, сотрудник не удалён и действующий, отдел активен.
    Один сотрудник может руководить несколькими отделами (manager — FK)."""

def department_manager_user_ids(department_ids: list[int]) -> dict[int, int]:
    """{id отдела: user_id главы} — для уведомления главе отдела-получателя
    при переносе и для решающих по запросу «на владение» (K-31)."""
```

Запросы:
- `department_subtree_ids`: 1) `Department.objects.filter(id__in=ids).values("id", "path")`; 2) один запрос `Q(path__in=paths) | Q(path__startswith=p + ".") | …` по всем путям, раскладка по корням в Python. Длина `ids` на практике 1–3 (свой отдел + управляемые).
- `managed_department_ids`: `Department.objects.filter(manager__user_id=user_id, manager__is_deleted=False, manager__status=ACTIVE, is_active=True).values_list("id", flat=True)`.
- Опорный индекс — уникальный индекс `path` (`hr/models.py:84`); для `LIKE 'P.%'` нужен `varchar_pattern_ops` — проверить, создал ли его Django (`_like`-индекс у `unique` `CharField`); если нет — миграция `hr/00xx_department_path_like` (`AddIndex` с `opclasses`) в этапе 1. Таблица отделов мала (сотни строк), поэтому это страховка, а не условие.
- Временных исполнителей и замещающих функция не учитывает (K-09): права главы — только у `Department.manager`, остальное закрывает администратор.

**Кэш на время запроса.** В `hr.interface` кэша нет и не появляется. Кэширует потребитель: `tasks/services/task_scope.py::for_request(request)` строит `TaskScope` один раз и кладёт на `request.task_scope = (company, user_id, scope)` — тем же приёмом, что `request.access_resolution` (`htqweb/http.py:201-203`): явный атрибут запроса, переиспользуется только при совпадении компании и `user_id`. `TaskScope` использует `request.access_resolution` для `flags_for(..., resolution=…)` — сейчас `board_scope.board_refs_for` считает права дважды без него (`board_scope.py:26,28`).

Сторож изоляции: `tasks` зовёт только `apps.hr.interface` — `test_app_isolation` остаётся зелёным.

---

## 5. Видимость и права

### 5.1 `TaskScope`

```python
@dataclass(frozen=True)
class TaskScope:
    user_id: int
    elevated: bool                    # token.is_elevated
    own_department_id: int | None     # Employee.department
    managed_ids: frozenset[int]       # hr.managed_department_ids
    department_ids: frozenset[int]    # объединение поддеревьев own + managed
    all_departments: bool             # view на tasks.departments.all
    board_refs: object                # board_scope.board_refs_for: None | ALL_LINKED | [uuid…]
```
`scope_for(token)` возвращает `TaskScope`; `visibility_q(scope)` строит условие; `load_for_action(task_id, token, *, request=None)` и пять потребителей в `views.py` (`:448` список, `:1452` задачи объекта, `:1833` роудмапа, `:1867` доски проекта, `load_for_action`) переходят на него. `/tasks/stats` (`:487`) остаётся на `_report_visibility_q` (Q-K15).

### 5.2 Формулы

Обозначения: `u` — пользователь, `S` — `scope.department_ids`.

```
Q_part(u)    = assignee_id=u | reporter_id=u | supervisor_id=u
               | assignees__user_id=u | delegates__user_id=u | watchers__user_id=u     # как сейчас
Q_dept(S)    = department_id ∈ S | Exists(TaskDepartmentLink(task=OuterRef, department_id ∈ S))
Q_alldept    = department_id IS NOT NULL | Exists(TaskDepartmentLink(task=OuterRef))
Q_boards(r)  = board_scope.board_q(r, prefix="project__")      # project__project_ref > '' | ∈ refs
Q_personal(u)= Q_part(u)                                       # K-03: исполнитель, автор, руководитель, делегат, наблюдатель
Q_head(u)    = Q_dept(⋃ subtree(m) для m ∈ managed(u))         # задачи, где u — глава отдела (K-06)

Visible(u) =
  если elevated:   без ограничений (None, как сейчас)                        # K-17
  иначе:           Q_part(u)
                   | Q_dept(S)                    (если S непусто)
                   | Q_alldept                    (если all_departments)
                   | Q_boards(board_refs)         (если board_refs не None)
```
- Новые ветки — через `Exists`, а не джойн: `filtered_tasks` и так делает `.distinct()` из-за джойнов `Q_part` (`task_service.py:233-237`), и ещё один джойн к ссылкам отделов множил бы строки.
- **Личная доска** — `Visible(u) & Q_personal(u)`; `Q_personal = Q_part`, поэтому всё, что на личной доске, открывает и `load_for_action`. Карточка несёт `my_role` (`assignee`, `supervisor`, `reporter`, `delegate`, `watcher` — старшая из ролей), чтобы на доске отличать «делаю» от «наблюдаю»; фильтр «Моя роль» в шапке.
- **Права главы (K-06)** — `can_edit(task, token, scope)`: прежнее правило **или** основной отдел задачи либо её связь `member` в `scope.managed_subtree`; `can_progress` наследует это через `can_edit`. Сигнатуры `can_edit`/`can_progress`/`require_*` получают `scope` (из `TaskScope` запроса), чтобы не ходить в `hr` второй раз. Связь `origin` прав не даёт: отдел-отправитель видит задачу, но править её после переноса может только глава отдела-получателя. У каждой карточки личной доски — `is_new` (K-28: строка `TaskAssignee` пользователя с `seen_at IS NULL`, подзапросом `Exists`).
- **Задача без проекта, отдела и связей отдела** не попадает ни в `Q_dept`, ни в `Q_alldept`, ни в `Q_boards` — её видят только участники и администратор задач (K-10, K-17).
- **Доска отдела `b`** — `Visible(u) & Q_dept(subtree(b))`; доступ к самой доске: `b ∈ S` или `all_departments` или `elevated`, иначе 404.
- **Доска проекта `p`** — `Visible(u) & Q(project_id=p)`; доступ к доске — существующий `project_service._visible` (отдел доски, `board_q`, `elevated`).
- Карточка на доске отдела несёт `relation`: `own` (основной отдел в поддереве), `linked` (связь `member`), `sent` (только связь `origin` — «отправлено в …»).

### 5.3 Роль × доска × действие

«Видит» — карточки на доске и открытие карточки; «двигает» — статус и порядок; ✎ — правка по существующим правилам (`can_edit`/`can_progress`, `task_service.py:296-326`), то есть только если человек — участник задачи; у главы отдела — ещё по всем задачам своего поддерева (K-06).

| Кто | Своя личная | Чужая личная | Доска своего отдела (и подотделов) | Доска родительского отдела | Доска чужого отдела | Доска проекта |
|---|---|---|---|---|---|---|
| Сотрудник отдела D | видит, двигает свои | **нет** (ручки нет) | видит все задачи поддерева D; ✎ — где участник; «Взять в работу» — неразобранные | — (нет родителя в его ветке) | нет (404) | доска видна, если `Project.department_id = D` (как сейчас); задачи — по `Visible` |
| Сотрудник подотдела D′ ⊂ D | то же | нет | видит поддерево D′ | **нет** (404) | нет | то же |
| Глава отдела D (`Department.manager`) | то же | нет | видит поддерево каждого управляемого отдела; ✎ **все задачи поддерева** (правит, двигает, переставляет, удаляет); «Отправить в отдел» | нет, если не глава родителя | нет; задачу туда отправить может | то же; задачи своего отдела на доске проекта — ✎ |
| ПМ (`bpp-pm`) | то же | нет | как сотрудник своего отдела | — | нет | доски своих проектов, **все задачи** (K-14) |
| ТД, АДМ (`bpp-td`, `bpp-adm`) | то же | нет | как сотрудник | — | нет | все связанные доски, все задачи (K-14) |
| ОД, ГД (`bpp-od`, `bpp-gd`) | то же | нет | **все доски всех отделов**, все задачи; только чтение и комментарии | все | все | все связанные доски, все задачи; чтение и комментарии |
| Администратор задач (`is_elevated`) | то же | доски нет; сами задачи — в реестре и по ссылке (K-17) | все доски, все задачи, полная правка, перенос в любой отдел | все | все | все |

Действия над карточкой:

| Действие | Кто | Проверка |
|---|---|---|
| Открыть, комментировать, «Наблюдать» | все, кому `Visible` | `load_for_action` (K-16) |
| Запросить доступ «на исполнение» / «на владение» | все, кому `Visible`, кто ещё не в этой роли (в т.ч. ОД и ГД) | `load_for_action` |
| Подтвердить «на владение» (с заменой / делегатом) | владелец задачи (руководитель) и глава отдела задачи; без них — `elevated` | `deciders(task, "own")` (K-31) |
| Подтвердить «на исполнение» (только заменой) | руководитель, делегаты, автор, исполнители, глава отдела задачи; без них — `elevated` | `deciders(task, "execute")` (K-31) |
| История запросов и передач владения отдела | глава отдела доски, ОД и ГД, `elevated` | `department_history` (K-32) |
| Получать уведомления о задаче | только участники (K-29), минус выключенные доски (K-30) | `task_notify.notify_participants` |
| Статус (перетаскивание между колонками), прогресс, отметить/добавить пункт чек-листа, вложение | исполнители, автор, руководитель, делегаты, глава отдела задачи, `elevated` | `require_soft_edit` + FSM |
| Порядок внутри колонки | личная доска — её владелец; доска отдела — `require_soft_edit` по задаче **или** глава отдела доски; доска проекта — `require_soft_edit` **или** `Project.owner_id` | `services/board_service.can_reorder` |
| Правка полей, участники, метки, срок, удаление чек-листа, удаление задачи | автор, руководитель, делегаты, глава отдела задачи (K-06), `elevated` | `require_full_edit` |
| «Взять в работу» | кто видит задачу через `Q_dept` | задача без исполнителя, статус `backlog`/`todo` (409 иначе) |
| «Отправить в отдел» | глава отдела, в поддереве управляемых отделов которого лежит основной отдел задачи; если отдела у задачи нет — глава с полной правкой задачи; `elevated` | 403 `task_transfer_forbidden` |
| Отдел при создании / `PATCH` | рядовой — только поддерево своего отдела или пусто; глава — любой; `elevated` — любой | 403 `task_department_forbidden` |

ОД и ГД «только чтение» получается само: видимость им расширена, а `can_edit`/`can_progress` не меняются — права на правку у директора есть, только если он сам участник задачи.

### 5.4 Как не открыть чужую личную доску

1. Ручки личной доски — `GET boards/personal`, `GET boards/personal/summary` (профиль), `POST tasks/<id>/move` с `board.kind="personal"` — берут владельца **только** из `request.token.user_id`; в схемах Pydantic нет поля пользователя, лишнее поле отвергается (`extra="forbid"`).
2. Ранги личной доски пишутся и читаются по `board_id = token.user_id`; ручки выборки рангов по чужому `board_id` для `personal` нет. Признак «новая» (`seen_at`) отдаётся только по строке самого вызывающего.
3. Задачи без проекта, отдела и связей не входят ни в `Q_dept`, ни в `Q_alldept`, ни в `Q_boards` — значит, ни директор, ни ПМ не увидят чужую личную задачу ни на одной доске, ни в общем списке `GET tasks/`. Администратор задач видит их в реестре (K-17), но доска как представление (ранги владельца, «новые» владельца) ему недоступна.
4. Сторож-тест (§9, этап 1): параметризованно по ролям ОД, ГД, ТД, ПМ, глава отдела — чужая личная задача: 404 в `GET tasks/<id>`, нет в `GET tasks/`, нет на досках отделов и проектов, 404 на `comments`, `feed`, `move`. Для `elevated` — проверка, что `boards/personal` отдаёт **его** доску, а не чью-то ещё, при любых query-параметрах.
5. Сторож на форму ручки: в `urls.py` у `boards/personal*` нет параметров пути, схема ответа не содержит `user_id` владельца.

### 5.5 Отдел задачи и перенос

`services/department_rules.py`:
- `assert_department_allowed(scope, department_ids)` — для создания и `PATCH`. Пусто — можно. Рядовой: каждый id ∈ `S`. Глава: любой действующий. `elevated`: любой. Нужен `hr`: при выключенном `hr` и непустом отделе — 503 (было: «принимаем любые id, чтобы создание работало без `hr`», `task_service.py:437-441` — меняется сознательно: проверка прав важнее).
- `transfer(task, target_department_id, actor, *, sender_department_id=None)` — одна транзакция, `select_for_update` задачи:
  1. проверка права (§5.3), цель — действующий отдел, не текущий; задача не `done`/`cancelled` (409 `task_transfer_terminal`);
  2. отправитель = прежний основной отдел (если его нет — `sender_department_id` из диалога, по умолчанию первый управляемый отдел актёра; у администратора без управляемых отделов — без связи `origin`);
  3. связь отправителя → `origin` (если цель — бывший `origin`, он становится `member`); прежняя `member`-связь основного отдела снимается; `department_id = target` + `member`-связь цели;
  4. `assignee_id = None`, строки `TaskAssignee` удаляются; руководитель и автор остаются;
  5. статус → `todo` системным переходом (`Task.apply_transition` не зовётся: из `in_review` FSM в `todo` не пускает; переход логируется как `status` с пометкой события `transfer`);
  6. журнал: `transfer`, `department_id`, `assignee_id`, `status`;
  7. ранги прежней доски отдела удаляются, на доске цели — в конец колонки `todo`;
  8. уведомление главе отдела-получателя через `notifications.interface.notify` (`deliver=False`, как прочие уведомления задач, `task_service.py:356-368`).
- Создание с чужим отделом главой — то же правило отправителя: связь `origin` на его управляемый (или свой) отдел; исполнители при этом не принимаются (422 `task_transfer_assignees`).

---

## 6. API

Префикс `/api/tasks/v1/`. Гейт — `api_view(module="tasks", level="read")` для чтения, `level="write"` для записи (у `employee-basic` модуль `tasks` агрегируется в `write`, `access/0004`); `test_gate.py` требует `module=` и `level=` у каждой ручки. Диспетчеры в `urls.py` — строгие, только по `request.method`. Новые вьюхи — пара `views_boards.py`/`urls_boards.py` и `views_checklists.py`/`urls_checklists.py`, подключаются из `urls.py` (`include`), чтобы не раздувать `views.py` (2467 строк).

### 6.1 Доски

| Ручка | Метод | Ответ / тело |
|---|---|---|
| `boards/` | GET | `{personal: true, departments: [{id, name, path, depth, source: own\|managed\|all, is_active}], projects: [{id, name, color, project_ref, project_code}]}` — что можно открыть. `departments`: поддерево своего отдела + управляемых (только действующие отделы); с `tasks.departments.all` — все отделы компании, **включая неактивные** (с пометкой «неактивен», в конце списка; Q-K17). Доска неактивного отдела открывается по прямой ссылке тем, кто её видит. `projects` — `project_service` видимые доски |
| `boards/personal` | GET | Доска (формат ниже). Фильтры: `?q=&label=&member=&due=overdue\|soon\|none&new=1&done_days=30` |
| `boards/personal/summary` | GET | Блок профиля (K-27): `{new: [карточка…] (до 5, новые сверху по `assigned_at`), new_count, upcoming: [карточка…] (до 5: `todo`/`in_progress`/`in_review` по `due_date`, без срока — в конце), columns: [{status, count}], overdue_count}`. Те же облегчённые карточки, что на доске. Владелец — только из токена |
| `boards/departments/<id>` | GET | Доска отдела `<id>` с поддеревом. 404 — нет доступа или отдела. 503 — `hr` выключен |
| `boards/projects/<id>` | GET | Доска проекта (`tasks.Project.id`). 404 — доска не видна |
| `tasks/<id>/move` | POST | `{board: {kind, id?}, status, before_id?, after_id?}` (у `personal` поля `id` нет). Ответ — карточка. Ошибки: 400 `task_transition_invalid` + `allowed` (FSM; код 400 — как у нынешнего `PATCH`, `views.py:520-522`), 403 (нет права на статус/порядок), 404 (задача не на этой доске), 409 `board_order_stale` (соседи не в этой колонке — клиент перечитывает колонку) |

| `boards/notifications` | GET | Доски, по которым у меня выключены уведомления (K-30): `[{board: {kind, id, title}}]`; доски, к которым доступ потерян, не отдаются |
| `boards/departments/<id>/notifications`, `boards/projects/<id>/notifications` | PUT | `{enabled: bool}` → `{enabled}`. Право — видимость доски (404 иначе); идемпотентно |

Формат доски:
```json
{
  "board": {"kind": "department", "id": 12, "title": "Отдел снабжения", "background": {"type": "gradient", "value": "neutral"},
            "notifications_enabled": true},
  "columns": [{"status": "todo", "count": 14, "cards": [ … ], "has_more": false}],
  "can": {"reorder": true, "create": true}
}
```
Карточка (облегчённая, не `build_detail`):
```json
{"id": 501, "key": "TSK-501", "summary": "…", "status": "todo", "priority": "high",
 "labels": [{"id": 3, "name": "Срочно", "color": "#e11d48"}],
 "due_date": "2026-10-25", "completed_at": null, "progress_percent": 30,
 "has_description": true,
 "counts": {"comments": 4, "attachments": 1, "checklist_done": 3, "checklist_total": 7},
 "members": [{"user_id": 7, "name": "…", "avatar_url": "…", "role": "primary"}],
 "project": {"id": 2, "name": "…", "color": "#3b82f6"}, "department": {"id": 12, "name": "…"},
 "relation": "own", "rank": "a0V", "is_new": false}
```
`is_new` — только на личной доске и в `summary` (K-28); на досках отделов и проектов — всегда `false`, чтобы не раскрывать, что открыл или не открыл другой человек.
- Сборка — `services/board_service.py::build_board`: одна выборка задач `Visible & условие доски`, `select_related("project")`, `prefetch_related("labels", "assignees")`, счётчики — коррелированными подзапросами `Subquery(Count)` + `Coalesce(…, 0)` (не джойн, иначе `.distinct()` и счётчики множат друг друга), ранг — `Subquery` по `BoardCardRank` доски; имена и аватары — одним батчем `users.interface` (как `hydration.user_briefs`). Итого ~6 запросов на доску независимо от числа карточек; сторож `django_assert_max_num_queries`.
- Колонка до 200 карточек; больше — `has_more` и `GET boards/<…>?status=<s>&after_rank=<r>` (дозагрузка колонки).
- Фон: доска проекта — `tasks.Project.color` (сервер отдаёт цвет, градиент строит фронт), личная и отдела — нейтральный градиент темы.

### 6.2 Изменённые ручки задач

| Ручка | Что меняется |
|---|---|
| `POST tasks/` | `assert_department_allowed` (403 `task_department_forbidden`); `reporter_id` — только `elevated` (K-25); начальный статус `backlog`/`todo` у не-`elevated` (422 иначе); новое поле `board: {kind, id?}` — карточка встаёт в конец колонки этой доски (быстрое добавление); глава с чужим отделом — связь `origin`, исполнители запрещены |
| `PATCH tasks/<id>` | отдел (`department_id`, `department_ids`) — то же правило; за поддерево рядового — 403; `department_ids` заменяет только `member` |
| `GET tasks/<id>` | + `checklists` (этап 3), + `department_links: [{department_id, name, kind}]` (этап 1), + `can` — этап 1: `{full_edit, soft_edit, comment, transfer, claim, delete}`, этап 3: `+ request_access: ["execute","own"], decide_access` — для кнопок модального окна, + `pending_access_requests` (число, решающим); `activities` — сортировка явно по `created_at` |
| `GET tasks/` | + `?scope=mine\|department` (этап 1, для старых вкладок `EmployeeTasks`, §2.2 п.4) |
| `POST tasks/<id>/claim` | новая (этап 1): 409 `task_claim_unavailable` — уже есть исполнитель или статус не `backlog`/`todo`; 404 — не видна |
| `POST tasks/<id>/transfer` | новая (этап 1): `{department_id, sender_department_id?}`; 403 `task_transfer_forbidden`, 409 `task_transfer_terminal`, 422 — цель неактивна или совпадает с текущей |
| `POST tasks/<id>/seen` | новая (этап 2): 204; ставит `seen_at` строке `TaskAssignee` вызывающего (§3.3); невидимая задача — 404 |
| `PATCH tasks/<id>/assignees`, `PATCH tasks/<id>` (`assignee_id`) | `seen_at` новым исполнителям — `NULL`, самому актёру — `now()` (§3.3); уведомления — через `notify_participants` (§3.4) |
| `POST tasks/<id>/access-requests` | новая (этап 3, K-31): `{kind: "execute"\|"own", comment?}` → 201 запрос; 404 — задача не видна; 409 `task_access_already` (уже в этой роли), `task_access_pending` (уже ждёт) |
| `GET tasks/<id>/access-requests` | новая: решающим — все ожидающие и последние 20 решённых; остальным — только свои |
| `POST access-requests/<id>/approve` | новая: `{mode?: "replace"\|"delegate", comment?}` — для «владения» `mode` обязателен, для «исполнения» запрещён (422 `task_access_mode`); решает любой из `deciders(task, kind)` (403 `task_access_forbidden`); уже решён другим — 409 `task_access_decided` с тем, кто и как решил |
| `POST access-requests/<id>/reject` | новая: `{comment?}`; те же решающие и коды |
| `DELETE access-requests/<id>` | новая: отзыв своим автором, пока `pending` (204) |
| `GET access-requests/inbox` | новая (K-32): `{to_decide: […], mine: […], to_decide_count}` — ожидающие запросы к задачам, где я решающий, и мои запросы за 90 дней со статусом. Строка: `{id, task: {id, key, summary, board}, requester, kind, comment, status, decided_by, decided_at, created_at}` |
| `GET boards/departments/<id>/access-history` | новая (K-32): `?kind=execute\|own\|transfer&status=&from=&to=&cursor=` — история отдела: запросы (с `approve_mode` и кого заменили) и передачи владения. Право — глава этого отдела (отдел в поддереве управляемых), ОД и ГД (`tasks.departments.all`), `elevated`; иначе 404 |

### 6.3 Чек-листы (этап 3)

| Ручка | Метод | Права |
|---|---|---|
| `tasks/<id>/checklists` | GET (видимость), POST `{title}` | POST — `require_soft_edit` |
| `checklists/<id>` | PATCH `{title?, before_id?, after_id?}`, DELETE | PATCH — soft, DELETE — `require_full_edit` |
| `checklists/<id>/items` | POST `{text, before_id?, after_id?}` | soft |
| `checklist-items/<id>` | PATCH `{text?, is_done?, checklist_id?, before_id?, after_id?}`, DELETE | soft |

Ответ — чек-лист целиком `{id, title, position, items: [{id, text, is_done, done_by: {id, name}, done_at, position}], done, total}`. Каждая запись — строка `TaskActivity` в той же транзакции. Задача ищется через `load_for_action` (404 на невидимую), ключ пункта — через его чек-лист и задачу (404, а не 403, на чужой).

### 6.4 Лента (этап 3)

`GET tasks/<id>/feed?details=0|1&before=<курсор>&limit=30` — комментарии и записи `TaskActivity` одной хронологией (новые сверху). `details=0` — комментарии и ключевые события (`status`, `transfer`, `claim`, `checklist_item_checked`); `details=1` — все записи. Значения журнала гидрируются: id пользователей и отделов → имена, статусы — ключи i18n на фронте. Курсор — `(created_at, kind, id)`. Права — видимость.

### 6.5 Узлы прав и `API.md`

- `apps/tasks/access_functions.py`: `("tasks.departments", "Доски отделов")`, `("tasks.departments.all", "Доски всех отделов", ("view",))`, `EXPLICIT_ONLY = frozenset({"tasks.departments.all"})`. Узел `tasks.departments` — только родитель для дерева редактора ролей, ручки его не проверяют.
- `apps/project/access_functions.py`: `EXPLICIT_ONLY |= {"project.board"}` (K-15).
- `API.md`, раздел «apps.tasks»: строки всех ручек §6.1–6.4, правка строк `tasks/`, `tasks/{id}/`, `projects/` (видимость задач держателем `project.board` больше не «по своим правилам»), коды ошибок.

---

## 7. Фронт

### 7.1 Компоненты — `fe/features/tasks/board/`

| Компонент | Что |
|---|---|
| `BoardsPage.tsx` | страница; разбор маршрута → ключ доски, фон, шапка, холст, модальное окно по `?card` |
| `BoardHeader.tsx` | название; переключатель «Моя / Отдел / Проекты» (`BoardSwitcher`); у ОД и ГД — выбор отдела и проекта из `GET boards/` (поиск по названию); фильтры участник/метка/срок; поиск; кнопка-колокольчик «Уведомления по доске» (вкл/выкл, `BoardNotificationsToggle`) — на досках отделов и проектов, не на личной |
| `BoardNotificationsToggle.tsx` | колокольчик с подсказкой «Уведомления о ваших задачах на этой доске» (перечёркнутый — выключены); `PUT …/notifications`, оптимистично; в `BoardSwitcher` у каждой доски — тот же переключатель, чтобы держатель узла включал и выключал уведомления по многим доскам, не открывая каждую |
| `BoardCanvas.tsx` | горизонтальная прокрутка, `DragDropContext`, `onDragEnd` → `useMoveCard` |
| `BoardColumn.tsx` | колонка 272 px, `rounded-xl` (12 px), заголовок жирный + счётчик + меню «…» (свернуть, «показать завершённые за …»); вертикальная прокрутка внутри (`max-height: calc(100dvh − шапка)`), без пагинации; `Droppable` |
| `BoardCard.tsx` | карточка `rounded-lg` (8 px), тень `shadow-card`, рамка `ring` при наведении, карандаш быстрой правки в углу; `Draggable`; клик → `?card=<id>` |
| `CardLabels.tsx` | полоски 8 px сверху; клик разворачивает подписи на всех карточках (флаг в `localStorage` с `try/catch`) |
| `CardBadges.tsx` | срок (красный — просрочен, жёлтый — ≤ 2 дней, зелёный — выполнено), чек-лист `3/7` (зелёный при полном), комментарии, вложения, значок описания, аватары справа |
| `CardQuickEdit.tsx` | поповер карандаша: название, метки, срок, участники (переиспользует редакторы из `KanbanBoard.tsx:498-662`, перенесённые в `features/tasks/board/editors/`) |
| `QuickAddCard.tsx` | «+ Добавить карточку» внизу колонки → поле на месте, Enter создаёт (`POST tasks/` с `board`, статус колонки), Esc отменяет; отдел — доски отдела, проект — доски проекта |
| `CardModal.tsx` | shadcn `Dialog` поверх доски (затемнение), ширина до 768 px; на телефоне — на весь экран |
| `CardTitle.tsx`, `CardDescription.tsx` | правка на месте (textarea с автоувеличением; Enter/blur — сохранить, Esc — отмена) |
| `CardMetaRow.tsx` | отдел/проект и «в колонке В работе», участники, метки, срок, приоритет, прогресс |
| `ChecklistBlock.tsx`, `ChecklistItem.tsx` | полоса прогресса над чек-листом, «скрыть отмеченные», добавление пункта, перетаскивание пунктов |
| `ActivityFeed.tsx` | лента `GET feed` (бесконечная), переключатель «показать подробности», поле комментария сверху |
| `CardSidebar.tsx` | «Добавить»: участники, метки, чек-лист, срок, вложение; «Действия»: переместить (колонка + место), «Отправить в отдел» (только при `can.transfer`), «Наблюдать», «Запросить доступ» (при непустом `can.request_access`), «Удалить» (при `can.delete`). Тому, кто только видит задачу, блок «Добавить» не показывается — у него «Комментарий», «Наблюдать», «Запросить доступ» |
| `AccessRequestDialog.tsx` | выбор «На исполнение» / «На владение» с пояснением, что это даёт, и комментарий; после отправки — плашка «Запрос отправлен, ждёт решения» с кнопкой «Отозвать» |
| `AccessRequestsBanner.tsx` | решающим — плашка над описанием «Запросы доступа: N» со списком (кто, вид, комментарий) и кнопками: «на исполнение» — «Заменить исполнителя» (с именем того, кого снимут) / «Отклонить»; «на владение» — «Передать владение (заменить)» / «Сделать делегатом» / «Отклонить»; комментарий к отказу; ответ 409 «уже решено» — плашка обновляется с именем решившего |
| `TasksRequestsPanel.tsx` | панель «Запросы» на странице досок (K-32): кнопка в шапке со счётчиком ожидающих, выдвижная панель справа (`Sheet`) с вкладками «Ждут моего решения» (одобрить/отклонить прямо из списка, клик по задаче — `?card=<id>`), «Мои запросы» (статус, отзыв) и — главе отдела текущей доски — «История отдела» (лента запросов и передач владения с фильтрами вид/статус/период). Адрес — `?panel=requests` (ссылки из колокольчика ведут сюда) |
| `TransferDialog.tsx` | выбор отдела-получателя (дерево `GET hr/v1/departments` уже есть на фронте), отдел-отправитель |
| `ProfileTasksWidget.tsx` | блок «Мои задачи» в `fe/pages/MyProfile.tsx` (K-27) — карточка в стиле соседних блоков (`bg-card rounded-3xl border p-6`, как календарь `:197-203`), ставится **первым** в основной колонке (`order-3 … space-y-6`, перед `ConnectCorporateMailbox`): строка счётчиков по колонкам и «просрочено», список «Новые» с точкой-меткой, список «Ближайшие»; элемент — мини-карточка (метки-полоски, название, срок, чек-лист); клик → `navigate('/tasks/board?card=<id>')`; кнопка «Открыть мою доску» → `/tasks/board`. Пусто — «Задач нет» и кнопка «Создать задачу» (открывает доску с полем быстрого добавления). Блок скрыт, если нет `tasks:read` или модуль `tasks` выключен у компании (503 — без тоста) |

Кнопки показываются по `can` из ответа карточки и доски — сервер единственный источник прав; фронт ничего не выводит из ролей.

### 7.2 Хуки и ключи запросов — `fe/features/tasks/board/hooks/`

| Хук | Ключ | Что |
|---|---|---|
| `useBoards()` | `['tasks','boards']` | список досок |
| `useBoard(key, filters)` | `['tasks','board',kind,id,filters]` | доска |
| `useMoveCard(key)` | — | оптимистично: `cancelQueries` → снимок → перестановка в кэше → `onError` откат + toast с текстом сервера → `onSettled` инвалидация доски и `['tasks','card',id]` |
| `useCard(id)` | `['tasks','card',id]` | detail |
| `useCardParam()` | — | синхронизация `?card` (§7.3) |
| `useChecklists(taskId)` | внутри `['tasks','card',id]` | отметка пункта — оптимистично |
| `useTaskFeed(id, details)` | `['tasks','feed',id,details]` | `useInfiniteQuery` |
| `useQuickAdd(key, status)` | — | оптимистичная вставка временной карточки, замена по ответу |
| `useBoardNotifications(key)` | `['tasks','boards','notifications']` | переключение с оптимистичным обновлением кэша доски и списка выключенных досок |
| `useAccessRequests(taskId)` | `['tasks','card',id,'access-requests']` | список, создание, одобрение, отказ, отзыв; после решения — инвалидация карточки (сменились участники и `can`) и `['tasks','requests']` |
| `useRequestsInbox()` | `['tasks','requests','inbox']` | панель и счётчик; перечитывается при фокусе окна и по приходу уведомления колокольчика с кодом `access_*` |
| `useDepartmentHistory(id, filters)` | `['tasks','requests','history',id,filters]` | `useInfiniteQuery` |
| `usePersonalSummary()` | `['tasks','boards','personal','summary']` | блок профиля; `staleTime` 30 с, перечитывается при фокусе окна — новые задачи появляются без перезагрузки |
| `useMarkSeen(id)` | — | `POST tasks/<id>/seen` при открытии окна карточки; оптимистично снимает `is_new` в кэше личной доски и `summary` |

API-функции — в `fe/api/tasks.ts` (рядом с существующими), типы — `fe/types/tasks.ts` (`BoardKey`, `Board`, `BoardCard`, `Checklist`, `FeedEntry`).

### 7.3 Маршруты и `?card`

- `routeDefinitions.ts`: `/tasks/board` (личная), `/tasks/board/department/:id`, `/tasks/board/project/:id` — `requiresAuth`, `requires: {module: 'tasks', level: 'read'}`; объявить до `/tasks/:id` (тот совпадает только с одним сегментом, но порядок — по образцу `:106`).
- Открытие карточки внутри приложения — `navigate({search: '?card=<id>'}, {state: {cardFromBoard: true}})` (запись в историю: «назад» закрывает окно). Закрытие (Esc, крестик, клик по затемнению): если `state.cardFromBoard` — `navigate(-1)`, иначе (прямой заход по ссылке) — удалить параметр с `replace`. Образец синхронизации — `fe/components/calendar/CalendarWidget.tsx:114-134`.
- Прямой заход: доска и карточка грузятся параллельно; 404 карточки — toast «Карточка недоступна» и удаление параметра; карточка не с этой доски, но видна — окно открывается всё равно (подпись «на другой доске» со ссылкой).
- Переход из профиля (K-27) — это прямой заход: `/tasks/board?card=<id>` открывает личную доску с окном карточки; закрытие удаляет параметр с `replace`, пользователь остаётся на своей доске, «назад» в браузере возвращает в профиль; переключатель в шапке ведёт на доску отдела.
- Остальные фильтры доски — тоже в адресе (`?q=&label=&member=&due=`), через `setSearchParams(fn, {replace: true})`, как `features/bpp/core/useRegistryState.ts:61-82`.

### 7.4 Визуальный язык

- Токены в `fe/index.css` (`:root` и `.dark`): `--board-canvas-from/to` (нейтральный градиент), `--board-column` (светло-серый / поверхность темы на шаг светлее `--card` в тёмной), `--board-card`, `--board-card-hover-ring`, `--board-badge-overdue/soon/done`. В `tailwind.config.ts` — `colors.board.*`. Цвет проекта — из данных: градиент `linear-gradient(135deg, <color>, <color сдвинутый по светлоте>)` с контрастным текстом шапки (вычисление светлоты на клиенте).
- Наклон при перетаскивании — `rotate(3deg)` и `shadow-elevated` на **внутреннем** элементе карточки по `snapshot.isDragging` (на обёртку `Draggable` нельзя: библиотека пишет туда свой `transform`); место вставки — `provided.placeholder` в стиле пустой карточки с пунктирной рамкой.
- Телефон: колонка `min(272px, 85vw)`, `scroll-snap-type: x mandatory` у холста, поля по краям 16 px; окно карточки — на весь экран.
- Клавиатура: `@hello-pangea/dnd` поддерживает перенос с клавиатуры (пробел/стрелки); у окна — фокус-ловушка Radix `Dialog`.
- Все строки — новые ключи `tasks.board.*`, `tasks.card.*`, `tasks.checklist.*`, `tasks.feed.*` в `public/locales/ru|en/translation.json`; сторож — `translationKeys.test.ts`.

### 7.5 Судьба старых страниц

| Страница | Этапы 4–5 | Этап 6 |
|---|---|---|
| `KanbanBoard.tsx` | без изменений (только §2.2 п.13 не чиним) | удаляется |
| `EmployeeTasks.tsx` | `?scope=mine\|department`, «Принять» → `claim` (этап 1) | удаляется: «Мои задачи» = личная доска, «Задачи отдела» = доска отдела |
| `HRTasks.tsx` | без изменений | остаётся реестром с фильтрами для `tasks:admin` по адресу `/tasks/list`; вид «Доска» в нём убирается (ведёт на `/tasks/board`) |
| `TaskRouter.tsx` | без изменений | `/tasks` → редирект на `/tasks/board` |
| `TaskDetailRouter.tsx`, `HRTaskDetail`, `EmployeeTaskDetail` | без изменений | `/tasks/:id` остаётся (совместимость, ссылки уведомлений `notificationTargetUrl`), получает кнопку «Открыть на доске» |
| `HRProjects.tsx`, вкладка «Задачи» | — | кнопка «Открыть доску» → `/tasks/board/project/<id>` |
| `TasksLayout.tsx` (меню) | пункт «Доски» скрыт до этапа 6 | пункт «Доски» первым |
| `MyProfile.tsx` | без изменений | блок «Мои задачи» (`ProfileTasksWidget`) первым в основной колонке |

### 7.6 Производительность

- Доска — один запрос (§6.1), без N+1: счётчики подзапросами, участники батчем; карточка — облегчённая.
- `BoardCard` — `React.memo` по `card` и `labelsExpanded`; колонка не перерисовывает соседей при переносе (кэш доски нормализован по колонкам).
- Виртуализации в первой версии нет: колонка до 200 карточек; `@hello-pangea/dnd` с виртуальными списками требует отдельного API — вернуться, если замеры на стенде покажут проседание (порог — 300 карточек на доске на среднем ноутбуке).
- Бюджет бандла — `npm run build` (проверка размера в `postbuild`); фича грузится лениво (`lazyPages.ts`).

---

## 8. Этапы

Каждый этап самостоятельно выкатывается; порядок — по зависимостям. Задачи этапа — фаза K в `Plans.md`, пошаговый план — к старту этапа.

### Этап 1. Видимость и права (бэкенд)
- **K1.1** `hr.interface.department_subtree_ids`, `managed_department_ids` (+ индекс `path` для `LIKE`, если нет) и их тесты.
- **K1.2** `access/0028_tasks_board_nodes`: узел `tasks.departments.all` (+ `EXPLICIT_ONLY`), `bpp-gd` → `view` на `project.board`, `project.board` в `EXPLICIT_ONLY` + пустые строки у не-`bpp` системных ролей; правка матрицы ролей БЗО; сторож строк на двух узлах этапа.
- **K1.3** `TaskScope`, новые `visibility_q`/`scope_for`/`load_for_action`, переход пяти потребителей; кэш на запрос; `board_scope` — с `resolution=`.
- **K1.4** `tasks/0027_department_link_kind`; `department_rules` (создание, `PATCH`), `reporter_id`, начальный статус; `department_id` в `TRACKED_FIELDS`.
- **K1.5** `POST tasks/<id>/transfer`, `POST tasks/<id>/claim`, `?scope=mine|department`, `can` в ответе карточки; фронт: «Принять» в `EmployeeTasks` → `claim`, обе вкладки → `?scope=`, простой диалог «Отправить в отдел» на `/tasks/:id` (тот же компонент потом встанет в окно карточки, этап 5).
- Выкатывается сам: пользователи видят больше задач в старом интерфейсе, директора — задачи внутри досок проектов.

### Этап 2. API досок и порядок (бэкенд) — после этапа 1
- **K2.1** `services/board_rank.py` (чистые функции + перебалансировка), `tasks/0028_board_card_rank`.
- **K2.2** `services/board_service.py`: `GET boards/`, `boards/personal`, `boards/departments/<id>`, `boards/projects/<id>`, облегчённая карточка со счётчиками.
- **K2.3** `POST tasks/<id>/move` (FSM, права на порядок, ранг одной записью), `board` в `POST tasks/`.
- **K2.4** «Новые задачи»: `tasks/0029_assignee_seen_at`, `seen_at` в назначениях, `POST tasks/<id>/seen`, `is_new` на личной доске, `GET boards/personal/summary`; вызов `seen` со старой страницы `/tasks/:id` (`HRTaskDetail`, `EmployeeTaskDetail`) — чтобы признак гас и до нового окна карточки.
- Выкатывается сам: API без потребителя, старый интерфейс не меняется.

### Этап 3. Чек-листы и лента (бэкенд) — после этапа 1 (параллельно этапу 2)
- **K3.1** `tasks/0030_checklists`, сервис, ручки §6.3, журнал.
- **K3.2** `GET tasks/<id>/feed`, гидрация значений журнала; `checklists`, `department_links`, `can` в detail.
- **K3.3** Уведомления участникам (K-29, K-30): `services/task_notify.py` вместо разрозненных `_notify`, `tasks/0031_board_notification_mute`, ручки выключателя, `notifications_enabled` в ответе доски; события — добавлен исполнитель, смена основного исполнителя и `claim`, статус, комментарий, перенос. Зависит от `boards/` этапа 2 только ответом доски.
- **K3.4** Запросы доступа (K-31, K-32): `tasks/0032_task_access_request`, `services/access_requests.py` (решающие, «первый решивший», история отдела), ручки §6.2 включая `inbox` и `access-history`, `can.request_access`/`decide_access` в detail, журнал и адресные уведомления.

### Этап 4. Доски на фронте — после этапа 2
- **K4.1** Токены `--board-*`, `BoardsPage`, `BoardHeader`/`BoardSwitcher`, `BoardCanvas`, `BoardColumn`, `BoardCard`, `CardLabels`, `CardBadges`.
- **K4.2** Перетаскивание с порядком (`useMoveCard`, откат), `QuickAddCard`, `CardQuickEdit`, фильтры и поиск в адресе.
- **K4.3** Выключатель уведомлений в шапке доски и в переключателе досок (после K3.3).
- Маршруты `/tasks/board/*` живут, пункта меню ещё нет — проверка на стенде по прямой ссылке.

### Этап 5. Карточка-окно — после этапов 3 и 4
- **K5.1** `CardModal` и `?card` (`useCardParam`), заголовок и описание на месте, строка мета-данных.
- **K5.2** `ChecklistBlock`, `ActivityFeed`, `CardSidebar`, `TransferDialog`, `AccessRequestDialog`, `AccessRequestsBanner` (после K3.4).
- **K5.3** `TasksRequestsPanel` на странице досок: «Ждут моего решения», «Мои запросы», «История отдела» (K-32).

### Этап 6. Переключение и уборка — после этапа 5
- **K6.1** Меню «Доски», `/tasks` → `/tasks/board`, `HRTasks` → `/tasks/list`, удаление `EmployeeTasks`, `KanbanBoard`, `TaskRouter`; «Открыть на доске» в `/tasks/:id`; «Открыть доску» в `HRProjects`.
- **K6.2** Блок «Мои задачи» в профиле (`ProfileTasksWidget`, K-27): переход на `/tasks/board?card=<id>`, «Открыть мою доску». Идёт вместе с K6.1: блок ведёт на доски, поэтому показывается, когда доски открыты всем.
- **K6.3** e2e, `STRUCTURE.md` §4.2 (абзац Kanban), `API.md`, `CLAUDE.md` (абзац «Канбан-доски»), `harness-review`, PR.

```
Этап 1 ──┬── Этап 2 ──┬── Этап 4 (K4.3 — после K3.3) ──┐
         └── Этап 3 ──┴────────────────────────────────┴── Этап 5 ── Этап 6
```

---

## 9. Тесты по этапам

Бэкенд — pytest на Postgres `:55432`, Python 3.14 (корневой `.venv`), один прогон за раз; заголовок компании и роль — `apps/tasks/tests/helpers.py::auth`, `apps/access/tests/helpers.py::assign`; оргструктура — фикстурой через модели `hr` в схеме компании теста. Фронт — vitest, eslint, `tsc -p tsconfig.app.json` (число ошибок не растёт против базы на старте этапа).

### Этап 1 — `tasks/tests/test_board_visibility.py`, `test_department_rules.py`, `test_transfer.py`, `test_claim.py`; `hr/tests/test_interface_departments.py`; `access/tests/test_tasks_board_nodes.py`, `test_explicit_only_rows.py`
- сотрудник отдела `it` видит задачу подотдела `it.dev` в статусе `in_progress` с чужим исполнителем — в `GET tasks/`, в `GET tasks/<id>`, в `comments`;
- сотрудник `it.dev` не видит задачу отдела `it` (404) и не видит задачу `it.devops` (проверка разделителя «.»);
- задача видна через `TaskDepartmentLink(kind=member)` и через `origin`;
- глава `it` (числится в `directorate`) видит поддерево `it`; глава двух отделов — оба;
- рядовой создаёт задачу с отделом вне поддерева → 403 `task_department_forbidden`; со своим подотделом → 201; без отдела → 201; `PATCH department_ids` за пределы → 403;
- глава создаёт задачу в чужой отдел → 201, связь `origin` на его отдел, исполнители → 422;
- глава переносит задачу `in_review` с исполнителем в чужой отдел → у получателя без исполнителя, статус `todo`, `origin` у отправителя, журнал `transfer`/`department_id`/`assignee_id`/`status`, уведомление главе-получателю; рядовой → 403; `done` → 409; повторный перенос обратно → `origin` стал `member`;
- `PATCH department_ids` не стирает `origin`;
- ОД и ГД: видят задачи любого отдела и любой связанной доски проекта; `PATCH` такой задачи → 403; комментарий → 201;
- глава отдела `it` (не участник) правит задачу подотдела `it.dev` (`PATCH` полей, участники, статус, удаление) → 200; задачу соседнего `ops` → 403 (и 404, если не видит); после переноса задачи из `it` в `ops` глава `it` видит её по связи `origin`, но `PATCH` → 403; глава `ops` — 200;
- ТД/АДМ/ПМ через `project.board` — задачи досок (ПМ — только своих проектов);
- чужая личная задача (без проекта и отдела) не видна ОД, ГД, ТД, ПМ, главе отдела: 404 в detail, нет в списке, 404 в `comments`, `activity`; `elevated` её видит в `GET tasks/` и `GET tasks/<id>` (K-17);
- `elevated` переносит задачу в любой отдел, не будучи главой (K-09);
- `claim`: неразобранная задача отдела → primary + `in_progress`; уже с исполнителем → 409; невидимая → 404;
- `reporter_id` от рядового игнорируется;
- `hr` выключен: ветка отдела пустая, задачи-участия видны, создание с отделом → 503;
- число запросов `GET tasks/` не растёт с числом отделов поддерева (`django_assert_max_num_queries`);
- `access/0028`: строки `tasks.departments.all` у всех системных ролей кроме `platform-admin` (`view` — только `bpp-od`, `bpp-gd`); `bpp-gd` — `view` на `project.board`; кастомная роль с `tasks:admin` не видит «все отделы»; `project.board` — явная строка у каждой системной роли, кроме `platform-admin`, и `EXPLICIT_ONLY`;
- обновлённые `test_bpp_roles.py::test_board_link_is_for_td_od_pm_and_adm` (+ГД), `test_board_scope.py` (держатель видит задачи доски).

### Этап 2 — `test_board_rank.py` (чистые функции), `test_boards_api.py`, `test_move.py`
- `between` на краях и в середине, длина, перебалансировка сохраняет порядок;
- `boards/personal` содержит задачи-исполнения, автора, руководителя, делегирования и наблюдения (K-03) с верным `my_role`; задача отдела, где пользователь только коллега, — нет; ручка не принимает `user_id` (лишний query/тело игнорируется/422) и не отдаёт чужие ранги;
- `boards/`: у ОД и ГД неактивный отдел в списке с `is_active=false`, у главы и рядового — нет (Q-K17);
- `boards/departments/<id>`: поддерево, `relation` own/linked/sent; чужой отдел → 404; ОД → 200 для любого;
- `boards/projects/<id>`: ОД видит все задачи; сотрудник без участия — только свои;
- `move` соблюдает FSM: `backlog → done` → 400 `task_transition_invalid` с `allowed`; `in_progress → in_review` → 200 и `status` в журнале; перестановка без смены статуса журнал не пишет; несвежие соседи → 409; директор → 403; владелец личной доски переставляет задачу, где он только автор;
- быстрое добавление: `POST tasks/` с `board` встаёт в конец колонки;
- число запросов доски постоянно для 5 и 150 карточек;
- «новые»: задача, назначенная пользователю другим, — `is_new` на личной доске и в `summary.new`; назначенная самим собой, взятая через `claim`, созданная им же — не новая; `POST seen` гасит признак, повторный — 204 без изменений; переназначение после просмотра снова делает новой; на доске отдела `is_new` всегда `false`; миграция `0029` не делает новыми существующие назначения;
- `summary`: счётчики по колонкам совпадают с личной доской, «ближайшие» — без `done`/`cancelled`/`backlog`, сортировка по сроку, до 5; `elevated` получает **свою** сводку.

### Этап 3 — `test_checklists.py`, `test_feed.py`
- создание чек-листа, пункта, отметка, снятие отметки, переименование, удаление пункта — исполнитель может, ОД и наблюдатель → 403; удаление чек-листа — только полная правка;
- **каждое действие чек-листа пишет `TaskActivity`** с ожидаемыми `field_name`/значениями;
- `ck_checklist_item_done` держит согласованность; лимиты → 422;
- `progress_percent` не меняется от отметок;
- лента: хронология комментариев и журнала, `details=0` прячет мелкие события, курсор без дублей и пропусков, гидрация имён.
- уведомления (`test_task_notify.py`): смену статуса получают все участники (исполнители, руководитель, автор, делегаты, наблюдатели), кроме автора события; **ОД и коллега по отделу, видящие задачу на доске, но не причастные к ней, не получают ничего**; «добавлен исполнитель» уходит участникам и адресно новому исполнителю; ОД — руководитель задачи чужого отдела — получает, пока доска этого отдела не выключена, после `PUT …/notifications {enabled:false}` — нет, а по задаче другого отдела — да (выключение одной доски не трогает другие); выключение доски `it` гасит задачи `it.dev`; адресное «вас назначили» приходит и при выключенной доске; ручка выключателя на невидимую доску — 404; одно событие — одно уведомление на человека; после отката транзакции — ни одного; `deliver=False`, ссылка — `/tasks/board?card=<id>`;
- запросы доступа (`test_access_requests.py`):
  - «на исполнение»: уведомление получают руководитель, делегаты, автор, исполнители и глава отдела, запросивший — нет; одобряет соисполнитель — запросивший стал основным исполнителем, прежний основной снят с задачи (уведомление «вас заменил»), соисполнители остались; без исполнителя — просто стал основным; `mode="delegate"` — 422; журнал `access_approved` + `assignee_id`;
  - «на владение»: уведомление получают только руководитель и глава отдела; одобряет руководитель с `replace` — запросивший стал руководителем, прежний снят; с `delegate` — запросивший делегат, руководитель тот же; третий и четвёртый делегат добавляются (ограничения нет); без `mode` — 422; автор, делегат или исполнитель пытается одобрить «владение» — 403; глава отдела одобряет — 200; глава соседнего отдела — 403; у задачи без руководителя и без отдела решает `elevated`;
  - **второй решающий после первого получает 409 `task_access_decided`**; при одновременном решении двух — ровно одно проходит (тест с двумя потоками на `transaction=True`);
  - отказ с комментарием; повторный ожидающий запрос — 409; запрос участника в его же роли — 409; запрос на невидимую задачу — 404; решает не-решающий (коллега, ОД) — 403; снятый с задачи, пока запрос ждал, — 403; отзыв — только автором и только `pending`; ОД может запросить доступ и после одобрения правит как участник; выключенная доска не гасит уведомление о запросе;
- `inbox`: «ждут решения» — только задачи, где я решающий, решённые исчезают; «мои» — со статусом;
- история отдела: глава видит запросы (с режимом подтверждения и тем, кого заменили) и передачи владения (решением по запросу и ручной `PATCH supervisor`) по задачам отдела и подотделов, со статусом и решившим; ОД и ГД — тоже, по любому отделу; глава соседнего отдела и рядовой сотрудник — 404; задачи вне поддерева в историю не попадают; фильтры вид/статус/период; курсор.

### Этап 4–5 — vitest (`features/tasks/board/__tests__/`)
- `useMoveCard`: оптимистичная перестановка и откат при 400/409;
- `useCardParam`: открытие пишет историю, закрытие после внутреннего открытия — `navigate(-1)`, после прямого захода — `replace`;
- `CardBadges`: цвета срока и чек-листа на границах дат (фиксированное «сегодня»);
- `BoardColumn`/`QuickAddCard`: Enter создаёт, Esc отменяет;
- `translationKeys.test.ts` зелёный; снимок разметки карточки в `.dark`;
- `BoardNotificationsToggle`: переключение оптимистично, откат при ошибке; на личной доске колокольчика нет;
- `CardSidebar`: у причастного — «Добавить» и «Действия», у только видящего — комментарий, «Наблюдать», «Запросить доступ»; `AccessRequestsBanner` виден только при `can.decide_access`;
- `TasksRequestsPanel`: счётчик, одобрение из списка убирает строку оптимистично и возвращает её при 409; вкладка «История отдела» только у главы текущей доски; `?panel=requests` открывает панель;
- `ProfileTasksWidget` (этап 6): клик по задаче ведёт на `/tasks/board?card=<id>`; без `tasks:read` блока нет; пустое состояние; 503 — блок скрыт без тоста; открытие окна карточки зовёт `seen` и снимает точку «новая» в кэше.

### Этап 6 — e2e `frontend/tests/e2e/42_tasks_boards.spec.ts` (`--project=chromium`)
- сотрудник: личная доска → перетаскивание в «В работе» → обновление страницы сохраняет колонку и порядок;
- `?card=` по прямой ссылке открывает окно, «назад» его закрывает, Esc — тоже;
- чек-лист: добавить, отметить, прогресс «1/2», запись в ленте;
- глава отправляет задачу в чужой отдел, получатель видит её без исполнителя, отправитель — с пометкой «отправлено»;
- ОД открывает доску чужого отдела, кнопок правки нет, комментарий публикуется;
- коллега открывает задачу отдела с доски, запрашивает доступ «на исполнение»; исполнитель задачи видит запрос в панели «Запросы» и подтверждает заменой; у автора задачи запрос пропал из «Ждут моего решения»; коллега видит задачу на своей личной доске, прежний исполнитель — уже нет; глава отдела видит запись в «Истории отдела» со статусом «Одобрено (замена)»;
- запрос «на владение»: автор задачи кнопок решения не видит, руководитель выбирает «Сделать делегатом» — запросивший получает полную правку, руководитель прежний;
- профиль: задача, назначенная другим, видна в «Новые»; клик открывает доску с окном карточки; после закрытия пользователь на своей доске, переключается на доску отдела; вернувшись в профиль, задача уже не «новая».

Сторожа на каждом этапе (быстрый CI): `test_app_isolation`, `test_invariants`, `test_platform_today`, `test_metrics*`, `translationKeys.test.ts`; руками перед PR — `test_gate`, `test_bootstrap`, `test_depth` (в `ci.yml` их нет, только в `backend-full`).

---

## 10. Выкатка на прод

**Зависимость.** `access/0028` стоит после `access/0027_tender_roles` и цепочки БЗО (`0014`–`0025`), а `project.board` и «Проекты» существуют только с модулем БЗО. На бою БЗО ещё не выкачен (прод ≈ PR #21), поэтому этапы 1–3 идут на прод **в окне выкатки БЗО или после него**, не раньше ([bpp-rollout-runbook](../deploy/bpp-rollout-runbook.md)).

Порядок (по образцу ранбука БЗО; на стенде — репетиция на дампе):
1. `manage.py tenancy_status --json` — слепок раскладки до.
2. Код этапа → `backend-web` стартует с `migrate_shared` → `access/0028` в `public`.
3. `manage.py migrate_companies` — `tasks/0027…0032` во всех схемах `co_<slug>` (expand; представления `holding.*` сносятся и собираются командой штатно).
4. Отдельного бэкфилла нет: ранги появляются при первом перемещении, `kind` — `member` по умолчанию у существующих связей, `seen_at` заполняет сама миграция `0029` (одна `UPDATE` на схему).
5. `tenancy_status` — слепок после; проверка: ОД открывает доску чужого отдела, сотрудник — задачу подотдела.
6. Фронт этапов 4–5 — без пункта меню; этап 6 — переключение `/tasks`.
7. Объявление пользователям до этапа 1: сотрудники отдела начинают видеть все задачи отдела и подотделов (§11 п.1).

**Откат.**
- Фронт — откат сборки; старые страницы живут до этапа 6, после него — откат коммита этапа 6.
- Бэкенд — откат кода: миграции `tasks` только добавляют (столбец с `db_default`, новые таблицы), старый код их не читает. Видимость возвращается вместе с кодом.
- `access/0028` обратима (`unseed`: удалить строки `tasks.departments.all`, вернуть пустую строку ГД на `project.board`, снять пустые строки `project.board` у не-`bpp` ролей) — только если откатывается и код этапа 1; иначе оставить.
- Перенесённые задачи после отката остаются в новом отделе; связи `origin` старый код видит как обычный отдел задачи — сознательно приемлемо.

---

## 11. Риски

1. **Расширение видимости — изменение приватности.** Сотрудники отдела увидят чужие задачи в работе, директора — все задачи отделов. Это решение заказчика, но пользователей надо предупредить до выкатки этапа 1, а описания задач с личными данными — перепроверить.
2. **Администратор задач видит чужие личные задачи (K-17).** Решение заказчика; приватность личных задач держится на том, что `is_elevated` выдаётся узкому кругу (`is_staff`/суперпользователь). Выдача `is_staff` «для удобства» открывает все задачи компании — это стоит держать в памяти при раздаче флага.
3. **Выкатка БЗО** ещё не прошла — этапы 1–3 стоят за ней (§10).
4. **Целостность `Department.path`.** Правка `path` через API не переписывает потомков (`department_service.py:211-218`) — поддерево «рассыплется», и подотдел выпадет из доски родителя. Решение вне плана: запретить правку `path` с потомками или переписывать их в той же транзакции (задача для `hr`, Q-K16).
5. **Цена одной ветки видимости на всех потребителях.** `Visible` используется списком задач, деревом объекта, роудмапами, досками и `load_for_action`; ошибка в формуле — утечка или пропажа задач везде сразу. Тесты этапа 1 покрывают все пять потребителей, а не только доски.
6. **Ранги при параллельной работе.** Два человека, бросившие карточки в одну щель, получат одинаковые ранги — порядок решается `task_id`; это не ошибка данных, а случайный порядок двух карточек. `409 board_order_stale` закрывает случай устаревших соседей.
7. **Объём фронта** (≈ 20 компонентов) — главный по трудоёмкости; этапы 4 и 5 разведены, чтобы доска без окна карточки уже была полезна.
8. **Тёмная тема** не включается в интерфейсе (§2.2 п.14) — тёмные токены доски проверяются только тестом, пока переключатель не вернут.
9. **Нет главы на месте — переносить некому, кроме администратора** (K-09). Если администраторов в компании мало, перенос будет ждать; это осознанная цена отказа от замещения.
10. **Больше уведомлений участникам.** Смену статуса сейчас узнаёт только основной исполнитель, после K3.3 — все участники задачи. Шум ограничен тем, что уведомления получают только причастные (K-29), есть выключатель по доске (K-30) и окно дублей 60 с.
11. **Запросы доступа без ответа.** Решающий может не ответить; запрос висит `pending`. Напоминаний и срока у запроса в первой версии нет — запросивший видит статус в карточке и может написать комментарий.

---

## 12. Открытые вопросы к заказчику

**Ответы 21.10** (внесены в §1):

| № | Вопрос | Ответ |
|---|---|---|
| Q-K01 | Расширение видимости через «Доску задач проекта» — для всех держателей узла или только для ОД и ГД? | Для всех держателей узла (K-14) |
| Q-K04 | Правила переноса в другой отдел | По умолчанию: статус `todo`, исполнители снимаются, завершённые не переносятся, переносит глава отдела задачи (K-08) |
| Q-K05 | Замещающие главы | Не нужны: перенос и прочие права главы есть у администратора задач (K-09) |
| Q-K07 | Видит ли администратор задач чужие личные задачи | Видит, как сейчас; скрывать незачем (K-17) |
| — | Дополнение | Личная доска в профиле, переход в доски по клику (K-27, K-28) |
| Q-K18 | Что считать «новой» задачей в профиле | По умолчанию: только назначение исполнителем (K-28) |
| — | Дополнение | Уведомления можно включать и выключать по каждой доске отдельно (K-30) |
| Q-K19 | Какие события и кто получает | + «добавлен исполнитель»; уведомления получают только причастные к задаче, на общей доске остальные просто видят ход работ (K-29, K-30) |
| Q-K20 | Что может тот, кто видит задачу, но не причастен | Оставить комментарий и запросить доступ «на исполнение» или «на владение» (K-31) |
| Q-K21 | Кто решает по запросу доступа | Руководитель, делегаты, автор и исполнители; уведомление — всем, решает любой, первое решение окончательное; глава отдела доски видит историю запросов и передач владения со статусами; уведомления и история — на странице «Задачи» (K-31, K-32) |
| Q-K22 | Каналы уведомлений | Пока только колокольчик; после обновления — Telegram-бот (K-33) |
| Q-K23 | Кто и как подтверждает | «Владение» — только владелец задачи и глава отдела, на выбор: с заменой или делегатом (делегатов сколько угодно); «исполнение» — все остальные причастные, только заменой (K-31) |
| Q-K24 | Видят ли историю отдела ОД и ГД | Да (K-32) |
| Q-K25 | Судьба снятого при замене; администратор как запасной решающий | По умолчанию: снятый убирается с задачи полностью (уведомление «вас заменил …»); администратор решает, только если решающих этого вида нет (K-31) |
| Q-K02 | `project.board` выдаётся только явно | По умолчанию: да (K-15) |
| Q-K03 | Входят ли в личную доску делегирования и наблюдения | Входят (K-03) |
| Q-K06 | Директора комментируют и «наблюдают» | По умолчанию: оставить (K-16) |
| Q-K08 | Права главы на задачи своего отдела | Править, видеть, переставлять, переносить (K-06) |
| Q-K17 | Доски неактивных отделов в списке | Для держателей узла `tasks.departments.all` — да, остальным — нет; задачи остаются и на доске родителя (§6.1) |

**Открытые:**

| № | Вопрос | Умолчание до ответа |
|---|---|---|
| Q-K09 | Удалять пункт чек-листа может любой исполнитель или только автор/руководитель? | Любой исполнитель (soft edit) |
| Q-K10 | Нужен ли флаг «прогресс по чек-листам» (прогресс задачи = доля отмеченных пунктов)? | Нет; на карточке отдельный значок «3/7» |
| Q-K11 | Метки — общие на компанию (как сейчас) или свои у каждой доски, как в Trello? | Общие (K-22) |
| Q-K12 | Сколько показывать завершённых и отменённых карточек на доске? | За последние 30 дней, колонки сворачиваются (K-26) |
| Q-K13 | Задачи дочерних компаний: директор холдинга, работающий на группу (`serves_subsidiaries`), на поддомене дочерней компании получит роли ОД/ГД по наследству и увидит все её доски — так и задумано? | Да (следствие модели прав) |
| Q-K14 | Возвращать ли переключатель тёмной темы в интерфейс (сейчас не смонтирован)? | Вне этого плана |
| Q-K15 | Статистика задач (`/tasks/stats`) считает по своему правилу — привести её к новой видимости? | Нет, отдельно |
| Q-K16 | Правка `path` отдела с подотделами ломает поддерево досок — запретить её в `hr` или переписывать пути потомков? | Отдельная задача в `hr`, до неё — риск §11 п.4 |

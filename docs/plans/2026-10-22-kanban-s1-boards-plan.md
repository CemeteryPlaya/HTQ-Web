# Канбан, этап S1 «Доски» — план и итог

22–23.10.2026 · ветка `ruslan` поверх `db69de26` (слияние `sanzhar`: этап 1 канбана K1.1–K1.7) · исполнитель — Руслан · статус: **сделано, не закоммичено** (коммит — по команде пользователя)

Источники: [мастер-план канбана](2026-10-21-kanban-boards-master-plan.md) §3.2–3.3, §5, §6.1–6.2, §7 (этапы 2 и 4) и [Trello-план](2026-10-22-kanban-trello-automation-plan.md) (решения K-34, K-39). Порядок: мастер-план > Trello-план > этот файл.

## Что вошло

Доски — личная, отдела (с поддеревом), проекта задач — как в Trello: холст, колонки с названиями, цветами и скрытием, карточки со значками, быстрое добавление, перетаскивание с порядком, быстрая правка, фильтр. Пункта меню нет, вход по ссылке `/tasks/board`, `/tasks/board/department/:id`, `/tasks/board/project/:id`. Окно карточки, чек-листы, лента, уведомления и запросы доступа — этап S2; карточка пока открывает страницу задачи `/tasks/:id`.

## Задачи

| № | Что | Файлы | Проверка |
|---|---|---|---|
| S1.1 | Порядок карточек и «новая задача»: `BoardCardRank` (ранг — collation `C`, уникален по доске и задаче), `TaskAssignee.seen_at` с заполнением `assigned_at` и частичным индексом непросмотренных | `tasks/models.py`, миграции `tasks/0028_board_card_rank`, `0029_assignee_seen_at` | `makemigrations tasks --check` чисто |
| S1.2 | Дробные ранги base-62: `between` (вставка между соседями, в начало и в конец без роста длины на каждой вставке), `spread` (раскладка колонки), перебалансировка длиннее 48 символов | `services/board_rank.py` | `test_board_rank.py` — 23 |
| S1.3 | Настройки колонок (K-34): `BoardSettings(board_kind, board_id, columns)`, палитра из 10 цветов, «скрыть все» — 422 `board_columns_hidden` | `models.py`, `tasks/0030_board_settings`, `schemas.py` (`BoardRef`, `CardMove`, `ColumnSettingIn`, `BoardSettingsIn`) | `test_boards_api.py` |
| S1.4 | Администратор доски (K-39): личная — владелец, отдел — глава (в т.ч. вышестоящего), проект — владелец проекта задач, плюс узел `tasks.boards.admin` (`EXPLICIT_ONLY`, явная пустая строка у системных ролей кроме `platform-admin`) и `is_elevated` | `access_functions.py`, `access/0029_tasks_boards_admin`, `board_service.is_admin` | `test_tasks_boards_admin_node.py`, `test_boards_api.py` |
| S1.5 | Доски и карточки: какая доска видна (невидимая — 404; личная — только своя), выборка задач (внутренний запрос — только id, джойны видимости не множат строки), фильтры как в Trello (422 `board_filter_invalid`), колонки — окно `RowNumber` по статусу, до 200 карточек и дозагрузка `?status=&offset=`, у скрытой колонки — счётчик без карточек, завершённые старше `done_days` (30) не показываются; облегчённая карточка (метки, срок, счётчики, участники с аватарами, `relation`, `rank`, `is_new` только на личной, `can_move`); список досок и сводка личной доски | `services/board_service.py`, `views_boards.py`, `urls_boards.py`, `urls.py` | `test_boards_api.py` — 20 |
| S1.6 | Перенос `POST tasks/<id>/move`: соседи места вставки в целевой колонке, смена колонки = смена статуса через `update_task` (право вести задачу, схема `TRANSITIONS` — 400 `task_transition_invalid` с `details.allowed`), только порядок — администратор доски или тот, кто ведёт задачу (403), сосед не из колонки — 409 `board_order_stale`, ранги под `pg_advisory_xact_lock` доски; быстрое добавление (`board` в `POST tasks/`) ставит задачу в конец колонки; перенос в отдел забывает места на досках отделов и ставит задачу в конец колонки нового отдела; `seen` | `board_service.move/place_new/place_on_department/forget_department_ranks/mark_seen`, `views.py` (`_create_task`), `transfer.py`, `task_service.py` | `test_board_move.py` — 15, `test_transfer.py`, `test_claim.py` |
| S1.7 | Журнал: смена статуса пишется в `TaskActivity` (раньше не писалась; нужна ленте карточки §6.4 и истории «кто переложил»); `seen_at` новых исполнителей — сейчас у назначившего себя, пусто у остальных | `task_service.update_task/_sync_primary_assignee/replace_assignees/claim/create_task` | `test_tasks_api.py::test_status_changes_are_logged` (заменил тест, закреплявший старое поведение) |
| S1.8 | Фронт доски: страница, шапка и переключатель досок, холст с перетаскиванием (колонки, куда схема не пустит, гаснут), колонка (свернуть, цвет, скрыть), карточка (метки-полоски/подписи, срок жёлтый/красный/зелёный, значки, аватары, кружок «выполнено», карандаш), быстрое добавление (у рядового — только «Бэклог»/«К выполнению», сервер иначе ответит `task_status_initial`), быстрая правка (название, «Открыть», «Переместить», «Копировать ссылку»), фильтр в адресе, настройки колонок; оптимистичный перенос с откатом и текстом сервера; токены `--board-*` в обеих темах; «просмотрено» — при открытии `/tasks/:id`; переводы `tasks.board.*` в ru/en | `features/tasks/board/**`, `lib/tasks/transitions.ts`, `index.css`, `tailwind.config.ts`, `routeDefinitions.ts`, `lazyPages.ts`, `TaskDetailRouter.tsx`, `public/locales/*` | vitest `features/tasks/board` — 30, `uxContract`, `translationKeys` |
| S1.9 | Сторож копии схемы переходов: `lib/tasks/transitions.ts` = `TRANSITIONS` модели | `tasks/tests/test_transitions_mirror.py` | зелёный |
| S1.10 | Хвосты слияния в зоне задач: `HRTaskDetail` показывал тост «Перенести» мимо `reportApiError` (`reportTaskError` принимает настройки тоста), `TransferDialog` не объяснял пустой список отделов-получателей | `features/tasks/errors.ts`, `pages/hr/HRTaskDetail.tsx`, `features/tasks/board/TransferDialog.tsx` | `uxContract.test.ts` зелёный |
| S1.11 | Документация | `API.md` (ручки досок, а также перенос и «Взять в работу» этапа 1), `STRUCTURE.md` §4.2, Trello-план, этот файл, `Plans.md` (фаза K2), мастер-план (§1 K-34…K-40, §3.8) | — |

## Отступления от мастер-плана

- **Номера миграций.** `tasks/0030` — настройки досок (K-34, решения 22.10), поэтому чек-листы, выключатель уведомлений и запросы доступа сдвигаются на `0031`–`0033` (мастер-план §3.8 обновлён).
- **Смена статуса теперь в журнале задачи** — раньше `update_task` её не писал, и тест это закреплял; лента карточки (§6.4) и Trello-подобная история без неё пусты.
- **`can.reorder` = администратор доски**, у остальных порядок решает `can_move` карточки (§5.3).
- **Старые завершённые задачи без `completed_at`** (отметка появилась позже них) срезаются по `updated_at`, иначе «Готово» и «Отменена» показывали бы весь архив.
- **Скрытая колонка** приходит со счётчиком, но без карточек — фронт её не рисует, а настройки показывают, сколько скрыто.

## Проверка (22–23.10)

- pytest на Python 3.14, Postgres `:55432`: `test_board_rank`, `test_boards_api`, `test_board_move`, `test_tasks_api`, `test_transfer`, `test_claim` — 133 passed; сторожа и права (`test_gate`, `test_app_isolation`, `test_invariants`, `test_periodic_tasks`, `test_tasks_board_nodes`, `test_tasks_boards_admin_node`) — 1422 passed; соседи (`test_transitions_mirror`, `test_contract_parity`, `test_task_content_api`, `test_department_rules`, `test_permissions`, `test_daily_reports_api`) — 125 passed; `makemigrations --check` чисто.
- Регрессия после слияния `sanzhar` (группами): core 1765, hr 523 + 705, прочее 2024 (+1 из `ci-known-failures.txt`), signoff 588, tasks 938, tender 147 + 260, bpp 496 + 284, companies/users/access 1145 — всё зелёное.
- Фронт: `tsc -p tsconfig.app.json` — 148 (база), в файлах этапа ошибок нет; `eslint -c eslint.ci.config.js` по `features/tasks`, `lib/tasks` — 0 ошибок и предупреждений; vitest доски — 30 passed. Полный vitest: падают 8 старых тестов кадров (`CardT2SectionDialog`, `EmployeeFormDialog` — «нет поля Оклад», «React is not defined»; компоненты не менялись с 03.08), ещё 10 падают по таймауту только под нагрузкой параллельного pytest.

## Хвосты

1. **Живая проверка на стенде** — после `migrate_shared` + `migrate_companies` (миграции слияния и этапа) и дампа базы; по правилам стенда — только после «да» пользователя.
2. Дозагруженные «Показать ещё» карточки пропадают при перезапросе доски (после переноса) — колонка снова показывает первые 200.
3. Список участников в фильтре — из карточек, встреченных на этой доске; отдельной ручки «участники доски» нет.
4. Счётчики чек-листа на карточке — нули до этапа S2 (`tasks/0031`).
5. Сводка личной доски (`boards/personal/summary`) есть, экрана нет — блок «Мои задачи» в профиле, этап S6.
6. Восемь старых падений vitest в кадровых диалогах — не этап S1, разобрать отдельно: пока они есть, шаг vitest в CI на этой ветке красный.

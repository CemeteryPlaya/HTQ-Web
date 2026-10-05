# Этап 1 БЗО — устранение отложенных замечаний финального ревью

**Цель:** закрыть десять мелких замечаний финального ревью этапа 1 исполнителя A (ревью `f3d4adb..b2c17e6`, исправления важных — `a4e5684`) до того, как на ядро этапа 1 начнёт опираться этап 2.

**Исполнитель:** A (Санжар), ветка `new-module-BPP-sanzhar`; после — PR в `new-module-BPP-merge`.

**Правила:** каждое исправление — тест, который падает до правки и проходит после (TDD); один прогон pytest за раз; межаппный доступ только через `apps.<x>.interface`; тексты ошибок — по ТЗ §26 (что случилось, почему, что делать).

---

## Сводка

| № | Замечание | Решение | Где |
|---|---|---|---|
| M1 | Неверный UUID в пути → 500; `int(limit)` и битый JSON вебхука → 500 | UUID разбирается до запроса в БД, неверный — 404; неверный `limit` — 422; битый JSON вебхука — 400 | `htqweb/http.py` (`uuid_or_404`), `notifications/services/center.py`, `notifications/views.py`, `project/views.py`, `refdata/views.py` |
| M2 | Файлы: гонка лимита, `replace` без аудита, ошибка медиа → 500, MIME клиента, «сирота» в S3 | Рекомендательная блокировка на (владелец, тип); аудит `file_replaced`; `UploadValidationError` → `E-FILE-01`; MIME из хранилища; удаление объекта при сбое после записи | `bpp/services/core/files.py`, `bpp/services/core/audit.py`, `media_files/interface.py` |
| M3 | Битое число / `quant=0` у НБРК роняет всю загрузку | Плохая позиция пропускается через `fallback(expected=True)`, остальные грузятся | `refdata/services/nbrk.py` |
| M4 | Пустое имя бота → ссылка `t.me/?start=` | `telegram/link` — 503 `E-NTF-03`, `prefs` отдаёт `telegram_available`; фронт прячет подключение | `notifications/services/telegram.py`, `notifications/views.py`, `pages/NotificationSettings.tsx` |
| M5 | `/\host` проходит проверку внутреннего пути | Отсекать `/\` так же, как `//` | `frontend/src/api/tasks.ts` |
| M6 | `project_link_tasks` привяжет вручную созданный «Проект» с кодом `TP-<n>` | Переиспользуется только «Проект», заведённый самой командой (`created_by` пуст); иначе — конфликт в выводе, доска не связывается | `project/management/commands/project_link_tasks.py` |
| M7 | Мгновенный показ: событие Socket.IO никто не слушает | `NotificationToasts` слушает `notification` с `type: "notification"` и сразу перечитывает ленту | `frontend/src/components/NotificationToasts.tsx` |
| M8 | Журнал аудита не защищён от `TRUNCATE` | **Кодом не закрывается** — см. ниже | ранбук выкатки |
| M9 | CLAUDE.md местами перечисляет тенантные аппки литералом без `bpp`/`project` | Переписать перечни на «`settings.TENANT_APPS`» | `CLAUDE.md` |
| M10 | `platform-admin` наследует денежные операции модуля | **Вопрос Алгазы** (Q-E28), кодом не закрывается | `docs/plans/2026-09-25-bpp-open-questions.md` |

## Решения по пунктам без правки кода

**M8.** Триггер `BEFORE TRUNCATE` на `bpp_auditlog` ломает инфраструктуру тестов: очистка схем компаний в `conftest.py` (`_truncate_schema`) и `flush` в транзакционных тестах Django идут через `TRUNCATE`. Обход через сессионный флаг пришлось бы ставить в каждом месте очистки, включая код Django. `TRUNCATE` — привилегия владельца таблицы, а не операция приложения: защита на уровне БД — роль приложения без права `TRUNCATE` на `bpp_auditlog`. Это пункт ранбука выкатки модуля (этап 8), не код этапа 1. Цена, если неверно: журнал можно очистить целиком под учёткой владельца схемы.

**M10.** Алгазы утвердил матрицу восьми ролей `bpp-*`; `platform-admin` в ней нет. Роль заведена для администрирования платформы и через корень `bpp` получает всё, включая решение ФД по счёту и отметку оплаты. Разделение обязанностей по деньгам — финансовое решение: вопрос [Q-E28](2026-09-25-bpp-open-questions.md#q-e28) в `docs/plans/2026-09-25-bpp-open-questions.md` («запретить `platform-admin` денежные операции модуля явными строками?»). До ответа — без изменений.

## Порядок и тесты

1. **M1.** `htqweb/http.py::uuid_or_404(value) -> uuid.UUID`. Тесты: `notifications/tests/test_api.py::test_malformed_id_is_404`, `…::test_bad_limit_is_422`, `test_telegram.py::test_webhook_with_broken_json_is_400`; `tasks/tests/test_notifications_api.py::test_malformed_id_is_404`; `project/tests/test_api.py::test_malformed_project_id_is_404`; `refdata/tests/test_api.py::test_malformed_id_is_404`.
2. **M2.** Тесты в `bpp/tests/test_files.py`: `test_parallel_attach_respects_the_limit` (транзакционный, 5 потоков на тип с пределом 1 → ровно один файл), `test_replace_is_audited`, `test_media_rejection_is_a_domain_error`, `test_stored_mime_wins`, `test_stored_object_is_removed_when_the_row_fails`. Экспорт `UploadValidationError` через `media_files.interface` (соседу нельзя импортировать `services`).
3. **M3.** `refdata/tests/test_nbrk.py::test_bad_items_are_skipped`.
4. **M4.** `notifications/tests/test_telegram.py::test_link_without_bot_is_503`, `test_api.py::test_prefs_report_telegram_availability`; `NotificationSettings.test.tsx` — «без бота нет кнопки подключения».
5. **M5.** `api/__tests__/notificationTargetUrl.test.ts` — `/\evil.example`.
6. **M6.** `project/tests/test_link_tasks.py::test_manual_project_with_the_same_code_is_not_hijacked`.
7. **M7.** `components/__tests__/NotificationToasts.test.tsx` — «событие сокета сразу перечитывает ленту».
8. **M9, M10, ранбук M8** — документы.
9. Проверка: весь бэкенд (без `ci-known-failures.txt`), весь vitest, `tsc` не больше 148 ошибок, eslint изменённых файлов без новых ошибок.

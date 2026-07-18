# Админка инфраструктуры: что сделано и что улучшить

Дата: 2026-05-07

## Кратко

Добавлена отдельная зона администрирования инфраструктуры для супер-админов. Через нее можно быстро открыть MongoDB/AdminJS, MinIO Console и посмотреть параметры подключений к PostgreSQL, MongoDB, Redis и MinIO.

Пароли и секретные URI не показываются сразу. Для просмотра секретов администратор должен повторно ввести пароль своей текущей учетной записи.

## Что сделано

### Frontend

- Добавлена страница `frontend/src/pages/AdminInfrastructure.tsx`.
- В профильный sidebar добавлен пункт администрирования инфраструктуры.
- Добавлен маршрут `/admin/infrastructure`.
- Страница показывает управляемые ресурсы:
  - PostgreSQL / PgBouncer
  - MongoDB
  - Redis
  - MinIO / S3
- Для каждого ресурса показываются endpoint, database/bucket, логин и другие поля подключения.
- Секреты по умолчанию скрыты как `********`.
- Добавлена кнопка `Показать пароли`, которая открывает диалог повторной проверки пароля.
- После успешной повторной проверки секреты автоматически скрываются через 10 минут.
- Для полей добавлены кнопки копирования.
- Ссылки на MongoDB/AdminJS и MinIO Console доступны прямо из карточек ресурсов.

### Admin API

- Добавлен backend endpoint в `services/admin/app/api/v1/infrastructure.py`.
- `GET /api/admin/v1/infrastructure/` возвращает список ресурсов с замаскированными секретами.
- `POST /api/admin/v1/infrastructure/credentials/reveal` повторно проверяет пароль администратора через `user-service` и только после этого возвращает секретные значения.
- Доступ разрешен только JWT-пользователям с admin/staff/superuser правами.
- Для ответов с секретами выставлены `Cache-Control: no-store` и `Pragma: no-cache`.
- Добавлены smoke-тесты для проверки доступа, маскирования и повторной авторизации.

### MongoDB/AdminJS

- AdminJS перенесен на root path `/mongo-admin`.
- Добавлен frontend/nginx proxy для `/mongo-admin`.
- Логин AdminJS теперь проверяет учетку через `user-service`, поэтому `qa_superadmin@htq.test` может входить тем же паролем, что и в основное приложение.
- Оставлен fallback на `ADMIN_EMAIL` / `ADMIN_PASSWORD` для аварийного dev-входа.
- Health endpoint AdminJS доступен по `/mongo-admin/api/health`.
- Исправлен Docker healthcheck AdminJS, чтобы контейнер не оставался ложным `unhealthy`.

### MinIO

- В dev-окружении MinIO root credentials синхронизированы с `qa_superadmin@htq.test`.
- Обновлены переменные в `.env.example`, `docker-compose.yml`, `services/admin/.env.example` и `services/media/.env.example`.
- `media-service`, worker и scheduler получают S3 credentials из тех же dev-переменных.
- MinIO Console доступна на `http://localhost:9001`.

### Docker/Admin service

- Исправлен конфликт импортов в `admin-service`: сервис случайно мог подхватывать чужой `app.main` из другого сервиса.
- Добавлен `services/admin/app/__init__.py`.
- Обновлен `PYTHONPATH` для `admin-service` в Dockerfile и docker-compose.

## Как пользоваться

1. Войти в приложение как супер-админ, например `qa_superadmin@htq.test`.
2. Открыть профиль и перейти в раздел администрирования инфраструктуры.
3. На странице `/admin/infrastructure` посмотреть endpoints и логины.
4. Для просмотра паролей нажать `Показать пароли` и повторно ввести пароль текущей учетной записи.
5. Для MongoDB открыть `Mongo Admin`.
6. Для MinIO открыть `MinIO Console`.

Пароль тестового супер-админа хранится в `docs/test_accounts.md`. В этом документе он намеренно не дублируется.

## Проверено

- `qa_superadmin@htq.test` получает JWT через `user-service`.
- `/api/admin/v1/infrastructure/` через frontend proxy возвращает 4 ресурса.
- MongoDB и MinIO присутствуют в списке ресурсов.
- В обычном ответе секретные поля замаскированы.
- После повторного ввода пароля секреты раскрываются.
- Вход в AdminJS через `http://localhost:3000/mongo-admin/` проходит успешно.
- Вход в MinIO Console через `http://localhost:9001` проходит успешно.
- Контейнеры `admin-service`, `adminjs-panel`, `minio`, `user-service` находятся в состоянии `healthy`.
- Прошли проверки:
  - `npm run build`
  - `node --check services/adminjs/src/index.js`
  - `python -m compileall -q services/admin/app`
  - `docker compose config --quiet`
  - `git diff --check`

## Что можно улучшить

### Безопасность секретов

- Не хранить реальные dev-пароли в `.env.example`; заменить их на явно фейковые placeholders.
- Вынести секреты в Vault, Docker secrets, SOPS или другой secret manager.
- Добавить отдельный audit log события `infrastructure_credentials_revealed`: кто, когда и с какого IP смотрел секреты.
- Ограничить раскрытие секретов короткоживущей server-side сессией, а не только frontend timeout на 10 минут.
- Добавить rate limit на endpoint повторной авторизации.
- Добавить 2FA/step-up authentication для просмотра секретов в production.
- Не показывать полный DSN целиком, если администратору достаточно отдельных host/user/database полей.

### MinIO

- Для production не использовать root пользователя как повседневный access key.
- Создать отдельные MinIO service accounts для media-service, backup jobs и ручного администрирования.
- Настроить MinIO policies с минимальными правами на конкретный bucket.
- Рассмотреть SSO/OIDC для MinIO Console, чтобы не синхронизировать пароль вручную.
- Добавить автоматическую проверку bucket existence и policy при старте media-service.

### MongoDB/AdminJS

- Добавить ролевые ограничения внутри AdminJS по типам ресурсов и действиям.
- Скрыть или сделать read-only опасные коллекции/таблицы.
- Добавить audit trail для действий в AdminJS.
- Убрать fallback `ADMIN_EMAIL` / `ADMIN_PASSWORD` в production или разрешать его только при явном `NODE_ENV=development`.
- Добавить e2e-тест логина AdminJS через frontend proxy.

### Admin Infrastructure UI

- Добавить фильтр/поиск по ресурсам.
- Добавить статус реального подключения, а не только `configured`.
- Показывать last checked time для каждого ресурса.
- Добавить быстрые действия: открыть dashboard, проверить health, скопировать безопасный connection template.
- Добавить отдельные предупреждения для production-секретов и root-credentials.
- Сделать granular RBAC: например, staff admin может видеть endpoints, но не секреты.

### Backend и тесты

- Покрыть `/api/admin/v1/infrastructure/credentials/reveal` интеграционным тестом через настоящий `user-service` в docker-compose test profile.
- Добавить Playwright сценарий: вход супер-админа, открытие страницы инфраструктуры, раскрытие секретов, переход в Mongo/AdminJS и MinIO.
- Добавить проверку, что не-admin пользователь получает `403`.
- Добавить structured audit events в общий лог/observability pipeline.
- Сделать health endpoint для каждого ресурса: PostgreSQL ping, Mongo ping, Redis ping, MinIO live/ready.

## Важные замечания

- Текущая синхронизация MinIO root credentials с QA superadmin удобна для локальной разработки, но это не production-паттерн.
- Просмотр паролей в UI нужен только для dev/ops-сценариев. В production лучше выдавать временные scoped credentials или показывать инструкции подключения без раскрытия master secret.
- Если MinIO volume уже существовал со старыми root credentials, потребуется пересоздать volume или обновить пользователя вручную. В текущем локальном запуске MinIO был пересоздан и принял новые credentials.

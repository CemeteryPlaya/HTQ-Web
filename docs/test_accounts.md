# Тестовые аккаунты HTQWeb QA

Эти аккаунты были сгенерированы автоматически скриптом `scripts/generate_test_users.py`. Все они присутствуют в базе данных PostgreSQL (схема `public` и `auth`) и имеют сгенерированные документы в MongoDB.

## Учетные данные

> **Формат пароля**: у всех пользователей пароль соответствует их роли, например `SuperAdmin!2026`, `JuniorDev!2026`.

| # | Email | Пароль | Роль / Права | Статус / Особенности |
|---|---|---|---|---|
| 1 | `qa_superadmin@htq.test` | `SuperAdmin!2026` | **superuser** | Генеральный директор |
| 2 | `qa_superadmin2@htq.test` | `SuperAdmin2!2026` | **superuser** | Исполнительный директор |
| 3 | `qa_staff_admin@htq.test` | `StaffAdmin!2026` | **staff** (admin) | Системный администратор |
| 4 | `qa_staff_hr@htq.test` | `StaffHR!2026` | **staff** (hr) | HR Директор |
| 5 | `qa_senior_hr@htq.test` | `SeniorHR!2026` | **staff** (hr) | Старший HR-менеджер |
| 6 | `qa_junior_hr@htq.test` | `JuniorHR!2026` | **employee** | Младший HR-специалист |
| 7 | `qa_recruiter@htq.test` | `Recruiter!2026` | **employee** | Рекрутер |
| 8 | `qa_senior_dev@htq.test` | `SeniorDev!2026` | **employee** | Старший разработчик |
| 9 | `qa_junior_dev@htq.test` | `JuniorDev!2026` | **employee** | Младший разработчик |
| 10 | `qa_manager@htq.test` | `Manager!2026` | **employee** | Менеджер проектов |
| 11 | `qa_accountant@htq.test` | `Accountant!2026` | **employee** | Главный бухгалтер |
| 12 | `qa_suspended@htq.test` | `Suspended!2026` | employee | **[suspended]** (заблокирован) |
| 13 | `qa_pending@htq.test` | `Pending!2026` | employee | **[pending]** (ожидает подтверждения) |
| 14 | `qa_rejected@htq.test` | `Rejected!2026` | employee | **[rejected]** (отклонён) |
| 15 | `qa_must_change_pw@htq.test` | `MustChange!2026` | employee | **[must_change_pw]** (требует смены пароля) |

## Что было сгенерировано:
- **15 пользователей** (`auth.users`)
- **13 сотрудников** (`public.hr_employees`) — для всех, кроме rejected/pending
- **33 MongoDB документа** (`htqweb_docs.hr_documents`) — трудовые договоры, приказы и оценки (performance reviews)
- **15 должностей** (`public.hr_positions`)
- **5 отделов** (`public.hr_departments`)

## Как использовать для тестирования (QA):
1. **Проверка авторизации**: попробуйте войти под `qa_suspended@htq.test` или `qa_pending@htq.test`. Ожидается ошибка `401 Unauthorized`.
2. **Проверка смены пароля**: войдите под `qa_must_change_pw@htq.test`. Система должна потребовать сменить пароль перед доступом к остальным ресурсам.
3. **Вертикальная эскалация (RBAC)**: войдите под `qa_junior_dev@htq.test` (обычный сотрудник) и попробуйте сделать запрос к `GET /api/users/v1/admin/users/` или создать MongoDB документ. Ожидается `403 Forbidden`.
4. **Доступ к AdminJS**: 
   - Панель управления MongoDB/AdminJS доступна по адресу http://localhost:3000/mongo-admin/ через frontend proxy или http://localhost:3300/mongo-admin/ напрямую.
   - Авторизация проходит через user-service: используйте любой активный `superuser` / `staff`, например `qa_superadmin@htq.test`.
   - MinIO Console доступна по адресу http://localhost:9001. В dev-окружении root credentials синхронизированы с `qa_superadmin@htq.test`.
   - Там вы можете визуально проверить созданные PostgreSQL записи, MongoDB документы и S3/MinIO storage.

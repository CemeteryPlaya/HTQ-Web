# Техническое задание: HR Service (Микросервис)

> **Контекст:** Enterprise-платформа Hi-Tech Group (HTQWeb). Миграция из Django-монолита в микросервисы через паттерн Strangler Fig.
> **Статус:** 🟡 Planned (Phase 1b согласно API.md)
> **Приоритет:** Высокий
> **Дата:** 10.04.2026

---

## 📋 1. Обзор задачи

### 1.1. Цель
Выделить домен **HR management** из legacy Django monolith в отдельный микросервис **HR Service** с сохранением обратной совместимости и нулевым downtime.

### 1.2. Бизнес-домен
HR Service управляет следующими сущностями:
- **Сотрудники** (Employees) — профиль, контакты, документы, статус
- **Отделы** (Departments) — иерархическая структура (ltree)
- **Должности** (Positions) — грейды, роли, требования
- **Вакансии** (Vacancies) — открытые позиции, статусы
- **Кандидаты и отклики** (Applications) — воронка найма
- **Учет времени** (Time Tracking) — рабочие часы, перерывы, отчеты
- **Документы** (Documents) — приказы, договоры, справки
- **История изменений** (History/Audit) — кто, что, когда изменил
- **Доступы/Аккаунты** (Accounts) — привязка к User Service
- **Профили** (Profiles) — расширенные данные сотрудника

### 1.3. Текущее состояние
- Все HR-эндпоинты сейчас обрабатываются legacy Django (`/api/hr/`)
- Модели проанализированы, схема БД известна
- Требуется создание сервиса с нуля и постепенная миграция трафика

---

## 🏗 2. Архитектурные требования

### 2.1. Технологический стек
| Компонент | Технология | Версия | Обоснование |
|-----------|------------|--------|-------------|
| **Фреймворк** | FastAPI | ≥0.115 | Async/await, автодокументация, Pydantic |
| **ORM** | SQLAlchemy | ≥2.0 | Async поддержка, zser style, миграции |
| **Миграции** | Alembic | ≥1.14 | Стандарт де-факто для SQLAlchemy |
| **БД** | PostgreSQL | ≥15 | Поддержка ltree, JSONB, полнотекстовый поиск |
| **Connection Pool** | PgBouncer | ≥1.21 | Уже используется в проекте (порт 55432) |
| **Cache** | Redis | ≥7 | Кэширование справочников, сессий |
| **Auth** | PyJWT | ≥2.10 | Stateless JWT валидация (как User Service) |
| **Логирование** | structlog | ≥24.4 | Структурированные JSON логи |
| **Тесты** | pytest + httpx | — | Unit + интеграционные тесты |
| **Контейнеризация** | Docker | — | Изоляция, деплой |

### 2.2. Структура проекта
```
services/hr/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app factory
│   ├── config.py                  # Settings (pydantic-settings)
│   ├── dependencies.py            # DI providers (JWT, DB, Redis)
│   ├── middleware/
│   │   ├── request_id.py          # X-Request-ID propagation
│   │   └── logging.py             # Structured logging middleware
│   ├── models/                    # SQLAlchemy models (DB layer)
│   │   ├── base.py                # Base class (id, timestamps)
│   │   ├── employee.py            # Сотрудники
│   │   ├── department.py          # Отделы (ltree)
│   │   ├── position.py            # Должности
│   │   ├── vacancy.py             # Вакансии
│   │   ├── application.py         # Отклики кандидатов
│   │   ├── time_tracking.py       # Учет времени
│   │   ├── document.py            # Документы
│   │   └── audit_log.py           # История изменений
│   ├── schemas/                   # Pydantic schemas (API contract)
│   │   ├── employee.py
│   │   ├── department.py
│   │   ├── position.py
│   │   ├── vacancy.py
│   │   ├── application.py
│   │   ├── time_tracking.py
│   │   ├── document.py
│   │   └── common.py              # Pagination, Error responses
│   ├── api/                       # Router layers (HTTP layer)
│   │   ├── v1/
│   │   │   ├── employees.py
│   │   │   ├── departments.py
│   │   │   ├── positions.py
│   │   │   ├── vacancies.py
│   │   │   ├── applications.py
│   │   │   ├── time.py
│   │   │   ├── documents.py
│   │   │   └── audit.py
│   │   └── health.py              # Health checks
│   ├── services/                  # Business logic layer
│   │   ├── employee_service.py
│   │   ├── department_service.py
│   │   ├── recruitment_service.py
│   │   ├── time_service.py
│   │   └── audit_service.py
│   ├── repositories/              # Data access layer
│   │   ├── employee_repo.py
│   │   └── base_repo.py
│   └── utils/
│       ├── jwt.py                 # JWT validation helpers
│       └── ltree.py               # ltree query helpers
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/                  # Миграции БД
├── tests/
│   ├── conftest.py                # Fixtures (db, client, auth)
│   ├── test_employees.py
│   ├── test_departments.py
│   ├── test_vacancies.py
│   └── test_health.py
├── Dockerfile
├── docker-compose.override.yml    # Dev overrides
├── requirements.txt
├── pyproject.toml                 # Metadata, tool configs
├── alembic.ini
└── README.md
```

### 2.3. Layered Architecture (правила)
```
┌─────────────────────────────────────┐
│         API Layer (api/)            │  ← HTTP request/response, validation
├─────────────────────────────────────┤
│      Service Layer (services/)      │  ← Business rules, orchestration
├─────────────────────────────────────┤
│    Repository Layer (repositories/) │  ← Data access, queries
├─────────────────────────────────────┤
│       Model Layer (models/)         │  ← SQLAlchemy models
└─────────────────────────────────────┘
```

**Правила:**
- ✅ API layer → Service layer → Repository layer → Models (строго вниз)
- ❌ Запрещено: Service → API, Repository → Service (циклические зависимости)
- ✅ Service layer — единственное место для бизнес-логики
- ✅ Repository layer — единственное место для SQL-запросов
- ✅ Schemas используются только в API layer (request/response)
- ✅ Models используются только в Repository/Service layer

---

## 🔌 3. Контракт API

### 3.1. Общие правила
| Правило | Описание |
|---------|----------|
| **Base path** | `/api/hr/v1/` |
| **Auth** | JWT Bearer token в `Authorization` header |
| **Request ID** | `X-Request-ID` header (обязательно, UUID v4) |
| **Pagination** | `?page=1&limit=20` → `{items: [], total: 100, page: 1, pages: 5}` |
| **Sorting** | `?sort=created_at&order=desc` |
| **Filtering** | Query params: `?department_id=5&status=active` |
| **Content-Type** | `application/json` |
| **Error format** | `{error: {code: "EMPLOYEE_NOT_FOUND", message: "...", details: {}}}` |
| **Response codes** | 200 (OK), 201 (Created), 400 (Bad Request), 401 (Unauthorized), 403 (Forbidden), 404 (Not Found), 409 (Conflict), 422 (Validation), 500 (Server Error) |

### 3.2. Health Check endpoints (обязательно для всех сервисов)
```
GET /health/
→ 200 {"status":"ok","service":"hr-service","version":"1.0.0"}

GET /health/ready
→ 200 {"status":"ready"} или 503 {"status":"not_ready","reason":"db_unavailable"}
```

### 3.3. Эндпоинты (CRUD + специфичные операции)

#### 👥 Employees (Сотрудники)
```
GET    /api/hr/v1/employees/              # Список сотрудников (paginated)
POST   /api/hr/v1/employees/              # Создать сотрудника
GET    /api/hr/v1/employees/{id}/         # Получить сотрудника
PUT    /api/hr/v1/employees/{id}/         # Обновить сотрудника
DELETE /api/hr/v1/employees/{id}/         # Удалить сотрудника (soft delete)

POST   /api/hr/v1/employees/{id}/transfer # Перевод в другой отдел
GET    /api/hr/v1/employees/{id}/history  # История изменений
GET    /api/hr/v1/employees/{id}/documents# Документы сотрудника
```

#### 🏢 Departments (Отделы)
```
GET    /api/hr/v1/departments/            # Дерево отделов
POST   /api/hr/v1/departments/            # Создать отдел
GET    /api/hr/v1/departments/{id}/       # Получить отдел
PUT    /api/hr/v1/departments/{id}/       # Обновить отдел
DELETE /api/hr/v1/departments/{id}/       # Удалить отдел

GET    /api/hr/v1/departments/tree        # Полное дерево (иерархия)
GET    /api/hr/v1/departments/{id}/children # Дочерние отделы
GET    /api/hr/v1/departments/{id}/employees # Сотрудники отдела
```

#### 💼 Positions (Должности)
```
GET    /api/hr/v1/positions/              # Список должностей
POST   /api/hr/v1/positions/              # Создать должность
GET    /api/hr/v1/positions/{id}/         # Получить должность
PUT    /api/hr/v1/positions/{id}/         # Обновить должность
DELETE /api/hr/v1/positions/{id}/         # Удалить должность
```

#### 📢 Vacancies (Вакансии)
```
GET    /api/hr/v1/vacancies/              # Список вакансий (paginated)
POST   /api/hr/v1/vacancies/              # Создать вакансию
GET    /api/hr/v1/vacancies/{id}/         # Получить вакансию
PUT    /api/hr/v1/vacancies/{id}/         # Обновить вакансию
DELETE /api/hr/v1/vacancies/{id}/         # Закрыть вакансию

GET    /api/hr/v1/vacancies/{id}/applications # Отклики на вакансию
```

#### 📨 Applications (Отклики)
```
GET    /api/hr/v1/applications/           # Список откликов
POST   /api/hr/v1/applications/           # Создать отклик
GET    /api/hr/v1/applications/{id}/      # Получить отклик
PUT    /api/hr/v1/applications/{id}/      # Обновить статус
DELETE /api/hr/v1/applications/{id}/      # Удалить отклик

POST   /api/hr/v1/applications/{id}/status # Сменить статус
```

#### ⏱ Time Tracking (Учет времени)
```
GET    /api/hr/v1/time/entries/           # Записи учета времени
POST   /api/hr/v1/time/entries/           # Создать запись
PUT    /api/hr/v1/time/entries/{id}/      # Обновить запись
DELETE /api/hr/v1/time/entries/{id}/      # Удалить запись

GET    /api/hr/v1/time/reports/daily      # Дневной отчет
GET    /api/hr/v1/time/reports/weekly     # Недельный отчет
GET    /api/hr/v1/time/reports/monthly    # Месячный отчет
```

#### 📄 Documents (Документы)
```
GET    /api/hr/v1/documents/              # Список документов
POST   /api/hr/v1/documents/              # Загрузить документ
GET    /api/hr/v1/documents/{id}/         # Получить документ
DELETE /api/hr/v1/documents/{id}/         # Удалить документ
```

#### 📜 Audit Log (История изменений)
```
GET    /api/hr/v1/audit/?entity_type=employee&entity_id=5
```

### 3.4. Примеры request/response

#### Создание сотрудника
```json
// POST /api/hr/v1/employees/
// Request:
{
  "first_name": "Иван",
  "last_name": "Петров",
  "middle_name": "Сергеевич",
  "email": "ivan.petrov@company.ru",
  "phone": "+79001234567",
  "department_id": 5,
  "position_id": 12,
  "hire_date": "2024-01-15",
  "status": "active"
}

// Response (201 Created):
{
  "id": 42,
  "first_name": "Иван",
  "last_name": "Петров",
  "middle_name": "Сергеевич",
  "email": "ivan.petrov@company.ru",
  "phone": "+79001234567",
  "department_id": 5,
  "department": {"id": 5, "name": "Разработка"},
  "position_id": 12,
  "position": {"id": 12, "title": "Senior Developer"},
  "hire_date": "2024-01-15",
  "status": "active",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

#### Ошибка валидации
```json
// Response (422 Unprocessable Entity):
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Неверные данные запроса",
    "details": [
      {
        "field": "email",
        "message": "Неверный формат email"
      },
      {
        "field": "department_id",
        "message": "Отдел не найден"
      }
    ]
  }
}
```

---

## 🗄 4. Модели данных (SQLAlchemy)

### 4.1. Base Model (абстрактный базовый класс)
```python
class BaseModel(Base):
    __abstract__ = True
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
```

### 4.2. Department (Отделы с ltree)
```python
class Department(BaseModel):
    __tablename__ = "hr_departments"
    
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    path: Mapped[str] = mapped_column(LTREE, unique=True, nullable=False)  # ltree путь
    description: Mapped[str | None] = mapped_column(Text)
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("hr_employees.id"))
    is_active: Mapped[bool] = mapped_column(default=True)
    
    # Relationships
    employees: Mapped[list["Employee"]] = relationship(back_populates="department")
    manager: Mapped["Employee | None"] = relationship(back_populates="managed_department")
```

### 4.3. Employee (Сотрудник)
```python
class Employee(BaseModel):
    __tablename__ = "hr_employees"
    
    user_id: Mapped[int | None] = mapped_column(unique=True)  # Связь с User Service
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    middle_name: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))
    department_id: Mapped[int] = mapped_column(ForeignKey("hr_departments.id"))
    position_id: Mapped[int] = mapped_column(ForeignKey("hr_positions.id"))
    hire_date: Mapped[date] = mapped_column(nullable=False)
    termination_date: Mapped[date | None]
    status: Mapped[str] = mapped_column(String(20), default="active")  # active, inactive, terminated
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    bio: Mapped[str | None] = mapped_column(Text)
    
    # Relationships
    department: Mapped["Department"] = relationship(back_populates="employees")
    position: Mapped["Position"] = relationship()
    time_entries: Mapped[list["TimeEntry"]] = relationship(back_populates="employee")
    documents: Mapped[list["Document"]] = relationship(back_populates="employee")
    managed_department: Mapped["Department | None"] = relationship(back_populates="manager")
```

### 4.4. Position (Должность)
```python
class Position(BaseModel):
    __tablename__ = "hr_positions"
    
    title: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    department_id: Mapped[int] = mapped_column(ForeignKey("hr_departments.id"))
    grade: Mapped[int] = mapped_column(default=1)  # 1-10
    description: Mapped[str | None] = mapped_column(Text)
    requirements: Mapped[str | None] = mapped_column(JSON)  # JSONB
    is_active: Mapped[bool] = mapped_column(default=True)
```

### 4.5. Vacancy (Вакансия)
```python
class Vacancy(BaseModel):
    __tablename__ = "hr_vacancies"
    
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    department_id: Mapped[int] = mapped_column(ForeignKey("hr_departments.id"))
    position_id: Mapped[int] = mapped_column(ForeignKey("hr_positions.id"))
    description: Mapped[str] = mapped_column(Text)
    requirements: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open, closed, on_hold
    opened_at: Mapped[date] = mapped_column(server_default=func.now())
    closed_at: Mapped[date | None]
    assigned_recruiter_id: Mapped[int | None] = mapped_column(ForeignKey("hr_employees.id"))
```

### 4.6. Application (Отклик)
```python
class Application(BaseModel):
    __tablename__ = "hr_applications"
    
    vacancy_id: Mapped[int] = mapped_column(ForeignKey("hr_vacancies.id"))
    candidate_name: Mapped[str] = mapped_column(String(255), nullable=False)
    candidate_email: Mapped[str] = mapped_column(String(255), nullable=False)
    candidate_phone: Mapped[str | None] = mapped_column(String(20))
    resume_url: Mapped[str | None] = mapped_column(String(500))
    cover_letter: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="new")  # new, reviewed, interview, offer, rejected, hired
    applied_at: Mapped[datetime] = mapped_column(server_default=func.now())
    notes: Mapped[str | None] = mapped_column(Text)
```

### 4.7. TimeEntry (Учет времени)
```python
class TimeEntry(BaseModel):
    __tablename__ = "hr_time_entries"
    
    employee_id: Mapped[int] = mapped_column(ForeignKey("hr_employees.id"))
    date: Mapped[date] = mapped_column(nullable=False)
    start_time: Mapped[time] = mapped_column(nullable=False)
    end_time: Mapped[time] = mapped_column(nullable=False)
    break_minutes: Mapped[int] = mapped_column(default=0)
    description: Mapped[str | None] = mapped_column(Text)
    project: Mapped[str | None] = mapped_column(String(255))
    task: Mapped[str | None] = mapped_column(String(255))
    
    __table_args__ = (
        UniqueConstraint("employee_id", "date", "start_time", name="uq_employee_time_entry"),
    )
```

### 4.8. Document (Документ)
```python
class Document(BaseModel):
    __tablename__ = "hr_documents"
    
    employee_id: Mapped[int] = mapped_column(ForeignKey("hr_employees.id"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)  # contract, order, certificate, etc.
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100))
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("hr_employees.id"))
    metadata: Mapped[dict | None] = mapped_column(JSON)
```

### 4.9. AuditLog (История изменений)
```python
class AuditLog(BaseModel):
    __tablename__ = "hr_audit_log"
    
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)  # employee, department, etc.
    entity_id: Mapped[int] = mapped_column(nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # create, update, delete
    old_values: Mapped[dict | None] = mapped_column(JSON)
    new_values: Mapped[dict | None] = mapped_column(JSON)
    changed_by: Mapped[int] = mapped_column(ForeignKey("hr_employees.id"))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    
    __table_args__ = (
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
    )
```

---

## 🔐 5. Аутентификация и авторизация

### 5.1. JWT валидация
- **Метод:** Stateless валидация через `PyJWT`
- **Алгоритм:** HS256 (как User Service)
- **Secret:** Из ENV (`JWT_SECRET_KEY`)
- **Проверки:** `exp`, `iat`, `user_id` в payload

### 5.2. Middleware для JWT
```python
async def validate_jwt(request: Request) -> dict:
    """Извлекает и валидирует JWT токен из Authorization header"""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=["HS256"])
        return payload  # {"user_id": 5, "exp": ..., ...}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
```

### 5.3. RBAC (Role-Based Access Control)
```python
# Разрешения по ролям
ROLE_PERMISSIONS = {
    "hr_admin": ["read", "write"],       # Полный доступ к HR данным
    "hr_manager": ["read", "write", "delete"],  # Удаление включительно
    "employee": ["read_own"],            # Только свои данные
    "recruiter": ["read", "write_vacancies", "write_applications"],
    "admin": ["*"],                      # Полный доступ ко всему
}
```

### 5.4. Зависимости FastAPI
```python
async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """FastAPI dependency для получения текущего пользователя"""
    return await validate_jwt(token)

async def require_role(required_roles: list[str]):
    """Dependency factory для проверки ролей"""
    def role_checker(user: dict = Depends(get_current_user)):
        if user.get("role") not in required_roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return role_checker
```

---

## 🔄 6. Стратегия миграции (Strangler Fig)

### 6.1. Фазы миграции

| Фаза | Действие | Длительность | Критерий успеха |
|------|----------|--------------|-----------------|
| **Phase 0** | Создать сервис, настроить routing | 1 день | Service deploys, health checks pass |
| **Phase 1a** | Dual-write (Django + новый сервис) | 3-5 дней | Данные синхронизированы |
| **Phase 1b** | Canary (10% трафика на новый сервис) | 2-3 дня | Ошибки <1%, latency в норме |
| **Phase 1c** | Увеличить до 50% | 2-3 дня | Стабильная работа |
| **Phase 2** | 100% трафика на новый сервис | 1 день | Legacy Django не получает HR запросы |
| **Phase 3** | Удалить HR код из Django | 1-2 дня | Monolith стал меньше, нет регрессий |

### 6.2. Dual-Write паттерн
```python
# В Django monolith (legacy):
class EmployeeViewSet(viewsets.ModelViewSet):
    def create(self, request, *args, **kwargs):
        # 1. Сохраняем в Django БД
        response = super().create(request, *args, **kwargs)
        
        # 2. Дублируем в новый HR Service
        try:
            requests.post(
                "http://hr-service:8006/api/hr/v1/employees/",
                json=response.data,
                headers={"Authorization": request.META.get("HTTP_AUTHORIZATION")}
            )
        except Exception as e:
            logger.error(f"Dual-write to HR service failed: {e}")
        
        return response
```

### 6.3. Nginx Canary routing
```nginx
# nginx/default.conf
# Canary: 10% трафика на новый HR Service
split_clients $request_uri $hr_backend {
    10%    hr_service;
    *      legacy_django;
}

location /api/hr/ {
    proxy_pass http://$hr_backend;
    proxy_set_header X-Request-ID $request_id;
}
```

---

## 🚨 7. Observability

### 7.1. Health Checks
```python
@router.get("/health/")
async def health_check():
    return {
        "status": "ok",
        "service": "hr-service",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }

@router.get("/health/ready")
async def readiness_check(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {str(e)}")
```

### 7.2. Логирование
```python
# Структурированные JSON логи
import structlog

logger = structlog.get_logger()

# Каждый запрос логируется:
logger.info(
    "employee_created",
    employee_id=emp.id,
    user_id=current_user["user_id"],
    request_id=request.headers.get("X-Request-ID")
)
```

### 7.3. Метрики (опционально)
- Количество запросов/секунду по эндпоинтам
- Latency (p50, p95, p99)
- Ошибки (4xx, 5xx)
- DB connection pool utilization
- Cache hit/miss ratio

---

## 🧪 8. Тестирование

### 8.1. Типы тестов
| Тип | Покрытие | Инструменты |
|-----|----------|-------------|
| **Unit** | Service layer, Utils | pytest |
| **Integration** | API endpoints | pytest + httpx |
| **DB** | Migrations, Queries | pytest + testcontainers |
| **Contract** | API schemas | pytest |

### 8.2. Fixtures
```python
# tests/conftest.py
@pytest.fixture
async def db_session():
    """Создает тестовую БД и очищает после теста"""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async with AsyncSession(async_engine) as session:
        yield session
    
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest.fixture
def client(db_session):
    """FastAPI TestClient с тестовой БД"""
    def override_get_db():
        yield db_session
    
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c

@pytest.fixture
def auth_headers():
    """JWT токен для тестов"""
    token = jwt.encode({"user_id": 1, "role": "hr_admin"}, settings.JWT_SECRET_KEY)
    return {"Authorization": f"Bearer {token}"}
```

### 8.3. Пример теста
```python
async def test_create_employee(client: TestClient, auth_headers: dict):
    response = client.post(
        "/api/hr/v1/employees/",
        json={
            "first_name": "Иван",
            "last_name": "Петров",
            "email": "test@example.com",
            "department_id": 1,
            "position_id": 1,
            "hire_date": "2024-01-15",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["first_name"] == "Иван"
    assert data["email"] == "test@example.com"
    assert "id" in data
```

---

## 🐳 9. Docker & Infrastructure

### 9.1. Dockerfile
```dockerfile
FROM python:3.14-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY . .

# Run
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8006", "--workers", "4"]
```

### 9.2. Docker Compose (добавить в основной docker-compose.yml)
```yaml
hr-service:
  build: ./services/hr
  container_name: hr-service
  ports:
    - "8006:8006"
  environment:
    - DATABASE_URL=postgresql+asyncpg://htquser:password@postgres:5432/hr_db
    - REDIS_URL=redis://redis:6379/1
    - JWT_SECRET_KEY=${JWT_SECRET_KEY}
    - ENVIRONMENT=development
  depends_on:
    postgres:
      condition: service_healthy
    redis:
      condition: service_healthy
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8006/health/"]
    interval: 10s
    timeout: 5s
    retries: 3
  networks:
    - htqweb-network
```

### 9.3. Environment Variables
```bash
# .env
DATABASE_URL=postgresql+asyncpg://htquser:password@postgres:5432/hr_db
REDIS_URL=redis://redis:6379/1
JWT_SECRET_KEY=your-secret-key-change-in-production
ENVIRONMENT=development  # development | staging | production
LOG_LEVEL=INFO
API_PREFIX=/api/hr/v1
```

---

## 📊 10. Nginx Routing (обновить nginx/default.conf)

```nginx
upstream hr_service {
    server hr-service:8006;
}

# HR Service (новый микросервис)
location /api/hr/ {
    # Временно: proxy_pass http://legacy_backend;  # Закомментировать после canary
    proxy_pass http://hr_service;
    
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Request-ID $request_id;
    proxy_set_header X-Forwarded-Proto $scheme;
    
    # Timeouts
    proxy_connect_timeout 60s;
    proxy_send_timeout 60s;
    proxy_read_timeout 60s;
    
    # Rate limiting (опционально)
    limit_req zone=hr_api burst=20 nodelay;
}
```

---

## 📝 11. Критерии приемки (Acceptance Criteria)

### ✅ Обязательные
- [ ] HR Service деплоится через Docker
- [ ] Health check endpoints работают (`/health/`, `/health/ready`)
- [ ] JWT валидация работает корректно
- [ ] Все CRUD эндпоинты реализованы
- [ ] Пагинация, сортировка, фильтрация работают
- [ ] PostgreSQL миграции через Alembic
- [ ] Redis интегрирован для кэширования
- [ ] Structured logging настроен
- [ ] X-Request-ID propagation работает
- [ ] Тесты написаны и проходят (покрытие ≥80%)
- [ ] Nginx routing настроен
- [ ] docker-compose.yml обновлен

### 🌟 Желательные
- [ ] ltree запросы для иерархии отделов
- [ ] Audit log для всех сущностей
- [ ] RBAC (role-based access control)
- [ ] Rate limiting на эндпоинтах
- [ ] API документация (Swagger/Redoc) доступна
- [ ] Ошибки валидации в формате `{error: {code, message, details}}`
- [ ] Soft delete для критичных сущностей
- [ ] Метрики (latency, error rate, throughput)

### 🚀 Опциональные
- [ ] GraphQL endpoint для сложных запросов
- [ ] WebSocket для real-time уведомлений
- [ ] File upload (документы) через S3
- [ ] Background jobs (Celery/RQ) для отчетов
- [ ] Full-text поиск по сотрудникам/вакансиям

---

## 🔗 12. Ссылки и контекст

### Документация проекта
- [API.md](../API.md) — Routing table, service contracts
- [README.md](../README.md) — Общая информация о проекте
- [services/README.md](../services/README.md) — Microservices guide
- [docs/architecture.md](../docs/architecture.md) — Architecture guide

### Связанные сервисы
- **User Service** (порт 8005): JWT auth, профили пользователей
- **Legacy Django** (порт 8000): Остальные домены
- **SFU** (порт 4443): Mediasoup WebRTC
- **Redis** (порт 6379): Cache
- **PostgreSQL** (порт 55432): Via PgBouncer

### External Docs
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy 2.0 Documentation](https://docs.sqlalchemy.org/en/20/)
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [structlog Documentation](https://www.structlog.org/)

---

## 💡 13. Рекомендации для ИИ-агента

### 13.1. Порядок выполнения
1. **Изучить User Service** (`services/user/`) как референс
2. **Создать структуру** через `python services/scaffold.py hr "HR management"`
3. **Настроить config.py** (ENV vars, pydantic-settings)
4. **Реализовать models/** (SQLAlchemy модели из раздела 4)
5. **Написать Alembic миграции**
6. **Реализовать repositories/** (data access layer)
7. **Реализовать services/** (business logic)
8. **Реализовать api/** (HTTP endpoints)
9. **Написать middleware** (JWT validation, logging)
10. **Написать тесты** (unit + integration)
11. **Создать Dockerfile**
12. **Обновить docker-compose.yml**
13. **Обновить nginx/default.conf**
14. **Протестировать локально**
15. **Написать README.md**

### 13.2. Важные замечания
- ✅ Следовать layered architecture (API → Service → Repository → Model)
- ✅ Использовать async/await везде, где возможно
- ✅ Все ошибки возвращать в формате `{error: {code, message, details}}`
- ✅ Логировать все операции с request_id
- ✅ Писать типизированный код (type hints обязательно)
- ✅ Следовать DRY, KISS, SOLID принципам
- ✅ Комментировать нетривиальные участки кода
- ✅ Тестировать edge cases (пустые списки, дубликаты, невалидные данные)

### 13.3. Чего НЕ делать
- ❌ НЕ смешивать business logic с HTTP layer
- ❌ НЕ использовать синхронные вызовы в async коде
- ❌ НЕ игнорировать ошибки (всегда try/except или обработчики)
- ❌ НЕ хардкодить конфигурацию (всегда через pydantic-settings)
- ❌ НЕ пропускать тесты (каждый эндпоинт должен иметь тест)
- ❌ НЕ создавать circular dependencies между модулями
- ❌ НЕ логировать чувствительные данные (пароли, токены)

### 13.4. Паттерны и best practices
```python
# ✅ Правильно: Dependency Injection
async def get_employee_service(
    db: AsyncSession = Depends(get_db),
    cache: Redis = Depends(get_redis),
) -> EmployeeService:
    return EmployeeService(db, cache)

# ✅ Правильно: Service layer
class EmployeeService:
    def __init__(self, db: AsyncSession, cache: Redis):
        self.db = db
        self.cache = cache
    
    async def create_employee(self, data: EmployeeCreate) -> Employee:
        # Business logic here
        employee = Employee(**data.model_dump())
        self.db.add(employee)
        await self.db.commit()
        await self.db.refresh(employee)
        await self.cache.set(f"employee:{employee.id}", employee.model_dump_json())
        return employee

# ✅ Правильно: Error handling
try:
    employee = await service.create_employee(data)
except IntegrityError:
    raise HTTPException(status_code=409, detail="Employee with this email already exists")
except Exception as e:
    logger.error("employee_creation_failed", error=str(e))
    raise HTTPException(status_code=500, detail="Internal server error")
```

---

## 📌 14. Чек-лист перед коммитом

- [ ] Код следует layered architecture
- [ ] Все type hints указаны
- [ ] Тесты написаны и проходят
- [ ] Нет хардкода в конфигурации
- [ ] Логи структурированы (JSON)
- [ ] Ошибки в правильном формате
- [ ] Health checks работают
- [ ] Dockerfile оптимизирован
- [ ] README.md обновлен
- [ ] Нет чувствительных данных в коде
- [ ] Alembic миграции корректны
- [ ] Nginx routing настроен

---

## 🎯 15. Итоговый результат

После выполнения задачи должно быть:
1. ✅ Работающий HR Service на порту 8006
2. ✅ Swagger UI доступен по `/docs`
3. ✅ Health checks работают
4. ✅ Все CRUD эндпоинты реализованы
5. ✅ JWT валидация работает
6. ✅ Docker контейнер запускается
7. ✅ Nginx маршрутизирует запросы
8. ✅ Тесты проходят (покрытие ≥80%)
9. ✅ Документация написана
10. ✅ Готовность к canary деплою

---

> **Примечание:** Это живое техническое задание. При обнаружении несоответствий или новых требований — обновляйте этот документ с указанием даты и автора изменений.

**Версия:** 1.0  
**Дата создания:** 10.04.2026  
**Автор:** AI Assistant  
**Статус:** ✅ Готово к реализации

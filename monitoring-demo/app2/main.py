"""
User Service (app2) — внутренний микросервис.
Предоставляет данные о пользователях.
Экспортирует метрики Prometheus на /metrics.
"""

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter
import os
import random
import asyncio

# ─── Конфигурация ───────────────────────────────────────────────
APP_NAME = os.getenv("APP_NAME", "user-service")

# ─── Инициализация FastAPI ──────────────────────────────────────
app = FastAPI(
    title="User Service",
    description="Внутренний сервис пользователей с мониторингом Prometheus",
    version="1.0.0",
)

# ─── Кастомные бизнес-метрики ───────────────────────────────────
# Best Practice: бизнес-метрики помогают отслеживать не только
# техническое здоровье, но и бизнес-логику.
db_queries_total = Counter(
    "db_queries_total",
    "Количество запросов к базе данных",
    ["app_name", "operation", "table"],
)

# ─── Prometheus Instrumentator ──────────────────────────────────
# Те же 3 строки для интеграции: создание → instrument → expose
instrumentator = Instrumentator(
    should_group_status_codes=False,
    should_ignore_untemplated=True,
    should_respect_env_var=False,
    excluded_handlers=["/health"],
)

instrumentator.instrument(app).expose(app, include_in_schema=False)


# ─── Фейковые данные для демонстрации ───────────────────────────
FAKE_USERS = [
    {"id": 1, "name": "Алексей Петров", "role": "developer"},
    {"id": 2, "name": "Мария Иванова", "role": "designer"},
    {"id": 3, "name": "Дмитрий Козлов", "role": "devops"},
    {"id": 4, "name": "Елена Смирнова", "role": "manager"},
    {"id": 5, "name": "Сергей Волков", "role": "developer"},
]

FAKE_DATA = [
    {"metric": "cpu_usage", "value": 42.5, "unit": "%"},
    {"metric": "memory_usage", "value": 68.2, "unit": "%"},
    {"metric": "disk_io", "value": 120, "unit": "MB/s"},
    {"metric": "active_connections", "value": 847, "unit": "count"},
]


# ─── Эндпоинты ──────────────────────────────────────────────────
@app.get("/health")
async def health_check():
    """Health-check. Исключён из метрик Prometheus."""
    return {"status": "healthy", "service": APP_NAME}


@app.get("/")
async def root():
    """Информация о сервисе."""
    return {
        "service": APP_NAME,
        "version": "1.0.0",
        "endpoints": ["/health", "/metrics", "/users", "/data"],
    }


@app.get("/users")
async def get_users():
    """
    Возвращает список пользователей.
    Имитирует задержку БД для реалистичных метрик.
    """
    # Имитация задержки обращения к БД (10-100ms)
    delay = random.uniform(0.01, 0.1)
    await asyncio.sleep(delay)

    # Записываем бизнес-метрику
    db_queries_total.labels(
        app_name=APP_NAME, operation="SELECT", table="users"
    ).inc()

    return {"users": FAKE_USERS, "total": len(FAKE_USERS)}


@app.get("/data")
async def get_data():
    """
    Возвращает системные данные/метрики.
    Имитирует задержку обработки.
    """
    delay = random.uniform(0.005, 0.05)
    await asyncio.sleep(delay)

    db_queries_total.labels(
        app_name=APP_NAME, operation="SELECT", table="system_metrics"
    ).inc()

    return {"data": FAKE_DATA, "timestamp": "2026-06-09T12:00:00Z"}


@app.get("/users/{user_id}")
async def get_user(user_id: int):
    """
    Возвращает конкретного пользователя по ID.
    Демонстрирует разные HTTP-статусы в метриках (200 vs 404).
    """
    delay = random.uniform(0.005, 0.03)
    await asyncio.sleep(delay)

    db_queries_total.labels(
        app_name=APP_NAME, operation="SELECT", table="users"
    ).inc()

    user = next((u for u in FAKE_USERS if u["id"] == user_id), None)
    if user is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    return user

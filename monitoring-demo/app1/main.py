"""
API Gateway (app1) — точка входа в микросервисную архитектуру.
Проксирует запросы к внутреннему сервису (app2).
Экспортирует метрики Prometheus на /metrics.
"""

from fastapi import FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter, Histogram
import httpx
import os
import time

# ─── Конфигурация ───────────────────────────────────────────────
APP_NAME = os.getenv("APP_NAME", "api-gateway")
INTERNAL_SERVICE_URL = os.getenv("INTERNAL_SERVICE_URL", "http://app2:8000")

# ─── Инициализация FastAPI ──────────────────────────────────────
app = FastAPI(
    title="API Gateway",
    description="Точка входа с мониторингом Prometheus",
    version="1.0.0",
)

# ─── Prometheus: кастомные метрики с тегом app_name ─────────────
# Best Practice: всегда добавляй label app_name, чтобы в Grafana
# можно было фильтровать графики по конкретному микросервису.

# Счётчик проксированных запросов к внутренним сервисам
proxy_requests_total = Counter(
    "gateway_proxy_requests_total",
    "Общее количество проксированных запросов",
    ["app_name", "target_service", "status"],
)

# Гистограмма времени проксирования
proxy_request_duration = Histogram(
    "gateway_proxy_request_duration_seconds",
    "Время проксирования запроса к внутреннему сервису",
    ["app_name", "target_service"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)


# ─── Prometheus Instrumentator ──────────────────────────────────
# Автоматический трекинг: RPS, время ответа, HTTP-коды.
# Все стандартные метрики автоматически получат label handler и method.
#
# Для тегирования по app_name используем instrument_hook,
# который добавит label ко всем стандартным метрикам.
instrumentator = Instrumentator(
    should_group_status_codes=False,       # Не группировать 2xx/4xx/5xx — точные коды
    should_ignore_untemplated=True,        # Игнорировать запросы без роута
    should_respect_env_var=False,          # Всегда включён (не зависит от env var)
    excluded_handlers=["/health"],         # Исключаем health-check из метрик
    env_var_name="ENABLE_METRICS",
)

# instrument() навешивает middleware на все запросы
# expose() создаёт эндпоинт /metrics
instrumentator.instrument(app).expose(app, include_in_schema=False)


# ─── Эндпоинты ──────────────────────────────────────────────────
@app.get("/health")
async def health_check():
    """Health-check для Docker/K8s. Не попадает в метрики."""
    return {"status": "healthy", "service": APP_NAME}


@app.get("/")
async def root():
    """Корневой эндпоинт API Gateway."""
    return {
        "service": APP_NAME,
        "version": "1.0.0",
        "endpoints": ["/health", "/metrics", "/api/users", "/api/data"],
    }


@app.get("/api/users")
async def get_users():
    """
    Проксирует запрос к внутреннему сервису (app2) за списком пользователей.
    Отслеживает время проксирования и статус ответа.
    """
    start_time = time.time()
    target = "user-service"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{INTERNAL_SERVICE_URL}/users")
            response.raise_for_status()

        duration = time.time() - start_time

        # Записываем кастомные метрики
        proxy_requests_total.labels(
            app_name=APP_NAME, target_service=target, status="success"
        ).inc()
        proxy_request_duration.labels(
            app_name=APP_NAME, target_service=target
        ).observe(duration)

        return response.json()

    except httpx.RequestError as exc:
        proxy_requests_total.labels(
            app_name=APP_NAME, target_service=target, status="error"
        ).inc()
        raise HTTPException(
            status_code=502, detail=f"Ошибка соединения с {target}: {exc}"
        )


@app.get("/api/data")
async def get_data():
    """
    Проксирует запрос к внутреннему сервису (app2) за данными.
    """
    start_time = time.time()
    target = "user-service"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{INTERNAL_SERVICE_URL}/data")
            response.raise_for_status()

        duration = time.time() - start_time

        proxy_requests_total.labels(
            app_name=APP_NAME, target_service=target, status="success"
        ).inc()
        proxy_request_duration.labels(
            app_name=APP_NAME, target_service=target
        ).observe(duration)

        return response.json()

    except httpx.RequestError as exc:
        proxy_requests_total.labels(
            app_name=APP_NAME, target_service=target, status="error"
        ).inc()
        raise HTTPException(
            status_code=502, detail=f"Ошибка соединения с {target}: {exc}"
        )

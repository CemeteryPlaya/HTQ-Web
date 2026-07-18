# ─── Dockerfile для FastAPI-микросервиса ────────────────────────
# Multi-stage не нужен: это lightweight Python-приложение.

FROM python:3.12-slim

# Метаданные
LABEL maintainer="devops-team"
LABEL description="FastAPI microservice with Prometheus metrics"

# Не буферизовать вывод Python (видно логи сразу)
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Сначала копируем только requirements (кэширование слоёв Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Затем копируем код приложения
COPY . .

# Порт приложения
EXPOSE 8000

# Запуск через uvicorn
# --host 0.0.0.0 — слушать на всех интерфейсах (обязательно в Docker)
# --workers 1 — для demo достаточно; в проде: 2-4 × CPU cores
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

#!/usr/bin/env bash
# Поднять тестовый стек HTQWeb с ЛОКАЛЬНОЙ БД (http://localhost:3000, Vite HMR).
# Запускать из корня репозитория.
#
# Это обёртка над docker-compose.test-local.yml — обычный режим разработки:
# Postgres в контейнере, миграции применяются, боевая БД не задействована.
#
# Нужен стек против БД из .env — это другой файл (миграции там по умолчанию OFF):
#   docker compose -f docker-compose.test-env.yml up -d --build
# Нужен только Postgres для pytest, без остального стека:
#   docker compose -f docker-compose.test-local.yml up -d db
set -e
cd "$(dirname "$0")"
docker compose -f docker-compose.test-local.yml down
docker compose -f docker-compose.test-local.yml up -d --build "$@"

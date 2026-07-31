#!/usr/bin/env bash
# Start the HTQWeb dev stack (Django backend + Vite frontend on http://localhost:3000).
# Run from the repo root. The dev override is what brings up the browsable Vite server;
# plain `docker compose up` does NOT (it only builds static files for nginx).
set -e
cd "$(dirname "$0")"
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build "$@"

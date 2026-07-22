#!/usr/bin/env bash
# Generate test traffic across the Django backend's endpoints so Prometheus/
# Grafana dashboards have data to show. Safe: GET-only + a few intentional
# 404/401s (they feed the error-rate panels).
#
# Usage:  ./scripts/generate-monitoring-traffic.sh [rounds] [email] [password] [port]
#         rounds — how many passes over the endpoint list (default 20)
#         port   — backend port (default 8000; use 80 to go through nginx)

set -euo pipefail

ROUNDS="${1:-20}"
EMAIL="${2:-ina.sanzhar@gmail.com}"
PASSWORD="${3:-}"
BASE="http://localhost"

if [ -z "$PASSWORD" ]; then
    read -r -s -p "Password for $EMAIL: " PASSWORD; echo
fi

# Единый Django-backend (WSGI) — все домены на одном порту (в dev :8000,
# в проде — через nginx :80). PORT переопределяется 4-м аргументом.
PORT="${4:-8000}"

TOKEN=$(curl -s -X POST "$BASE:$PORT/api/users/v1/token/" \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" \
    | python -c "import sys,json;print(json.load(sys.stdin)['access'])")
AUTH="Authorization: Bearer $TOKEN"

# path                                          auth?
ENDPOINTS=(
    "/api/core/v1/services/                      no"
    "/api/users/v1/profile/                      yes"
    "/api/users/v1/users/                        yes"
    "/api/hr/v1/employees/                       yes"
    "/api/hr/v1/departments/                     yes"
    "/api/hr/v1/positions/                       yes"
    "/api/tasks/v1/tasks/                        yes"
    "/api/tasks/v1/equipment/                    yes"
    "/api/tasks/v1/notifications/                yes"
    "/api/messenger/v1/rooms/                    yes"
    "/api/cms/v1/news/                           no"
    "/api/cms/v1/news/?page=2                    no"
    "/api/requests/v1/templates/                 yes"
    "/api/mail/v1/accounts/                      yes"
    "/api/media/v1/files/                        yes"
    # Deliberate misses — feed the 4xx/error panels:
    "/api/tasks/v1/tasks/999999/                 yes"
    "/api/hr/v1/does-not-exist/                  no"
    "/api/users/v1/profile/                      no"
)

echo "Generating traffic: $ROUNDS rounds x ${#ENDPOINTS[@]} endpoints (backend :$PORT)..."
total=0
for _ in $(seq 1 "$ROUNDS"); do
    for entry in "${ENDPOINTS[@]}"; do
        path=$(echo "$entry" | awk '{print $1}')
        needs_auth=$(echo "$entry" | awk '{print $2}')
        if [ "$needs_auth" = "yes" ]; then
            curl -s -o /dev/null -H "$AUTH" "$BASE:$PORT$path" || true
        else
            curl -s -o /dev/null "$BASE:$PORT$path" || true
        fi
        total=$((total + 1))
    done
done
echo "Done: $total requests sent. Prometheus picks them up within ~15-30s."

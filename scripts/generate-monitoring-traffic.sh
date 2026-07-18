#!/usr/bin/env bash
# Generate test traffic across every HTQWeb service so Prometheus/Grafana
# dashboards have data to show. Safe: GET-only + a few intentional 404/401s
# (they feed the error-rate panels).
#
# Usage:  ./scripts/generate-monitoring-traffic.sh [rounds] [email] [password]
#         rounds — how many passes over the endpoint list (default 20)

set -euo pipefail

ROUNDS="${1:-20}"
EMAIL="${2:-ina.sanzhar@gmail.com}"
PASSWORD="${3:-}"
BASE="http://localhost"

if [ -z "$PASSWORD" ]; then
    read -r -s -p "Password for $EMAIL: " PASSWORD; echo
fi

TOKEN=$(curl -s -X POST "$BASE:8005/api/users/v1/token/" \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" \
    | python -c "import sys,json;print(json.load(sys.stdin)['access'])")
AUTH="Authorization: Bearer $TOKEN"

# port  path                                    auth?
ENDPOINTS=(
    "8005 /api/users/v1/profile/                 yes"
    "8005 /api/users/v1/users/                   yes"
    "8005 /health/                               no"
    "8006 /api/hr/v1/employees/                  yes"
    "8006 /api/hr/v1/departments/                yes"
    "8006 /api/hr/v1/positions/                  yes"
    "8006 /health/                               no"
    "8007 /api/tasks/v1/tasks/                   yes"
    "8007 /api/tasks/v1/equipment/               yes"
    "8007 /api/tasks/v1/reports/resource-gantt?from=2026-07-01&to=2026-07-31 yes"
    "8007 /api/tasks/v1/notifications/           yes"
    "8008 /api/messenger/v1/rooms/               yes"
    "8008 /health/                               no"
    "8009 /health/                               no"
    "8010 /health/                               no"
    "8011 /api/cms/v1/news/                      no"
    "8011 /api/cms/v1/news/?page=2               no"
    "8013 /api/requests/v1/templates/            yes"
    "8013 /health/                               no"
    # Deliberate misses — feed the 4xx/error panels:
    "8007 /api/tasks/v1/tasks/999999/            yes"
    "8006 /api/hr/v1/does-not-exist/             no"
    "8005 /api/users/v1/profile/                 no"
)

echo "Generating traffic: $ROUNDS rounds x ${#ENDPOINTS[@]} endpoints..."
total=0
for _ in $(seq 1 "$ROUNDS"); do
    for entry in "${ENDPOINTS[@]}"; do
        port=$(echo "$entry" | awk '{print $1}')
        path=$(echo "$entry" | awk '{print $2}')
        needs_auth=$(echo "$entry" | awk '{print $3}')
        if [ "$needs_auth" = "yes" ]; then
            curl -s -o /dev/null -H "$AUTH" "$BASE:$port$path" || true
        else
            curl -s -o /dev/null "$BASE:$port$path" || true
        fi
        total=$((total + 1))
    done
done
echo "Done: $total requests sent. Prometheus picks them up within ~15-30s."

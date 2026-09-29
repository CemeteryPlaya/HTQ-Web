#!/usr/bin/env bash
# Проверить конфигурацию наблюдаемости, НЕ поднимая стек.
#
# Ловит ровно те поломки, которые иначе обнаруживаются на проде и молча:
#   1. невалидный prometheus.yml — Prometheus не стартует;
#   2. невалидный compose — стек не поднимается;
#   3. битый JSON дашборда — Grafana молча его пропустит, панели исчезнут;
#   4. ⚠️ ГЛАВНОЕ: провижининг алертинга. Grafana 10.4 ВАЛИДИРУЕТ
#      контакт-пойнты на старте и при пустом токене или сломанном шаблоне
#      падает целиком (exit 1, рестарт-петля) — то есть теряются не только
#      алерты, но и все дашборды. Именно так прод и стоял: переменная
#      GF_TELEGRAM_BOT_TOKEN не передавалась контейнеру, и Grafana не
#      поднималась вовсе, а заметили это только при разборе.
#
# Usage:  ./scripts/check-monitoring-config.sh
# Требует docker. Ничего в репозитории не меняет, портов не занимает.

set -euo pipefail

cd "$(dirname "$0")/.."

# Git Bash на Windows переписывает пути внутри аргументов docker (/tmp/p.yml
# превращается в C:/Users/.../p.yml) и ломает и -v, и аргументы команды.
# На Linux переменная просто игнорируется, поэтому ставим безусловно.
export MSYS_NO_PATHCONV=1

# Хост-путь для -v: docker на Windows понимает C:/..., а не /e/...
# `pwd -W` есть только в Git Bash, поэтому с запасным вариантом.
HOST_PWD="$(pwd -W 2>/dev/null || pwd)"

PROM_IMAGE="prom/prometheus:v2.53.4"
GRAFANA_IMAGE="grafana/grafana-oss:10.4.4"
CONTAINER="htqweb-provisioning-check-$$"

fail() { echo "  ✗ $1" >&2; exit 1; }
ok()   { echo "  ✓ $1"; }

cleanup() { docker rm -f "$CONTAINER" >/dev/null 2>&1 || true; }
trap cleanup EXIT

# ─── 1. prometheus.yml ───────────────────────────────────────────────────────
echo "prometheus.yml"
docker run --rm -v "$HOST_PWD/infra/logging/prometheus/prometheus.yml:/tmp/p.yml:ro" \
    --entrypoint promtool "$PROM_IMAGE" check config /tmp/p.yml >/dev/null \
    || fail "promtool отверг конфиг"
ok "синтаксис принят promtool"

# ─── 2. compose-файлы ────────────────────────────────────────────────────────
# Значения-заглушки: у прод-файла обязательные переменные объявлены через :?,
# и без них compose откажется разбирать файл — это фича, а не помеха.
echo "compose"
for file in docker-compose.yml docker-compose.test-local.yml docker-compose.test-env.yml; do
    GRAFANA_ADMIN_PASSWORD=ci-placeholder \
    GF_TELEGRAM_BOT_TOKEN="000000:CI-PLACEHOLDER" \
    ALERT_EMAIL_TO="ci@example.invalid" \
        docker compose -f "$file" config >/dev/null 2>&1 \
        || fail "$file не разбирается"
    ok "$file"
done

# ─── 3. дашборды — валидный JSON ─────────────────────────────────────────────
# На runner'ах есть python3; на Windows-хосте `python` часто оказывается
# заглушкой Microsoft Store, которая существует, но не запускается. Поэтому
# кандидатов не просто ищем, а ПРОБУЕМ — иначе проверка объявит битым первый
# же валидный дашборд, как и случилось при написании этого скрипта.
PYTHON=""
for candidate in python3 python ./.venv/Scripts/python.exe ./.venv/bin/python; do
    if "$candidate" -c "pass" >/dev/null 2>&1; then PYTHON="$candidate"; break; fi
done
[ -n "$PYTHON" ] || fail "не найден рабочий python для проверки JSON"

echo "дашборды"
count=0
for dashboard in infra/logging/grafana-dashboards/*.json; do
    "$PYTHON" -c "import json,sys; json.load(open(sys.argv[1],encoding='utf-8'))" "$dashboard" \
        || fail "$dashboard — битый JSON"
    count=$((count + 1))
done
ok "$count файлов, JSON валиден"

# ─── 4. провижининг алертинга ────────────────────────────────────────────────
# Поднимаем настоящую Grafana с настоящим провижинингом. Токен и адрес —
# заглушки, но НЕПУСТЫЕ: пустые роняют старт, и проверка бы этого не увидела,
# приняв падение за особенность CI.
echo "провижининг Grafana"
docker run -d --name "$CONTAINER" \
    -e GF_SECURITY_ADMIN_PASSWORD=ci-placeholder \
    -e GF_TELEGRAM_BOT_TOKEN="000000:CI-PLACEHOLDER" \
    -e ALERT_EMAIL_TO="ci@example.invalid" \
    -v "$HOST_PWD/infra/logging/grafana-provisioning:/etc/grafana/provisioning:ro" \
    -v "$HOST_PWD/infra/logging/grafana-dashboards:/etc/grafana/dashboards:ro" \
    "$GRAFANA_IMAGE" >/dev/null

deadline=$((SECONDS + 90))
while [ $SECONDS -lt $deadline ]; do
    status="$(docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || echo missing)"
    [ "$status" = "exited" ] && break
    if docker exec "$CONTAINER" wget -qO- http://localhost:3000/api/health >/dev/null 2>&1; then
        break
    fi
    sleep 3
done

logs="$(docker logs "$CONTAINER" 2>&1 || true)"
if [ "$(docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null)" != "running" ]; then
    echo "$logs" | grep -iE "^Error:|failed to provision|failure to map" >&2 || true
    fail "Grafana не поднялась с этим провижинингом"
fi
if echo "$logs" | grep -qiE "failed to provision|failure to map"; then
    echo "$logs" | grep -iE "failed to provision|failure to map" >&2
    fail "провижининг принят с ошибками"
fi
ok "Grafana стартовала, провижининг без ошибок"

echo
echo "Конфигурация наблюдаемости в порядке."

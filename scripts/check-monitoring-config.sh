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
#   1б. правила алертинга БЗО (и два правила этапа 7) СРАБАТЫВАЮТ: генератор
#      scripts/monitoring/grafana_rules_to_promtool.py переводит их в rule-файл
#      Prometheus, `promtool test rules` гоняет его на подложенных рядах
#      infra/logging/promtool-tests/bpp_rules_test.yml (выше порога — алерт,
#      ниже — тишина). Провижининг (п. 4) этого не ловит: правило с опечаткой
#      в метрике принимается и молчит вечно.
#
# Usage:  ./scripts/check-monitoring-config.sh
# Требует docker и python с PyYAML (для п. 1б; в CI — actions/setup-python +
# pip install pyyaml). Ничего в репозитории не меняет, портов не занимает.

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

RULES_TMP=""

cleanup() {
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    if [ -n "$RULES_TMP" ]; then rm -rf "$RULES_TMP"; fi
}
trap cleanup EXIT

# ─── 1. prometheus.yml ───────────────────────────────────────────────────────
echo "prometheus.yml"
docker run --rm -v "$HOST_PWD/infra/logging/prometheus/prometheus.yml:/tmp/p.yml:ro" \
    --entrypoint promtool "$PROM_IMAGE" check config /tmp/p.yml >/dev/null \
    || fail "promtool отверг конфиг"
ok "синтаксис принят promtool"

# ─── 1б. правила алертинга срабатывают на подложенных данных ─────────────────
# Провижининг (п. 4) проверяет, что правила ПРИНЯТЫ, но не что они СРАБОТАЮТ:
# опечатка в имени метрики или порог не в тех единицах дают правило, которое
# молчит вечно (noDataState: OK). Правила — Grafana, а не Prometheus, поэтому
# генератор переводит выбранные в rule-файл Prometheus (тот же PromQL, тот же
# порог и for), и promtool прогоняет его на подложенных рядах:
# выше порога — алерт, ниже — тишина. Набор: все правила, читающие
# htqweb_bpp_* (новое правило БЗО попадает сюда само и без своих тестов роняет
# шаг), плюс два правила этапа 7. Генератору нужен PyYAML — пробуем
# кандидатов так же, как в п. 3, но с `import yaml`.
echo "правила алертинга (promtool test rules)"
RULES_PYTHON=""
for candidate in python3 python ./.venv/Scripts/python.exe ./.venv/bin/python; do
    if "$candidate" -c "import yaml" >/dev/null 2>&1; then RULES_PYTHON="$candidate"; break; fi
done
[ -n "$RULES_PYTHON" ] || fail "не найден python с PyYAML для генератора правил (pip install pyyaml)"

RULES_TMP="$(mktemp -d)"
# mktemp -d на Linux даёт 0700, а promtool в образе работает от nobody и
# каталог бы не прочитал (Docker Desktop под Windows права bind-mount не
# учитывает — локально это не видно). Права — как у файлов checkout, которые
# монтирует п. 1: каталог 755, файл 644.
chmod 755 "$RULES_TMP"
RULES_TMP_HOST="$(cd "$RULES_TMP" && (pwd -W 2>/dev/null || pwd))"
rules_count="$("$RULES_PYTHON" scripts/monitoring/grafana_rules_to_promtool.py \
    infra/logging/grafana-provisioning/alerting/rules.yml \
    "$RULES_TMP_HOST/grafana_rules.yml" \
    --match htqweb_bpp_ \
    --uid htqweb-auth-lockout-burst \
    --uid htqweb-antivirus-unavailable \
    --tests infra/logging/promtool-tests/bpp_rules_test.yml)" \
    || fail "генератор не перевёл правила Grafana в rule-файл Prometheus (причина выше)"
chmod 644 "$RULES_TMP/grafana_rules.yml"
docker run --rm \
    -v "$RULES_TMP_HOST:/rules:ro" \
    -v "$HOST_PWD/infra/logging/promtool-tests:/tests:ro" \
    --entrypoint promtool "$PROM_IMAGE" test rules /tests/bpp_rules_test.yml >&2 \
    || fail "правила не срабатывают так, как ждут тесты infra/logging/promtool-tests/bpp_rules_test.yml"
ok "правила БЗО срабатывают на подложенных данных ($rules_count)"

# ─── 2. compose-файлы ────────────────────────────────────────────────────────
# Значения-заглушки: у прод-файла обязательные переменные объявлены через :?,
# и без них compose откажется разбирать файл — это фича, а не помеха.
# DB_HOST — тоже :? (адрес БД умолчания не имеет, см. CLAUDE.md «БД»); на
# машине разработчика его даёт .env, в CI .env нет — без заглушки прод-файл
# и test-env «не разбираются», и проверка падает не по делу.
echo "compose"
for file in docker-compose.yml docker-compose.test-local.yml docker-compose.test-env.yml; do
    DB_HOST=ci-placeholder \
    GRAFANA_ADMIN_PASSWORD=ci-placeholder \
    GF_TELEGRAM_BOT_TOKEN="000000:CI-PLACEHOLDER" \
    ALERT_EMAIL_TO="ci@example.invalid" \
        docker compose -f "$file" config >/dev/null 2>&1 \
        || fail "$file не разбирается"
    ok "$file"
    # Второй разбор — с профилем antivirus: сервис clamav (healthcheck, лимит
    # памяти, зеркало баз) без профиля в `config` не попадает, и его поломка
    # осталась бы незамеченной до включения сканера на бою (A7.4).
    DB_HOST=ci-placeholder \
    GRAFANA_ADMIN_PASSWORD=ci-placeholder \
    GF_TELEGRAM_BOT_TOKEN="000000:CI-PLACEHOLDER" \
    ALERT_EMAIL_TO="ci@example.invalid" \
        docker compose -f "$file" --profile antivirus config >/dev/null 2>&1 \
        || fail "$file не разбирается с профилем antivirus"
    ok "$file --profile antivirus"
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

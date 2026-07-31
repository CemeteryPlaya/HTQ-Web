#!/bin/sh
# Точка входа Django-контейнеров.
#   * ждёт БД;
#   * при RUN_MIGRATIONS=1 — migrate (ТОЛЬКО схема БД, см. ниже);
#   * при RUN_BOOTSTRAP=1 (только web) — collectstatic + бакеты + сид админа;
#   * затем exec на команду из compose (gunicorn / uvicorn / celery / beat).
#
# Почему два флага, а не один. Раньше всё висело на RUN_MIGRATIONS=1, поэтому
# выключить накат миграций на боевую БД можно было только вместе со сборкой
# статики, созданием бакетов и сидом админа — а они к схеме БД отношения не
# имеют и нужны при каждом старте. Теперь RUN_MIGRATIONS отвечает РОВНО за
# `manage.py migrate`, а RUN_BOOTSTRAP — за остальную инициализацию процесса-web.
# По умолчанию RUN_BOOTSTRAP наследует RUN_MIGRATIONS, чтобы старые compose-файлы
# и окружения, знающие только про один флаг, вели себя как прежде.
set -e

DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"
RUN_BOOTSTRAP="${RUN_BOOTSTRAP:-${RUN_MIGRATIONS}}"

echo "[entrypoint] ждём Postgres ${DB_HOST}:${DB_PORT} ..."
python - <<PY
import os, socket, sys, time
h, p = os.environ.get("DB_HOST", "db"), int(os.environ.get("DB_PORT", "5432"))
for _ in range(60):
    try:
        socket.create_connection((h, p), 2).close()
        print("[entrypoint] Postgres доступен")
        sys.exit(0)
    except OSError:
        time.sleep(1)
print("[entrypoint] Postgres недоступен за 60с", file=sys.stderr)
sys.exit(1)
PY

if [ "${RUN_MIGRATIONS}" = "1" ]; then
    echo "[entrypoint] migrate ..."
    python manage.py migrate --noinput
else
    echo "[entrypoint] migrate ПРОПУЩЕН (RUN_MIGRATIONS=${RUN_MIGRATIONS:-<не задан>})"
fi

if [ "${RUN_BOOTSTRAP}" = "1" ]; then
    echo "[entrypoint] collectstatic ..."
    python manage.py collectstatic --noinput

    # Бакеты объектного хранилища. Раньше их создавал одноразовый compose-job
    # minio-bootstrap, от которого никто не зависел — при точечном запуске
    # (up -d backend-web) или пересозданном томе бакетов не было, и любая
    # загрузка файла падала 500 NoSuchBucket. Идемпотентно, не валит старт.
    echo "[entrypoint] бакеты хранилища ..."
    python manage.py ensure_buckets || echo "[entrypoint] ensure_buckets не отработал — загрузка файлов может падать"

    echo "[entrypoint] сид админа (идемпотентно) ..."
    python manage.py shell -c "
from apps.users.models import User, UserStatus
u, created = User.objects.get_or_create(
    username='admin',
    defaults=dict(email='admin@htq.local', status=UserStatus.ACTIVE,
                  is_staff=True, is_superuser=True),
)
if created:
    u.set_password('admin12345')
    u.save()
print('[entrypoint] админ готов: admin / admin12345 (created=%s)' % created)
"
fi

exec "$@"

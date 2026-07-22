#!/bin/sh
# Точка входа Django-контейнеров проверочной сборки.
#   * ждёт БД;
#   * при RUN_MIGRATIONS=1 (только web) — migrate + идемпотентный сид админа;
#   * затем exec на команду из compose (runserver / celery worker / beat).
set -e

DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"

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
    echo "[entrypoint] collectstatic ..."
    python manage.py collectstatic --noinput

    echo "[entrypoint] migrate ..."
    python manage.py migrate --noinput

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

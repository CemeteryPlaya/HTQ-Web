# ─── HTQWeb Django backend (проверочная сборка) ─────────────────────────────
# Один образ на все процессы Django: web (runserver), celery worker, beat —
# различаются только `command` в docker-compose.django.yml (тот же приём, что
# у web/worker в исходном стеке).
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=htqweb.settings.dev

WORKDIR /app

# build-essential/libpq на случай, если у какого-то пина нет колеса под 3.14
# (psycopg[binary]/Pillow/bcrypt обычно ставятся как wheels — это подстраховка).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
# По умолчанию — dev-сервер Django: в DEBUG сам отдаёт /static (CSS django-admin)
# и оба типа вью (sync/async). Для проверки этого достаточно.
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000", "--noreload"]

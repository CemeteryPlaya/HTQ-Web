# ─── HTQWeb Django backend (проверочная сборка) ─────────────────────────────
# Один образ на все процессы Django: web (runserver), celery worker, beat —
# различаются только `command` в docker-compose.django.yml (тот же приём, что
# у web/worker в исходном стеке).
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=htqweb.settings.base

WORKDIR /app

# build-essential/libpq на случай, если у какого-то пина нет колеса под 3.14
# (psycopg[binary]/Pillow/bcrypt обычно ставятся как wheels — это подстраховка).
# libpango*/libharfbuzz-subset0/fontconfig — WeasyPrint (bpp: печать
# документов в PDF, этап 2 A, задача 6): с 53.0 ему не нужен GTK/cairo, только
# Pango (тянет HarfBuzz) и fontconfig; harfbuzz-subset — встраивание в PDF
# только использованных глифов (список пакетов — из инструкции WeasyPrint для
# Debian). fonts-dejavu-core — шрифт кириллицы (шаблон
# apps/bpp/templates/bpp/print/base.html): без него текст ушёл бы
# пустыми прямоугольниками без единой ошибки.
# Hash Sum mismatch: перехватывающий прокси (Falcongaze) ломает скачивание.
# Одинаковый размер при разном SHA — признак порчи HTTP-pipeline, поэтому
# Pipeline-Depth=0 (один файл на соединение). No-Cache гонит прокси
# перепроверять вместо отдачи протухшего кэша, Retries переживает рассинхрон
# зеркала, чистка списков до update убирает уже подсунутый старый индекс.
RUN rm -rf /var/lib/apt/lists/* \
    && apt-get -o Acquire::http::Pipeline-Depth=0 \
               -o Acquire::http::No-Cache=true \
               -o Acquire::https::No-Cache=true \
               -o Acquire::Retries=3 \
               update \
    && apt-get -o Acquire::http::Pipeline-Depth=0 \
               -o Acquire::http::No-Cache=true \
               -o Acquire::https::No-Cache=true \
               -o Acquire::Retries=3 \
               install -y --no-install-recommends \
        build-essential libpq5 \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fontconfig fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

ARG CORPORATE_CA_BASE64=""
RUN if [ -n "$CORPORATE_CA_BASE64" ]; then \
      printf '%s' "$CORPORATE_CA_BASE64" | base64 -d > /usr/local/share/ca-certificates/corporate-ca.crt \
      && update-ca-certificates; \
    fi

COPY requirements.txt ./
RUN if [ -f /usr/local/share/ca-certificates/corporate-ca.crt ]; then \
      PIP_CERT=/etc/ssl/certs/ca-certificates.crt pip install --upgrade pip \
      && PIP_CERT=/etc/ssl/certs/ca-certificates.crt pip install -r requirements.txt; \
    else \
      pip install --upgrade pip && pip install -r requirements.txt; \
    fi

COPY . .
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
# Настройки по умолчанию — боевые (base, DEBUG=False): образ, запущенный мимо
# compose, не должен отдавать наружу DEBUG-трейсбеки. Все три compose-файла
# задают DJANGO_SETTINGS_MODULE явно; dev-стеки ставят htqweb.settings.dev.
# Статику при DEBUG=False отдаёт WhiteNoise (collectstatic — в entrypoint).
# CMD — dev-сервер Django (оба типа вью, sync/async); в compose он перекрыт.
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000", "--noreload"]

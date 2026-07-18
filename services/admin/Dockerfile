FROM python:3.14-slim

WORKDIR /app

# Смонтированные сервисы доступны через /services/<svc>/app.
# htqweb_auth копируется в /app/libs/ и добавляется в PYTHONPATH.
ENV PYTHONPATH=/app:/services:/app/libs

COPY services/admin/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/admin/app /app/app
COPY libs /app/libs

EXPOSE 8012
HEALTHCHECK --interval=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8012/health/').read()" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8012"]

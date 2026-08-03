"""Идемпотентное создание S3/MinIO-бакетов, которыми пользуется монолит.

Зачем это здесь, а не только в compose. В эпоху микросервисов бакеты
раскатывал одноразовый job ``minio-bootstrap`` (тестовые compose-файлы): от
него никто не зависел через ``depends_on``, поэтому точечный запуск
(``up -d backend-web``, ``--no-deps``) или пересозданный том ``minio_data``
оставляли хранилище пустым — и ЛЮБАЯ загрузка файла падала 500
``NoSuchBucket`` (вложения мессенджера, файлы отделов hr, вложения почты,
обложки новостей cms, аватары — всё это сегодня идёт в те же два бакета).
Монолит владеет своим хранилищем сам: команда зовётся из
``docker-entrypoint.sh`` рядом с ``migrate`` (гейт ``RUN_MIGRATIONS=1``,
только backend-web), так что бакеты появляются при любом способе поднять
стек.

Бакетов ровно ДВА — по числу реальных потребителей ``htqweb.storage.
get_storage()``:

* ``settings.S3_BUCKET`` (``htqweb-cms``) — снапшоты новостей
  (``apps.cms.services.news_snapshot``) и архив истории чатов
  (``apps.messenger.services.history_archive_service``);
* ``settings.MEDIA_S3_BUCKET`` (``htqweb-media``) — ВСЕ бинарные файлы
  платформы, потому что после схлопывания в монолит каждая аппка кладёт
  байты через ``apps.media_files.interface.store_file()``, а не в свой
  собственный бакет.

Старые ``htqweb-messenger``/``htqweb-conferences``/``htqweb-mail-attachments``
(по бакету на микросервис) в коде не упоминаются ни разу — они умерли
вместе с сервисами.

Никакого отношения к миграциям БД команда не имеет: только ``head_bucket``/
``create_bucket`` в объектном хранилище.
"""
from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand


def buckets_in_use() -> list[str]:
    """Уникальные имена бакетов, реально читаемые из настроек (порядок
    сохранён, дубли схлопнуты — прод может указать одно имя в обе настройки)."""
    names: list[str] = []
    for name in (settings.S3_BUCKET, settings.MEDIA_S3_BUCKET):
        if name and name not in names:
            names.append(name)
    return names


class Command(BaseCommand):
    help = "Создать (идемпотентно) S3/MinIO-бакеты, которыми пользуется backend."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Только показать, каких бакетов не хватает, ничего не создавая.",
        )

    def handle(self, *args, **options):
        if settings.STORAGE_BACKEND != "s3":
            # LocalStorage сам создаёт каталог в конструкторе — создавать нечего.
            self.stdout.write(
                f"STORAGE_BACKEND={settings.STORAGE_BACKEND!r} — бакеты не нужны, пропуск."
            )
            return

        import boto3
        from botocore.exceptions import ClientError

        from htqweb.storage.s3 import S3Storage

        # Переиспользуем сборку клиента из S3Storage, чтобы endpoint/креды/
        # path-style-адресация не разъехались с рабочим путём загрузки.
        probe = S3Storage(
            bucket="",
            endpoint=settings.S3_ENDPOINT,
            access_key=settings.S3_ACCESS_KEY,
            secret_key=settings.S3_SECRET_KEY,
            region=settings.S3_REGION,
            use_path_style=settings.S3_USE_PATH_STYLE,
        )
        s3 = boto3.client("s3", **probe._client_kwargs())

        dry_run = options["dry_run"]
        for bucket in buckets_in_use():
            try:
                s3.head_bucket(Bucket=bucket)
            except ClientError:
                # 404 (нет бакета) и 403 (нет прав на head) выглядят одинаково
                # у части S3-совместимых бэкендов — пробуем создать и разбираем
                # исход ниже, вместо разбора кода ошибки head_bucket.
                if dry_run:
                    self.stdout.write(self.style.WARNING(f"нет бакета: {bucket}"))
                    continue
                try:
                    s3.create_bucket(Bucket=bucket)
                except ClientError as exc:
                    code = exc.response.get("Error", {}).get("Code", "")
                    if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                        self.stdout.write(f"бакет уже есть: {bucket}")
                        continue
                    # Прод на настоящем AWS может запрещать CreateBucket роли
                    # приложения — это не повод валить старт контейнера, бакет
                    # там заводят инфраструктурой. Сообщаем и идём дальше.
                    self.stderr.write(self.style.WARNING(
                        f"не удалось создать бакет {bucket}: {code or exc}"
                    ))
                    continue
                self.stdout.write(self.style.SUCCESS(f"создан бакет: {bucket}"))
            else:
                self.stdout.write(f"бакет уже есть: {bucket}")

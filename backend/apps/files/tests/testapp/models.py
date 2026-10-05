"""Пробные владельцы документов для тестов файловой подсистемы.

Подсистема универсальна: она не знает ни одного владельца. Тестировать её на
конкретном домене значило бы ловить в её тестах чужие регрессии, а владельцы
модуля БЗО (``apps.bpp``) ещё не написаны. Поэтому здесь свои минимальные
модели, подключённые тем же способом, каким подключится любой владелец
(регистрация из ``AppConfig.ready()``).

Таблицы создаёт тестовый раннер: пакета ``migrations`` у аппки нет, а
``migrate --run-syncdb`` (его вызывает pytest-django) заводит таблицы именно
для таких аппок. В ``INSTALLED_APPS`` она добавлена только в
``htqweb.settings.test``.
"""

import uuid

from django.db import models


class ProbeFolder(models.Model):
    """Владелец с целым ключом и жизненным циклом документа на согласовании:
    черновик → отправлен → возвращён на доработку. Правила — как у заявки
    из ТЗ §21: меняет автор в черновике и на доработке, после отправки —
    только новая версия."""

    DRAFT, SENT, RETURNED = "draft", "sent", "returned"

    code = models.CharField(max_length=32, default="ПР-1")
    author_id = models.IntegerField(default=7)
    # Кому ещё виден объект (согласующие): видит тот, кто видит владельца.
    viewer_ids = models.JSONField(default=list)
    status = models.CharField(max_length=16, default=DRAFT)
    sent_at = models.DateTimeField(null=True, blank=True)


class UuidProbeFolder(models.Model):
    """Владелец с UUID-ключом — так устроены документы модуля БЗО
    (мастер-план D-05)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author_id = models.IntegerField(default=7)

"""Файловая подсистема ТЗ §21 — справочник типов и таблица ``file_object``.

Аппка общая (``public``), хотя владельцы файлов бывают и общими (заявка), и
тенантными (договор — в схеме ``co_<slug>``). Поэтому у файла есть
``company_slug``: id договоров в разных компаниях повторяются, и без компании
в ключе владельца файлы одной компании были бы видны в другой. Для
тенантного владельца компания — часть ключа и обязательный фильтр каждого
запроса; для общего — только факт «из какой компании загрузили». Тот же
приём, что в ``apps.access`` (``PositionRole.company_slug``).
"""

from django.db import models
from django.db.models import Q
from django.db.models.functions import Now


class FileType(models.Model):
    """Справочник «Типы файлов» (ТЗ стр. 61, раздел 18).

    Строки фиксированы разделом 21, а заводит их владелец документов своей
    миграцией (``update_or_create`` по ``code``) — сама подсистема не знает
    ни одного владельца. Создавать и удалять типы через API нельзя,
    администратор меняет только ``max_mb`` — в ТЗ «Нет / размеры / нет».
    Правила количества (сколько документов, «1 действующий + версии»,
    обязательность) в справочник не входят — их объявляет владелец в коде
    (``FileTypeSpec`` в реестре владельцев).
    """

    code = models.CharField(max_length=64, primary_key=True)
    owner_type = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=200)
    # Расширения с точкой: [".pdf", ".docx", …]. Только для чтения.
    formats = models.JSONField(default=list)
    max_mb = models.PositiveIntegerField()
    sort_order = models.PositiveIntegerField(default=0, db_default=0)
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())
    updated_by_id = models.IntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "Тип файла"
        verbose_name_plural = "Типы файлов"
        ordering = ["owner_type", "sort_order", "code"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class FileObject(models.Model):
    """Одна версия документа объекта — таблица ``file_object`` из ТЗ (стр. 70).

    **Документ и версии.** Все версии одного документа делят ``document_id``.
    Строка неизменяема: «изменить файл» = добавить версию (ТЗ стр. 9: «Нельзя
    изменять; только новая версия»). ``version_no`` присваивается один раз —
    следующий по документу, под блокировкой владельца — и не меняется
    никогда. Новая версия загружается поверх конкретной действующей; если ту
    уже заменили, загрузка отвергается (409 ``E-CON-01``), поэтому параллельные
    версии одного документа не возникают вовсе.

    **«Заменён».** У предыдущей версии ``is_replaced`` и ``replaced_by`` (ТЗ:
    ``replaced_by_id``) ставятся в той же транзакции, что вставка новой.

    **Удаление.** После отправки владельца файлы физически не удаляются
    (ТЗ §21): только ``deleted_at`` у всех версий документа. Физически — лишь
    документ ни разу не отправленного владельца.

    Байты — в ``apps.media_files`` (scope ``file_object``, ключ по папке
    владельца), здесь — метаданные ТЗ: имя, тип, размер, SHA-256, версия, кто
    и когда загрузил, признак «Заменён».
    """

    company_slug = models.CharField(max_length=64, default="", blank=True,
                                    db_default="")
    owner_type = models.CharField(max_length=64)
    # Строка: документы модуля БЗО адресуются UUID (мастер-план D-05).
    # Хранится каноническая строка ключа модели владельца
    # (``OwnerEntry.storage_id``) — ``"5"`` или UUID в нижнем регистре.
    owner_id = models.CharField(max_length=64)
    file_type = models.ForeignKey(FileType, on_delete=models.PROTECT,
                                  related_name="files")
    document_id = models.UUIDField(db_index=True)
    version_no = models.PositiveIntegerField()
    is_replaced = models.BooleanField(default=False, db_default=False)
    replaced_by = models.ForeignKey("self", on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="+")

    name = models.CharField(max_length=512)
    mime = models.CharField(max_length=255)
    size = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    # Ключ объекта в хранилище — уникален по ТЗ.
    storage_key = models.CharField(max_length=1024, unique=True)
    # id FileMetadata в apps.media_files — строкой: межаппный FK запрещён.
    media_file_id = models.CharField(max_length=64, unique=True)

    uploaded_by_id = models.IntegerField(db_index=True)
    uploaded_by_name = models.CharField(max_length=255, default="", blank=True,
                                        db_default="")
    uploaded_by_department_id = models.IntegerField(null=True, blank=True)
    uploaded_by_department_name = models.CharField(max_length=255, default="",
                                                   blank=True, db_default="")
    uploaded_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    # Ключ повтора (заголовок Idempotency-Key): повтор того же запроса
    # возвращает первую запись, а не создаёт вторую.
    idempotency_key = models.CharField(max_length=64, default="", blank=True,
                                       db_default="")

    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by_id = models.IntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "Файл объекта"
        verbose_name_plural = "Файлы объектов"
        constraints = [
            models.UniqueConstraint(fields=["document_id", "version_no"],
                                    name="uq_file_object_version"),
            models.UniqueConstraint(
                fields=["company_slug", "owner_type", "owner_id", "idempotency_key"],
                condition=~Q(idempotency_key=""),
                name="uq_file_object_idempotency"),
        ]
        indexes = [
            models.Index(fields=["owner_type", "owner_id", "company_slug"],
                         name="ix_file_object_owner"),
        ]

    def __repr__(self) -> str:  # pragma: no cover
        return (f"<FileObject id={self.id} {self.owner_type}:{self.owner_id} "
                f"document={self.document_id} v{self.version_no}>")


class FileEvent(models.Model):
    """Журнал файловых операций (ТЗ §25.2: «загрузка / замена / скачивание
    файлов» — кто, когда, IP, user-agent).

    Один на всех владельцев. У заявки события дублируются ещё и в её ленту
    (``RequestActivity``, колбэк ``on_event``), но лента — то, что видит
    пользователь в карточке, а журнал — аудит, и у владельцев без своей ленты
    (договор) другого места для него нет.

    Только вставка: строки не правятся и не удаляются кодом. ``file_id`` —
    голое число, а не FK на ``FileObject``: физическое удаление документа из
    ни разу не отправленного черновика не должно ни стирать, ни обнулять
    запись о том, что файл был и кто его удалил.
    """

    company_slug = models.CharField(max_length=64, default="", blank=True,
                                    db_default="")
    owner_type = models.CharField(max_length=64)
    owner_id = models.CharField(max_length=64)  # как FileObject.owner_id
    event = models.CharField(max_length=32)
    document_id = models.UUIDField(null=True, blank=True)
    file_id = models.BigIntegerField(null=True, blank=True)
    actor_id = models.IntegerField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    ip = models.CharField(max_length=64, default="", blank=True, db_default="")
    user_agent = models.CharField(max_length=300, default="", blank=True,
                                  db_default="")
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        verbose_name = "Событие файла"
        verbose_name_plural = "Журнал файлов"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["owner_type", "owner_id", "company_slug", "created_at"],
                         name="ix_file_event_owner"),
        ]

    def __repr__(self) -> str:  # pragma: no cover
        return (f"<FileEvent id={self.id} {self.event} "
                f"{self.owner_type}:{self.owner_id} file={self.file_id}>")

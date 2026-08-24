"""Журнал видеоконференций: встречи, участники, записи, протокол.

Почему эти таблицы вообще появились. До сих пор конференция не оставляла
следа: комнату заводил браузер (случайный ``room_id``), SFU держал её только
в памяти, и единственной строкой в БД было приглашение
(``apps.cms.ConferenceInvite``). Ответить на вопрос «кто собирал встречу
двадцатого числа и что там решили» было нечем. Здесь — ответ.

Владелец данных — SFU: он единственный знает, когда комната реально
началась, кто в неё вошёл и когда вышел. Django принимает эти факты через
``/api/conference/v1/internal/*`` (см. ``views``) и хранит их.

**FK на пользователя нет ни в одной модели** — ``apps.conference`` не
владеет таблицей людей (правило изоляции аппок,
``apps/core/tests/test_app_isolation.py``), поэтому человек хранится числом
``user_id`` плюс СНИМКОМ имени. Снимок здесь не денормализация ради
скорости: протокол встречи должен читаться и через год, когда сотрудник
уволился, а строка в ``users`` уже удалена или переименована.
"""

from __future__ import annotations

from django.db import models
from django.db.models.functions import Now


class RecordingState(models.TextChoices):
    """Что сейчас с видеозаписью встречи.

    ``PURGED`` — отдельное состояние, а не удалённая строка: через 25 дней
    (см. ``purge_expired``) исчезают байты, но факт «запись была и её больше
    нет» остаётся, иначе интерфейс не отличит «не писали» от «записали и
    вычистили по сроку», и пользователь будет искать пропавший файл.
    """

    NONE = "none", "Не велась"
    RECORDING = "recording", "Идёт запись"
    PROCESSING = "processing", "Обработка"
    READY = "ready", "Готова"
    FAILED = "failed", "Ошибка"
    PURGED = "purged", "Удалена по сроку"


class TranscriptState(models.TextChoices):
    PENDING = "pending", "Ожидает распознавания"
    PROCESSING = "processing", "Распознаётся"
    READY = "ready", "Готов"
    FAILED = "failed", "Ошибка"
    SKIPPED = "skipped", "Пропущен"


class ConferenceSession(models.Model):
    """Одна состоявшаяся встреча в комнате ``room_id``.

    Комната переиспользуется (ссылка-приглашение живёт неделями, встречи по
    ней проходят каждый понедельник), поэтому сессия — это НЕ комната.
    Открытая сессия в комнате ровно одна: SFU заводит её на первом вошедшем
    и закрывает, когда вышел последний. Отсюда частичный уникальный индекс
    ниже — он и есть защита от гонки двух одновременных входов.
    """

    room_id = models.CharField(max_length=64, db_index=True)
    title = models.CharField(max_length=255, default="", blank=True, db_default="")
    #: Первый вошедший. Он же — автор встречи для интерфейса: комнату никто
    #: не «создаёт» явным действием, встреча начинается с первого человека.
    created_by_id = models.IntegerField(null=True, blank=True, db_index=True)
    created_by_name = models.CharField(max_length=255, default="", blank=True,
                                       db_default="")
    started_at = models.DateTimeField(db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_sec = models.PositiveIntegerField(null=True, blank=True)
    peak_participants = models.PositiveIntegerField(default=0, db_default=0)
    recording_state = models.CharField(max_length=16, choices=RecordingState.choices,
                                       default=RecordingState.NONE,
                                       db_default=RecordingState.NONE)
    transcript_state = models.CharField(max_length=16, choices=TranscriptState.choices,
                                        default=TranscriptState.PENDING,
                                        db_default=TranscriptState.PENDING)
    #: Когда медиа этой встречи подлежит уничтожению. Хранится колонкой, а
    #: не считается на лету из started_at: по нему идёт индексный запрос
    #: уборщика, и его видно в админке, когда спрашивают «а до какого числа
    #: доживёт эта запись».
    expires_at = models.DateTimeField(db_index=True)
    purged_at = models.DateTimeField(null=True, blank=True)
    #: Диагностика: почему обработка или распознавание не сложились.
    error = models.TextField(default="", blank=True, db_default="")
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        verbose_name = "Конференция"
        verbose_name_plural = "Конференции"
        ordering = ("-started_at",)
        constraints = [
            # Одна открытая сессия на комнату. Два человека, нажавших «войти»
            # в одну и ту же секунду, дают SFU два параллельных запроса на
            # создание сессии; без этого индекса встреча раздваивалась бы, и
            # половина участников с половиной записи оказывалась бы в одной
            # строке, половина — в другой.
            models.UniqueConstraint(
                fields=("room_id",),
                condition=models.Q(ended_at__isnull=True),
                name="conference_one_open_session_per_room",
            ),
        ]
        indexes = [
            # Запрос уборщика: «что пора чистить». Без составного индекса это
            # скан всей таблицы раз в сутки.
            models.Index(fields=("expires_at", "recording_state"),
                         name="conf_session_retention_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.title or self.room_id} · {self.started_at:%d.%m.%Y %H:%M}"


class ConferenceParticipant(models.Model):
    """Кто и когда был на встрече.

    Строка на ОДИН вход: человек, который вылетел по сети и вернулся, даст
    две строки с разными ``peer_id``. Так и надо — это фактический журнал
    присутствия, а не список приглашённых.
    """

    session = models.ForeignKey(ConferenceSession, on_delete=models.CASCADE,
                                related_name="participants")
    #: NULL — гость по ссылке (у гостевого JWT намеренно нет user_id, см.
    #: htqweb/authn/jwt.py::issue_guest_token).
    user_id = models.IntegerField(null=True, blank=True, db_index=True)
    display_name = models.CharField(max_length=255)
    #: Идентификатор соединения в SFU. Ключ, по которому дорожки записи
    #: сопоставляются с человеком.
    peer_id = models.CharField(max_length=64)
    is_guest = models.BooleanField(default=False, db_default=False)
    joined_at = models.DateTimeField()
    left_at = models.DateTimeField(null=True, blank=True)
    #: Сдвиг входа относительно начала встречи. Нужен и сборке видео
    #: (дорожка начинается не с нуля), и протоколу (тайм-коды Whisper
    #: считаются от начала ДОРОЖКИ, а показывать надо от начала ВСТРЕЧИ).
    joined_offset_ms = models.PositiveIntegerField(default=0, db_default=0)

    class Meta:
        verbose_name = "Участник конференции"
        verbose_name_plural = "Участники конференции"
        ordering = ("joined_at",)
        constraints = [
            models.UniqueConstraint(fields=("session", "peer_id"),
                                    name="conference_participant_unique_peer"),
        ]

    def __str__(self) -> str:
        return f"{self.display_name} ({self.peer_id})"


class RecordingKind(models.TextChoices):
    #: Готовое к просмотру видео всей встречи — то, что играет плеер.
    COMPOSED = "composed", "Сведённая запись"
    #: Сырьё: по дорожке на участника. Хранится до сборки и распознавания,
    #: потом удаляется. Модель их знает, чтобы уборка после сбоя не гадала.
    PEER_AUDIO = "peer_audio", "Аудиодорожка участника"
    PEER_VIDEO = "peer_video", "Видеодорожка участника"
    POSTER = "poster", "Кадр-заставка"


class ConferenceRecording(models.Model):
    """Один файл записи в объектном хранилище."""

    session = models.ForeignKey(ConferenceSession, on_delete=models.CASCADE,
                                related_name="recordings")
    kind = models.CharField(max_length=16, choices=RecordingKind.choices)
    participant = models.ForeignKey(ConferenceParticipant, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="recordings")
    #: Где лежат байты. Смысл зависит от ``kind``, и это единственное место,
    #: где такая двойственность допущена:
    #:
    #: * ``composed``/``poster`` — ключ объекта в бакете
    #:   ``CONFERENCE_S3_BUCKET``. Не URL: адрес подписывается на каждый
    #:   показ, и в БД ему делать нечего.
    #: * ``peer_audio``/``peer_video`` — путь ОТНОСИТЕЛЬНО
    #:   ``CONFERENCE_RAW_DIR`` на общем томе. Это сырьё, живущее до сборки и
    #:   распознавания; в объектное хранилище оно не попадает никогда.
    storage_path = models.CharField(max_length=1024)
    size = models.BigIntegerField(default=0, db_default=0)
    duration_sec = models.PositiveIntegerField(null=True, blank=True)
    mime = models.CharField(max_length=100, default="video/mp4", db_default="video/mp4")
    started_offset_ms = models.PositiveIntegerField(default=0, db_default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        verbose_name = "Файл записи"
        verbose_name_plural = "Файлы записей"
        ordering = ("kind", "started_offset_ms")
        indexes = [
            models.Index(fields=("session", "kind"), name="conf_recording_kind_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.storage_path}"


class ConferenceTranscriptSegment(models.Model):
    """Одна реплика протокола: кто, когда, что сказал.

    Атрибуция здесь точная, а не угаданная: аудио пишется ПОУЧАСТНИКОВО, и
    распознавание идёт по каждой дорожке отдельно, поэтому «кто говорит»
    известно из того, чей это файл. Диаризация — самая хрупкая часть любой
    системы расшифровки — в этой схеме просто не нужна.
    """

    session = models.ForeignKey(ConferenceSession, on_delete=models.CASCADE,
                                related_name="segments")
    participant = models.ForeignKey(ConferenceParticipant, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="segments")
    #: Снимок имени на момент встречи — см. докстринг модуля.
    speaker_name = models.CharField(max_length=255)
    #: Миллисекунды от НАЧАЛА ВСТРЕЧИ (не от начала дорожки говорящего).
    start_ms = models.PositiveIntegerField()
    end_ms = models.PositiveIntegerField()
    text = models.TextField()
    #: Средняя уверенность модели по реплике, 0..1. NULL — движок её не дал.
    confidence = models.FloatField(null=True, blank=True)

    class Meta:
        verbose_name = "Реплика протокола"
        verbose_name_plural = "Протокол"
        ordering = ("start_ms", "id")
        indexes = [
            models.Index(fields=("session", "start_ms"), name="conf_segment_time_idx"),
        ]

    def __str__(self) -> str:
        return f"[{self.start_ms // 1000}s] {self.speaker_name}: {self.text[:40]}"


class EventKind(models.TextChoices):
    JOIN = "join", "Вошёл"
    LEAVE = "leave", "Вышел"
    #: Камера, а НЕ демонстрация экрана: протокол сигналинга их не
    #: различает — и то и другое приезжает одним сообщением `mediaState`
    #: с флагом `camEnabled`. Называть это «показом экрана» значило бы
    #: обещать в протоколе сведения, которых у нас нет.
    CAMERA_ON = "camera_on", "Включил камеру"
    CAMERA_OFF = "camera_off", "Выключил камеру"
    CHAT = "chat", "Сообщение в чате"
    RECORDING_STARTED = "recording_started", "Запись начата"
    RECORDING_STOPPED = "recording_stopped", "Запись остановлена"


class ConferenceEvent(models.Model):
    """Журнал происходившего на встрече помимо речи.

    Вход и выход дублируют ``ConferenceParticipant`` намеренно: там это
    состояние («сейчас в комнате такие-то»), здесь — лента событий, которую
    можно показать одним списком вперемешку с репликами протокола.
    """

    session = models.ForeignKey(ConferenceSession, on_delete=models.CASCADE,
                                related_name="events")
    participant = models.ForeignKey(ConferenceParticipant, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="events")
    kind = models.CharField(max_length=24, choices=EventKind.choices)
    at_ms = models.PositiveIntegerField()
    payload = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        verbose_name = "Событие конференции"
        verbose_name_plural = "События конференции"
        ordering = ("at_ms", "id")
        indexes = [
            models.Index(fields=("session", "at_ms"), name="conf_event_time_idx"),
        ]

    def __str__(self) -> str:
        return f"[{self.at_ms // 1000}s] {self.get_kind_display()}"

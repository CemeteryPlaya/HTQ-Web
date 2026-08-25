"""Фоновые задачи конференций.

Тяжёлое здесь отделено от живого звонка намеренно: во время встречи SFU
только ремуксит потоки в файлы (``-c copy``, почти без CPU), а сборка одного
видео и распознавание речи выполняются потом — и не общим воркером, а
``backend-media-worker`` в очереди ``conference_media`` (маршрутизация —
``CELERY_TASK_ROUTES`` в settings/base.py). Часовая встреча считается
десятками минут, и в общей очереди она задержала бы отправку почты и
пересчёт метрик.

Первая строка каждой задачи — ``require_service("conference")``: конвенция
платформы, выключенный сервис не должен продолжать работать фоном.
"""

from __future__ import annotations

import datetime
import logging
import shutil

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from apps.core.services import require_service

from .models import (
    ConferenceRecording,
    ConferenceSession,
    ConferenceTranscriptSegment,
    RecordingKind,
    RecordingState,
    TranscriptState,
)
from .services import compose_service, session_service, storage_service

logger = logging.getLogger(__name__)


@shared_task
def notify_session_started(session_id: int) -> int:
    """Сообщить приглашённым, что встреча уже идёт. Возвращает их число.

    Три канала независимы намеренно: колокольчик переживает закрытую вкладку,
    живой тост доставляется мгновенно, письмо доходит до тех, кого сейчас нет
    в системе. Падение одного не отменяет двух других — тот же приём, что в
    ``cms.services.conference_invite_service.send_invite``.
    """
    require_service("conference")

    session = ConferenceSession.objects.filter(pk=session_id).first()
    if session is None or session.calendar_event_id is None:
        return 0

    from apps.tasks.interface import get_conference_event_for_room

    event = get_conference_event_for_room(session.room_id)
    if not event:
        return 0

    recipients = [uid for uid in event["invitee_ids"]
                  if uid != session.created_by_id]
    if not recipients:
        return 0

    title = session.title or event["title"]
    join_url = f"/room/{session.room_id}"

    try:
        from apps.tasks.interface import push_notification

        for user_id in recipients:
            push_notification(recipient_id=user_id,
                              verb=f"Видеоконференция «{title}» началась",
                              target_type="conference_session",
                              target_id=session.pk)
    except Exception:
        logger.warning("conference: колокольчик не принял уведомление о старте %s",
                       session.pk, exc_info=True)

    try:
        from apps.messenger import interface as messenger

        messenger.dispatch_notification(recipients, {
            "type": "conference_started",
            "session_id": session.pk,
            "room_id": session.room_id,
            "title": title,
            "join_url": join_url,
            "started_at": session.started_at.isoformat(),
        })
    except Exception:
        logger.warning("conference: живое уведомление о старте %s не ушло",
                       session.pk, exc_info=True)

    try:
        from apps.users.interface import get_users_brief

        emails = [row["email"] for row in get_users_brief(recipients)
                  if row.get("email")]
        if emails:
            # Время с явной пометкой пояса: платформа живёт в UTC+5, а письмо
            # может открыть внешний участник, у которого он другой.
            local = timezone.localtime(session.started_at)
            send_mail(
                f"Видеоконференция «{title}» началась",
                f"Встреча началась в {local:%H:%M} (UTC+5).\n"
                f"Подключиться: {settings.PUBLIC_BASE_URL.rstrip('/')}{join_url}",
                None, emails, fail_silently=False)
    except Exception:
        logger.warning("conference: письмо о старте %s не ушло", session.pk,
                       exc_info=True)

    return len(recipients)


@shared_task
def process_session_recording(session_id: int) -> str:
    """Свести дорожки встречи в одно видео и залить его в хранилище."""
    require_service("conference")

    session = ConferenceSession.objects.filter(pk=session_id).first()
    if session is None:
        logger.warning("conference: сессия %s исчезла до обработки", session_id)
        return "missing"
    if session.recording_state == RecordingState.READY:
        return "already_ready"

    raw_rows = list(session.recordings.filter(
        kind__in=(RecordingKind.PEER_AUDIO, RecordingKind.PEER_VIDEO),
    ).select_related("participant"))

    video_inputs, audio_inputs = [], []
    for row in raw_rows:
        path = compose_service.raw_path(session, row)
        if not path.exists():
            logger.warning("conference: дорожка %s не найдена на томе", path)
            continue
        target = video_inputs if row.kind == RecordingKind.PEER_VIDEO else audio_inputs
        target.append((path, row.started_offset_ms))

    if not video_inputs and not audio_inputs:
        # Не ошибка: встреча могла состояться при выключенной записи или
        # оборваться раньше, чем кто-либо включил микрофон.
        session.recording_state = RecordingState.NONE
        session.transcript_state = TranscriptState.SKIPPED
        session.save(update_fields=["recording_state", "transcript_state",
                                    "updated_at"])
        return "nothing_to_compose"

    # В картинку попадают не все: сетка ограничена CONFERENCE_MAX_TILES.
    # Порядок — по времени входа, чтобы раскладка была предсказуемой, а не
    # зависела от порядка строк в базе.
    video_inputs.sort(key=lambda item: item[1])
    video_inputs = video_inputs[:settings.CONFERENCE_MAX_TILES]
    audio_inputs.sort(key=lambda item: item[1])

    duration_sec = session.duration_sec or 0
    if duration_sec <= 0:
        duration_sec = max(int(offset / 1000) for _p, offset in
                           [*video_inputs, *audio_inputs]) + 1

    work_dir = compose_service.raw_root() / str(session.pk)
    output = work_dir / "recording.mp4"

    try:
        args = compose_service.build_command(
            video_inputs=video_inputs, audio_inputs=audio_inputs,
            duration_sec=duration_sec, output=output,
        )
        # Потолок времени — вчетверо от длительности встречи, но не меньше
        # десяти минут: veryfast на CPU обычно быстрее реального времени,
        # четырёхкратный запас покрывает загруженный хост.
        compose_service.run(args, timeout=max(600, duration_sec * 4))
    except compose_service.ComposeError as exc:
        logger.exception("conference: сборка сессии %s не удалась", session.pk)
        session.recording_state = RecordingState.FAILED
        session.error = str(exc)[:2000]
        session.save(update_fields=["recording_state", "error", "updated_at"])
        # Расшифровку всё равно пробуем: сырое аудио на месте, и протокол
        # ценен сам по себе, даже когда видео собрать не вышло.
        transcribe_session.delay(session.pk)
        return "compose_failed"

    prefix = storage_service.session_prefix(session)
    video_key = f"{prefix}/recording.mp4"
    storage_service.put(video_key, output.read_bytes(), "video/mp4")

    with transaction.atomic():
        ConferenceRecording.objects.update_or_create(
            session=session, kind=RecordingKind.COMPOSED,
            defaults={
                "storage_path": video_key,
                "size": output.stat().st_size,
                "duration_sec": duration_sec,
                "mime": "video/mp4",
                "participant": None,
                "started_offset_ms": 0,
            },
        )
        session.recording_state = RecordingState.READY
        session.error = ""
        session.save(update_fields=["recording_state", "error", "updated_at"])

    poster = work_dir / "poster.jpg"
    if compose_service.extract_poster(output, poster):
        poster_key = f"{prefix}/poster.jpg"
        storage_service.put(poster_key, poster.read_bytes(), "image/jpeg")
        ConferenceRecording.objects.update_or_create(
            session=session, kind=RecordingKind.POSTER,
            defaults={"storage_path": poster_key, "size": poster.stat().st_size,
                      "mime": "image/jpeg", "participant": None,
                      "started_offset_ms": 0},
        )

    output.unlink(missing_ok=True)
    transcribe_session.delay(session.pk)
    return "ready"


@shared_task
def transcribe_session(session_id: int) -> int:
    """Распознать речь по дорожкам участников и собрать протокол."""
    require_service("conference")

    session = ConferenceSession.objects.filter(pk=session_id).first()
    if session is None:
        return 0
    if session.transcript_state in (TranscriptState.READY, TranscriptState.SKIPPED):
        return session.segments.count()

    audio_rows = list(session.recordings
                      .filter(kind=RecordingKind.PEER_AUDIO)
                      .select_related("participant"))
    if not audio_rows:
        session.transcript_state = TranscriptState.SKIPPED
        session.save(update_fields=["transcript_state", "updated_at"])
        _drop_raw_dir(session)
        return 0

    session.transcript_state = TranscriptState.PROCESSING
    session.save(update_fields=["transcript_state", "updated_at"])

    from .services import transcript_service

    segments: list[ConferenceTranscriptSegment] = []
    failures = 0
    for row in audio_rows:
        path = compose_service.raw_path(session, row)
        if not path.exists():
            continue
        speaker = (row.participant.display_name if row.participant else "Участник")
        try:
            pieces = transcript_service.transcribe_track(
                path, offset_ms=row.started_offset_ms,
            )
        except transcript_service.TranscriptionUnavailable:
            # Задача попала не в тот воркер — состояние не портим, пусть её
            # переставят в правильную очередь.
            session.transcript_state = TranscriptState.PENDING
            session.save(update_fields=["transcript_state", "updated_at"])
            raise
        except Exception:
            logger.exception("conference: не распозналась дорожка %s", path)
            failures += 1
            continue

        segments.extend(
            ConferenceTranscriptSegment(
                session=session, participant=row.participant, speaker_name=speaker,
                start_ms=piece["start_ms"], end_ms=piece["end_ms"],
                text=piece["text"], confidence=piece["confidence"],
            )
            for piece in pieces
        )

    # Сортировка по времени и есть «слияние» дорожек в единый протокол:
    # порядок реплик — это порядок, в котором они прозвучали на встрече.
    segments.sort(key=lambda item: item.start_ms)

    with transaction.atomic():
        session.segments.all().delete()  # повторный прогон не должен двоить
        ConferenceTranscriptSegment.objects.bulk_create(segments, batch_size=500)
        session.transcript_state = (TranscriptState.FAILED
                                    if failures and not segments
                                    else TranscriptState.READY)
        session.save(update_fields=["transcript_state", "updated_at"])

    _drop_raw_dir(session)
    logger.info("conference: сессия %s — %d реплик протокола", session.pk,
                len(segments))
    return len(segments)


def _drop_raw_dir(session: ConferenceSession) -> None:
    """Убрать сырьё с тома: оно больше не нужно и занимает больше всего места.

    Строки сырых дорожек удаляем вместе с файлами — иначе в базе останутся
    записи, указывающие в пустоту, и сборщик при повторном запуске будет
    искать несуществующие файлы.
    """
    session.recordings.filter(
        kind__in=(RecordingKind.PEER_AUDIO, RecordingKind.PEER_VIDEO),
    ).delete()

    work_dir = compose_service.raw_root() / str(session.pk)
    try:
        shutil.rmtree(work_dir, ignore_errors=True)
    except Exception:
        logger.exception("conference: не удалось убрать каталог %s", work_dir)


@shared_task
def purge_expired() -> int:
    """Стереть медиа встреч, у которых вышел срок хранения.

    Удаляются ТОЛЬКО байты: объекты в хранилище и строки о файлах. Сама
    встреча, список участников, журнал событий и текстовый протокол
    остаются навсегда (решение заказчика) — они весят копейки и являются
    памятью компании, тогда как видео это гигабайты и персональные данные.

    Состояние ``purged`` выставляется вместо удаления строки, чтобы
    интерфейс мог отличить «не записывали» от «записали и вычистили по
    сроку» — иначе человек будет искать пропавший файл.
    """
    require_service("conference")

    now = timezone.now()
    sessions = list(ConferenceSession.objects.filter(
        expires_at__lte=now,
        recording_state__in=(RecordingState.READY, RecordingState.FAILED,
                             RecordingState.PROCESSING),
    ))
    if not sessions:
        return 0

    purged = 0
    for session in sessions:
        recordings = list(session.recordings.all())
        keys = [row.storage_path for row in recordings
                if row.kind in (RecordingKind.COMPOSED, RecordingKind.POSTER)]
        storage_service.delete_many(keys)
        # Сырьё, если сборка так и не доехала, лежит на томе — его тоже под нож.
        _drop_raw_dir(session)

        session.recordings.all().delete()
        session.recording_state = RecordingState.PURGED
        session.purged_at = now
        session.save(update_fields=["recording_state", "purged_at", "updated_at"])
        purged += 1

    logger.info("conference: вычищено медиа %d встреч (срок %d дней)",
                purged, settings.CONFERENCE_RETENTION_DAYS)
    return purged


@shared_task
def reap_orphan_sessions() -> int:
    """Закрыть встречи, о конце которых SFU не сообщил.

    Штатно сессию закрывает SFU, когда из комнаты вышел последний участник.
    Если SFU перезапустился посреди звонка, строка останется открытой
    навсегда: она будет висеть в истории как «идёт», занимать частичный
    уникальный индекс комнаты (то есть следующая встреча в той же комнате
    прилипнет к ней) и держать сырьё на томе. Отсюда эта задача.
    """
    require_service("conference")

    cutoff = timezone.now() - datetime.timedelta(hours=settings.CONFERENCE_ORPHAN_HOURS)
    stale = list(ConferenceSession.objects.filter(ended_at__isnull=True,
                                                  started_at__lt=cutoff))
    for session in stale:
        # Время конца — последний известный признак жизни, а не «сейчас»:
        # иначе брошенная встреча получила бы длительность в шесть часов.
        last_seen = (session.participants
                     .order_by("-joined_at")
                     .values_list("joined_at", flat=True)
                     .first())
        session_service.finish_session(session, ended_at=last_seen or session.started_at)

    if stale:
        logger.info("conference: принудительно закрыто %d осиротевших встреч",
                    len(stale))
    return len(stale)


@shared_task
def sweep_orphan_raw_dirs() -> int:
    """Убрать каталоги на томе, которым не соответствует ни одна встреча.

    Страховка от обратного сбоя: SFU успел создать каталог и написать в него
    дорожки, но сообщить о сессии не смог (Django был недоступен). Такие
    каталоги никем не подобраны и растут молча.
    """
    require_service("conference")

    root = compose_service.raw_root()
    if not root.exists():
        return 0

    cutoff = timezone.now() - datetime.timedelta(hours=settings.CONFERENCE_ORPHAN_HOURS)
    removed = 0
    for entry in root.iterdir():
        if not entry.is_dir() or not entry.name.isdigit():
            continue
        if ConferenceSession.objects.filter(pk=int(entry.name)).exists():
            continue
        modified = datetime.datetime.fromtimestamp(entry.stat().st_mtime,
                                                   tz=datetime.timezone.utc)
        if modified > cutoff:
            continue  # каталог ещё пишется — сессия может доехать позже
        shutil.rmtree(entry, ignore_errors=True)
        removed += 1

    if removed:
        logger.info("conference: убрано %d осиротевших каталогов записи", removed)
    return removed

"""Приём фактов о встрече от SFU и ведение журнала.

Источник истины о том, что происходило в комнате, — SFU: только он знает,
когда звонок реально начался, кто вошёл и когда все разошлись. Django эти
факты принимает и хранит; сам он ничего о ходе встречи не выясняет.

Отсюда главное требование к каждой функции здесь — **идемпотентность**.
Сеть между контейнерами теряет ответы, SFU повторяет запрос, и повтор не
должен раздваивать встречу или плодить участников. Поэтому «начать сессию» —
это get_or_create по открытой сессии комнаты, а «участник вошёл» —
update_or_create по паре (сессия, peer_id).
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.conference.models import (
    ConferenceEvent,
    ConferenceParticipant,
    ConferenceRecording,
    ConferenceSession,
    EventKind,
    RecordingKind,
    RecordingState,
    TranscriptState,
)

logger = logging.getLogger(__name__)


def _room_title(room_id: str) -> str:
    """Название встречи из приглашения, если оно есть.

    Через ``apps.cms.interface``, а не прямым запросом к ``cms.models`` —
    правило изоляции аппок (apps/core/tests/test_app_isolation.py). Импорт
    внутри функции: так же поступает
    ``cms.services.conference_invite_service.send_invite`` с messenger'ом,
    и по той же причине — чтобы выключенный сосед не ронял импорт модуля.
    """
    try:
        from apps.cms.interface import get_conference_room_title

        return get_conference_room_title(room_id)
    except Exception:
        # Название — украшение: без него встреча покажется по room_id.
        # Ронять из-за этого приём сессии нельзя, поэтому не fallback() —
        # это не подмена значения, а необязательное обогащение.
        logger.info("conference: не удалось получить название комнаты %s", room_id,
                    exc_info=True)
        return ""


def _default_title_from_creator(created_by_name: str) -> str:
    """Запасное автоназвание — НЕ основной путь.

    Основной расчёт «имя создателя + конференция» живёт на фронте (там же
    он показан плейсхолдером в поле названия, и он обязан совпадать с тем,
    что реально сохранится). Эта функция — вторая линия обороны на случай
    старого клиента, который ещё не шлёт ``title``, или прямого обращения к
    SFU в обход фронта: тогда сюда долетает только ``created_by_name``.
    """
    first_name = (created_by_name or "").strip().split(" ")[0]
    if not first_name:
        return ""
    return f"{first_name} конференция"


def _calendar_event_for(room_id: str) -> dict | None:
    """Событие календаря этой комнаты — или None.

    Импорт внутри функции и широкий ``except``: связь с календарём —
    обогащение, а не условие приёма встречи. Выключенный или упавший
    ``tasks`` не должен мешать людям разговаривать.
    """
    try:
        from apps.tasks.interface import get_conference_event_for_room

        return get_conference_event_for_room(room_id)
    except Exception:
        logger.info("conference: календарное событие для комнаты %s недоступно",
                    room_id, exc_info=True)
        return None


def start_session(*, room_id: str, started_at=None, created_by_id: int | None = None,
                  created_by_name: str = "", title: str = "") -> ConferenceSession:
    """Открыть сессию в комнате или вернуть уже открытую.

    Вызывается на КАЖДОМ входе в комнату, а не только на первом: SFU не
    обязан помнить, сообщал ли он уже об этой встрече (он мог перезапуститься
    в середине звонка). Автором остаётся тот, кто пришёл первым.
    """
    started_at = started_at or timezone.now()

    existing = ConferenceSession.objects.filter(room_id=room_id,
                                                ended_at__isnull=True).first()
    if existing is not None:
        return existing

    event = _calendar_event_for(room_id)

    # Порядок разрешения названия — по убыванию приоритета:
    #   1) название события календаря — у запланированной встречи название
    #      уже есть, и вошедший (тем более вторым) не должен переименовывать
    #      её своим автоназванием;
    #   2) title, присланный SFU — это либо то, что человек сам вписал в
    #      лобби, либо вычисленное фронтом автоназвание («Санжар конференция»),
    #      которое СОВПАДАЕТ с плейсхолдером в поле — из фронта сюда всегда
    #      приезжает непустая строка;
    #   3) название из приглашения (см. _room_title) — прежний фолбэк;
    #   4) собственный расчёт автоназвания из created_by_name — страховка на
    #      случай старого клиента или прямого обращения к SFU в обход фронта,
    #      когда title вообще не пришёл.
    session = ConferenceSession(
        room_id=room_id,
        title=(
            (event or {}).get("title")
            or title
            or _room_title(room_id)
            or _default_title_from_creator(created_by_name)
        ),
        calendar_event_id=(event or {}).get("id"),
        created_by_id=created_by_id,
        created_by_name=created_by_name,
        started_at=started_at,
        expires_at=started_at + timedelta(days=settings.CONFERENCE_RETENTION_DAYS),
        recording_state=(RecordingState.RECORDING
                         if settings.CONFERENCE_RECORDING_ENABLED
                         else RecordingState.NONE),
        transcript_state=(TranscriptState.PENDING
                          if settings.CONFERENCE_RECORDING_ENABLED
                          else TranscriptState.SKIPPED),
    )
    try:
        with transaction.atomic():
            session.save()
    except IntegrityError:
        # Гонка двух одновременных входов: частичный уникальный индекс
        # conference_one_open_session_per_room отдал победу другому запросу.
        # Это не ошибка — сессия существует, что нам и нужно.
        session = ConferenceSession.objects.filter(room_id=room_id,
                                                   ended_at__isnull=True).first()
        if session is None:  # pragma: no cover — только при гонке с finish()
            raise
    else:
        # Ставим ТОЛЬКО на ветке создания. start_session зовётся на каждом
        # входе в комнату, и это единственное место, где новая встреча
        # появляется ровно один раз, — значит идемпотентность рассылки
        # получается даром, без флагов в БД.
        if session.calendar_event_id is not None:
            from apps.conference.tasks import notify_session_started

            # Ошибка брокера не должна ронять start_session: сессия уже
            # создана и сохранена, а из-за упавшего .delay() SFU получил бы
            # 500 на успешно открытую встречу. Прецедент — enqueue_processing
            # ниже в этом файле, обёрнут по той же причине.
            try:
                notify_session_started.delay(session.pk)
            except Exception:
                logger.exception("conference: не удалось поставить уведомление "
                                 "о начале сессии %s", session.pk)
    return session


def participant_joined(session: ConferenceSession, *, peer_id: str, display_name: str,
                       user_id: int | None, is_guest: bool,
                       joined_at=None) -> ConferenceParticipant:
    joined_at = joined_at or timezone.now()
    offset_ms = max(0, int((joined_at - session.started_at).total_seconds() * 1000))

    participant, created = ConferenceParticipant.objects.update_or_create(
        session=session,
        peer_id=peer_id,
        defaults={
            "display_name": display_name or "Участник",
            "user_id": user_id,
            "is_guest": is_guest,
            "joined_at": joined_at,
            "joined_offset_ms": offset_ms,
        },
    )
    if created:
        log_event(session, kind=EventKind.JOIN, at_ms=offset_ms, participant=participant)
        _bump_peak(session)
    return participant


def participant_left(session: ConferenceSession, *, peer_id: str,
                     left_at=None) -> ConferenceParticipant | None:
    left_at = left_at or timezone.now()
    participant = ConferenceParticipant.objects.filter(session=session,
                                                       peer_id=peer_id).first()
    if participant is None:
        return None
    if participant.left_at is None:
        participant.left_at = left_at
        participant.save(update_fields=["left_at"])
        log_event(session, kind=EventKind.LEAVE,
                  at_ms=_offset_ms(session, left_at), participant=participant)
    return participant


def _bump_peak(session: ConferenceSession) -> None:
    """Максимум одновременно присутствовавших.

    Считаем по «вошёл и ещё не вышел» в момент входа — дешевле и честнее,
    чем общее число строк участников: человек, переподключившийся трижды,
    не должен выглядеть как трое.
    """
    current = session.participants.filter(left_at__isnull=True).count()
    if current > session.peak_participants:
        session.peak_participants = current
        session.save(update_fields=["peak_participants", "updated_at"])


def _offset_ms(session: ConferenceSession, moment) -> int:
    return max(0, int((moment - session.started_at).total_seconds() * 1000))


def log_event(session: ConferenceSession, *, kind: str, at_ms: int | None = None,
              participant: ConferenceParticipant | None = None,
              payload: dict | None = None) -> ConferenceEvent:
    if at_ms is None:
        at_ms = _offset_ms(session, timezone.now())
    return ConferenceEvent.objects.create(
        session=session, kind=kind, at_ms=at_ms,
        participant=participant, payload=payload,
    )


def register_artifacts(session: ConferenceSession, artifacts) -> int:
    """Запомнить сырые дорожки, дописанные рекордером на общий том.

    Идемпотентно по (сессия, вид, путь): SFU сообщает о дорожке сразу после
    её закрытия и повторяет весь список в ``finish``, потому что потерянный
    ответ на первое сообщение не должен стоить участнику места в записи.
    """
    stored = 0
    for artifact in artifacts:
        rel_path = _safe_rel_path(artifact.rel_path)
        if rel_path is None:
            logger.warning("conference: отклонён путь дорожки %r (сессия %s)",
                           artifact.rel_path, session.pk)
            continue

        participant = session.participants.filter(peer_id=artifact.peer_id).first()
        _, created = ConferenceRecording.objects.update_or_create(
            session=session,
            kind=artifact.kind,
            storage_path=rel_path,
            defaults={
                "participant": participant,
                "started_offset_ms": artifact.started_offset_ms,
                "size": artifact.size,
                "mime": ("audio/x-matroska" if artifact.kind == RecordingKind.PEER_AUDIO
                         else "video/x-matroska"),
            },
        )
        stored += int(created)
    return stored


def _safe_rel_path(raw: str) -> str | None:
    """Отфильтровать путь, пришедший из чужого контейнера.

    Рекордер сообщает, куда он положил дорожку, и этот путь потом подставится
    в файловые операции сборщика. Принимать его как есть нельзя: ``..`` или
    ведущий слэш превратили бы сообщение о записи в чтение (а после уборки —
    и в удаление) произвольного файла воркера. Пропускаем только простые
    относительные пути.
    """
    value = (raw or "").strip().replace("\\", "/")
    if not value or value.startswith("/"):
        return None
    parts = [part for part in value.split("/") if part]
    if any(part in ("..", ".") for part in parts):
        return None
    return "/".join(parts) if parts else None


def finish_session(session: ConferenceSession, *, ended_at=None) -> ConferenceSession:
    """Закрыть встречу и поставить её в очередь на обработку.

    Идемпотентна: повторный finish на уже закрытой сессии ничего не делает и
    НЕ ставит вторую задачу обработки — иначе один потерянный ответ SFU
    приводил бы к двум параллельным сборкам одного и того же видео.
    """
    if session.ended_at is not None:
        return session

    ended_at = ended_at or timezone.now()
    session.ended_at = ended_at
    session.duration_sec = max(0, int((ended_at - session.started_at).total_seconds()))
    session.participants.filter(left_at__isnull=True).update(left_at=ended_at)
    if session.recording_state == RecordingState.RECORDING:
        session.recording_state = RecordingState.PROCESSING
    session.save(update_fields=["ended_at", "duration_sec", "recording_state",
                                "updated_at"])

    if session.recording_state == RecordingState.PROCESSING:
        enqueue_processing(session)
    return session


def enqueue_processing(session: ConferenceSession) -> None:
    """Поставить сборку записи в очередь conference_media.

    Ошибка брокера не должна ронять закрытие встречи: сессия уже закрыта и
    сохранена, дорожки лежат на томе, и подобрать их сможет
    ``reap_orphan_sessions``. Прецедент — ``media_files.interface.store_file``,
    где .delay() обёрнут по той же причине.
    """
    from apps.conference.tasks import process_session_recording

    try:
        process_session_recording.delay(session.pk)
    except Exception:
        logger.exception("conference: не удалось поставить обработку сессии %s",
                         session.pk)

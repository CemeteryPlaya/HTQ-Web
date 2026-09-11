"""Чтение истории встреч: список, карточка, протокол, экспорт."""

from __future__ import annotations

from django.db.models import Count, Q

from apps.conference import schemas
from apps.conference.models import (
    ConferenceSession,
    RecordingKind,
    RecordingState,
)
from apps.conference.services import access, signing


def _playable(session: ConferenceSession) -> bool:
    return session.recording_state == RecordingState.READY


def to_list_item(session: ConferenceSession) -> schemas.SessionListItem:
    return schemas.SessionListItem(
        id=session.pk,
        room_id=session.room_id,
        title=session.title,
        created_by_id=session.created_by_id,
        created_by_name=session.created_by_name,
        started_at=session.started_at,
        ended_at=session.ended_at,
        duration_sec=session.duration_sec,
        peak_participants=session.peak_participants,
        recording_state=session.recording_state,
        transcript_state=session.transcript_state,
        expires_at=session.expires_at,
        participant_count=getattr(session, "participant_count", 0),
        has_recording=_playable(session),
    )


def list_sessions(request, *, page: int, limit: int, query: str = "",
                  date_from=None, date_to=None,
                  mine: bool = False) -> schemas.SessionListResponse:
    queryset = access.visible_sessions(request)

    if mine:
        token = getattr(request, "token", None)
        if token is not None:
            queryset = queryset.filter(created_by_id=token.user_id)
    if query:
        queryset = queryset.filter(Q(title__icontains=query)
                                   | Q(created_by_name__icontains=query)
                                   | Q(room_id__icontains=query))
    if date_from is not None:
        queryset = queryset.filter(started_at__date__gte=date_from)
    if date_to is not None:
        queryset = queryset.filter(started_at__date__lte=date_to)

    queryset = queryset.annotate(participant_count=Count("participants", distinct=True))

    total = queryset.count()
    # Сводки считаем по ТОМУ ЖЕ отфильтрованному набору, а не по всей
    # таблице: «сколько из найденного записано» — осмысленное число,
    # «сколько записано вообще» рядом с фильтром по датам вводит в
    # заблуждение.
    recorded_total = queryset.filter(recording_state=RecordingState.READY).count()
    active_total = queryset.filter(ended_at__isnull=True).count()

    pages = max(1, -(-total // limit))  # ceil без импорта math
    offset = (page - 1) * limit
    rows = list(queryset.order_by("-started_at")[offset:offset + limit])

    return schemas.SessionListResponse(
        items=[to_list_item(row) for row in rows],
        total=total, page=page, pages=pages, limit=limit,
        recorded_total=recorded_total, active_total=active_total,
    )


def session_detail(session: ConferenceSession) -> schemas.SessionDetail:
    participants = list(session.participants.all())
    base = to_list_item(session)
    playable = _playable(session)

    # Ссылки подписываем ЗДЕСЬ, потому что права проверены прямо перед
    # вызовом (access.get_visible_session). Плеер потом ходит по подписи —
    # заголовок Authorization он отправить не может. См. services/signing.py.
    recording_url = signing.recording_url(session.pk) if playable else None
    download_url = (signing.recording_url(session.pk, download=True)
                    if playable else None)
    poster_url = (signing.poster_url(session.pk)
                  if playable and _has_poster(session) else None)

    participants_read = []
    for row in participants:
        item = schemas.ParticipantRead.model_validate(row)
        if row.left_at is not None:
            delta = row.left_at - session.started_at
            item.left_offset_ms = max(0, int(delta.total_seconds() * 1000))
        participants_read.append(item)

    return schemas.SessionDetail(
        **base.model_dump(),
        error=session.error,
        purged_at=session.purged_at,
        participants=participants_read,
        playable=playable,
        recording_url=recording_url,
        download_url=download_url,
        poster_url=poster_url,
    )


def _has_poster(session: ConferenceSession) -> bool:
    return session.recordings.filter(kind=RecordingKind.POSTER).exists()


def transcript(session: ConferenceSession) -> schemas.TranscriptResponse:
    segments = session.segments.all()
    return schemas.TranscriptResponse(
        session_id=session.pk,
        state=session.transcript_state,
        segments=[schemas.TranscriptSegmentRead.model_validate(s) for s in segments],
    )


def composed_recording(session: ConferenceSession):
    """Файл, который играет плеер, или None."""
    return session.recordings.filter(kind=RecordingKind.COMPOSED).first()


def poster_recording(session: ConferenceSession):
    return session.recordings.filter(kind=RecordingKind.POSTER).first()


def _timecode(ms: int) -> str:
    total = ms // 1000
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def render_transcript(session: ConferenceSession, fmt: str) -> tuple[str, str, str]:
    """Протокол текстом. Возвращает (содержимое, mime, имя файла).

    Экспорт делаем на сервере, а не сборкой строки в браузере: тот же текст
    нужен и в письме, и в задаче, и человеку «просто файлом», и держать две
    расходящиеся реализации формата протокола не стоит.
    """
    segments = list(session.segments.all())
    when = session.started_at.strftime("%d.%m.%Y %H:%M")
    title = session.title or f"Конференция {session.room_id}"

    if fmt == "md":
        lines = [f"# {title}", "",
                 f"**Дата:** {when}  ",
                 f"**Организатор:** {session.created_by_name or '—'}  ",
                 f"**Участников:** {session.peak_participants}", ""]
        if not segments:
            lines.append("_Протокол пуст: речь не распознана._")
        for seg in segments:
            lines.append(f"**[{_timecode(seg.start_ms)}] {seg.speaker_name}:** "
                         f"{seg.text}")
            lines.append("")
        body = "\n".join(lines)
        return body, "text/markdown; charset=utf-8", f"protocol-{session.pk}.md"

    lines = [title, when,
             f"Организатор: {session.created_by_name or '—'}",
             f"Участников: {session.peak_participants}",
             "-" * 60, ""]
    if not segments:
        lines.append("Протокол пуст: речь не распознана.")
    for seg in segments:
        lines.append(f"[{_timecode(seg.start_ms)}] {seg.speaker_name}: {seg.text}")
    body = "\n".join(lines)
    return body, "text/plain; charset=utf-8", f"protocol-{session.pk}.txt"

"""Расшифровка речи: аудиодорожки участников → реплики протокола.

Атрибуция здесь бесплатна, и это следствие того, как ведётся запись. Аудио
пишется ПОУЧАСТНИКОВО, по файлу на человека, поэтому вопрос «кто сейчас
говорит» не решается вовсе — ответ известен из того, чей это файл.
Диаризация (разделение говорящих по голосу) — самая ненадёжная часть любой
системы расшифровки, и в этой схеме она просто не нужна.

Каждая дорожка распознаётся отдельно, а её тайм-коды сдвигаются на
``started_offset_ms`` участника: Whisper считает время от начала СВОЕГО
файла, а протоколу нужно время от начала ВСТРЕЧИ. После сдвига все реплики
всех участников складываются в один список и сортируются по времени.

Модель грузится лениво и один раз на процесс: ``WhisperModel`` тянет с диска
полтора гигабайта весов, и делать это на каждую дорожку — значит потратить
на загрузку больше, чем на распознавание.
"""

from __future__ import annotations

import logging
import threading

from django.conf import settings

logger = logging.getLogger(__name__)

_model = None
_model_lock = threading.Lock()


class TranscriptionUnavailable(RuntimeError):
    """Движок распознавания недоступен в этом процессе."""


def get_model():
    """Загруженная модель Whisper (одна на процесс).

    Импорт внутри функции намеренно: ``faster_whisper`` стоит только в образе
    backend/Dockerfile.media. Обычный backend-web не должен падать на импорте
    модуля из-за библиотеки, которой у него нет и которая ему не нужна.
    """
    global _model
    if _model is not None:
        return _model

    with _model_lock:
        if _model is not None:  # pragma: no cover — гонка двух потоков воркера
            return _model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise TranscriptionUnavailable(
                "faster-whisper не установлен: задача должна выполняться "
                "воркером backend-media-worker (образ backend/Dockerfile.media)"
            ) from exc

        logger.info("conference: загружаю Whisper %s (%s/%s)",
                    settings.WHISPER_MODEL, settings.WHISPER_DEVICE,
                    settings.WHISPER_COMPUTE_TYPE)
        _model = WhisperModel(
            settings.WHISPER_MODEL,
            device=settings.WHISPER_DEVICE,
            compute_type=settings.WHISPER_COMPUTE_TYPE,
        )
    return _model


def transcribe_track(path, *, offset_ms: int = 0) -> list[dict]:
    """Распознать одну дорожку и вернуть реплики со сдвигом.

    ``vad_filter`` обязателен: в записи совещания человек молчит бо́льшую
    часть времени, и без отсечения тишины Whisper и считает дольше, и
    склонен галлюцинировать текст на пустом месте.
    """
    model = get_model()
    segments, _info = model.transcribe(
        str(path),
        language=settings.WHISPER_LANGUAGE or None,
        vad_filter=True,
        # Без этого на длинной паузе модель повторяет последнюю фразу
        # десятки раз, и протокол превращается в мусор.
        condition_on_previous_text=False,
    )

    result: list[dict] = []
    for segment in segments:
        text = (segment.text or "").strip()
        if not text:
            continue
        result.append({
            "start_ms": max(0, int(segment.start * 1000) + offset_ms),
            "end_ms": max(0, int(segment.end * 1000) + offset_ms),
            "text": text,
            "confidence": _confidence(segment),
        })
    return result


def _confidence(segment) -> float | None:
    """Уверенность 0..1 из логарифмической вероятности сегмента.

    faster-whisper отдаёт ``avg_logprob`` (натуральный логарифм, обычно от
    −1 до 0). Показывать это число пользователю бессмысленно, поэтому
    переводим в привычную шкалу экспонентой и подрезаем края.
    """
    raw = getattr(segment, "avg_logprob", None)
    if raw is None:
        return None
    import math

    return round(min(1.0, max(0.0, math.exp(raw))), 3)

"""Сведение подорожечной записи в одно видео.

Во время встречи SFU пишет по файлу на каждую дорожку каждого участника
(ремукс без перекодирования). Здесь эти файлы превращаются в один mp4,
который можно открыть плеером.

Три вещи, которые делают эту задачу нетривиальной, и как они решены:

1. **Дорожки начинаются в разное время.** Человек, вошедший на десятой
   минуте, дал файл, у которого нулевая секунда — это десятая минута
   встречи. Поэтому каждая дорожка сдвигается фильтром ``tpad`` на свой
   ``started_offset_ms``, а не подставляется как есть.
2. **Дорожки заканчиваются в разное время.** Без выравнивания ``xstack``
   оборвал бы всю сетку на самой короткой. Поэтому каждая доводится до
   полной длины встречи (``tpad stop_duration``).
3. **Участников может быть сколько угодно.** Сетка считается по фактическому
   числу видеодорожек, а лишние (сверх ``CONFERENCE_MAX_TILES``) в картинку
   не попадают — но в аудиомикс и в протокол попадают все.

ffmpeg зовётся ОДИН раз на всю сборку. Соблазн собирать попарно велик, но
каждый промежуточный проход — это лишнее перекодирование, то есть и время, и
потеря качества.
"""

from __future__ import annotations

import logging
import math
import shutil
import subprocess
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

#: Размер одной плитки. 640×360 держит 16:9 и даёт при сетке 3×3 честные
#: 1920×1080 — то, что ожидается от «записи совещания».
TILE_WIDTH = 640
TILE_HEIGHT = 360


class ComposeError(RuntimeError):
    """Сборка не удалась. Текст уходит в ConferenceSession.error."""


def ffmpeg_binary() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def ffprobe_binary() -> str:
    return shutil.which("ffprobe") or "ffprobe"


def raw_root() -> Path:
    return Path(settings.CONFERENCE_RAW_DIR)


def raw_path(session, recording) -> Path:
    """Абсолютный путь к сырой дорожке на общем томе.

    ``storage_path`` у сырых дорожек — путь ОТНОСИТЕЛЬНО тома (см. модель), и
    он уже отфильтрован при приёме (``session_service._safe_rel_path``).
    Собираем его здесь, а не храним абсолютным, чтобы том можно было
    перемонтировать в другую точку, не переписывая базу.
    """
    return raw_root() / str(session.pk) / recording.storage_path


def grid_layout(count: int) -> tuple[int, int]:
    """Сколько колонок и строк под ``count`` плиток.

    Квадратная сетка: 2 участника — 2×1, 4 — 2×2, 5..6 — 3×2, 7..9 — 3×3.
    """
    if count <= 1:
        return 1, 1
    columns = math.ceil(math.sqrt(count))
    rows = math.ceil(count / columns)
    return columns, rows


def _xstack_layout(count: int, columns: int) -> str:
    """Раскладка ``xstack``: координаты левого верхнего угла каждой плитки."""
    cells = []
    for index in range(count):
        column, row = index % columns, index // columns
        cells.append(f"{column * TILE_WIDTH}_{row * TILE_HEIGHT}")
    return "|".join(cells)


def build_command(*, video_inputs, audio_inputs, duration_sec: int,
                  output: Path) -> list[str]:
    """Собрать вызов ffmpeg.

    Вынесено из ``compose()`` отдельной чистой функцией, чтобы её можно было
    проверить тестом, не запуская ffmpeg и не имея на диске ни одного файла.

    ``video_inputs``/``audio_inputs`` — списки ``(путь, сдвиг_мс)``.
    """
    if not video_inputs and not audio_inputs:
        raise ComposeError("нет ни одной дорожки для сборки")

    args = [ffmpeg_binary(), "-y", "-nostdin"]
    for path, _offset in [*video_inputs, *audio_inputs]:
        args += ["-i", str(path)]

    filters: list[str] = []
    video_labels: list[str] = []
    for index, (_path, offset_ms) in enumerate(video_inputs):
        offset_sec = offset_ms / 1000
        label = f"v{index}"
        filters.append(
            # scale + pad: приводим к плитке, не растягивая кадр (у кого-то
            # камера 4:3, у кого-то демонстрация экрана 16:10).
            f"[{index}:v]scale={TILE_WIDTH}:{TILE_HEIGHT}:"
            f"force_original_aspect_ratio=decrease,"
            f"pad={TILE_WIDTH}:{TILE_HEIGHT}:-1:-1:color=black,"
            f"setsar=1,fps=25,"
            f"tpad=start_duration={offset_sec:.3f}:start_mode=add:color=black,"
            f"tpad=stop_duration={duration_sec}:stop_mode=clone,"
            f"trim=duration={duration_sec},setpts=PTS-STARTPTS[{label}]"
        )
        video_labels.append(f"[{label}]")

    if video_labels:
        if len(video_labels) == 1:
            filters.append(f"{video_labels[0]}copy[vout]")
        else:
            columns, _rows = grid_layout(len(video_labels))
            layout = _xstack_layout(len(video_labels), columns)
            filters.append(
                f"{''.join(video_labels)}xstack=inputs={len(video_labels)}:"
                f"layout={layout}:fill=black[vout]"
            )

    audio_labels: list[str] = []
    offset_of_audio = len(video_inputs)
    for index, (_path, offset_ms) in enumerate(audio_inputs):
        stream = offset_of_audio + index
        label = f"a{index}"
        filters.append(
            f"[{stream}:a]aresample=async=1,"
            f"adelay={int(offset_ms)}:all=1[{label}]"
        )
        audio_labels.append(f"[{label}]")

    if audio_labels:
        if len(audio_labels) == 1:
            filters.append(f"{audio_labels[0]}anull[aout]")
        else:
            filters.append(
                # dropout_transition=0 — иначе ffmpeg поднимает громкость
                # оставшихся, когда кто-то замолкает, и запись «дышит».
                f"{''.join(audio_labels)}amix=inputs={len(audio_labels)}:"
                f"duration=longest:dropout_transition=0:normalize=0[aout]"
            )

    args += ["-filter_complex", ";".join(filters)]
    if video_labels:
        args += ["-map", "[vout]", "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", "26", "-pix_fmt", "yuv420p"]
    if audio_labels:
        args += ["-map", "[aout]", "-c:a", "aac", "-b:a", "128k"]
    # +faststart: без него плеер вынужден скачать файл целиком, прежде чем
    # показать первый кадр, — то есть перемотка по ссылке не работает.
    args += ["-movflags", "+faststart", str(output)]
    return args


def run(args: list[str], *, timeout: int) -> None:
    logger.info("conference: ffmpeg %s", " ".join(args[1:]))
    try:
        completed = subprocess.run(args, capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise ComposeError("ffmpeg не найден в образе") from exc
    except subprocess.TimeoutExpired as exc:
        raise ComposeError(f"ffmpeg не уложился в {timeout} с") from exc

    if completed.returncode != 0:
        # Последние строки stderr — там ffmpeg пишет причину; целиком он
        # выдаёт мегабайты прогресса, которым в логе не место.
        tail = completed.stderr.decode("utf-8", "replace").strip().splitlines()[-8:]
        raise ComposeError("ffmpeg вернул код "
                           f"{completed.returncode}: {' | '.join(tail)}")


def extract_poster(source: Path, target: Path, *, at_sec: int = 3) -> bool:
    """Кадр-заставка для карточки встречи. Не критично — best effort."""
    args = [ffmpeg_binary(), "-y", "-nostdin", "-ss", str(at_sec), "-i", str(source),
            "-frames:v", "1", "-q:v", "3", str(target)]
    try:
        run(args, timeout=120)
        return target.exists()
    except ComposeError:
        logger.info("conference: постер не получился для %s", source, exc_info=True)
        return False

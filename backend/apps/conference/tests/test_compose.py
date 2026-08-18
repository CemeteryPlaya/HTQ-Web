"""Сборка вызова ffmpeg.

Проверяется команда, а не результат: запускать ffmpeg в тестах — это минуты
на прогон и зависимость от бинаря в системе. При этом ошибиться здесь легко
и последствия тихие — неверный сдвиг не уронит сборку, а просто разъедет
картинку с голосом.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.conference.services import compose_service


def test_grid_stays_square():
    assert compose_service.grid_layout(1) == (1, 1)
    assert compose_service.grid_layout(2) == (2, 1)
    assert compose_service.grid_layout(4) == (2, 2)
    assert compose_service.grid_layout(6) == (3, 2)
    assert compose_service.grid_layout(9) == (3, 3)


def test_late_joiner_is_shifted_by_own_offset():
    """Дорожка вошедшего на десятой минуте должна начинаться на 600 секунде.

    Без tpad она приклеилась бы к началу встречи, и человек говорил бы
    поверх чужого вступления.
    """
    args = compose_service.build_command(
        video_inputs=[(Path("a.mkv"), 0), (Path("b.mkv"), 600_000)],
        audio_inputs=[],
        duration_sec=1800,
        output=Path("out.mp4"),
    )
    filters = args[args.index("-filter_complex") + 1]

    assert "tpad=start_duration=0.000" in filters
    assert "tpad=start_duration=600.000" in filters
    # Обе плитки доводятся до полной длины, иначе xstack оборвёт сетку на
    # самой короткой дорожке.
    assert filters.count("stop_duration=1800") == 2
    assert "xstack=inputs=2" in filters


def test_single_video_skips_xstack():
    args = compose_service.build_command(
        video_inputs=[(Path("a.mkv"), 0)], audio_inputs=[],
        duration_sec=60, output=Path("out.mp4"),
    )
    filters = args[args.index("-filter_complex") + 1]
    assert "xstack" not in filters


def test_audio_delay_matches_join_offset():
    args = compose_service.build_command(
        video_inputs=[], audio_inputs=[(Path("a.mkv"), 0), (Path("b.mkv"), 12_500)],
        duration_sec=100, output=Path("out.mp4"),
    )
    filters = args[args.index("-filter_complex") + 1]

    assert "adelay=0:all=1" in filters
    assert "adelay=12500:all=1" in filters
    # normalize=0 и dropout_transition=0: иначе микс «дышит» — громкость
    # оставшихся подскакивает, когда кто-то замолкает.
    assert "normalize=0" in filters and "dropout_transition=0" in filters


def test_output_is_seekable_mp4():
    args = compose_service.build_command(
        video_inputs=[(Path("a.mkv"), 0)], audio_inputs=[(Path("a.mkv"), 0)],
        duration_sec=60, output=Path("out.mp4"),
    )
    # +faststart обязателен: без него плеер не покажет первый кадр, пока не
    # скачает файл целиком, и перемотка по ссылке не работает.
    assert "+faststart" in args
    assert args[-1] == "out.mp4"


def test_empty_input_is_refused():
    with pytest.raises(compose_service.ComposeError):
        compose_service.build_command(
            video_inputs=[], audio_inputs=[], duration_sec=10,
            output=Path("out.mp4"),
        )
